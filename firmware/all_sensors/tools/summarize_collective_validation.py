"""Validate archived browser/UART/backend evidence, without starting simulations."""
import hashlib
import json
from pathlib import Path
import re

BASE = Path(__file__).resolve().parents[1]
EVIDENCE = BASE / 'validation/collective'


def text_hash(path):
    return hashlib.sha256(path.read_text(encoding='utf-8').encode('utf-8')).hexdigest()


def source_text_hash(project):
    digest = hashlib.sha256()
    for path in sorted(project.iterdir()):
        if path.suffix in {'.ino', '.h'} or path.name == 'libraries.txt':
            digest.update(path.name.encode())
            digest.update(path.read_text(encoding='utf-8').encode('utf-8'))
    return digest.hexdigest()


def main():
    inventory = json.loads((BASE / 'inventory.json').read_text(encoding='utf-8'))
    groups = [e for e in inventory['entities'] if e['type'] == 'zone' or e['id'] in {'R001', 'R002', 'R003'}]
    devices = {d['id']: d for d in inventory['devices']}
    compiled = json.loads((BASE / 'collective/compilation.json').read_text())
    reports = []
    for group in groups:
        ident = group['id']
        report = json.loads((EVIDENCE / f'{ident}.json').read_text(encoding='utf-8'))
        trace = [json.loads(line) for line in (EVIDENCE / f'{ident}.jsonl').read_text().splitlines() if line]
        expected = {d['id'] for d in devices.values() if d['entity_id'] == ident}
        assert report['entity'] == ident and report['actual_wokwi_browser'] is True, ident
        assert re.fullmatch(r'https://wokwi.com/projects/\d+', report['url']), ident
        assert report['firmware_sha256'] == compiled[ident]['firmware_sha256'], ident
        project = BASE / 'collective' / ident
        assert report['diagram_text_sha256'] == text_hash(project / 'diagram.json'), ident
        assert report['source_text_sha256'] == source_text_hash(project), ident
        assert set(report['expected_ids']) == set(report['endpoint_ids']) == expected, ident
        assert set(report['backend_current_boot_ids']) == expected and report['complete_communication'], ident
        seen = {device: set() for device in expected}
        frames = {}
        for row in trace:
            device = row['device_id']
            assert device in expected and row['entity_id'] == ident and row['kind'] == devices[device]['kind'], ident
            assert row['source'] == 'wokwi' and row['schema'] == 1 and row['boot'] and row['seq'] > 0, ident
            assert set(row['values']) <= set(devices[device]['fields']), device
            frames[(device, row['boot'], row['seq'])] = row
            if row['available']:
                seen[device].update(key for key, value in row['values'].items() if value is not None)
        for device in expected:
            assert seen[device] == set(devices[device]['fields']) == set(report['fields'][device]), device
        assert report['all_fields_observed'] and not report['missing_fields'], ident
        for received in report['backend']:
            assert received['boot'] == trace[-1]['boot'], received['id']
            frame = frames[(received['id'], received['boot'], received['seq'])]
            if received['status'] == 'live':
                assert received['values'] == frame['values'], received['id']
        reports.append(report)
    observation = json.loads((EVIDENCE / 'simultaneous-observation.json').read_text())
    assert observation['communication_passed'] and observation['communication_held_seconds'] >= 30
    assert set(observation['expected']) == {'R001', 'R002', 'R003', 'entree'}
    count = sum(len(r['expected_ids']) for r in reports)
    assert len(reports) == 23 and count == 214
    print(f'{len(reports)} browser projects / {count} independent endpoints: serial fields and backend receipts verified')
    print('Scope: sequential zone tests; simultaneous observation covers three residents and entrance only')


if __name__ == '__main__':
    main()
