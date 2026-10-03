"""Supervise real Wokwi CLI processes and verify their MQTT reception.

This program forwards actual virtual UART samples to local MQTT, without changing
payloads, generating values, replaying old samples, or cloning resident readings.
Credentials remain in the environment; logs and status files redact tokens.
"""
import argparse
import asyncio
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import shutil
import signal
import ssl
import time
import urllib.request
from build_collective import source_hash
from export_collective import OUT, ROOT, select_groups


def token_from_environment():
    value = os.environ.get('WOKWI_CLI_TOKEN', '').strip()
    if not value and os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
                value = winreg.QueryValueEx(key, 'WOKWI_CLI_TOKEN')[0].strip()
        except FileNotFoundError:
            pass
    return value


def redact(text, secret=''):
    if secret:
        text = text.replace(secret, '[REDACTED]')
    return re.sub(r'wok_[A-Za-z0-9_-]+', '[REDACTED]', text)


def cli_environment(secret, output):
    env = dict(os.environ, WOKWI_CLI_TOKEN=secret)
    if os.name == 'nt' and not env.get('NODE_EXTRA_CA_CERTS'):
        # Trust the same server-authentication roots as Windows, without disabling TLS.
        roots = [ssl.DER_cert_to_PEM_cert(cert) for cert, encoding, trust
                 in ssl.enum_certificates('ROOT')
                 if encoding == 'x509_asn' and
                 (trust is True or ssl.Purpose.SERVER_AUTH.oid in trust)]
        bundle = output / 'windows-ca.pem'
        bundle.write_text(''.join(roots), encoding='ascii')
        env['NODE_EXTRA_CA_CERTS'] = str(bundle.resolve())
    return env


def read_snapshot(api):
    with urllib.request.urlopen(api.rstrip('/') + '/api/hardware/snapshot?source=wokwi', timeout=5) as response:
        return json.load(response)


def coverage(snapshot, expected, boots, now=None):
    """Count only recent backend receipts from this run's actual simulator boots."""
    now = time.time() if now is None else now
    connected, measured = set(), set()
    for entity in snapshot.get('entities', []):
        for device in entity.get('devices', []):
            ident = device['id']
            if ident not in expected or not boots.get(ident) or device.get('boot') != boots[ident]:
                continue
            received = device.get('received_at')
            if received is None or not 0 <= now - received <= 15 or device.get('status') == 'offline':
                continue
            connected.add(ident)
            if device.get('status') == 'live':
                measured.add(ident)
    return connected, measured


def atomic_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temporary.replace(path)


class Fleet:
    def __init__(self, args, groups, secret):
        self.args, self.groups, self.secret = args, groups, secret
        self.stop = asyncio.Event()
        self.states = {g['id']: {'state': 'queued', 'restarts': 0, 'boot': None, 'last_serial_at': None} for g in groups}
        self.processes = {}
        self.boots = {}
        self.expected = {d['id'] for g in groups for d in g['devices']}
        self.started = time.time()
        self.last_complete = None
        self.complete_since = None
        self.best_connected = 0
        self.error = None
        self.mqtt = None
        self.args.output.mkdir(parents=True, exist_ok=True)
        self.cli_env = cli_environment(secret, self.args.output)

    async def pause(self, seconds):
        try:
            await asyncio.wait_for(self.stop.wait(), seconds)
        except asyncio.TimeoutError:
            pass

    async def worker(self, group, slot):
        ident = group['id']
        state = self.states[ident]
        allowed = {d['id'] for d in group['devices']}
        logger = logging.getLogger('wokwi.' + ident)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = RotatingFileHandler(self.args.output / f'{ident}.log', maxBytes=1000000, backupCount=2, encoding='utf-8')
        logger.addHandler(handler)
        async with slot:
            attempt = 0
            while not self.stop.is_set():
                state.update(state='starting', boot=None, last_serial_at=None)
                for device in allowed:
                    self.boots.pop(device, None)
                env = self.cli_env
                command = [self.args.cli, str(self.args.projects / ident), '--timeout', str(self.args.session_seconds * 1000), '--timeout-exit-code', '0']
                try:
                    process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env)
                except OSError as error:
                    state.update(state='failed', error=redact(str(error), self.secret))
                    self.error = 'Cannot start Wokwi CLI'
                    self.stop.set()
                    break
                self.processes[ident] = process
                state.update(state='running', pid=process.pid, started_at=time.time())
                last_serial = time.monotonic()
                fatal = False
                while not self.stop.is_set():
                    timeout = self.args.serial_timeout if state['last_serial_at'] else 300
                    if time.monotonic() - last_serial > timeout:
                        state['error'] = 'No valid sensor frame; restarting simulator'
                        break
                    try:
                        line = await asyncio.wait_for(process.stdout.readline(), timeout=1)
                    except asyncio.TimeoutError:
                        if process.returncode is not None:
                            break
                        continue
                    if not line:
                        break
                    line = redact(line.decode('utf-8', errors='replace').strip(), self.secret)
                    logger.info(line)
                    lowered = line.lower()
                    if 'unable to verify the first certificate' in lowered:
                        self.error = 'Wokwi TLS trust failed; check Windows roots or NODE_EXTRA_CA_CERTS'
                        fatal = True
                        self.stop.set()
                    if any(term in lowered for term in ['invalid token', 'unauthorized', 'quota exceeded', 'monthly ci minute quota', 'out of simulation', 'no simulation time', 'insufficient simulation', 'payment required']):
                        self.error = 'Wokwi access or simulation quota refused; automatic retries stopped'
                        fatal = True
                        self.stop.set()
                    if line.startswith(('PUB ', 'SAMPLE ')):
                        try:
                            payload = line.split(' ', 1)[1]
                            row = json.loads(payload)
                            if not isinstance(row, dict):
                                raise ValueError('Expected a sensor object')
                            if row.get('entity_id') != ident or row.get('device_id') not in allowed or row.get('source') != 'wokwi':
                                raise ValueError('Unexpected endpoint identity')
                            if not row.get('boot'):
                                continue
                            last_serial = time.monotonic()
                            state['last_serial_at'] = time.time()
                            if line.startswith('SAMPLE '):
                                if not self.mqtt.is_connected():
                                    state['mqtt_dropped'] = state.get('mqtt_dropped', 0) + 1
                                    continue
                                # Exact payload, live-only QoS0: no retained or queued replay.
                                sent = self.mqtt.publish('ehpad/lab/lebretyves-all/v1/' + row['device_id'] + '/telemetry', payload, qos=0, retain=False)
                                if sent.rc != 0:
                                    state['mqtt_dropped'] = state.get('mqtt_dropped', 0) + 1
                                    continue
                            self.boots[row['device_id']] = row['boot']
                            state['boot'] = row['boot']
                            state['last_serial_at'] = time.time()
                        except (ValueError, TypeError):
                            state['invalid_serial_frames'] = state.get('invalid_serial_frames', 0) + 1
                if process.returncode is None:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), 5)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
                else:
                    await process.wait()
                self.processes.pop(ident, None)
                state['exit_code'] = process.returncode
                if self.stop.is_set() or fatal:
                    state['state'] = 'stopped'
                    break
                state['state'] = 'restarting'
                state['restarts'] += 1
                attempt = attempt + 1 if process.returncode else 0
                if attempt >= 5:
                    state['state'] = 'failed'
                    self.error = f'Wokwi repeatedly failed for {ident}; fleet stopped'
                    self.stop.set()
                    break
                await self.pause(min(60, 2 ** attempt))
        handler.close()
        logger.removeHandler(handler)

    async def monitor(self):
        while not self.stop.is_set():
            now = time.time()
            connected, measured = set(), set()
            api_error = None
            try:
                snapshot = await asyncio.to_thread(read_snapshot, self.args.api)
                connected, measured = coverage(snapshot, self.expected, self.boots)
                if len(connected) == len(self.expected):
                    self.last_complete = now
                    if self.complete_since is None:
                        self.complete_since = now
                else:
                    self.complete_since = None
            except Exception as error:
                api_error = redact(str(error), self.secret)
                self.complete_since = None
            self.best_connected = max(self.best_connected, len(connected))
            report = {'source': 'real-wokwi-cli', 'started_at': self.started, 'updated_at': now,
                      'expected_groups': len(self.groups), 'expected_devices': len(self.expected),
                      'connected_devices': len(connected), 'devices_with_recent_measurement': len(measured),
                      'missing_devices': sorted(self.expected - connected), 'best_connected': self.best_connected,
                      'last_complete_at': self.last_complete, 'complete_for_seconds': round(now - self.complete_since, 1) if self.complete_since else 0,
                      'api_error': api_error, 'error': self.error, 'groups': self.states}
            atomic_json(self.args.output / 'status.json', report)
            print(f'Wokwi MQTT: {len(connected)}/{len(self.expected)} communicating, {len(measured)} with recent measurements', flush=True)
            if self.args.verify_seconds and self.complete_since and now - self.complete_since >= self.args.verify_seconds:
                report['result'] = 'passed'
                atomic_json(self.args.output / 'verification.json', report)
                if self.args.stop_after_verify:
                    self.stop.set()
            if self.args.seconds and now - self.started >= self.args.seconds:
                self.stop.set()
            if self.error:
                self.stop.set()
            await self.pause(3)

    async def run(self):
        import paho.mqtt.client as mqtt
        self.mqtt = mqtt.Client(client_id='ehpad-collective-gateway-' + str(os.getpid()))
        self.mqtt.reconnect_delay_set(1, 10)
        self.mqtt.connect(self.args.mqtt_host, self.args.mqtt_port, 30)
        self.mqtt.loop_start()
        for _ in range(50):
            if self.mqtt.is_connected():
                break
            await asyncio.sleep(.1)
        if not self.mqtt.is_connected():
            self.mqtt.loop_stop()
            raise RuntimeError('Local MQTT gateway connection failed')
        loop = asyncio.get_running_loop()
        for sig in [signal.SIGINT, signal.SIGTERM]:
            try:
                loop.add_signal_handler(sig, self.stop.set)
            except (NotImplementedError, RuntimeError):
                signal.signal(sig, lambda *_: loop.call_soon_threadsafe(self.stop.set))
        slot = asyncio.Semaphore(self.args.concurrency)
        monitor = asyncio.create_task(self.monitor())
        tasks = [asyncio.create_task(self.worker(group, slot)) for group in self.groups]
        try:
            await asyncio.gather(*tasks, monitor)
        finally:
            self.stop.set()
            for process in list(self.processes.values()):
                if process.returncode is None:
                    process.terminate()
            await asyncio.gather(*(p.wait() for p in self.processes.values()), return_exceptions=True)
            self.mqtt.disconnect()
            self.mqtt.loop_stop()
            status_path = self.args.output / 'status.json'
            report = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {}
            report.update(updated_at=time.time(), stopped_at=time.time(),
                          error=self.error, groups=self.states, state='stopped',
                          connected_devices=0, devices_with_recent_measurement=0,
                          missing_devices=sorted(self.expected))
            atomic_json(status_path, report)
        if self.error:
            raise RuntimeError(self.error)
        if self.args.verify_seconds and not (self.args.output / 'verification.json').exists():
            raise RuntimeError('Full MQTT coverage was not sustained for the required duration')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--projects', type=Path, default=OUT)
    parser.add_argument('--entity', action='append')
    parser.add_argument('--pilot', action='store_true', help='R001-R003 and all 20 environmental zones')
    parser.add_argument('--api', default='http://localhost:8005')
    parser.add_argument('--mqtt-host', default='127.0.0.1')
    parser.add_argument('--mqtt-port', type=int, default=1887)
    parser.add_argument('--cli', default=shutil.which('wokwi-cli') or str(Path(os.environ.get('LOCALAPPDATA', '.')) / 'WokwiCLI/wokwi-cli.exe'))
    parser.add_argument('--concurrency', type=int, default=45)
    parser.add_argument('--seconds', type=int, default=120, help='Wall-clock duration; 0 means continuous')
    parser.add_argument('--session-seconds', type=int, default=300, help='Simulation time per CLI session before renewal')
    parser.add_argument('--serial-timeout', type=int, default=60, help='Restart after this many wall seconds without sensor frames')
    parser.add_argument('--verify-seconds', type=int, default=30)
    parser.add_argument('--stop-after-verify', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/collective-runtime')
    parser.add_argument('--check', action='store_true', help='Validate inputs without starting cloud simulations')
    args = parser.parse_args()
    if args.concurrency < 1 or args.seconds < 0 or args.session_seconds < 1 or args.verify_seconds < 0 or args.serial_timeout < 5:
        parser.error('Invalid duration or concurrency')
    manifest = json.loads((args.projects / 'manifest.json').read_text())
    if manifest['source'] != 'wokwi':
        parser.error('This launcher only accepts Wokwi simulation exports')
    try:
        groups = select_groups(manifest['groups'], args.entity, args.pilot)
    except ValueError as error:
        parser.error(str(error))
    report_path = args.projects / 'compilation.json'
    compiled = json.loads(report_path.read_text()) if report_path.exists() else {}
    for group in groups:
        project = args.projects / group['id']
        build = compiled.get(group['id'], {})
        binary = project / 'build/sketch.ino.bin'
        if not binary.exists() or build.get('source_sha256') != source_hash(project) or build.get('firmware_sha256') != hashlib.sha256(binary.read_bytes()).hexdigest():
            parser.error('Missing or stale compiled firmware: ' + group['id'])
    print(f'{len(groups)} groups, {sum(len(g["devices"]) for g in groups)} independently acquired endpoints')
    if args.check:
        print('Firmware inputs verified; no simulation started and no token used')
        return
    token = token_from_environment()
    if not re.fullmatch(r'wok_[A-Za-z0-9_-]{40}', token):
        parser.error('Configure a valid WOKWI_CLI_TOKEN in the user environment; do not put it in source files')
    # Fail before consuming cloud quota if the local receiver is inaccessible.
    read_snapshot(args.api)
    if (args.output / 'verification.json').exists():
        (args.output / 'verification.json').unlink()
    try:
        asyncio.run(Fleet(args, groups, token).run())
    except (RuntimeError, KeyboardInterrupt) as error:
        raise SystemExit(redact(str(error), token))


if __name__ == '__main__':
    main()
