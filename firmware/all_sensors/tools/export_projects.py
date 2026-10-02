"""Reproducible Wokwi projects for every physical endpoint in the original roster."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
sys.path.insert(0,str(BASE))
from catalog import CATALOG, ALIASES, SOFTWARE

def load_roster():
 spec=importlib.util.spec_from_file_location('roster',ROOT/'simulator/profiles.py')
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 return mod

def inventory():
 roster=load_roster();entities=[];devices=[]
 for resident,room in zip(roster.RESIDENTS,roster.ROOM_ASSIGNMENTS):
  assert resident['room']==room['room']
  entities.append({'id':resident['id'],'name':resident['name'],'type':'resident','room':room['room'],'floor':room['floor'],'sensors':room['room_sensors']})
 for zone in roster.ZONES:
  # AmbientSensorSimulator publishes these seven environmental channels in EVERY zone,
  # including zones whose original sensor list only named a software dashboard.
  sensors=list(zone['sensors'])
  for role in ['ambiant','co2','son','co','fumee']:
   if role not in sensors:sensors.append(role)
  entities.append({**zone,'sensors':sensors,'declared_sensors':zone['sensors'],'type':'zone','zone_type':zone['type']})
 for entity in entities:
  for role in entity['sensors']:
   if role in SOFTWARE: continue
   if role not in ALIASES: raise ValueError(f'Unmapped sensor: {role}')
   for sensor in ALIASES[role]:
    device_id=f"{entity['id']}-{role}-{sensor}"
    devices.append({'id':device_id,'entity_id':entity['id'],'role':role,'kind':sensor,'fields':CATALOG[sensor]['fields']})
 assert len({d['id'] for d in devices})==len(devices)
 return {'schema':1,'origin':'https://github.com/lebretyves/D-tection-de-malaise-en-EHPAD','entities':entities,'devices':devices,'catalog':CATALOG,'software_functions':sorted(SOFTWARE)}

def diagram(kind,hardware=False):
 item=CATALOG[kind];part=item.get('native') or 'chip-'+item['chip']
 if kind=='rfid':part='board-mfrc522'
 parts=[{'type':'board-esp32-devkit-c-v4','id':'esp','top':0,'left':0,'attrs':{}},{'type':part,'id':'sensor','top':-20,'left':270,'attrs':{}}]
 pins=[]
 if kind in {'mpu6050','max30102','tmp117','scd41','sgp30','sgp40','amg8833','ble'}:
  pins=[('VCC','3V3'),('GND','GND.1'),('SDA','21'),('SCL','22')]
 elif kind in {'gps','ze07co','nibp'}:pins=[('VCC','5V'),('GND','GND.1'),('TX','16'),('RX','17')]
 elif kind=='sos':pins=[('1.l','27'),('2.l','GND.1')];parts[1]['attrs']={'color':'red','label':'SOS'}
 elif kind=='door':pins=[('2','27'),('1','GND.1')]
 elif kind=='pir':pins=[('VCC','5V'),('GND','GND.1'),('OUT','27')]
 elif kind=='radar':pins=[('VCC','5V'),('GND','GND.1'),('OUT','27')]
 elif kind=='dht22':pins=[('VCC','3V3'),('GND','GND.1'),('SDA','27')]
 elif kind=='hx711':pins=[('VCC','3V3'),('GND','GND.1'),('DT','26'),('SCK','25')];parts[1]['attrs']={'type':'50kg'}
 elif kind=='mq2':
  # Wokwi does not solve resistor divider voltages. Its virtual ADC uses 5V.
  # Real hardware requires 10k/18k attenuation (5V -> 3.21V); never wire AO directly.
  pins=[('VCC','5V'),('GND','GND.1')]
  if hardware:
   parts += [{'type':'wokwi-resistor','id':'r1','top':160,'left':200,'attrs':{'value':'10000'}},{'type':'wokwi-resistor','id':'r2','top':220,'left':200,'attrs':{'value':'18000'}}]
  else:
   pins.append(('AO','34'))
   parts.append({'type':'wokwi-text','id':'adc_note','top':180,'left':200,'attrs':{'text':'SIMULATION ONLY: virtual ADC 5V.\nHardware: AO -> 10k -> GPIO34 -> 18k -> GND.'}})
 elif kind in {'ecg','sound','respiration'}:
  pins=[('VCC','3V3'),('GND','GND.1'),('OUT','34')]
  if kind=='sound':pins[0]=('VCC','5V')
  if kind=='ecg':pins += [('LOP','32'),('LOM','33')]
  if kind!='sound':parts[1]['attrs']={'frequency':'0.25' if kind=='respiration' else '1.2'}
 elif kind=='rfid':pins=[('3.3V','3V3'),('GND','GND.1'),('SDA','5'),('SCK','18'),('MOSI','23'),('MISO','19'),('RST','22')]
 else:raise ValueError(kind)
 connections=[['esp:TX','$serialMonitor:RX','',[]],['esp:RX','$serialMonitor:TX','',[]]]
 connections += [[f'sensor:{a}',f'esp:{b}','black' if b.startswith('GND') else 'red' if b in {'3V3','5V'} else 'green',[]] for a,b in pins]
 if kind=='mq2' and hardware:connections += [['sensor:AO','r1:1','green',[]],['r1:2','esp:34','green',[]],['r1:2','r2:1','green',[]],['r2:2','esp:GND.1','black',[]]]
 if kind=='nibp':
  for name,pin,color in [('start',27,'green'),('stop',26,'red')]:
   parts.append({'type':'wokwi-pushbutton','id':name,'top':160,'left':270 if name=='start' else 370,'attrs':{'color':color,'label':name.upper()}})
   connections += [[name+':1.l','esp:'+str(pin),'green',[]],[name+':2.l','esp:GND.1','black',[]]]
 return {'version':1,'author':'EHPAD — banc matériel','editor':'wokwi','parts':parts,'connections':connections,'dependencies':{}}

def export(device,out,hardware=False):
 out.mkdir(parents=True,exist_ok=True)
 for source in (BASE/'src').iterdir():shutil.copyfile(source,out/source.name)
 config={'DEVICE_ID':device['id'],'ENTITY_ID':device['entity_id'],'SENSOR_KIND':device['kind'],
  'MQTT_PREFIX':'ehpad/hardware/v1' if hardware else 'ehpad/lab/lebretyves-all/v1',
  'MQTT_HOST':'192.168.1.10' if hardware else 'test.mosquitto.org','MQTT_PORT':1883,
  'MQTT_USER':device['id'] if hardware else '','MQTT_PASSWORD':'','WIFI_SSID':'CHANGE_ME' if hardware else 'Wokwi-GUEST','WIFI_PASSWORD':'',
  'WOKWI_BUILD':0 if hardware else 1,'LOAD_SCALE':0 if hardware else 420,'LOAD_OFFSET':0}
 (out/'device_config.h').write_text('#pragma once\n'+''.join(f'#define {k} {json.dumps(v)}\n' for k,v in config.items()),encoding='utf-8')
 (out/'diagram.json').write_text(json.dumps(diagram(device['kind'],hardware),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 (out/'libraries.txt').write_text('PubSubClient@2.8\nArduinoJson@7.4.2\nDHT sensor library@1.4.6\nAdafruit Unified Sensor@1.1.15\nSparkFun MAX3010x Pulse and Proximity Sensor Library@1.1.2\nMFRC522@1.4.12\nTinyGPSPlus@1.0.3\nHX711 Arduino Library@0.7.5\nSensirion Gas Index Algorithm@3.2.3\n',encoding='utf-8')
 chip=CATALOG[device['kind']].get('chip')
 if chip:
  # Inline model so online Wokwi has no ambiguity about C header search paths.
  src=(BASE/'chips'/f'{chip}.chip.c').read_text(encoding='utf-8').replace('#include "model.h"',(BASE/'chips/model.h').read_text(encoding='utf-8'))
  (out/f'{chip}.chip.c').write_text(src.rstrip()+'\n',encoding='utf-8')
  shutil.copyfile(BASE/'chips'/f'{chip}.chip.json',out/f'{chip}.chip.json')
  wasm=BASE/'chips'/f'{chip}.wasm'
  if wasm.exists():shutil.copyfile(wasm,out/f'{chip}.chip.wasm')
 toml='[wokwi]\nversion = 1\nfirmware = "build/sketch.ino.bin"\nelf = "build/sketch.ino.elf"\n'
 if chip:toml+=f'\n[[chip]]\nname = "{chip}"\nbinary = "{chip}.chip.wasm"\n'
 (out/'wokwi.toml').write_text(toml,encoding='utf-8')

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--device');parser.add_argument('--hardware',action='store_true');parser.add_argument('--out',type=Path);parser.add_argument('--inventory-only',action='store_true');args=parser.parse_args()
 inv=inventory()
 for path in [BASE/'inventory.json',ROOT/'backend/hardware_inventory.json',ROOT/'dashboard/public/hardware-inventory.json']:
  path.write_text(json.dumps(inv,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 if args.inventory_only:return
 selected=[d for d in inv['devices'] if not args.device or d['id']==args.device]
 if not selected:parser.error('Identifiant inconnu')
 for device in selected:export(device,(args.out or BASE/'projects')/device['id'],args.hardware)
 print(f"Exported {len(selected)} endpoints, {len(inv['entities'])} entities")
if __name__=='__main__':main()
