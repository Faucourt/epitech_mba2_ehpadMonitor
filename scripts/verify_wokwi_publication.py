"""Recheck the 45 downloaded Wokwi projects offline, from any checkout location."""
import hashlib
import importlib.util
import json
from pathlib import Path, PureWindowsPath
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PUBLICATION = ROOT / 'output/wokwi-transfert'


def main():
    spec = importlib.util.spec_from_file_location('wokwi_zip', PUBLICATION / 'verify_wokwi_zip.py')
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    index = json.loads((PUBLICATION / 'pages-corrigees.json').read_text(encoding='utf8'))
    projects = index['projects']
    assert len(projects) == 45
    assert len({row['entity'] for row in projects}) == 45
    assert len({row['page_corrigee'] for row in projects}) == 45
    count = 0
    for row in projects:
        entity = row['entity']
        assert row['status'] == 'verified', entity
        report = json.loads((PUBLICATION / 'verified' / f'{entity}-full-comparison.json').read_text(encoding='utf8'))
        archive = PUBLICATION / 'verified' / PureWindowsPath(report['archive_copy']).name
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == report['zip_sha256'], entity
        downloaded, duplicates = verifier.read_archive(archive)
        expected = {p.name: p.read_bytes() for p in (PUBLICATION / 'upload' / entity).iterdir() if p.is_file()}
        original = None
        if report['policy'].get('r001_original_esp_left_allowed'):
            assert entity == 'R001'
            original_zip = PUBLICATION / 'backups' / PureWindowsPath(report['policy']['original_diagram_backup']).name
            original = verifier.read_archive(original_zip)[0]['diagram.json']
        checked = verifier.compare(expected, downloaded, duplicates, original,
                                   report['policy'].get('crlf_normalization_allowed', False))
        assert checked['status'] == 'passed', (entity, checked['mismatched_files'])
        metadata = downloaded['wokwi-project.txt'].decode('utf-8-sig')
        assert re.findall(r'https://wokwi\.com/projects/[0-9]+', metadata)[0] == row['page_corrigee'], entity
        for name, payload in expected.items():
            local = ROOT / 'firmware/all_sensors/collective' / entity / name
            assert local.read_bytes().replace(b'\r\n', b'\n') == payload.replace(b'\r\n', b'\n'), (entity, name)
        count += len(expected)
    assert count == 733
    archive = ROOT / 'output/sauvegardes-wokwi/WOKWI-REPRISE-DERNIERE.zip'
    expected_hash = archive.with_suffix('.sha256').read_text().split()[0]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected_hash
    with zipfile.ZipFile(archive) as backup:
        assert backup.testzip() is None
        state = json.loads(backup.read('wokwi-transfert/REPRISE-WOKWI.json'))
        assert state['verified_count'] == 45
    print(json.dumps({'projects': 45, 'source_files': count, 'unique_urls': 45,
                      'local_collective_sources': 'match', 'backup_integrity': 'passed'}))


if __name__ == '__main__':
    main()
