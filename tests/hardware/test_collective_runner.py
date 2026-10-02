"""Supervisor tests use fake processes, never claim to run a Wokwi simulation."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'firmware/all_sensors/tools'))
from run_collective import Fleet


class FakeProcess:
    def __init__(self, lines, code=0):
        self.pid = 1
        self.returncode = code
        self.stdout = asyncio.StreamReader()
        for line in lines:
            self.stdout.feed_data((line + '\n').encode())
        self.stdout.feed_eof()

    def terminate(self):
        self.returncode = -1

    def kill(self):
        self.returncode = -9

    async def wait(self):
        return self.returncode


class FakeMQTT:
    def __init__(self):
        self.sent = []

    def is_connected(self):
        return True

    def publish(self, topic, payload, **options):
        self.sent.append((topic, payload, options))
        return SimpleNamespace(rc=0)


class SupervisorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        args = SimpleNamespace(output=Path(self.temp.name), projects=Path(self.temp.name), cli='fake-wokwi', session_seconds=30, serial_timeout=60)
        self.group = {'id': 'R001', 'devices': [{'id': 'R001-sensor'}]}
        self.fleet = Fleet(args, [self.group], 'wok_' + 'x' * 40)
        self.fleet.mqtt = FakeMQTT()

    async def stop_at_restart(self, _):
        self.fleet.stop.set()

    async def test_only_matching_actual_frames_are_forwarded_unchanged(self):
        good = {'source': 'wokwi', 'entity_id': 'R001', 'device_id': 'R001-sensor', 'boot': 'current', 'values': {'heart_rate': 78}}
        lines = ['SAMPLE []', 'SAMPLE ' + json.dumps({**good, 'entity_id': 'R002'}), 'SAMPLE ' + json.dumps(good)]
        self.fleet.pause = self.stop_at_restart
        with patch('run_collective.asyncio.create_subprocess_exec', AsyncMock(return_value=FakeProcess(lines))):
            await self.fleet.worker(self.group, asyncio.Semaphore(1))
        self.assertEqual([('ehpad/lab/lebretyves-all/v1/R001-sensor/telemetry', json.dumps(good), {'qos': 0, 'retain': False})], self.fleet.mqtt.sent)
        self.assertEqual({'R001-sensor': 'current'}, self.fleet.boots)
        self.assertEqual(2, self.fleet.states['R001']['invalid_serial_frames'])

    async def test_quota_failure_stops_without_retry_and_redacts_token(self):
        proc = FakeProcess(['quota exceeded ' + self.fleet.secret], code=1)
        with patch('run_collective.asyncio.create_subprocess_exec', AsyncMock(return_value=proc)) as spawn:
            await self.fleet.worker(self.group, asyncio.Semaphore(1))
        self.assertEqual(1, spawn.await_count)
        self.assertTrue(self.fleet.stop.is_set())
        self.assertNotIn(self.fleet.secret, (self.fleet.args.output / 'R001.log').read_text())

    async def test_five_process_failures_stop_the_fleet(self):
        self.fleet.pause = AsyncMock()
        with patch('run_collective.asyncio.create_subprocess_exec', AsyncMock(side_effect=lambda *a, **k: FakeProcess([], code=1))) as spawn:
            await self.fleet.worker(self.group, asyncio.Semaphore(1))
        self.assertEqual(5, spawn.await_count)
        self.assertTrue(self.fleet.stop.is_set())
        self.assertEqual('failed', self.fleet.states['R001']['state'])

    async def test_serial_watchdog_restarts_a_silent_process(self):
        proc = FakeProcess([], code=None)
        self.fleet.pause = self.stop_at_restart
        # Override only the supervisor's clock, not asyncio's shared clock.
        clock = SimpleNamespace(time=lambda: 1000, monotonic=iter([0, 61]).__next__)
        with patch('run_collective.time', clock), patch('run_collective.asyncio.create_subprocess_exec', AsyncMock(return_value=proc)):
            await self.fleet.worker(self.group, asyncio.Semaphore(1))
        self.assertEqual(-1, proc.returncode)
        self.assertEqual(1, self.fleet.states['R001']['restarts'])
        self.assertIn('No valid sensor frame', self.fleet.states['R001']['error'])
        self.assertEqual([], self.fleet.mqtt.sent)
