# Documentation technique — EHPAD Monitor

## Alignement plan

Le projet couvre 25 résidents sur 2 niveaux (RDC chambres 101-108, 1er étage chambres 201-220).
Le simulateur publie le mapping MQTT `ehpad/{zone}/{resident_id}/{type_capteur}` pour `vitals`, `motion`, `bp_temp`, `sos`, `ambient/env` et `door/ambient`.

## 1. Flux de données

```
[Simulateur Python]
  ResidentSimulator.tick() → état JSON
    └─ publish MQTT → ehpad/residents/R001/vitals  (QoS 1)
                    → ehpad/residents/R001/critical (QoS 2, si chute/SOS)

[Backend FastAPI — thread MQTT]
  on_message() → _handle_vitals(state)
    ├─ ml_predictor.predict() → ml_risk (float 0-1)
    ├─ redis.setex(resident:R001:state, 30s, json)
    ├─ alert_engine.evaluate(state) → Alert|None
    │     └─ règles vitaux → niveau 1-5
    ├─ write_influx(state) → séries temporelles
    └─ ws_manager.broadcast() → dashboard WebSocket

[Thread d'escalade — toutes les 15s]
  alert_engine.check_escalations()
    └─ alertes non acquittées depuis X min → niveau+1

[Rapport LLM — à la demande]
  GET /api/llm/report/{id}
    └─ appel Ollama local (Meditron:7b) → rapport médical en français
```

## 2. Modèle de données

### Message MQTT vitaux
```json
{
  "resident_id": "R001",
  "name": "Marguerite Dupont",
  "room": "101",
  "timestamp": "2026-03-15T14:32:01Z",
  "vitals": {
    "heart_rate": 82,
    "spo2": 94.2,
    "blood_pressure_sys": 148,
    "temperature": 37.1
  },
  "movement": {
    "accel_magnitude": 0.42,
    "is_fall_detected": false,
    "last_movement_ago_s": 120,
    "is_sleeping": false
  },
  "location": "chambre_101",
  "scenario_active": null,
  "caregiver": "soignant_A"
}
```

### Alerte (Redis + WebSocket)
```json
{
  "id": "ALT-1710507121-0003",
  "resident_id": "R001",
  "resident_name": "Marguerite Dupont",
  "room": "101",
  "caregiver": "soignant_A",
  "level": 3,
  "level_name": "Alerte",
  "color": "orange",
  "reason": "SpO2 < 93% — SpO2=91.5%, FC=118, PA=148",
  "trigger_data": { "vitals": {}, "ml_risk": 0.72 },
  "created_at": "2026-03-15T14:32:01Z",
  "acknowledged": false,
  "escalated_from": 2,
  "resolved": false,
  "time_since_s": 45
}
```

## 3. Modèle ML

### Choix algorithmique — pourquoi GradientBoostingClassifier

| Critère | GradientBoosting | Random Forest | SVM | LSTM |
|---------|-----------------|---------------|-----|------|
| Données tabulaires hétérogènes | Excellent | Bon | Sensible à l'échelle | Nécessite séquences longues |
| Robustesse aux outliers vitaux | Oui (résidus) | Oui | Non | Non |
| Interprétabilité (feature importance) | Native | Native | Limitée | Boîte noire |
| Inférence <1ms (25 résidents/s) | Oui | Oui | Oui | GPU recommandé |
| Gestion déséquilibre classes | Via subsample | Oui | Partiel | Partiel |

**Conclusion** : GradientBoosting est le meilleur compromis pour des données vitales tabulaires avec 9 features, une inférence temps réel à 25 prédictions/s, et une nécessité d'interprétabilité médicale (feature importance compréhensible par les soignants).

### Features (9 dimensions)

| Feature | Description | Plage typique |
|---------|-------------|---------------|
| heart_rate | FC en bpm | 40-180 |
| spo2 | Saturation O2 % | 70-100 |
| blood_pressure_sys | PA systolique mmHg | 60-220 |
| temperature | T° corporelle °C | 35-41 |
| last_movement_ago_s | Inactivité en secondes | 0-7200 |
| hr_trend_10m | Tendance FC sur 10 mesures (polyfit slope) | -10 à +10 |
| spo2_trend_10m | Tendance SpO2 sur 10 mesures | -2 à +2 |
| age_factor | (age-60)/40 normalisé | 0-1 |
| risk_factor | Risque profil pathologies | 0-1 |

### Entraînement et métriques

- 5000 exemples synthétiques (seed=42, reproductible), split 80/20
- Pipeline : StandardScaler → GradientBoostingClassifier (100 estimateurs, lr=0.1, max_depth=4)
- **Split aléatoire** : acceptable sur données i.i.d. synthétiques. Sur données réelles, utiliser un **split temporel** (ex. : J-90→J-7 pour train, J-7→J pour test) afin d'éviter le data leakage.
- Métriques exposées via `GET /api/ml/metrics` :
  - **Sensibilité** (recall classe 1) : priorité absolue — un faux négatif = malaise non détecté
  - **Spécificité** (recall classe 0) : évite la fatigue des soignants par sur-alarmes
  - Accuracy, AUC-ROC, F1, precision, matrice de confusion complète
  - **Feature importance** : quelles variables influencent le plus la prédiction
- Persisté dans `/app/ml_model.joblib` (volume Docker)

## 4. Redis — schéma des clés

| Clé | TTL | Contenu |
|-----|-----|---------|
| `resident:{id}:state` | 30s | JSON état complet |
| `residents:all` | hash | Map id→JSON résumé |
| `alert:{id}:active` | 24h | JSON alerte active |
| `alerts:history` | liste | 1000 dernières alertes |
| `zone:{id}:state` | 30s | JSON zone ambiante |
| `zones:all` | hash | Map id→JSON zone |
| `ehpad:summary` | 5s | JSON résumé global |
| `alerts:elopement` | 1h | Liste alertes fugue |

## 5. Topics MQTT et stratégie QoS

| Topic | QoS | Justification | Fréquence | Publisher |
|-------|-----|---------------|-----------|-----------|
| `ehpad/residents/+/vitals` | 1 | Livraison garantie au moins une fois | 1/s/résident | simulator |
| `ehpad/residents/+/critical` | 2 | Chute détectée — exactement une fois, critique | À l'événement | simulator |
| `ehpad/{zone}/{id}/sos` | 2 | SOS appuyé — exactement une fois, critique | À l'événement | simulator |
| `ehpad/residents/+/location` | 0 | Position approximative, perte acceptable | 1/s/résident | simulator |
| `ehpad/zones/+/ambient` | 0 | Données environnementales, perte acceptable | 1/5s/zone | simulator |
| `ehpad/summary` | 0 | Agrégat global non critique | 1/s | simulator |

**Rationale QoS** :
- **QoS 0** (at most once) : données continues où une perte occasionnelle est tolérée (position, ambiant).
- **QoS 1** (at least once) : vitaux — on préfère un doublon à une perte.
- **QoS 2** (exactly once) : événements critiques irréversibles (chute, SOS) — aucune perte, aucun doublon.

## 6. Scalabilité

- **25 résidents × 3 topics × 1/s = 75 msg/s** → Mosquitto gère >100k msg/s
- Redis TTL évite l'accumulation : état courant toujours < 1 MB
- WebSocket broadcast unique (1 connexion par dashboard client)
- InfluxDB optimisé séries temporelles (compression, rétention configurable)
- Thread MQTT non-bloquant, escalade en thread séparé (toutes les 15s)
- Prédiction ML : ~0.5ms/inférence → 25 prédictions/s sans impact CPU

## 7. Rapport LLM (C2)

- Modèle : **Meditron:7b** via Ollama (local, no cloud)
- Fine-tuné sur PubMed + guidelines médicales → compréhension native des constantes vitales
- Aucune donnée patient ne quitte le système → **conformité RGPD**
- Fallback automatique si Ollama indisponible (résumé textuel)
- Endpoint : `GET /api/llm/report/{resident_id}`
