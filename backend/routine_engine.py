"""
routine_engine.py — Analyse des routines individuelles EHPAD Watch

Objectif :
- apprendre les habitudes par résident et par période de journée ;
- détecter les écarts : lever inhabituel, repas manqué, activité basse, errance nocturne,
  zone inattendue, constantes différentes de son baseline habituel ;
- renvoyer un score exploitable par le dashboard et le moteur d'alertes.

Dépendances : standard library uniquement.
"""

from __future__ import annotations

import json
import math
import time
from collections import Counter
from datetime import datetime
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional


ROUTINE_PERIODS = [
    "lever_toilette",
    "petit_dej",
    "soins_matin",
    "animation_matin",
    "trajet_dejeuner",
    "dejeuner",
    "sieste",
    "animation_apres_midi",
    "gouter",
    "trajet_diner",
    "diner",
    "soiree",
    "coucher",
    "nuit",
]

MEAL_PERIODS = {"petit_dej", "dejeuner", "gouter", "diner"}
REST_PERIODS = {"sieste", "coucher", "nuit"}
TRANSFER_PERIODS = {"lever_toilette", "trajet_dejeuner", "trajet_diner", "coucher"}

ACTIVITY_SCORES = {
    "immobile": 0.0,
    "immobilite_anormale": 0.0,
    "repos": 0.2,
    "repos_chambre": 0.2,
    "repas_en_chambre": 0.35,
    "repas": 0.45,
    "assis": 0.35,
    "sommeil": 0.0,
    "deplacement": 0.8,
    "animation": 0.65,
    "marche": 0.85,
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _z(value: float, avg: float, std: float, min_std: float = 1.0) -> float:
    std = max(abs(std), min_std)
    return (value - avg) / std


def _mode(values: List[str], default: Optional[str] = None) -> Optional[str]:
    values = [v for v in values if v]
    if not values:
        return default
    return Counter(values).most_common(1)[0][0]


def _entry_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    v = state.get("vitals") or {}
    m = state.get("movement") or {}
    period = state.get("time_of_day") or "unknown"
    activity = state.get("activity") or ""
    return {
        "schema_version": 2,
        "ts": time.time(),
        "iso": datetime.utcnow().isoformat() + "Z",
        "period": period,
        "time_label": state.get("time_label"),
        "routine_label": state.get("routine_label"),
        "zone": state.get("current_zone") or state.get("zone"),
        "target_zone": state.get("target_zone"),
        "activity": activity,
        "activity_score": ACTIVITY_SCORES.get(activity, 0.3),
        "is_sleeping": bool(m.get("is_sleeping", False)),
        "meal_mode": state.get("meal_mode"),
        "care_level": state.get("care_level"),
        "movement_scenario": state.get("movement_scenario"),
        "hr": _safe_float(v.get("heart_rate")),
        "spo2": _safe_float(v.get("spo2")),
        "bp_sys": _safe_float(v.get("blood_pressure_sys")),
        "bp_dia": _safe_float(v.get("blood_pressure_dia")),
        "temp": _safe_float(v.get("temperature")),
        "respiratory_rate": _safe_float(v.get("respiratory_rate")),
        "last_movement_ago_s": _safe_float(m.get("last_movement_ago_s")),
        "is_fall_detected": bool(m.get("is_fall_detected", False)),
        "ml_risk": _safe_float(state.get("ml_risk")),
    }


def _stats(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    def nums(name: str) -> List[float]:
        return [_safe_float(e.get(name)) for e in entries if e.get(name) is not None]

    def avg_std(name: str) -> Dict[str, Optional[float]]:
        values = nums(name)
        if not values:
            return {"avg": None, "std": None, "min": None, "max": None}
        return {
            "avg": round(mean(values), 2),
            "std": round(pstdev(values), 2) if len(values) > 1 else 0.0,
            "min": round(min(values), 2),
            "max": round(max(values), 2),
        }

    zones = [e.get("zone") for e in entries if e.get("zone")]
    activities = [e.get("activity") for e in entries if e.get("activity")]
    sleeping = [1 if e.get("is_sleeping") else 0 for e in entries]
    meal_modes = [e.get("meal_mode") for e in entries if e.get("meal_mode")]

    return {
        "samples": len(entries),
        "hr": avg_std("hr"),
        "spo2": avg_std("spo2"),
        "bp_sys": avg_std("bp_sys"),
        "temp": avg_std("temp"),
        "respiratory_rate": avg_std("respiratory_rate"),
        "activity_score": avg_std("activity_score"),
        "last_movement_ago_s": avg_std("last_movement_ago_s"),
        "dominant_zone": _mode(zones),
        "zone_distribution": dict(Counter(zones).most_common(5)),
        "dominant_activity": _mode(activities),
        "activity_distribution": dict(Counter(activities).most_common(5)),
        "sleeping_ratio": round(sum(sleeping) / len(sleeping), 2) if sleeping else 0,
        "dominant_meal_mode": _mode(meal_modes),
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }


def _period_summary(redis_client, resident_id: str, period: str, max_entries: int = 200) -> Dict[str, Any]:
    key = f"routine:{resident_id}:{period}"
    raw_entries = redis_client.lrange(key, 0, max_entries - 1)
    entries = []
    for raw in raw_entries:
        try:
            item = json.loads(raw)
            if item.get("schema_version") == 2:
                entries.append(item)
        except Exception:
            pass
    entries.reverse()
    return {
        "period": period,
        "baseline": _stats(entries),
        "last_entries": entries[-24:],
    }


def update_and_detect(redis_client, state: Dict[str, Any], *, max_samples: int = 240, ttl_days: int = 30) -> Dict[str, Any]:
    """
    À appeler à chaque message vitals dans _handle_vitals(state).

    Retourne :
    {
      "score": 0.0-1.0,
      "alert_level": 0-3,
      "flags": [...],
      "baseline": {...},
      "entry": {...}
    }
    """
    resident_id = state.get("resident_id")
    if not resident_id:
        return {"score": 0, "alert_level": 0, "flags": ["resident_id absent"]}

    entry = _entry_from_state(state)
    period = entry["period"]
    key = f"routine:{resident_id}:{period}"

    # Baseline AVANT insertion de la mesure courante.
    raw_history = redis_client.lrange(key, 0, max_samples - 1)
    history = []
    for raw in raw_history:
        try:
            item = json.loads(raw)
            if item.get("schema_version") == 2:
                history.append(item)
        except Exception:
            pass
    baseline = _stats(history)

    # Insertion mesure courante.
    redis_client.lpush(key, json.dumps(entry, ensure_ascii=False))
    redis_client.ltrim(key, 0, max_samples - 1)
    redis_client.expire(key, ttl_days * 86400)

    # Pas assez d'historique : apprentissage seulement.
    if baseline["samples"] < 20:
        return {
            "resident_id": resident_id,
            "period": period,
            "status": "learning",
            "score": 0.0,
            "alert_level": 0,
            "flags": [f"apprentissage routine {period}: {baseline['samples']}/20 mesures"],
            "baseline": baseline,
            "entry": entry,
        }

    flags: List[str] = []
    score = 0.0

    # 1) Écart constantes vs routine habituelle de CETTE période.
    for field, label, min_std, weight in [
        ("hr", "FC inhabituelle pour cette période", 5.0, 0.18),
        ("spo2", "SpO2 inhabituelle pour cette période", 1.2, 0.20),
        ("bp_sys", "PA systolique inhabituelle pour cette période", 8.0, 0.12),
        ("temp", "Température inhabituelle pour cette période", 0.25, 0.12),
        ("respiratory_rate", "FR inhabituelle pour cette période", 2.0, 0.14),
    ]:
        stat = baseline.get(field) or {}
        avg = stat.get("avg")
        std = stat.get("std")
        if avg is not None and std is not None:
            z = _z(entry[field], avg, std, min_std)
            if abs(z) >= 2.5:
                direction = "haute" if z > 0 else "basse"
                flags.append(f"{label}: {entry[field]:.1f} vs moy {avg:.1f} ({direction})")
                score += min(0.30, abs(z) * weight / 3.0)

    # 2) Activité différente.
    act_stat = baseline.get("activity_score") or {}
    if act_stat.get("avg") is not None:
        zact = _z(entry["activity_score"], act_stat["avg"], act_stat.get("std") or 0.2, 0.2)
        if zact <= -2.5 and period not in REST_PERIODS:
            flags.append("activité beaucoup plus basse que d'habitude sur cette période")
            score += 0.22
        elif zact >= 2.8 and period in {"nuit", "coucher"}:
            flags.append("activité nocturne inhabituelle")
            score += 0.25

    # 3) Zone inattendue.
    dominant_zone = baseline.get("dominant_zone")
    if dominant_zone and entry["zone"] and entry["zone"] != dominant_zone:
        zone_dist = baseline.get("zone_distribution") or {}
        seen_count = zone_dist.get(entry["zone"], 0)
        if seen_count <= max(2, baseline["samples"] * 0.05):
            flags.append(f"zone inhabituelle: {entry['zone']} au lieu de {dominant_zone}")
            score += 0.18

    # 4) Repas manqué / présence anormale.
    if period in MEAL_PERIODS:
        if entry["zone"] not in {"salle_manger", state.get("zone"), state.get("current_zone")} and entry.get("meal_mode") != "chambre":
            flags.append(f"présence repas à vérifier sur période {period}")
            score += 0.12
        if entry["activity"] in {"immobile", "repos", "repos_chambre"} and entry.get("meal_mode") != "chambre":
            flags.append(f"activité faible pendant le repas {period}")
            score += 0.15

    # 5) Nuit / errance / fugue.
    if period == "nuit":
        if entry["zone"] and not str(entry["zone"]).startswith("ch") and entry["zone"] not in {"chambre", state.get("zone")}:
            flags.append("sortie de chambre nocturne")
            score += 0.22
        if entry["last_movement_ago_s"] < 120 and not entry["is_sleeping"]:
            flags.append("réveil ou déambulation nocturne")
            score += 0.14

    # 6) Isolement ou immobilité hors repos.
    if period not in REST_PERIODS and entry["last_movement_ago_s"] >= 3600:
        flags.append("absence de mouvement > 1h hors période de repos")
        score += 0.25

    # 7) Scénario explicite simulateur.
    if entry.get("movement_scenario") in {
        "errance_nuit", "isolement_chambre", "desorientation_ascenseur",
        "fugue_hors_ehpad", "malaise_retour_repas", "chute_trajet_repas"
    }:
        flags.append(f"scénario comportemental détecté: {entry['movement_scenario']}")
        score += 0.25

    score = round(min(score, 1.0), 3)
    if score >= 0.70:
        level = 3
    elif score >= 0.40:
        level = 2
    elif score >= 0.20:
        level = 1
    else:
        level = 0

    return {
        "resident_id": resident_id,
        "period": period,
        "status": "ok",
        "score": score,
        "alert_level": level,
        "flags": flags or ["routine compatible avec le comportement habituel"],
        "baseline": baseline,
        "entry": entry,
        "computed_at": datetime.utcnow().isoformat() + "Z",
    }


def get_routine_summary(redis_client, resident_id: str) -> Dict[str, Any]:
    """Résumé complet pour endpoint GET /api/residents/{resident_id}/routine."""
    periods = []
    max_score = 0.0
    for period in ROUTINE_PERIODS:
        s = _period_summary(redis_client, resident_id, period)
        periods.append(s)
    current_raw = redis_client.get(f"resident:{resident_id}:state")
    current_analysis = None
    if current_raw:
        try:
            state = json.loads(current_raw)
            current_analysis = state.get("routine_analysis")
            if current_analysis:
                max_score = max(max_score, _safe_float(current_analysis.get("score")))
        except Exception:
            pass
    return {
        "resident_id": resident_id,
        "current_analysis": current_analysis,
        "periods": periods,
        "max_current_score": max_score,
        "interpretation": {
            "0": "routine normale",
            "1": "petit écart à surveiller",
            "2": "changement comportemental notable",
            "3": "changement fort pouvant justifier une alerte niveau 2/3",
        },
    }
