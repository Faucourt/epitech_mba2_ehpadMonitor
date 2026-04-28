"""
Couche A2A interne pour l'EHPAD.

Ce module ne depend pas d'un SDK externe: il expose un contrat simple entre agents
metier afin de garder les decisions rapides, tracables et explicables.
"""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean


def _risk_label(score: float) -> str:
    if score >= 0.75:
        return "eleve"
    if score >= 0.5:
        return "modere"
    if score >= 0.25:
        return "faible"
    return "bas"


def _clamp(value: float, low: float = 0.0, high: float = 0.98) -> float:
    return max(low, min(high, value))


def agent_card() -> dict:
    return {
        "protocol": "ehpad-a2a-internal",
        "version": "0.1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "agents": [
            {"id": "realtime", "role": "Lit l'etat MQTT/Redis du resident"},
            {"id": "ml", "role": "Score numerique rapide 30-60 min"},
            {"id": "behavior", "role": "Compare routine, zone, repas, sommeil, inactivite"},
            {"id": "alerts", "role": "Propose niveau 1-5 avec anti-bruit"},
            {"id": "llm_medical", "role": "Explique les causes et actions soignantes"},
            {"id": "transmission", "role": "Produit mini DPI et fiche de transmission"},
        ],
    }


def realtime_agent(state: dict) -> dict:
    vitals = state.get("vitals", {})
    movement = state.get("movement", {})
    return {
        "agent": "realtime",
        "resident_id": state.get("resident_id"),
        "location": state.get("location_label") or state.get("current_zone") or state.get("zone"),
        "routine": state.get("routine_label") or state.get("time_of_day"),
        "activity": state.get("activity"),
        "vitals": vitals,
        "movement": {
            "last_movement_ago_s": movement.get("last_movement_ago_s", 0),
            "is_sleeping": movement.get("is_sleeping", False),
            "is_fall_detected": movement.get("is_fall_detected", False),
            "sos_pressed": movement.get("sos_pressed", False),
        },
        "sensor_events": state.get("sensor_events", {}),
        "baseline": state.get("baseline", {}),
        "ml_risk_live": float(state.get("ml_risk", 0) or 0),
    }


def ml_agent(state: dict, history: dict, prediction_memory: dict | None = None) -> dict:
    ml_prediction = state.get("ml_prediction") or {}
    live_risk = float(state.get("ml_risk", 0) or 0)
    trend = history.get("risk_trend", "stable")
    memory = prediction_memory or {}
    short_trend = memory.get("trend", "indisponible")
    max_30d = float(history.get("max_ml_risk", live_risk) or live_risk)
    if ml_prediction:
        risk_30 = float(ml_prediction.get("risk_30min", live_risk) or 0)
        risk_60 = float(ml_prediction.get("risk_60min", live_risk) or 0)
    else:
        risk_30 = live_risk
        if trend == "hausse":
            risk_30 += 0.08
        if max_30d >= 0.75 and live_risk >= 0.5:
            risk_30 += 0.04
        risk_60 = risk_30 + (0.06 if trend == "hausse" else -0.03 if trend == "baisse" else 0.02)
    return {
        "agent": "ml",
        "risk_30min": round(_clamp(risk_30), 2),
        "risk_60min": round(_clamp(risk_60), 2),
        "label_30min": _risk_label(_clamp(risk_30)),
        "label_60min": _risk_label(_clamp(risk_60)),
        "inputs": {
            "live_ml_risk": round(live_risk, 2),
            "trend_30d": trend,
            "trend_predictions": short_trend,
            "risk_delta_15min": memory.get("delta_15min"),
            "max_30d": round(max_30d, 2),
            "ml_intent": ml_prediction.get("intent", "prediction 30-60 min"),
            "signals": ml_prediction.get("signals", []),
        },
    }


def behavior_agent(state: dict, history_rows: list[dict]) -> dict:
    vitals = state.get("vitals", {})
    movement = state.get("movement", {})
    baseline = state.get("baseline", {})
    current_zone = state.get("current_zone") or state.get("zone")
    routine = state.get("time_of_day") or ""
    scenario = state.get("movement_scenario") or state.get("scenario_active")
    flags = []
    score = 0.0

    if movement.get("last_movement_ago_s", 0) > 1800 and routine not in {"nuit", "sieste", "coucher"}:
        flags.append("inactivite inhabituelle hors periode de repos")
        score += 0.18
    if current_zone in {"ascenseur", "escalier", "entree", "hors_ehpad"}:
        flags.append(f"zone sensible: {current_zone}")
        score += 0.16
    if scenario:
        flags.append(f"scenario comportemental: {scenario}")
        score += 0.18
    if routine in {"trajet_dejeuner", "trajet_diner"}:
        flags.append("periode trajet repas: risque chute augmente")
        score += 0.08
    if vitals.get("spo2") is not None and baseline.get("spo2") is not None:
        if vitals["spo2"] <= float(baseline["spo2"]) - 2.5:
            flags.append("SpO2 en baisse vs baseline resident")
            score += 0.16
    if vitals.get("heart_rate") is not None and baseline.get("heart_rate") is not None:
        if vitals["heart_rate"] >= float(baseline["heart_rate"]) + 22:
            flags.append("frequence cardiaque en hausse vs baseline")
            score += 0.12

    recent_events = [r.get("event") for r in history_rows[-12:] if r.get("event") and r.get("event") != "routine"]
    if recent_events:
        flags.append("historique recent: " + ", ".join(sorted(set(recent_events))[:3]))
        score += 0.08

    return {
        "agent": "behavior",
        "score": round(_clamp(score), 2),
        "flags": flags or ["routine compatible avec l'etat habituel"],
        "routine": routine,
        "zone": current_zone,
    }


def alert_agent(ml: dict, behavior: dict, active_alert: dict | None) -> dict:
    risk = max(float(ml.get("risk_30min", 0)), float(ml.get("risk_60min", 0)))
    risk += float(behavior.get("score", 0)) * 0.45
    trend_predictions = ml.get("inputs", {}).get("trend_predictions")
    if trend_predictions == "hausse_rapide":
        risk += 0.12
    elif trend_predictions == "hausse":
        risk += 0.06
    active_level = int(active_alert.get("level", 0)) if active_alert else 0
    if active_level >= 4:
        recommended = active_level
    elif risk >= 0.82:
        recommended = 3
    elif risk >= 0.62:
        recommended = 2
    elif risk >= 0.42:
        recommended = 1
    else:
        recommended = 0
    return {
        "agent": "alerts",
        "recommended_level": recommended,
        "recommended_level_name": ["Stable", "Information", "Attention", "Alerte", "Urgence", "Danger vital"][recommended],
        "combined_risk": round(_clamp(risk), 2),
        "uses_active_alert": bool(active_alert),
    }


def llm_medical_agent(state: dict, ml: dict, behavior: dict, alert: dict) -> dict:
    name = state.get("resident_name") or state.get("name") or state.get("resident_id")
    reasons = behavior.get("flags", [])[:3]
    level = alert.get("recommended_level_name", "Stable")
    risk_30 = ml.get("risk_30min", 0)
    risk_60 = ml.get("risk_60min", 0)
    trend = ml.get("inputs", {}).get("trend_predictions", "indisponible")
    if alert.get("recommended_level", 0) >= 3:
        action = "controle clinique rapide, constantes rapprochees et accompagnement des deplacements"
    elif alert.get("recommended_level", 0) == 2:
        action = "controle dans 15-30 min et verification de la coherence capteurs/comportement"
    elif alert.get("recommended_level", 0) == 1:
        action = "surveillance simple et relecture au prochain passage"
    else:
        action = "surveillance habituelle"
    return {
        "agent": "llm_medical",
        "summary": (
            f"{name}: risque 30 min {risk_30:.0%}, risque 60 min {risk_60:.0%}, niveau propose {level}. "
            f"Tendance predictive: {trend}. Elements principaux: {', '.join(reasons)}. Action: {action}."
        ),
        "actions": [
            action,
            "documenter toute modification de comportement",
            "adapter l'accompagnement si trajet repas, nuit, jardin ou zone sensible",
        ],
    }


def transmission_agent(state: dict, ml: dict, behavior: dict, alert: dict, medical: dict) -> dict:
    return {
        "agent": "transmission",
        "handover_line": medical["summary"],
        "priority": alert.get("recommended_level_name", "Stable"),
        "risk_30min": ml.get("risk_30min"),
        "risk_60min": ml.get("risk_60min"),
        "prediction_trend": ml.get("inputs", {}).get("trend_predictions"),
        "risk_delta_15min": ml.get("inputs", {}).get("risk_delta_15min"),
        "watch_points": behavior.get("flags", [])[:4],
        "actions": medical.get("actions", []),
    }


def run_a2a_pipeline(
    state: dict,
    history_summary: dict,
    history_rows: list[dict],
    active_alert: dict | None = None,
    prediction_memory: dict | None = None,
) -> dict:
    realtime = realtime_agent(state)
    ml = ml_agent(state, history_summary, prediction_memory=prediction_memory)
    behavior = behavior_agent(state, history_rows)
    alert = alert_agent(ml, behavior, active_alert)
    medical = llm_medical_agent(state, ml, behavior, alert)
    transmission = transmission_agent(state, ml, behavior, alert, medical)
    return {
        "protocol": "ehpad-a2a-internal",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "resident_id": state.get("resident_id"),
        "agents": [realtime, ml, behavior, alert, medical, transmission],
        "prediction": {
            "risk_30min": ml["risk_30min"],
            "risk_60min": ml["risk_60min"],
            "label_30min": ml["label_30min"],
            "label_60min": ml["label_60min"],
            "recommended_level": alert["recommended_level"],
            "recommended_level_name": alert["recommended_level_name"],
            "prediction_trend": transmission.get("prediction_trend"),
            "risk_delta_15min": transmission.get("risk_delta_15min"),
            "summary": medical["summary"],
            "actions": medical["actions"],
            "watch_points": transmission["watch_points"],
        },
    }
