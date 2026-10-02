"""Compile collective firmware, with a cache and verifiable per-entity hashes."""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from export_collective import BASE, ROOT, OUT, select_groups


def source_hash(project):
    digest = hashlib.sha256()
    for path in sorted(project.iterdir()):
        if path.suffix in {'.ino', '.h'} or path.name == 'libraries.txt':
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cli', default='arduino-cli')
    parser.add_argument('--entity', action='append')
    parser.add_argument('--pilot', action='store_true', help='R001-R003 and all 20 environmental zones')
    parser.add_argument('--projects', type=Path, default=OUT)
    args = parser.parse_args()
    groups = json.loads((args.projects / 'manifest.json').read_text())['groups']
    try:
        groups = select_groups(groups, args.entity, args.pilot)
    except ValueError as error:
        parser.error(str(error))
    report_path = args.projects / 'compilation.json'
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    for group in groups:
        entity = group['id']
        if args.entity and entity not in args.entity:
            continue
        project = args.projects / entity
        digest = source_hash(project)
        binary = project / 'build/sketch.ino.bin'
        previous = report.get(entity, {})
        if previous.get('source_sha256') == digest and binary.exists() and previous.get('firmware_sha256') == hashlib.sha256(binary.read_bytes()).hexdigest():
            print(f'{entity}: verified cached build', flush=True)
            continue
        start = time.monotonic()
        result = subprocess.run([sys.executable, str(BASE / 'tools/build.py'), str(project), '--cli', args.cli,
                                 '--reuse-build', str(ROOT / 'build/collective-cache')], capture_output=True, text=True)
        report[entity] = {'source_sha256': digest, 'exit_code': result.returncode, 'seconds': round(time.monotonic() - start, 1),
                          'stdout': result.stdout[-2000:], 'stderr': result.stderr[-2000:]}
        if result.returncode == 0:
            report[entity]['firmware_sha256'] = hashlib.sha256(binary.read_bytes()).hexdigest()
        report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(f'{entity}: {"PASS" if result.returncode == 0 else "FAIL"} ({report[entity]["seconds"]}s)', flush=True)
        if result.returncode:
            print(result.stderr)
            raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
