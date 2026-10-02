import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'firmware/all_sensors/tools'))
import export_collective as exporter
from run_collective import coverage, redact


class CollectiveTests(unittest.TestCase):
    def test_pilot_contains_three_complete_residents_and_all_environment(self):
        manifest = json.loads((exporter.OUT / 'manifest.json').read_text())
        groups = exporter.select_groups(manifest['groups'], pilot=True)
        self.assertEqual(23, len(groups))
        self.assertEqual({'R001', 'R002', 'R003'}, {g['id'] for g in groups if g['entity_type'] == 'resident'})
        self.assertEqual(20, sum(g['entity_type'] == 'zone' for g in groups))
        self.assertEqual(214, sum(len(g['devices']) for g in groups))
        for group in groups:
            self.assertEqual(next(g for g in manifest['groups'] if g['id'] == group['id']), group)
        with self.assertRaises(ValueError):
            exporter.select_groups(manifest['groups'], entities=['missing'])
        with self.assertRaises(ValueError):
            exporter.select_groups(manifest['groups'], entities=['R001'], pilot=True)

    def test_all_437_endpoints_belong_to_exactly_one_entity(self):
        inv = exporter.inventory()
        manifest = json.loads((exporter.OUT / 'manifest.json').read_text())
        self.assertEqual(45, len(manifest['groups']))
        actual = []
        for group in manifest['groups']:
            expected = {d['id'] for d in inv['devices'] if d['entity_id'] == group['id']}
            self.assertEqual(expected, {d['id'] for d in group['devices']})
            actual.extend(d['id'] for d in group['devices'])
        self.assertEqual(437, len(actual))
        self.assertEqual(437, len(set(actual)))

    def test_no_gpio_collisions_and_uart_instances_are_independent(self):
        inv = exporter.inventory()
        for entity in inv['entities']:
            plans = exporter.allocate([d for d in inv['devices'] if d['entity_id'] == entity['id']])
            occupied, serials = {}, set()
            for p in plans:
                kind = p['device']['kind']
                for old, pin in p['pins'].items():
                    shared = (kind in exporter.I2C and old in {21, 22}) or (kind == 'rfid' and old in {18, 19, 23})
                    if shared:
                        continue
                    self.assertNotIn(pin, occupied, (entity['id'], occupied, p))
                    occupied[pin] = p['device']['id']
                    self.assertNotIn(pin, {0, 1, 2, 3, 6, 7, 8, 9, 10, 11, 12})
                if p['uart'] is not None:
                    self.assertNotIn(p['uart'], serials)
                    serials.add(p['uart'])
                if kind in exporter.ADC:
                    self.assertIn(p['pins'][34], exporter.ADC_PINS)

    def test_diagrams_have_every_declared_pin_and_unique_parts(self):
        manifest = json.loads((exporter.OUT / 'manifest.json').read_text())
        for group in manifest['groups']:
            diagram = json.loads((exporter.OUT / group['id'] / 'diagram.json').read_text())
            ids = [p['id'] for p in diagram['parts']]
            self.assertEqual(len(ids), len(set(ids)))
            for device in group['devices']:
                self.assertIn(device['part'], ids)
                pins = {str(p) for p in device['pins'].values()}
                actual = {{'VP': '36', 'VN': '39'}.get(end.split(':', 1)[1], end.split(':', 1)[1]) for wire in diagram['connections'] for end in wire[:2] if end.startswith('esp:')}
                self.assertTrue(pins <= actual, device)
            self.assertFalse(any(end in {'esp:36', 'esp:39'} for wire in diagram['connections'] for end in wire[:2]))

    def test_two_rfid_readers_use_different_select_and_reset(self):
        inv = exporter.inventory()
        plans = exporter.allocate([d for d in inv['devices'] if d['entity_id'] == 'entree'])
        readers = [p for p in plans if p['device']['kind'] == 'rfid']
        self.assertEqual(2, len(readers))
        self.assertNotEqual(readers[0]['pins'][5], readers[1]['pins'][5])
        self.assertNotEqual(readers[0]['pins'][22], readers[1]['pins'][22])

    def test_backend_coverage_requires_current_boot_and_actual_recent_receipt(self):
        devices = [
            {'id': 'A', 'boot': 'run1', 'status': 'live', 'received_at': 98},
            {'id': 'B', 'boot': 'old', 'status': 'live', 'received_at': 98},
            {'id': 'C', 'boot': 'run1', 'status': 'live', 'received_at': 80},
            {'id': 'D', 'boot': 'run1', 'status': 'unavailable', 'received_at': 98},
            {'id': 'E', 'boot': 'run1', 'status': 'offline', 'received_at': 98},
        ]
        connected, measured = coverage({'entities': [{'devices': devices}]}, set('ABCDE'), dict.fromkeys('ABCDE', 'run1'), now=100)
        self.assertEqual({'A', 'D'}, connected)
        self.assertEqual({'A'}, measured)

    def test_secrets_are_redacted_from_logs(self):
        token = 'wok_' + 'a' * 40
        self.assertEqual('error [REDACTED]', redact('error ' + token, token))
        self.assertNotIn('wok_', redact('another wok_not-a-real-token'))


if __name__ == '__main__':
    unittest.main()
