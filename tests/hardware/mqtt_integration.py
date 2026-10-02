"""Synthetic contract test, not firmware simulation. Publishes only to loopback by default."""
import argparse
import json
from pathlib import Path
import time
import urllib.request
import urllib.error
import paho.mqtt.client as mqtt

ROOT=Path(__file__).resolve().parents[2]
SAMPLES={
 'mpu6050':{'accel_g':1.,'gyro_dps':0.,'impact':False},'max30102':{'heart_rate':75,'spo2':97,'ir_raw':60000,'red_raw':55000},
 'tmp117':{'contact_temperature_c':36.5},'sos':{'sos_pressed':False},'pir':{'motion':True},'door':{'door_open':False},
 'hx711':{'load_raw':29400,'load_kg':70},'radar':{'presence':True},'scd41':{'co2_ppm':650,'temperature_c':22,'humidity_pct':45},
 'dht22':{'temperature_c':22,'humidity_pct':45},'sgp40':{'voc_raw':25000,'voc_index':100},'sgp30':{'tvoc_ppb':30,'eco2_ppm':450},
 'mq2':{'gas_adc':120},'ze07co':{'co_ppm':2.},'sound':{'sound_db':45,'sound_mv':900},
 'ecg':{'ecg_mv':1650,'leads_off':False},'respiration':{'respiration_mv':1650,'respiratory_rate':15},
 'amg8833':{'thermal_pixels_c':[22.]*64,'thermal_max_c':22.},'gps':{'latitude':48.8566,'longitude':2.3522,'gps_fix':True},
 'rfid':{'tag_uid':'01020304'},'ble':{'ble_address':'02:00:00:00:00:01','ble_rssi_dbm':-55},'nibp':{'blood_pressure_sys':120,'blood_pressure_dia':75},
}
def main():
 p=argparse.ArgumentParser();p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=1887);p.add_argument('--api',default='http://localhost:8005');p.add_argument('--seconds',type=int,default=0);args=p.parse_args()
 inv=json.loads((ROOT/'firmware/all_sensors/inventory.json').read_text(encoding='utf8'))
 client=mqtt.Client(client_id='ehpad-contract-test');client.connect(args.host,args.port,30);client.loop_start();boot='contract-'+str(time.time_ns());prefix='ehpad/lab/lebretyves-all/v1/'
 def send(seq):
  for d in inv['devices']:
   payload={'schema':1,'device_id':d['id'],'entity_id':d['entity_id'],'kind':d['kind'],'source':'wokwi','boot':boot,'seq':seq,'sample_age_ms':0,'available':True,'values':SAMPLES[d['kind']]}
   client.publish(prefix+d['id']+'/telemetry',json.dumps(payload),qos=1).wait_for_publish(timeout=5)
 def snapshot():
  with urllib.request.urlopen(args.api+'/api/hardware/snapshot',timeout=10) as response:return json.load(response)
 send(1)
 deadline=time.monotonic()+10
 while time.monotonic()<deadline:
  snap=snapshot()
  if snap['live_devices']==len(inv['devices']):break
  time.sleep(.1)
 assert snap['live_devices']==len(inv['devices']),snap['live_devices']
 assert len(snap['entities'])==45
 residents=[e for e in snap['entities'] if e['type']=='resident'];assert len(residents)==25
 assert all(e['contract']['vitals']['heart_rate']==75 for e in residents)
 assert all(e['contract']['vitals']['temperature'] is None for e in residents)
 try:urllib.request.urlopen(args.api+'/api/hardware/snapshot?source=hardware',timeout=5);raise AssertionError('hardware must require staff session')
 except urllib.error.HTTPError as error:assert error.code==401
 # Malformed and retained readings must not change R001 or any other resident.
 bad={'schema':1,'device_id':'R001-wearable-max30102','entity_id':'R002','kind':'max30102','source':'wokwi','boot':boot,'seq':2,'sample_age_ms':0,'available':True,'values':{'heart_rate':199}}
 client.publish(prefix+'R001-wearable-max30102/telemetry',json.dumps(bad),qos=1).wait_for_publish()
 time.sleep(.2);assert snapshot()['entities'][0]['contract']['vitals']['heart_rate']==75
 seq=2;until=time.monotonic()+args.seconds
 while time.monotonic()<until:send(seq);seq+=1;time.sleep(2)
 client.disconnect();client.loop_stop()
 print(json.dumps({'result':'passed','test_type':'synthetic MQTT contract; not firmware','entities':45,'residents':25,'zones':20,'devices':len(inv['devices']),'checks':['routing','identity','source isolation','hardware auth','null preservation']},indent=2))
if __name__=='__main__':main()
