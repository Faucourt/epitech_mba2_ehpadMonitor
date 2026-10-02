"""One ESP32 per entity; reuse tested drivers with independent state and pin allocation.

No telemetry is copied between entities. Every endpoint reads its own component.
The original single-sensor exports remain unchanged.
"""
import argparse
import copy
import hashlib
import json
import re
import shutil
from pathlib import Path
from export_projects import BASE, ROOT, CATALOG, diagram, inventory

OUT = BASE / 'collective'
I2C = {'mpu6050', 'max30102', 'tmp117', 'scd41', 'sgp40', 'amg8833', 'ble'}
UART = {'nibp', 'ze07co', 'gps'}
ADC = {'ecg', 'respiration', 'sound', 'mq2'}
GPIO = [4, 13, 14, 16, 17, 18, 19, 23, 25, 26, 27, 32, 33, 5]
ADC_PINS = [34, 35, 36, 39, 32, 33]


def select_groups(groups, entities=None, pilot=False):
    """The requested pilot includes three complete residents and every zone."""
    if pilot and entities:
        raise ValueError('Choose --pilot or --entity, not both')
    chosen = [g for g in groups if (g['entity_type'] == 'zone' or g['id'] in {'R001', 'R002', 'R003'})] if pilot else [g for g in groups if not entities or g['id'] in entities]
    if not chosen or entities and set(entities) - {g['id'] for g in chosen}:
        raise ValueError('Unknown entity')
    return chosen


def allocate(devices):
    used = {21, 22}
    if any(d['kind'] == 'rfid' for d in devices):
        used.update({18, 19, 23})
    plans = []
    for d in devices:
        p = {'device': d, 'pins': {}, 'uart': None}
        if d['kind'] in ADC:
            pin = next((n for n in ADC_PINS if n not in used), None)
            if pin is None:
                raise ValueError('ADC1 pin capacity exceeded')
            p['pins'][34] = pin
            used.add(pin)
        plans.append(p)

    def reserve():
        pin = next((n for n in GPIO if n not in used), None)
        if pin is None:
            raise ValueError('GPIO capacity exceeded; split this entity into two boards')
        used.add(pin)
        return pin

    uart = 0
    for p in plans:
        kind = p['device']['kind']
        if kind in I2C:
            p['pins'].update({21: 21, 22: 22})
        if kind in UART:
            uart += 1
            if uart > 2:
                raise ValueError('UART capacity exceeded')
            p['uart'] = uart
            p['pins'].update({16: reserve(), 17: reserve()})
        for old in ([27, 26] if kind == 'nibp' else [32, 33] if kind == 'ecg'
                    else [26, 25] if kind == 'hx711' else [5, 22] if kind == 'rfid'
                    else [27] if kind in {'sos', 'door', 'pir', 'radar', 'dht22'} else []):
            p['pins'][old] = reserve()
        if kind == 'rfid':
            p['pins'].update({18: 18, 19: 19, 23: 23})
    return plans


def driver(p, index):
    """Isolate static state; substitute only hardware bindings, never algorithms."""
    kind = p['device']['kind']
    source = (BASE / 'src/sensors.h').read_text(encoding='utf-8')
    nibp = (BASE / 'src/nibp.h').read_text(encoding='utf-8').replace('#pragma once', '')
    source = source.replace('#include "nibp.h"', nibp)
    source = re.sub(r'^#(?:include|pragma).*\n', '', source, flags=re.M)
    start = source.index('void sensorBegin() {')
    end = source.index('\nvoid readOptical()', start)
    original_begin = source[start:end]
    # Keep the proven per-model initialization, but initialize shared buses once.
    begin = original_begin
    for line in [
        '  Wire.begin(21,22); Wire.setTimeOut(50);\n',
        '  pinMode(27,INPUT_PULLUP); pinMode(32,INPUT_PULLDOWN); pinMode(33,INPUT_PULLDOWN);\n',
        '  if(kind("pir") || kind("radar"))pinMode(27,INPUT_PULLDOWN);\n',
        '  analogReadResolution(12); analogSetPinAttenuation(34,ADC_11db);\n',
        '  Serial2.begin(kind("nibp")?4800:9600,SERIAL_8N1,16,17);\n',
        '  if(kind("nibp"))pinMode(26,INPUT_PULLUP);\n',
    ]:
        if line not in begin:
            raise ValueError('Shared driver initialization changed; review collective bindings')
        begin = begin.replace(line, '')
    begin = begin.replace('Wire.end(); SPI.begin(); ', '')
    # A stale HX711 may be left in power-down / an incomplete conversion.
    # Reinitialize its clock on startup and on the existing 15-second retry.
    begin = begin.replace('scale.begin(26,25); sensorReady=true;',
                          'scale.begin(26,25); scale.power_down(); delayMicroseconds(80); scale.power_up(); sensorReady=true;')
    init = []
    if kind in {'sos', 'door', 'nibp'}:
        init.append('pinMode(27,INPUT_PULLUP);')
    if kind == 'nibp':
        init.append('pinMode(26,INPUT_PULLUP);')
    if kind in {'pir', 'radar'}:
        init.append('pinMode(27,INPUT_PULLDOWN);')
    if kind == 'ecg':
        init.append('pinMode(32,INPUT_PULLDOWN);pinMode(33,INPUT_PULLDOWN);')
    if kind in ADC:
        init.append('analogSetPinAttenuation(34,ADC_11db);')
    if kind in UART:
        init.append(f'Serial2.begin({4800 if kind == "nibp" else 9600},SERIAL_8N1,16,17);')
    begin = begin.replace('void sensorBegin() {', 'void sensorBegin() {\n' + ''.join(init))
    source = source[:start] + begin + source[end:]
    source = source.replace('isfinite(t)&&isfinite(h)', 'finiteMeasurement(t)&&finiteMeasurement(h)')
    # Calls and constructors use the endpoint's dedicated GPIO assignments.
    mapping = p['pins']
    def call_pin(match):
        return match[1] + str(mapping.get(int(match[2]), int(match[2])))
    source = re.sub(r'((?:pinMode|digitalRead|analogRead|adcMillivolts|analogSetPinAttenuation)\()(\d+)', call_pin, source)
    source = source.replace('DHT dht(27,DHT22)', f'DHT dht({mapping.get(27,27)},DHT22)')
    source = source.replace('MFRC522 rfid(5,22)', f'MFRC522 rfid({mapping.get(5,5)},{mapping.get(22,22)})')
    source = source.replace('scale.begin(26,25)', f'scale.begin({mapping.get(26,26)},{mapping.get(25,25)})')
    source = source.replace('SERIAL_8N1,16,17', f'SERIAL_8N1,{mapping.get(16,16)},{mapping.get(17,17)}')
    if p['uart']:
        source = source.replace('Serial2', f'collectiveSerial{p["uart"]}')
    # Unused UART code in non-UART instances compiles but is never called.
    return (f'namespace endpoint{index} {{\n'
            f'constexpr char SENSOR_KIND[]={json.dumps(kind)};\n'
            f'constexpr char DEVICE_ID[]={json.dumps(p["device"]["id"])};\n'
            + source + f'\n}} // endpoint{index}\n')


def export_entity(entity, devices, dest, hardware=False):
    plans = allocate(devices)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BASE / 'collective_src/finite_float.h', dest / 'finite_float.h')
    parts = [{'type': 'board-esp32-devkit-c-v4', 'id': 'esp', 'top': 0, 'left': 0, 'attrs': {}}]
    connections = [['esp:TX', '$serialMonitor:RX', '', []], ['esp:RX', '$serialMonitor:TX', '', []]]
    chips = set()
    for i, p in enumerate(plans):
        d = diagram(p['device']['kind'], hardware=hardware)
        names = {part['id']: f's{i}_{part["id"]}' for part in d['parts'] if part['id'] != 'esp'}
        for part in d['parts'][1:]:
            part = copy.deepcopy(part)
            part['id'] = names[part['id']]
            part['left'] += 350 * (i % 3)
            part['top'] += 300 * (i // 3)
            parts.append(part)
        for connection in d['connections'][2:]:
            connection = copy.deepcopy(connection)
            for j in [0, 1]:
                name, pin = connection[j].split(':', 1)
                if name == 'esp' and pin.isdigit():
                    pin = str(p['pins'].get(int(pin), int(pin)))
                    # The DevKit diagram names GPIO36/39 by their board labels.
                    pin = {'36': 'VP', '39': 'VN'}.get(pin, pin)
                connection[j] = names.get(name, name) + ':' + pin
            connections.append(connection)
        chip = CATALOG[p['device']['kind']].get('chip')
        if chip:
            chips.add(chip)
            original = BASE / 'projects' / p['device']['id']
            for suffix in ['chip.c', 'chip.json', 'chip.wasm']:
                shutil.copyfile(original / f'{chip}.{suffix}', dest / f'{chip}.{suffix}')
    (dest / 'diagram.json').write_text(json.dumps({'version': 1, 'author': 'EHPAD collective', 'editor': 'wokwi', 'parts': parts, 'connections': connections, 'dependencies': {}}, indent=2) + '\n', encoding='utf-8')
    headers = ['Wire.h', 'SPI.h', 'ArduinoJson.h', 'DHT.h', 'HX711.h', 'MAX30105.h', 'spo2_algorithm.h', 'MFRC522.h', 'TinyGPS++.h', 'VOCGasIndexAlgorithm.h']
    text = '#pragma once\n' + ''.join(f'#include <{h}>\n' for h in headers)
    text += '#include "protocols.h"\n#if !WOKWI_BUILD\n#include <BLEDevice.h>\n#endif\nHardwareSerial collectiveSerial1(1),collectiveSerial2(2);\n'
    text += ''.join(driver(p, i) for i, p in enumerate(plans))
    text += '\nstruct Endpoint {const char *id;const char *kind;void (*begin)();void (*tick)();JsonDocument *values;uint32_t *lastValid;uint32_t seq;};\nEndpoint endpoints[]={\n'
    for i, p in enumerate(plans):
        text += f'{{{json.dumps(p["device"]["id"])},{json.dumps(p["device"]["kind"])},endpoint{i}::sensorBegin,endpoint{i}::sensorTick,&endpoint{i}::values,&endpoint{i}::lastValid,0}},\n'
    text += '};\nconstexpr unsigned ENDPOINT_COUNT=sizeof(endpoints)/sizeof(endpoints[0]);\n'
    selects = [p['pins'][5] for p in plans if p['device']['kind'] == 'rfid']
    text += 'void prepareGroupSPI(){\n'
    for pin in selects:
        text += f'pinMode({pin},OUTPUT);digitalWrite({pin},HIGH);\n'
    if selects:
        text += 'SPI.begin();\n'
    text += '}\n'
    (dest / 'endpoints.h').write_text(text, encoding='utf-8')
    for name in ['sketch.ino', 'device_config.h']:
        template = (BASE / 'collective_src' / name).read_text(encoding='utf-8')
        template = template.replace('@ENTITY_ID@', entity['id']).replace('@WOKWI_BUILD@', '0' if hardware else '1')
        (dest / name).write_text(template, encoding='utf-8')
    shutil.copyfile(BASE / 'src/protocols.h', dest / 'protocols.h')
    shutil.copyfile(BASE / 'projects' / devices[0]['id'] / 'libraries.txt', dest / 'libraries.txt')
    toml = '[wokwi]\nversion = 1\nfirmware = "build/sketch.ino.bin"\nelf = "build/sketch.ino.elf"\n'
    for chip in sorted(chips):
        toml += f'\n[[chip]]\nname = "{chip}"\nbinary = "{chip}.chip.wasm"\n'
    (dest / 'wokwi.toml').write_text(toml, encoding='utf-8')
    record = {'id': entity['id'], 'entity_type': entity['type'], 'devices': [{'id': p['device']['id'], 'kind': p['device']['kind'], 'part': f's{i}_sensor', 'pins': p['pins'], 'uart': p['uart']} for i, p in enumerate(plans)]}
    (dest / 'wiring.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--entity')
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--hardware', action='store_true')
    args = parser.parse_args()
    inv = inventory()
    entities = [e for e in inv['entities'] if not args.entity or e['id'] == args.entity]
    if not entities:
        parser.error('Unknown entity')
    records = [export_entity(e, [d for d in inv['devices'] if d['entity_id'] == e['id']], args.out / e['id'], args.hardware) for e in entities]
    manifest = {'schema': 1, 'source': 'hardware' if args.hardware else 'wokwi', 'groups': records, 'device_count': sum(len(r['devices']) for r in records), 'driver_sha256': hashlib.sha256((BASE / 'src/sensors.h').read_bytes() + (BASE / 'src/nibp.h').read_bytes()).hexdigest()}
    (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(f'{len(records)} ESP32 groups / {manifest["device_count"]} independently acquired endpoints')


if __name__ == '__main__':
    main()
