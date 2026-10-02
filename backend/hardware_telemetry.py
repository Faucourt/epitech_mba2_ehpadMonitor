"""Isolated acquisition path: physical measurements never inherit simulator defaults."""
import copy
import json
import math
import re
import threading
import time
from collections import deque
from pathlib import Path

PREFIXES = {'wokwi': 'ehpad/lab/lebretyves-all/v1', 'hardware': 'ehpad/hardware/v1'}
BOOL_FIELDS = {'impact','sos_pressed','motion','door_open','presence','leads_off','gps_fix'}
LIMITS = {
 'heart_rate': (30,240), 'spo2': (50,100), 'co2_ppm':(0,40000), 'co_ppm':(0,500),
 'humidity_pct':(0,100),'temperature_c':(-50,130),'contact_temperature_c':(-55,150),
 'blood_pressure_sys':(40,300),'blood_pressure_dia':(20,200),'respiratory_rate':(0,60),
 'latitude':(-90,90),'longitude':(-180,180),'ble_rssi_dbm':(-127,20),
 'thermal_max_c':(-55,150),'accel_g':(0,30),'gyro_dps':(0,4000),
 'sound_db':(30,130),'voc_index':(1,500),'voc_raw':(0,65535),
}

class TelemetryStore:
 def __init__(self, inventory=None, clock=time.time):
  self.inventory=inventory or json.loads((Path(__file__).parent/'hardware_inventory.json').read_text(encoding='utf-8'))
  self.devices={d['id']:d for d in self.inventory['devices']}
  self.clock=clock;self.lock=threading.RLock();self.states={};self.status={};self.retired={};self.history={}

 def ingest(self, topic, payload, retained=False, source='hardware'):
  prefix=PREFIXES.get(source)
  if not prefix or not topic.startswith(prefix+'/'):return False
  tail=topic[len(prefix)+1:].split('/')
  if len(tail)!=2 or tail[0] not in self.devices or tail[1] not in {'status','telemetry'}:return False
  device_id,channel=tail;device=self.devices[device_id]
  try:
   if isinstance(payload,(bytes,str)):
    if len(payload)>8192:return False
    payload=json.loads(payload)
   if not isinstance(payload,dict):return False
   boot=payload.get('boot')
   if not isinstance(boot,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,32}',boot):return False
   key=(source,device_id);now=self.clock()
   with self.lock:
    old=self.states.get(key)
    if channel=='status':
     if type(payload.get('online')) is not bool:return False
     # A retained online marker is not evidence of a currently connected device.
     if old and old['boot']==boot and not payload['online']:
      self.status[key]=False
     return True
    if retained or type(payload.get('schema')) is not int or payload.get('schema')!=1 or payload.get('source')!=source:return False
    if payload.get('device_id')!=device_id or payload.get('entity_id')!=device['entity_id'] or payload.get('kind')!=device['kind']:return False
    seq=payload.get('seq');age=payload.get('sample_age_ms');available=payload.get('available')
    if type(seq) is not int or not 0<seq<=0xffffffff:return False
    if type(age) is not int or not 0<=age<=0xffffffff or type(available) is not bool:return False
    if boot in self.retired.get(key,()):return False
    if old and old['boot']==boot and seq<=old['seq']:return False
    vals=payload.get('values')
    if not isinstance(vals,dict) or set(vals)-set(device['fields']):return False
    clean={}
    for name,value in vals.items():
     if value is None:clean[name]=None;continue
     if name in BOOL_FIELDS:
      if type(value) is not bool:return False
     elif name=='tag_uid':
      if not isinstance(value,str) or not re.fullmatch(r'(?:[A-Fa-f0-9]{2}){4,10}',value):return False
     elif name=='ble_address':
      if not isinstance(value,str) or not re.fullmatch(r'(?:[A-Fa-f0-9]{2}:){5}[A-Fa-f0-9]{2}',value):return False
     elif name=='thermal_pixels_c':
      if not isinstance(value,list) or len(value)!=64 or any(type(v) not in {int,float} or not math.isfinite(v) or not -55<=v<=150 for v in value):return False
     else:
      if type(value) not in {int,float} or not math.isfinite(value):return False
      low,high=LIMITS.get(name,(-10000000,10000000))
      if not low<=value<=high:return False
     clean[name]=value
    if clean.get('blood_pressure_sys') is not None and clean.get('blood_pressure_dia') is not None and clean['blood_pressure_sys']<=clean['blood_pressure_dia']:return False
    if clean.get('gps_fix') is False and (clean.get('latitude') is not None or clean.get('longitude') is not None):return False
    if old and old['boot']!=boot:
     self.retired.setdefault(key,deque(maxlen=16)).append(old['boot'])
    self.states[key]={'boot':boot,'seq':seq,'received_at':now,'sample_at':now-age/1000,'available':available,'values':clean if available else {}}
    self.status[key]=True
    self.history.setdefault(key,deque(maxlen=180)).append({'at':now, 'values':copy.deepcopy(clean) if available else {}})
    return True
  except (ValueError,TypeError,UnicodeDecodeError):return False

 def snapshot(self, source='wokwi'):
  now=self.clock();entities={e['id']:{**copy.deepcopy(e),'devices':[],'alerts':[]} for e in self.inventory['entities']}
  with self.lock:
   for device_id,device in self.devices.items():
    key=(source,device_id);state=self.states.get(key);status='waiting'
    if state:
     status='live' if self.status.get(key,False) and state['available'] and now-state['sample_at']<=15 and now-state['received_at']<=15 else 'stale'
     if not self.status.get(key,False):status='offline'
     elif not state['available']:status='unavailable'
    vals=copy.deepcopy(state['values']) if status=='live' else {}
    communicating=bool(state and self.status.get(key,False) and now-state['received_at']<=15)
    item={**device,'status':status,'values':vals,'received_at':state['received_at'] if state else None,
      'communicating':communicating,'boot':state['boot'] if state else None,'seq':state['seq'] if state else None}
    entity=entities[device['entity_id']];entity['devices'].append(item)
    for field,label in [('sos_pressed','Bouton SOS activé'),('impact','Impact détecté — chute à vérifier')]:
     if vals.get(field) is True:entity['alerts'].append({'device_id':device_id,'field':field,'label':label})
    # Demonstration thresholds are configurable in the UI / policy documentation,
    # never converted into the original clinical risk score.
    if vals.get('co2_ppm',0)>1500:entity['alerts'].append({'device_id':device_id,'field':'co2_ppm','label':'CO₂ au-dessus du seuil de démonstration (1500 ppm)'})
    if vals.get('co_ppm',0)>10:entity['alerts'].append({'device_id':device_id,'field':'co_ppm','label':'CO au-dessus du seuil de démonstration (10 ppm)'})
   for entity in entities.values():entity['contract']=self.legacy_contract(entity)
   return {'source':source,'received_at':now,'entities':list(entities.values()),
     'communicating_devices':sum(d['communicating'] for e in entities.values() for d in e['devices']),
     'live_devices':sum(d['status']=='live' for e in entities.values() for d in e['devices']),'expected_devices':len(self.devices)}

 @staticmethod
 def legacy_contract(entity):
  """Original field names only when their meaning matches an acquired measurement."""
  readings={}
  by_role={}
  for device in entity['devices']:
   by_role.setdefault(device['role'],{}).update(device['values'])
   readings.update(device['values'])
  if entity['type']=='resident':
   vitals={name:readings.get(name) for name in ('heart_rate','spo2','blood_pressure_sys','blood_pressure_dia','respiratory_rate')}
   # A contact temperature is not automatically the simulator's core temperature.
   vitals.update(temperature=None,ecg_rhythm=None)
   events={
    'room_pir_motion':by_role.get('pir',{}).get('motion'),
    'room_radar_presence':by_role.get('radar',{}).get('presence'),
    'bathroom_motion':by_role.get('sdb_pir',{}).get('motion'),
    'door_open':by_role.get('porte',{}).get('door_open'),
    'bed_occupied':None,'mattress_exit':None,'floor_pressure_event':None,'fall_confirmed_by_room_sensor':None,
   }
   return {'resident_id':entity['id'],'vitals':vitals,'sensor_events':events,
     'movement':{'accel_magnitude':readings.get('accel_g'),'gyro_magnitude_dps':readings.get('gyro_dps'),'sos_pressed':readings.get('sos_pressed'),
      'altitude_drop_cm':None,'is_fall_detected':None,'ambient_fall_confirmed':None,'last_movement_ago_s':None,'is_sleeping':None},
     'position':None,'current_zone':None,'activity':None,'ml_risk':None}
  return {'zone_id':entity['id'],**{name:readings.get(name) for name in ('temperature_c','humidity_pct','co2_ppm','co_ppm','door_open','voc_index','sound_db')},
    'motion_detected':readings.get('motion'),'occupancy':None,'resident_ids':None,'ble_seen':None,'last_motion_ago_s':None,
    'floor_pressure_event':None,'radar_immobile_low':None,'fall_confirmed':None,'smoke_ppm':None}

 def device_history(self, device_id, source='wokwi'):
  with self.lock:return copy.deepcopy(list(self.history.get((source,device_id),())))
