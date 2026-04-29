# Rapport benchmark scalabilite - 2026-04-29

## Objectif

Verifier la capacite du projet EHPAD a absorber une charge temps reel MQTT tout
en gardant une API dashboard reactive.

Deux cibles ont ete testees:

- cible cahier des charges: 120 messages/s;
- projection extension: 300 messages/s.

## Architecture testee

- MQTT Mosquitto pour ingestion capteurs;
- backend FastAPI single-worker;
- Redis pour etat courant residents;
- InfluxDB pour historique echantillonne;
- WebSocket throttle a 2 secondes par resident;
- ML/A2A hors boucle temps reel;
- LLM hors boucle temps reel.

## Test 1 - cible 120 messages/s

Commande:

```bash
docker compose run --rm --no-deps backend python benchmark_scalability.py --target-mps 120 --duration-s 60 --residents 25
```

Resultats:

| Mesure | Valeur |
|---|---:|
| Messages envoyes | 7 198 |
| Erreurs publication MQTT | 0 |
| Debit envoye reel | 116.01 msg/s |
| Debit observe backend | 198.41 msg/s |
| Latence API moyenne | 9.45 ms |
| Latence API p95 | 19.87 ms |
| Latence API p99 | 31.80 ms |
| Latence API max | 35.00 ms |
| CPU backend apres test | 55.29 % |
| RAM backend apres test | 174.9 MiB |

Interpretation:

```text
VALIDÉ pour la cible école.
Le backend absorbe la charge 120 msg/s sans erreur MQTT et avec une latence API
p95 tres basse.
```

## Test 2 - projection 300 messages/s

Commande:

```bash
docker compose run --rm --no-deps backend python benchmark_scalability.py --target-mps 300 --duration-s 60 --residents 50
```

Resultats:

| Mesure | Valeur |
|---|---:|
| Messages envoyes | 17 997 |
| Erreurs publication MQTT | 0 |
| Debit envoye reel | 290.05 msg/s |
| Debit observe backend | 175.29 msg/s |
| Latence API moyenne | 14.32 ms |
| Latence API p95 | 27.75 ms |
| Latence API p99 | 36.69 ms |
| Latence API max | 81.57 ms |
| CPU backend apres test | 85.28 % |
| RAM backend apres test | 182.6 MiB |

Interpretation:

```text
PARTIEL pour l'extension 50 residents.
L'API reste reactive, mais le backend single-worker ne traite pas encore 90%
des messages envoyes a 300 msg/s sur 60 secondes.
```

## Conclusion jury

La cible principale du cahier des charges est validee:

- 120 messages/s supportes;
- 0 erreur publication MQTT;
- API dashboard p95 autour de 20 ms;
- RAM faible;
- backend encore sous marge CPU.

L'extension 50 residents / 300 messages/s est identifiee comme axe
d'industrialisation:

- backend single-worker proche saturation CPU;
- debit observe insuffisant pour garantir 300 msg/s;
- necessite workers separes ingestion/alerting ou scaling horizontal.

## Phrase a utiliser a l'oral

```text
La scalabilite demandee par le sujet est validee par benchmark: 120 messages/s
pendant 60 secondes, sans erreur MQTT, avec une latence API p95 inferieure a
20 ms. Nous avons aussi teste une projection 50 residents a 300 messages/s:
l'API reste reactive, mais le backend single-worker ne traite pas encore toute
la charge, ce qui justifie l'axe d'amelioration vers des workers d'ingestion ou
un scaling horizontal.
```
