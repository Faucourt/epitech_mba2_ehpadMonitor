"""Generate Wokwi entrypoints and interactive controls from one model implementation."""
import json
from pathlib import Path
BASE = Path(__file__).resolve().parents[1] / 'chips'
MODELS = [
 ('max30102',1,0x57,[('bpm',75,30,220),('redRatio',.65,.1,2),('unused',0,0,1),('finger',1,0,1)]),
 ('tmp117',2,0x48,[('temperature',36.5,-40,125)]),
 ('scd41',3,0x62,[('co2',600,400,5000),('temperature',22,-10,60),('humidity',45,0,100)]),
 ('sgp30',4,0x58,[('tvoc',30,0,2000),('eco2',450,400,5000)]),
 ('amg8833',5,0x69,[('ambient',22,-20,80),('hotspot',34,-20,80),('pixel',27,0,63)]),
 ('ble-fixture',6,0x30,[('rssi',-55,-100,-20)]),
 ('digital-presence',7,0,[('presence',0,0,1)]),
 ('analog-signal',8,0,[('amplitude',.4,0,1.5),('offset',1.65,0,3.3),('frequency',1.2,.05,1000),('leadsOff',0,0,1)]),
 ('ze07co',9,0,[('co',2,0,500)]),
 ('gps-nmea',10,0,[('latitude',48.8566,-90,90),('longitude',2.3522,-180,180),('fix',1,0,1)]),
 ('nibp-fixture',11,0,[('systolic',120,40,300),('diastolic',75,20,200)]),
 ('sgp40',12,0x59,[('vocRaw',25000,10000,50000)]),
 ('sound-level',13,0,[('decibels',45,30,130)]),
]
def generate():
 for name,model,address,attrs in MODELS:
  source=f'#define MODEL {model}\n#define ADDRESS {address}\n'
  controls=[]
  for i in range(4):
   key,default,lo,hi=attrs[i] if i<len(attrs) else (f'unused{i}',0,0,1)
   source+=f'#define ATTR_{chr(65+i)} "{key}"\n#define DEFAULT_{chr(65+i)} {float(default)}f\n'
   if not key.startswith('unused'):
    controls.append({'id':key,'label':key,'type':'range','min':lo,'max':hi,'step':1 if key in {'finger','pixel','presence','leadsOff','fix'} else .01})
  source+='#include "model.h"\n'
  (BASE/f'{name}.chip.c').write_text(source,encoding='utf-8')
  pins=['VCC','GND']+(['SDA','SCL'] if model<=6 or model==12 else ['OUT','LOP','LOM'] if model==8 else ['OUT'] if model in {7,13} else ['TX','RX'])
  controls += [{'id':key,'label':key,'type':'range','min':0,'max':1,'step':1} for key in ['connected','corrupt']]
  (BASE/f'{name}.chip.json').write_text(json.dumps({'name':name+' (modèle pédagogique)','author':'EHPAD contributors','pins':pins,'controls':controls},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__': generate()
