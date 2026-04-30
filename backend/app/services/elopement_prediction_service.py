"""Prediction metier des scenarios de fugue / errance.

Ce service reste volontairement leger et explicable: il classe les hypotheses
de securite a partir des signaux capteurs, de la zone, du profil et de la
routine. Il ne remplace pas l'alerte regle, il aide a comprendre quelle
hypothese est la plus probable.
"""

from __future__ import annotations


def _clamp(value: float, low: float = 0.01, high: float = 0.96) -> float:
    return max(low, min(high, value))


def _norm(scores: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.01, v) for v in scores.values()) or 1.0
    return {key: round(_clamp(value / total), 2) for key, value in scores.items()}


def _has_cognitive_risk(profile: dict, state: dict) -> bool:
    text = " ".join([
        " ".join(str(x) for x in profile.get("pathologies", [])),
        str(profile.get("mobility", "")),
        str(state.get("care_level", "")),
        " ".join(str(x) for x in (state.get("life_profile", {}) or {}).get("main_risks", [])),
    ]).lower()
    return any(term in text for term in ("alzheimer", "cognitif", "desorientation", "errance", "fugue", "confusion"))


def predict_elopement(state: dict, profile: dict | None = None, active_alert: dict | None = None) -> dict:
    profile = profile or {}
    movement = state.get("movement", {}) or {}
    events = state.get("sensor_events", {}) or movement.get("sensor_events", {}) or {}
    zone = state.get("current_zone") or state.get("zone") or ""
    scenario = state.get("movement_scenario") or state.get("scenario_active") or state.get("scenario") or ""
    routine_score = float((state.get("routine_analysis", {}) or {}).get("score") or 0)
    activity = state.get("activity") or ""
    is_outside = zone == "hors_ehpad" or scenario == "fugue_hors_ehpad"
    cognitive = _has_cognitive_risk(profile, state)
    door_open = bool(events.get("door_open") or events.get("exit_door_open"))
    rfid_exit = bool(events.get("rfid_exit") or events.get("badge_exit") or events.get("gps_outside"))
    movement_active = activity in {"deplacement", "marche"} or bool(events.get("room_pir_motion"))
    night = state.get("time_of_day") in {"nuit", "coucher"} or state.get("routine_label") in {"nuit", "coucher"}
    accompanied = state.get("caregiver_nearby") or events.get("staff_badge_nearby") or scenario in {"sortie_jardin_accompagnee"}
    alert_text = " ".join([
        str((active_alert or {}).get("reason") or ""),
        str((active_alert or {}).get("reason_label") or ""),
        str((active_alert or {}).get("level_name") or ""),
    ]).lower()
    alert_says_fugue = "fugue" in alert_text or "hors ehpad" in alert_text or "sortie" in alert_text

    scores = {
        "fugue_confirmee": 0.12,
        "errance_desorientation": 0.10,
        "sortie_accompagnee": 0.08,
        "faux_positif_capteur": 0.06,
    }

    if is_outside:
        scores["fugue_confirmee"] += 0.46
    if alert_says_fugue:
        scores["fugue_confirmee"] += 0.38
        scores["faux_positif_capteur"] -= 0.08
    if door_open:
        scores["fugue_confirmee"] += 0.16
        scores["faux_positif_capteur"] += 0.04
    if rfid_exit:
        scores["fugue_confirmee"] += 0.18
    if cognitive:
        scores["fugue_confirmee"] += 0.10
        scores["errance_desorientation"] += 0.20
    if routine_score >= 0.45:
        scores["fugue_confirmee"] += 0.08
        scores["errance_desorientation"] += 0.10
    if night:
        scores["errance_desorientation"] += 0.12
    if movement_active and not is_outside:
        scores["errance_desorientation"] += 0.08
    if accompanied:
        scores["sortie_accompagnee"] += 0.35
        scores["fugue_confirmee"] -= 0.18
    if not is_outside and not door_open and not rfid_exit:
        scores["faux_positif_capteur"] += 0.22
        scores["fugue_confirmee"] -= 0.06

    probabilities = _norm(scores)
    labels = {
        "fugue_confirmee": "Fugue confirmee",
        "errance_desorientation": "Errance / desorientation",
        "sortie_accompagnee": "Sortie accompagnee probable",
        "faux_positif_capteur": "Faux positif capteur",
    }
    ordered = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
    signals = []
    if is_outside:
        signals.append("zone hors EHPAD")
    if door_open:
        signals.append("porte de sortie ouverte")
    if rfid_exit:
        signals.append("RFID/GPS sortie")
    if cognitive:
        signals.append("profil cognitif/errance")
    if routine_score >= 0.45:
        signals.append("routine inhabituelle")
    if accompanied:
        signals.append("presence soignant/accompagnement")
    if active_alert:
        signals.append(f"alerte active N{active_alert.get('level', '?')}")
    if alert_says_fugue:
        signals.append("motif alerte fugue")

    return {
        "type": "elopement_prediction",
        "label": labels[ordered[0][0]],
        "top_probability": ordered[0][1],
        "candidates": [
            {"id": key, "label": labels[key], "probability": prob}
            for key, prob in ordered
        ],
        "signals": signals or ["pas de signal fugue fort"],
        "summary": f"Hypothese dominante: {labels[ordered[0][0]]} ({round(ordered[0][1] * 100)}%).",
    }
