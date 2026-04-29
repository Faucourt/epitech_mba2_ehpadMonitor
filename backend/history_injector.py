"""
Injection et lecture de l'historique clinique dans InfluxDB.

- inject_all_history() : écrit 365j de données simulées pour tous les résidents
  au démarrage, une seule fois (vérification via Redis). Réinjecte si profil modifié.
- get_real_history_summary() : interroge InfluxDB et retourne un résumé
  avec tendances réelles sur 30j, utilisable par le LLM et l'analyse prédictive.
"""

import hashlib
import json
import logging
from typing import Callable, Optional

import numpy as np
from influxdb_client import Point, WritePrecision

log = logging.getLogger(__name__)

_MEASUREMENT = "vitals_history"
_HISTORY_DAYS = 365
_HISTORY_STEP_HOURS = 6


def _profile_hash(profile: dict) -> str:
    key = json.dumps({
        "risk_factor": profile.get("risk_factor"),
        "pathologies": sorted(profile.get("pathologies", [])),
        "mobility": profile.get("mobility"),
        "age": profile.get("age"),
    }, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def inject_all_history(
    write_api,
    influx_bucket: str,
    residents_map: dict,
    effective_profile_fn: Callable[[str], dict],
    redis_client,
    simulated_rows_fn: Callable,
) -> None:
    """Injecte 365j d'historique simulé dans InfluxDB pour tous les résidents.
    Ignoré si déjà fait. Réinjecte automatiquement si le profil a changé."""
    total = 0
    for resident_id in residents_map:
        try:
            profile = effective_profile_fn(resident_id)
            if not profile:
                continue
            phash = _profile_hash(profile)
            rkey = f"history:injected:v1:{resident_id}:{phash}"
            if redis_client.exists(rkey):
                continue

            log.info("Injection InfluxDB %s (%d jours)...", resident_id, _HISTORY_DAYS)
            rows = simulated_rows_fn(resident_id, days=_HISTORY_DAYS, step_hours=_HISTORY_STEP_HOURS)
            points = []
            for row in rows:
                try:
                    from datetime import datetime, timezone
                    ts = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
                except Exception:
                    continue
                points.append(
                    Point(_MEASUREMENT)
                    .tag("resident_id", resident_id)
                    .tag("event", str(row.get("event", "routine")))
                    .field("heart_rate", float(row.get("heart_rate") or 0))
                    .field("spo2", float(row.get("spo2") or 0))
                    .field("blood_pressure_sys", float(row.get("blood_pressure_sys") or 0))
                    .field("blood_pressure_dia", float(row.get("blood_pressure_dia") or 0))
                    .field("temperature", float(row.get("temperature") or 0))
                    .field("respiratory_rate", float(row.get("respiratory_rate") or 0))
                    .field("alert_level", int(row.get("alert_level") or 0))
                    .field("ml_risk", float(row.get("ml_risk") or 0))
                    .field("zone", str(row.get("zone") or ""))
                    .time(ts, WritePrecision.S)
                )
            write_api.write(bucket=influx_bucket, record=points)
            redis_client.setex(rkey, 400 * 86400, "1")
            total += len(points)
            log.info("Historique %s injecte : %d points", resident_id, len(points))
        except Exception as exc:
            log.warning("Injection historique %s echouee : %s", resident_id, exc)

    if total:
        log.info("Injection totale : %d points pour %d residents", total, len(residents_map))
    else:
        log.info("Historique InfluxDB deja present, injection ignoree")


def get_real_history_summary(
    query_api,
    influx_bucket: str,
    resident_id: str,
    days: int = 30,
) -> Optional[dict]:
    """Interroge InfluxDB et retourne un résumé clinique réel sur N jours.
    Retourne None si pas assez de données (le code appelant utilisera le fallback simulé)."""
    try:
        query = f'''
from(bucket: "{influx_bucket}")
  |> range(start: -{days}d)
  |> filter(fn: (r) => r._measurement == "{_MEASUREMENT}")
  |> filter(fn: (r) => r.resident_id == "{resident_id}")
  |> pivot(rowKey: ["_time", "resident_id", "event"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
'''
        tables = query_api.query(query)
        rows = []
        for table in tables:
            for record in table.records:
                v = record.values
                rows.append({
                    "time": str(record.get_time()),
                    "event": v.get("event", "routine"),
                    "heart_rate": v.get("heart_rate"),
                    "spo2": v.get("spo2"),
                    "blood_pressure_sys": v.get("blood_pressure_sys"),
                    "blood_pressure_dia": v.get("blood_pressure_dia"),
                    "temperature": v.get("temperature"),
                    "respiratory_rate": v.get("respiratory_rate"),
                    "alert_level": v.get("alert_level", 0),
                    "ml_risk": v.get("ml_risk", 0),
                    "zone": v.get("zone", ""),
                })

        if len(rows) < 10:
            return None

        def avg(key):
            vals = [float(r[key]) for r in rows if r.get(key) is not None]
            return round(float(np.mean(vals)), 1) if vals else 0.0

        # Tendance : comparer risque ML dernière semaine vs reste de la période
        cutoff = max(1, len(rows) * 3 // 4)
        recent_risk = float(np.mean([float(r["ml_risk"] or 0) for r in rows[cutoff:]])) if rows[cutoff:] else 0
        older_risk = float(np.mean([float(r["ml_risk"] or 0) for r in rows[:cutoff]])) if rows[:cutoff] else 0
        trend_delta = recent_risk - older_risk

        # Tendances 48h vs moyenne globale
        recent_48h = rows[-8:] if len(rows) >= 8 else rows
        avg_hr = avg("heart_rate")
        avg_spo2 = avg("spo2")
        hr_48h = round(float(np.mean([float(r["heart_rate"] or 0) for r in recent_48h if r.get("heart_rate")])), 1) if recent_48h else avg_hr
        spo2_48h = round(float(np.mean([float(r["spo2"] or 0) for r in recent_48h if r.get("spo2")])), 1) if recent_48h else avg_spo2
        hr_delta = round(hr_48h - avg_hr, 1)
        spo2_delta = round(spo2_48h - avg_spo2, 1)

        alert_rows = [r for r in rows if int(r.get("alert_level") or 0) > 0]
        notable = [
            r for r in rows
            if r.get("event") not in {"routine", "inactivite"}
            and int(r.get("alert_level") or 0) >= 2
        ][-8:]

        risk_trend = "hausse" if trend_delta > 0.04 else "baisse" if trend_delta < -0.04 else "stable"

        return {
            "source": "influxdb_real",
            "days": days,
            "points": len(rows),
            "avg_vitals": {
                "heart_rate": avg_hr,
                "spo2": avg_spo2,
                "blood_pressure_sys": avg("blood_pressure_sys"),
                "blood_pressure_dia": avg("blood_pressure_dia"),
                "temperature": avg("temperature"),
                "respiratory_rate": avg("respiratory_rate"),
            },
            "trends_48h": {
                "heart_rate": hr_48h,
                "heart_rate_delta": hr_delta,
                "heart_rate_trend": "hausse" if hr_delta > 5 else "baisse" if hr_delta < -5 else "stable",
                "spo2": spo2_48h,
                "spo2_delta": spo2_delta,
                "spo2_trend": "baisse" if spo2_delta < -1 else "hausse" if spo2_delta > 1 else "stable",
            },
            "max_ml_risk": round(max(float(r["ml_risk"] or 0) for r in rows), 2),
            "risk_trend": risk_trend,
            "alerts_count": len(alert_rows),
            "critical_events": [r for r in rows if int(r.get("alert_level") or 0) >= 3][-8:],
            "notable_events": notable,
            "history_30d": {
                "alerts_count": len(alert_rows),
                "risk_trend": risk_trend,
            },
        }

    except Exception as exc:
        log.warning("Lecture historique InfluxDB %s echouee : %s", resident_id, exc)
        return None
