import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from hardware_telemetry import TelemetryStore,PREFIXES
spec=importlib.util.spec_from_file_location('exporter',ROOT/'firmware/all_sensors/tools/export_projects.py')
exporter=importlib.util.module_from_spec(spec);spec.loader.exec_module(exporter)

class TelemetryTests(unittest.TestCase):
 def setUp(self):
  self.now=100.;self.store=TelemetryStore(exporter.inventory(),clock=lambda:self.now)
  self.device=self.store.devices['R001-wearable-max30102']
 def message(self, device=None, **overrides):
  d=device or self.device
  return {'schema':1,'device_id':d['id'],'entity_id':d['entity_id'],'kind':d['kind'],'source':'wokwi','boot':'boot1','seq':1,'sample_age_ms':0,'available':True,'values':{},**overrides}
 def ingest(self,p,**kwargs):return self.store.ingest(PREFIXES['wokwi']+'/'+p['device_id']+'/telemetry',p,source='wokwi',**kwargs)
 def test_roster_and_every_role(self):
  inv=self.store.inventory
  self.assertEqual(25,sum(e['type']=='resident' for e in inv['entities']))
  self.assertEqual(20,sum(e['type']=='zone' for e in inv['entities']))
  for d in inv['devices']:self.assertTrue(self.ingest(self.message(d)))
  self.assertEqual(len(inv['devices']),self.store.snapshot()['live_devices'])
 def test_missing_never_becomes_normal(self):
  state=self.store.snapshot()['entities'][0]
  self.assertTrue(all(v is None for v in state['contract']['vitals'].values()))
  self.assertTrue(all(d['status']=='waiting' for d in state['devices']))
 def test_resident_isolation_and_source_isolation(self):
  self.assertTrue(self.ingest(self.message(values={'heart_rate':123})))
  snap=self.store.snapshot()['entities']
  self.assertEqual(123,snap[0]['contract']['vitals']['heart_rate'])
  self.assertIsNone(snap[1]['contract']['vitals']['heart_rate'])
  self.assertIsNone(self.store.snapshot('hardware')['entities'][0]['contract']['vitals']['heart_rate'])
 def test_stale_sample_and_lwt(self):
  self.ingest(self.message(values={'heart_rate':85},sample_age_ms=14000));self.now+=2
  self.assertIsNone(self.store.snapshot()['entities'][0]['contract']['vitals']['heart_rate'])
  self.ingest(self.message(seq=2,values={'heart_rate':86}));topic=PREFIXES['wokwi']+'/'+self.device['id']+'/status'
  self.store.ingest(topic,{'boot':'other','online':False},source='wokwi')
  self.assertEqual(1,self.store.snapshot()['live_devices'])
  self.store.ingest(topic,{'boot':'boot1','online':False},source='wokwi')
  self.assertEqual(0,self.store.snapshot()['live_devices'])
 def test_retained_replay_and_reboot(self):
  p=self.message(values={'heart_rate':80})
  self.assertFalse(self.ingest(p,retained=True))
  self.assertTrue(self.ingest(p));self.assertFalse(self.ingest(p))
  self.assertTrue(self.ingest(self.message(boot='boot2')))
  self.assertFalse(self.ingest(self.message(seq=2)))
 def test_validation_rejects_nan_bool_and_identity_spoof(self):
  for changes in [{'schema':True},{'entity_id':'R025'},{'kind':'sos'},{'source':'hardware'},{'values':{'heart_rate':True}}, {'values':{'heart_rate':float('nan')}},{'values':{'heart_rate':999}}, {'values':{'unknown':2}},{'seq':True},{'sample_age_ms':-1}]:
   self.assertFalse(self.ingest(self.message(**changes)),changes)
 def test_roles_do_not_confuse_bathroom_and_room(self):
  d=self.store.devices['R001-sdb_pir-pir'];self.ingest(self.message(d,values={'motion':True}))
  events=self.store.snapshot()['entities'][0]['contract']['sensor_events']
  self.assertTrue(events['bathroom_motion']);self.assertIsNone(events['room_pir_motion'])
 def test_unavailable_clears_value(self):
  self.ingest(self.message(values={'heart_rate':80}));self.ingest(self.message(seq=2,available=False,values={'heart_rate':80}))
  self.assertIsNone(self.store.snapshot()['entities'][0]['contract']['vitals']['heart_rate'])
 def test_no_false_clinical_temperature_or_fall(self):
  d=self.store.devices['R001-wearable-tmp117'];self.ingest(self.message(d,values={'contact_temperature_c':36.5}))
  d=self.store.devices['R001-wearable-mpu6050'];self.ingest(self.message(d,values={'impact':True,'accel_g':2.9}))
  e=self.store.snapshot()['entities'][0]
  self.assertIsNone(e['contract']['vitals']['temperature']);self.assertIsNone(e['contract']['movement']['is_fall_detected'])
  self.assertEqual('impact',e['alerts'][0]['field'])
 def test_inventory_copies_match(self):
  expected=exporter.inventory()
  for path in ['backend/hardware_inventory.json','dashboard/public/hardware-inventory.json','firmware/all_sensors/inventory.json']:
   self.assertEqual(expected,json.loads((ROOT/path).read_text(encoding='utf-8')))
 def test_all_zone_environment_channels_exported(self):
  for e in self.store.inventory['entities']:
   if e['type']!='zone':continue
   fields=set(k for d in self.store.devices.values() if d['entity_id']==e['id'] for k in d['fields'])
   self.assertTrue({'temperature_c','humidity_pct','co2_ppm','co_ppm','voc_index','sound_db','gas_adc'}<=fields,e['id'])
 def test_every_export_uses_current_driver_and_unique_identity(self):
  base=ROOT/'firmware/all_sensors'
  for d in self.store.inventory['devices']:
   project=base/'projects'/d['id']
   for name in ['sketch.ino','sensors.h','protocols.h']:
    self.assertEqual((base/'src'/name).read_bytes(),(project/name).read_bytes(),str(project))
   cfg=(project/'device_config.h').read_text()
   self.assertIn('#define DEVICE_ID '+json.dumps(d['id']),cfg)
   self.assertIn('#define ENTITY_ID '+json.dumps(d['entity_id']),cfg)
   self.assertTrue((project/'diagram.json').exists())
   chip=self.store.inventory['catalog'][d['kind']].get('chip')
   if chip:
    self.assertEqual((base/'chips'/f'{chip}.wasm').read_bytes(),(project/f'{chip}.chip.wasm').read_bytes())
    self.assertIn(f'binary = "{chip}.chip.wasm"',(project/'wokwi.toml').read_text())
    self.assertTrue((project/f'{chip}.chip.json').exists())

if __name__=='__main__':unittest.main()
