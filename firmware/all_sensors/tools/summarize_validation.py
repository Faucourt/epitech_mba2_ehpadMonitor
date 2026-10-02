"""Check recorded Wokwi evidence against compiled firmware and list saved benches."""
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main():
    inventory = json.loads((BASE / 'inventory.json').read_text(encoding='utf-8'))
    compiled = {r['kind']: r for r in json.loads((BASE / 'validation/compilation.json').read_text())}
    kinds = sorted({d['kind'] for d in inventory['devices']})
    rows = []
    for kind in kinds:
        path = BASE / 'validation/wokwi' / (kind + '.json')
        report = json.loads(path.read_text(encoding='utf-8'))
        assert report['firmware_sha256'] == compiled[kind]['firmware_sha256'], kind
        assert re.fullmatch(r'https://wokwi.com/projects/\d+', report['url']), kind
        trace = [json.loads(line) for line in path.with_suffix('.jsonl').read_text().splitlines() if line]
        assert len(report['cases']) >= 2, kind
        for case in report['cases']:
            assert case['result'] == 'pass' and case['mqtt_received'] is True, (kind, case)
            assert case['sample'] in trace, (kind, 'sample absent from serial trace')
        rows.append(report)
    total = sum(len(r['cases']) for r in rows)
    summary = {'families': len(kinds), 'scenarios': total, 'configured_endpoints': len(inventory['devices']),
               'scope': 'One ESP32 Wokwi bench per active family; not 437 concurrent ESP32 simulations.',
               'results': rows}
    (BASE / 'validation/wokwi-results.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# Bancs Wokwi vérifiés', '',
             f'{len(kinds)} familles, {total} scénarios réussis avec réception MQTT dans le backend local.',
             'Chaque empreinte du firmware correspond à la matrice de compilation. Les traces série et les échantillons reçus sont conservés dans `wokwi/`.', '',
             '**Portée :** un banc ESP32 exécuté par famille. Les 437 configurations couvrent les 25 résidents et 20 zones ; elles ne tournent pas simultanément.', '',
             'Ouvrir un lien puis démarrer la simulation (▶). Le banc publie pour l’identifiant indiqué, pas pour les autres résidents. Le dashboard local doit écouter le même courtier MQTT.', '',
             '| Famille | Identifiant du banc | Scénarios réussis | Projet |', '|---|---|---:|---|']
    for r in rows:
        lines.append(f"| {r['kind']} | `{r['device_id']}` | {len(r['cases'])} | [Ouvrir Wokwi]({r['url']}) |")
    lines += ['', '## Commandes particulières', '',
              '- Tensiomètre PAR : attendre 8 secondes simulées au démarrage, puis presser START. STOP annule le cycle. Les curseurs règlent systolique, diastolique et erreurs. Aucune inflation automatique au démarrage.',
              '- RFID : maintenir la carte avec Hold pour une lecture reproductible. Le bref Tap de 500 ms peut être manqué lorsque le navigateur simule plus lentement que le temps réel. La présence d’un UID signifie une lecture récente, pas une localisation continue.',
              '- SGP40 : attendre la phase de stabilisation de l’algorithme avant l’indice COV. Le signal brut est disponible avant l’indice.',
              '- BLE : ce banc teste un adaptateur I²C de données MAC/RSSI. Wokwi ne valide pas la radio BLE ; le scanner BLE réel a été compilé séparément.',
              '- MQ-2 : le raccordement ADC direct est uniquement simulé. Le montage physique nécessite le pont diviseur décrit dans le README.', '',
              'Ces essais valident les échanges de données du prototype. Aucun capteur physique, brassard pneumatique ou algorithme clinique n’a été validé par ces simulations.', '']
    (BASE / 'validation/WOKWI.md').write_text('\n'.join(lines), encoding='utf-8')
    print(f'{len(kinds)} families / {total} scenarios / firmware hashes and serial evidence verified')


if __name__ == '__main__':
    main()
