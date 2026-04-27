"""
Backend EHPAD — FastAPI
- Consomme MQTT (vitaux résidents + capteurs ambiants)
- Stocke dans Redis (état courant) + InfluxDB (historique)
- Moteur d'alertes 5 niveaux avec escalade
- API REST + WebSocket pour le dashboard
- Prédiction ML de malaise
"""

import json
import os
import time
import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np

import redis
import paho.mqtt.client as mqtt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from alert_engine import AlertEngine
from ws_manager import WebSocketManager
from ml_model import MalaisePredictor

logging.basicConfig(level=logging.INFO, format='%(asctime)s [BACKEND] %(message)s')
log = logging.getLogger(__name__)

# --- Config ---
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
INFLUX_HOST = os.getenv("INFLUX_HOST", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "ehpad-super-secret-token")
INFLUX_ORG = os.getenv("INFLUX_ORG", "ehpad")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "residents")
DEMO_RESIDENT = os.getenv("DEMO_RESIDENT", "R005")
INFLUX_SAMPLE_INTERVAL_S = float(os.getenv("INFLUX_SAMPLE_INTERVAL_S", "5"))
WS_RESIDENT_MIN_INTERVAL_S = float(os.getenv("WS_RESIDENT_MIN_INTERVAL_S", "2"))
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "meditron:7b")

# --- Profils résidents (importé depuis le simulateur, ou hardcodé)
from resident_profiles import RESIDENTS_MAP

# --- Init ---
app = FastAPI(title="EHPAD API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def force_utf8_charset(request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("application/json") and "charset" not in content_type:
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
ws_manager = WebSocketManager()
alert_engine = AlertEngine(redis_client, ws_manager)
ml_predictor = MalaisePredictor()

# InfluxDB
influx = InfluxDBClient(url=INFLUX_HOST, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = influx.write_api(write_options=SYNCHRONOUS)

# Loop asyncio partagée
_loop: Optional[asyncio.AbstractEventLoop] = None
_last_influx_write: dict[str, float] = {}
_last_ws_push: dict[str, float] = {}
_last_daily_report_date: Optional[str] = None


def publish_mqtt_control(topic: str, payload: dict):
    client = mqtt.Client(client_id=f"ehpad_backend_control_{os.getpid()}_{int(time.time() * 1000)}")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.publish(topic, json.dumps(payload), qos=1, retain=True)
    client.disconnect()


def _simulated_history_rows(resident_id: str, days: int = 30, step_hours: int = 6):
    profile = RESIDENTS_MAP.get(resident_id, {})
    if not profile:
        raise HTTPException(404, "Resident non trouve")

    days = max(30, min(days, 120))
    step_hours = max(1, min(step_hours, 24))
    points = int((days * 24) / step_hours) + 1
    risk = float(profile.get("risk_factor", 0.3))
    mobility = profile.get("mobility", "moyenne")
    base_hr = 70 + int(risk * 12)
    base_spo2 = 97 - int(risk * 6)
    base_bp = 125 + int(risk * 45)
    base_temp = 36.6 + risk * 0.4
    now = datetime.now(timezone.utc)
    room_meal = mobility == "tres_faible" and risk >= 0.6
    meal_zone = f"ch{profile.get('room', '')}" if room_meal else "salle_manger"
    zones_by_hour = {
        7: (meal_zone, "petit_dejeuner_en_chambre" if room_meal else "petit_dejeuner"),
        8: (meal_zone, "petit_dejeuner_en_chambre" if room_meal else "petit_dejeuner"),
        10: ("salle_activites", "animation_matin"),
        11: ("couloir_principal", "trajet_repas"),
        12: (meal_zone, "dejeuner_en_chambre" if room_meal else "dejeuner"),
        13: (f"ch{profile.get('room', '')}", "sieste"),
        15: ("salle_commune", "animation_apres_midi"),
        16: (meal_zone, "gouter_en_chambre" if room_meal else "gouter"),
        18: (meal_zone, "diner_en_chambre" if room_meal else "diner"),
        19: ("salle_commune", "soiree"),
    }
    fallback_zones = [f"ch{profile.get('room', '')}", "couloir_principal", "salle_manger", "salle_commune", "salle_repos", "patio", "jardin"]
    rows = []

    for i in range(points):
        ts = now - timedelta(hours=(points - 1 - i) * step_hours)
        seed = sum(ord(c) for c in f"{resident_id}-{ts.date()}-{ts.hour}")
        phase = (seed % 17) - 8
        night = ts.hour < 6 or ts.hour >= 22
        meal = ts.hour in {7, 8, 12, 16, 18}
        scheduled = zones_by_hour.get(ts.hour)
        movement_base = 2400 if night else (300 if meal else 900)
        if mobility in {"faible", "tres_faible"}:
            movement_base += 600
        last_movement = max(30, movement_base + phase * 55)
        event = "routine"
        level = 0

        heart_rate = base_hr + phase
        spo2 = base_spo2 - (2 if night and risk > 0.5 else 0)
        blood_pressure = base_bp + phase * 2
        temperature = base_temp + (phase / 80)
        respiratory_rate = 15 + int(risk * 6) + (1 if spo2 < 93 else 0)
        zone = scheduled[0] if scheduled else fallback_zones[seed % len(fallback_zones)]
        routine = scheduled[1] if scheduled else ("nuit" if night else "routine")

        if ts.hour in {11, 18} and seed % 7 == 0 and risk > 0.35:
            event = "risque_trajet_repas"
            level = 2
            last_movement = 1200
            heart_rate += 10
        elif seed % 41 == 0 and risk > 0.45:
            event = "risque_chute"
            level = 3
            last_movement = 3800
        elif seed % 29 == 0 and risk > 0.35:
            event = "constantes_hors_norme"
            level = 2
            spo2 -= 2
            heart_rate += 18
        elif last_movement > 1800:
            event = "inactivite"
            level = 1

        if seed % 97 == 0 and risk > 0.65:
            event = "chute_detectee"
            level = 4
            last_movement = 4500
            heart_rate += 25
        if seed % 131 == 0 and risk > 0.75:
            event = "danger_vital"
            level = 5
            spo2 = min(spo2, 86)
            heart_rate = max(heart_rate, 142)

        rows.append({
            "time": ts.isoformat().replace("+00:00", "Z"),
            "resident_id": resident_id,
            "room": profile.get("room"),
            "zone": zone,
            "routine": routine,
            "event": event,
            "alert_level": level,
            "heart_rate": round(heart_rate),
            "spo2": round(max(80, min(100, spo2)), 1),
            "blood_pressure_sys": round(blood_pressure),
            "temperature": round(temperature, 1),
            "respiratory_rate": respiratory_rate,
            "last_movement_ago_s": int(last_movement),
            "ml_risk": round(min(0.98, risk + max(0, level - 1) * 0.12), 2),
        })
    return rows


def _local_report_date(value: Optional[str] = None) -> str:
    if value:
        return value
    return datetime.now().date().isoformat()


def _alert_level_name(level: int) -> str:
    names = ["Stable", "Information", "Attention", "Alerte", "Urgence", "Danger vital"]
    if 0 <= int(level) < len(names):
        return names[int(level)]
    return "Inconnu"


def _risk_label(score: float) -> str:
    if score >= 0.75:
        return "eleve"
    if score >= 0.5:
        return "modere"
    if score >= 0.25:
        return "faible"
    return "bas"


def _safe_state_for_report(resident_id: str) -> dict:
    raw = redis_client.get(f"resident:{resident_id}:state")
    profile = RESIDENTS_MAP.get(resident_id, {})
    if raw:
        state = json.loads(raw)
    else:
        hist = _simulated_history_rows(resident_id, days=30, step_hours=6)
        latest = hist[-1]
        state = {
            "resident_id": resident_id,
            "name": profile.get("name", resident_id),
            "room": profile.get("room"),
            "floor": 0 if str(profile.get("room", "100")).startswith("1") else 1,
            "current_zone": latest.get("zone"),
            "activity": latest.get("routine"),
            "vitals": {
                "heart_rate": latest.get("heart_rate"),
                "spo2": latest.get("spo2"),
                "blood_pressure_sys": latest.get("blood_pressure_sys"),
                "temperature": latest.get("temperature"),
                "respiratory_rate": latest.get("respiratory_rate"),
            },
            "movement": {"last_movement_ago_s": latest.get("last_movement_ago_s")},
            "ml_risk": latest.get("ml_risk", profile.get("risk_factor", 0.3)),
            "caregiver": profile.get("caregiver"),
        }
    state["profile"] = profile
    state["resident_name"] = state.get("name", profile.get("name", resident_id))
    return state


def _alerts_for_resident_on_date(resident_id: str, report_date: str) -> list[dict]:
    alerts = []
    for alert in alert_engine.get_history(500):
        if alert.get("resident_id") != resident_id:
            continue
        created = str(alert.get("created_at") or alert.get("timestamp") or "")
        if created.startswith(report_date):
            alerts.append(alert)
    return alerts


def _history_summary(resident_id: str) -> dict:
    rows = _simulated_history_rows(resident_id, days=30, step_hours=6)
    if not rows:
        return {}
    alert_rows = [r for r in rows if r.get("alert_level", 0) > 0]
    events: dict[str, int] = {}
    for row in rows:
        events[row["event"]] = events.get(row["event"], 0) + 1
    avg = lambda key: round(float(np.mean([r[key] for r in rows if r.get(key) is not None])), 1)
    trend = rows[-1]["ml_risk"] - rows[max(0, len(rows) - 15)]["ml_risk"]
    return {
        "days": 30,
        "points": len(rows),
        "avg_vitals": {
            "heart_rate": avg("heart_rate"),
            "spo2": avg("spo2"),
            "blood_pressure_sys": avg("blood_pressure_sys"),
            "temperature": avg("temperature"),
            "respiratory_rate": avg("respiratory_rate"),
        },
        "max_ml_risk": round(max(r["ml_risk"] for r in rows), 2),
        "risk_trend": "hausse" if trend > 0.04 else "baisse" if trend < -0.04 else "stable",
        "alerts_count": len(alert_rows),
        "critical_events": [r for r in alert_rows if r.get("alert_level", 0) >= 3][-8:],
        "event_counts": events,
    }


def _forecast_points(state: dict, hist: dict, alerts_today: list[dict]) -> list[str]:
    v = state.get("vitals", {})
    movement = state.get("movement", {})
    risk = float(state.get("ml_risk", 0))
    points = []
    if risk >= 0.7 or hist.get("risk_trend") == "hausse":
        points.append("Risque a venir augmente: surveiller constantes et comportement dans les prochaines 30-60 min.")
    if v.get("spo2", 100) < 94:
        points.append("SpO2 basse ou limite: verifier tolerance a l'effort, dyspnee et saturation.")
    if v.get("heart_rate", 0) > 105 or v.get("blood_pressure_sys", 0) > 165:
        points.append("Constantes cardio en tension: controle rapproche conseille.")
    if movement.get("last_movement_ago_s", 0) > 1800:
        points.append("Inactivite prolongee: verifier position, confort, hydratation et etat de vigilance.")
    if any(a.get("level", 0) >= 3 for a in alerts_today):
        points.append("Alerte significative aujourd'hui: tracer l'observation et confirmer l'acquittement.")
    if not points:
        points.append("Pas de signal fort a venir; maintenir la surveillance habituelle.")
    return points


def _build_resident_daily_report(resident_id: str, report_date: Optional[str] = None, force: bool = False) -> dict:
    report_date = _local_report_date(report_date)
    redis_key = f"daily_report:{report_date}:{resident_id}"
    if not force:
        cached = redis_client.get(redis_key)
        if cached:
            return json.loads(cached)

    state = _safe_state_for_report(resident_id)
    profile = state.get("profile", {})
    v = state.get("vitals", {})
    hist = _history_summary(resident_id)
    alerts_today = _alerts_for_resident_on_date(resident_id, report_date)
    active_alert_raw = redis_client.get(f"alert:{resident_id}:active")
    active_alert = json.loads(active_alert_raw) if active_alert_raw else None
    risk = float(state.get("ml_risk", 0))
    level = max([a.get("level", 0) for a in alerts_today] + ([active_alert.get("level", 0)] if active_alert else [0]))
    location = state.get("location_label") or state.get("current_zone") or state.get("zone") or f"chambre {state.get('room', profile.get('room'))}"
    forecast = _forecast_points(state, hist, alerts_today)
    pathologies = profile.get("pathologies", [])

    report = {
        "date": report_date,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "resident_id": resident_id,
        "resident_name": profile.get("name", state.get("resident_name", resident_id)),
        "room": state.get("room", profile.get("room")),
        "floor": state.get("floor"),
        "caregiver": state.get("caregiver", profile.get("caregiver")),
        "profile": {
            "age": profile.get("age"),
            "mobility": profile.get("mobility"),
            "pathologies": pathologies,
            "care_level": state.get("care_level"),
        },
        "current": {
            "location": location,
            "activity": state.get("activity"),
            "routine": state.get("routine_label") or state.get("time_of_day"),
            "time_label": state.get("time_label"),
            "vitals": v,
            "movement": state.get("movement", {}),
            "sensor_events": state.get("sensor_events", {}),
        },
        "risk": {
            "ml_risk": round(risk, 2),
            "label": _risk_label(risk),
            "alert_level": level,
            "alert_level_name": _alert_level_name(level),
            "trend_30d": hist.get("risk_trend", "stable"),
        },
        "history_30d": hist,
        "alerts_today": alerts_today[-10:],
        "transmission_summary": (
            f"{profile.get('name', resident_id)} - chambre {state.get('room', profile.get('room'))}: "
            f"risque {_risk_label(risk)} ({risk:.0%}), niveau {_alert_level_name(level)}. "
            f"Position actuelle: {location}. "
            f"{len(alerts_today)} alerte(s) ce jour, {hist.get('alerts_count', 0)} evenement(s) sur 30 jours."
        ),
        "watch_points": forecast,
        "next_actions": [
            "Controler les constantes selon le niveau de risque.",
            "Verifier la concordance capteurs chambre/sol/porte si anomalie.",
            "Tracer toute modification de comportement dans la transmission.",
        ],
    }
    redis_client.setex(redis_key, 45 * 86400, json.dumps(report))
    redis_client.hset(f"daily_reports:{report_date}", resident_id, json.dumps(report))
    redis_client.expire(f"daily_reports:{report_date}", 45 * 86400)
    return report


def _build_global_daily_report(report_date: Optional[str] = None, force: bool = False) -> dict:
    report_date = _local_report_date(report_date)
    redis_key = f"daily_report:{report_date}:global"
    if not force:
        cached = redis_client.get(redis_key)
        if cached:
            return json.loads(cached)

    resident_reports = [
        _build_resident_daily_report(rid, report_date=report_date, force=force)
        for rid in RESIDENTS_MAP.keys()
    ]
    resident_reports.sort(key=lambda r: (r["risk"]["alert_level"], r["risk"]["ml_risk"]), reverse=True)
    by_caregiver: dict[str, list[dict]] = {}
    for report in resident_reports:
        by_caregiver.setdefault(report.get("caregiver") or "non_assigne", []).append({
            "resident_id": report["resident_id"],
            "resident_name": report["resident_name"],
            "room": report["room"],
            "risk": report["risk"],
            "summary": report["transmission_summary"],
            "watch_points": report["watch_points"][:2],
        })

    global_report = {
        "date": report_date,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total_residents": len(resident_reports),
        "risk_counts": {
            "stable": sum(1 for r in resident_reports if r["risk"]["alert_level"] == 0 and r["risk"]["ml_risk"] < 0.5),
            "surveillance": sum(1 for r in resident_reports if r["risk"]["alert_level"] in {1, 2} or 0.5 <= r["risk"]["ml_risk"] < 0.7),
            "urgent": sum(1 for r in resident_reports if r["risk"]["alert_level"] >= 3 or r["risk"]["ml_risk"] >= 0.7),
        },
        "priority_residents": resident_reports[:8],
        "by_caregiver": by_caregiver,
        "residents": resident_reports,
        "handover_sheet": [
            {
                "resident_id": r["resident_id"],
                "resident_name": r["resident_name"],
                "room": r["room"],
                "caregiver": r.get("caregiver"),
                "level": r["risk"]["alert_level_name"],
                "risk": r["risk"]["ml_risk"],
                "location": r["current"]["location"],
                "summary": r["transmission_summary"],
                "watch": " ".join(r["watch_points"][:2]),
            }
            for r in resident_reports
        ],
    }
    redis_client.setex(redis_key, 45 * 86400, json.dumps(global_report))
    return global_report


def daily_report_loop():
    global _last_daily_report_date
    while True:
        try:
            today = _local_report_date()
            existing = redis_client.get(f"daily_report:{today}:global")
            if today != _last_daily_report_date and not existing:
                _build_global_daily_report(today, force=False)
                _last_daily_report_date = today
                log.info(f"Rapport quotidien automatise genere pour {today}")
        except Exception as e:
            log.error(f"Rapport quotidien error: {e}")
        time.sleep(300)


# ============================================================
# MQTT handlers
# ============================================================

def on_connect(client, userdata, flags, rc):
    log.info(f"Connecté au broker MQTT (rc={rc})")
    client.subscribe("ehpad/residents/+/vitals", qos=1)
    client.subscribe("ehpad/residents/+/movement", qos=1)
    client.subscribe("ehpad/zones/+/ambient", qos=0)
    client.subscribe("ehpad/+/+/vitals", qos=1)
    client.subscribe("ehpad/+/+/motion", qos=2)
    client.subscribe("ehpad/+/+/bp_temp", qos=1)
    client.subscribe("ehpad/+/+/sos", qos=2)
    client.subscribe("ehpad/+/ambient/env", qos=0)
    client.subscribe("ehpad/+/door/ambient", qos=1)
    client.subscribe("ehpad/summary", qos=0)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        topic = msg.topic
        if topic == "ehpad/summary":
            _handle_summary(payload)
        elif topic.endswith("/vitals"):
            _handle_vitals(payload)
        elif topic.endswith("/movement") or topic.endswith("/motion"):
            _handle_movement(payload)
        elif topic.endswith("/bp_temp"):
            _handle_bp_temp(payload)
        elif topic.endswith("/sos"):
            _handle_sos(payload)
        elif "/ambient" in topic or "/door/" in topic:
            _handle_ambient(payload)
    except Exception as e:
        log.error(f"Erreur traitement message MQTT {msg.topic}: {e}")


def _track_routine(state: dict):
    """Enregistre le comportement horaire du résident et détecte les déviations (C4)."""
    rid = state["resident_id"]
    tod = state.get("time_of_day", "unknown")
    v = state["vitals"]
    entry = json.dumps({
        "hr": v["heart_rate"], "spo2": v["spo2"],
        "activity": state.get("activity", ""), "ts": time.time()
    })
    history_key = f"routine:{rid}:{tod}"
    redis_client.lpush(history_key, entry)
    redis_client.ltrim(history_key, 0, 99)       # 100 mesures max par période
    redis_client.expire(history_key, 7 * 86400)  # TTL 7 jours

    history = redis_client.lrange(history_key, 1, -1)  # exclure la mesure courante
    if len(history) < 15:
        return None  # pas assez d'historique

    hrs = [json.loads(h)["hr"] for h in history]
    avg_hr = float(np.mean(hrs))
    std_hr = float(np.std(hrs)) or 5.0
    deviation = abs(v["heart_rate"] - avg_hr) / std_hr

    if deviation > 2.5 and std_hr > 2.0:
        direction = "elevee" if v["heart_rate"] > avg_hr else "basse"
        return f"FC {direction} pour cette heure ({v['heart_rate']} bpm vs moy. {avg_hr:.0f}+/-{std_hr:.0f})"
    return None


def _handle_vitals(state: dict):
    rid = state.get("resident_id")
    if not rid:
        return
    now = time.time()

    # Enrichir avec profil résident
    profile = RESIDENTS_MAP.get(rid, {})
    age = profile.get("age", 80)
    base_risk = profile.get("risk_factor", 0.3)

    # Prédiction ML
    ml_risk = ml_predictor.predict(
        rid, state["vitals"], state.get("movement", {}), age, base_risk
    )
    if rid == DEMO_RESIDENT and state.get("scenario_active") == "hypoxie":
        ml_risk = max(ml_risk, 0.72)
    state["ml_risk"] = ml_risk
    state["resident_name"] = state.get("name", profile.get("name", rid))

    # Analyse de routine C4 : détecter déviations comportementales
    routine_deviation = _track_routine(state)
    if routine_deviation:
        state["routine_deviation"] = routine_deviation

    # Stocker état courant dans Redis
    redis_client.setex(f"resident:{rid}:state", 30, json.dumps(state))
    redis_client.hset("residents:all", rid, json.dumps({
        "id": rid,
        "name": state.get("name", ""),
        "room": state.get("room", ""),
        "floor": state.get("floor"),
        "zone": state.get("zone"),
        "current_zone": state.get("current_zone"),
        "target_zone": state.get("target_zone"),
        "position": state.get("position"),
        "activity": state.get("activity"),
        "sensor_events": state.get("sensor_events", {}),
        "room_sensors": state.get("room_sensors", []),
        "vitals": state["vitals"],
        "movement": state.get("movement", {}),
        "ml_risk": ml_risk,
        "scenario": state.get("scenario_active"),
        "movement_scenario": state.get("movement_scenario"),
        "assigned_movement_scenario": state.get("assigned_movement_scenario"),
        "time_of_day": state.get("time_of_day"),
        "time_label": state.get("time_label"),
        "routine_label": state.get("routine_label"),
        "care_level": state.get("care_level"),
        "meal_mode": state.get("meal_mode"),
        "dining_table": state.get("dining_table"),
        "dining_seat": state.get("dining_seat"),
        "caregiver": state.get("caregiver", ""),
        "last_update": datetime.utcnow().isoformat() + "Z",
    }))

    # Évaluer alertes
    alert = alert_engine.evaluate(state)

    # Écrire dans InfluxDB
    if now - _last_influx_write.get(rid, 0) >= INFLUX_SAMPLE_INTERVAL_S:
        _last_influx_write[rid] = now
        _write_influx(state)

    # Notifier dashboard via WebSocket
    if _loop and not _loop.is_closed() and (alert is not None or now - _last_ws_push.get(rid, 0) >= WS_RESIDENT_MIN_INTERVAL_S):
        _last_ws_push[rid] = now
        asyncio.run_coroutine_threadsafe(
            ws_manager.send_state_update({
                "resident_id": rid,
                "name": state.get("name"),
                "room": state.get("room"),
                "floor": state.get("floor"),
                "zone": state.get("zone"),
                "current_zone": state.get("current_zone"),
                "target_zone": state.get("target_zone"),
                "position": state.get("position"),
                "activity": state.get("activity"),
                "sensor_events": state.get("sensor_events", {}),
                "room_sensors": state.get("room_sensors", []),
                "vitals": state["vitals"],
                "movement": state.get("movement", {}),
                "ml_risk": ml_risk,
                "scenario": state.get("scenario_active"),
                "movement_scenario": state.get("movement_scenario"),
                "assigned_movement_scenario": state.get("assigned_movement_scenario"),
                "time_of_day": state.get("time_of_day"),
                "time_label": state.get("time_label"),
                "routine_label": state.get("routine_label"),
                "care_level": state.get("care_level"),
                "meal_mode": state.get("meal_mode"),
                "dining_table": state.get("dining_table"),
                "dining_seat": state.get("dining_seat"),
                "alert": alert.to_dict() if alert else None,
            }),
            _loop
        )
        if alert:
            asyncio.run_coroutine_threadsafe(
                ws_manager.send_alert(alert.to_dict()),
                _loop
            )


def _handle_movement(data: dict):
    rid = data.get("resident_id")
    if rid:
        redis_client.setex(f"resident:{rid}:movement", 30, json.dumps(data))


def _handle_bp_temp(data: dict):
    rid = data.get("resident_id")
    if rid:
        redis_client.setex(f"resident:{rid}:bp_temp", 120, json.dumps(data))


def _handle_sos(data: dict):
    rid = data.get("resident_id")
    if not rid:
        return
    alert = {
        "type": "sos",
        "resident_id": rid,
        "room": data.get("room"),
        "zone": data.get("zone"),
        "timestamp": data.get("timestamp"),
        "message": "Bouton SOS resident active",
        "level": 4,
    }
    redis_client.lpush("alerts:sos", json.dumps(alert))
    redis_client.expire("alerts:sos", 3600)
    log.warning(f"[SOS] Resident {rid} chambre {data.get('room')}")


def _handle_ambient(data: dict):
    zone_id = data.get("zone_id")
    if zone_id:
        redis_client.setex(f"zone:{zone_id}:state", 30, json.dumps(data))
        redis_client.hset("zones:all", zone_id, json.dumps(data))

        # Détection de fugue : résident en zone sortie ou hors site
        if data.get("zone_id") == "hors_ehpad" and data.get("occupancy", 0) > 0:
            _check_elopement(data)
        elif data.get("zone_type") == "entree" and data.get("occupancy", 0) > 0:
            h = datetime.now().hour
            if h < 7 or h > 21:
                _check_elopement(data)


def _check_elopement(zone_data: dict):
    """Vérifie si un résident désorienté (alzheimer) est à l'entrée hors horaires."""
    alert = {
        "type": "elopement_risk",
        "zone": zone_data["zone_name"],
        "resident_ids": zone_data.get("resident_ids", []),
        "timestamp": zone_data.get("timestamp"),
        "message": "Fugue detectee: resident en sortie hors EHPAD",
        "level": 4
    }
    redis_client.lpush("alerts:elopement", json.dumps(alert))
    redis_client.expire("alerts:elopement", 3600)
    log.warning(f"[FUGUE] {alert['message']}")


def _handle_summary(data: dict):
    redis_client.setex("ehpad:summary", 5, json.dumps(data))


def _write_influx(state: dict):
    try:
        v = state["vitals"]
        rid = state["resident_id"]
        point = (
            Point("vitals")
            .tag("resident_id", rid)
            .tag("room", state.get("room", ""))
            .field("heart_rate", float(v.get("heart_rate", 0)))
            .field("spo2", float(v.get("spo2", 0)))
            .field("blood_pressure_sys", float(v.get("blood_pressure_sys", 0)))
            .field("blood_pressure_dia", float(v.get("blood_pressure_dia", 0)))
            .field("temperature", float(v.get("temperature", 0)))
            .field("respiratory_rate", float(v.get("respiratory_rate", 0)))
            .field("ml_risk", float(state.get("ml_risk", 0)))
            .time(datetime.utcnow(), WritePrecision.SECONDS)
        )
        write_api.write(bucket=INFLUX_BUCKET, record=point)
    except Exception as e:
        log.debug(f"InfluxDB write error (non-bloquant): {e}")


# ============================================================
# Escalade périodique
# ============================================================

def escalation_loop():
    while True:
        try:
            alert_engine.check_escalations()
        except Exception as e:
            log.error(f"Escalade error: {e}")
        time.sleep(15)


# ============================================================
# REST API
# ============================================================

@app.get("/")
def root():
    return {"service": "EHPAD Backend", "status": "ok"}


@app.get("/health")
def health():
    """Healthcheck pour Docker — vérifie Redis + compte les résidents actifs."""
    try:
        redis_client.ping()
        resident_count = len(redis_client.hgetall("residents:all"))
        return {"status": "ok", "residents": resident_count, "ts": datetime.utcnow().isoformat()}
    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content={"status": "degraded", "error": str(e)})


@app.get("/api/residents")
def get_all_residents():
    """Liste tous les résidents avec leur état courant."""
    data = redis_client.hgetall("residents:all")
    residents = []
    for rid, raw in data.items():
        try:
            r = json.loads(raw)
            # Ajouter l'alerte active si présente
            alert_raw = redis_client.get(f"alert:{rid}:active")
            r["active_alert"] = json.loads(alert_raw) if alert_raw else None
            residents.append(r)
        except Exception:
            pass
    return {"residents": residents, "count": len(residents)}


@app.get("/api/residents/{resident_id}")
def get_resident(resident_id: str):
    raw = redis_client.get(f"resident:{resident_id}:state")
    if not raw:
        raise HTTPException(404, "Résident non trouvé")
    state = json.loads(raw)
    # Historique comportemental
    profile = RESIDENTS_MAP.get(resident_id, {})
    state["profile"] = profile
    return state


@app.get("/api/residents/{resident_id}/history")
def get_resident_history(resident_id: str, minutes: int = 60):
    """Retourne l'historique InfluxDB du résident."""
    try:
        query_api = influx.query_api()
        query = f'''
        from(bucket: "{INFLUX_BUCKET}")
          |> range(start: -{minutes}m)
          |> filter(fn: (r) => r["resident_id"] == "{resident_id}")
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        '''
        result = query_api.query(query)
        rows = []
        for table in result:
            for record in table.records:
                rows.append({
                    "time": record.get_time().isoformat(),
                    "heart_rate": record.values.get("heart_rate"),
                    "spo2": record.values.get("spo2"),
                    "blood_pressure_sys": record.values.get("blood_pressure_sys"),
                    "blood_pressure_dia": record.values.get("blood_pressure_dia"),
                    "temperature": record.values.get("temperature"),
                    "respiratory_rate": record.values.get("respiratory_rate"),
                    "ml_risk": record.values.get("ml_risk"),
                })
        return {"resident_id": resident_id, "history": rows}
    except Exception as e:
        return {"resident_id": resident_id, "history": [], "error": str(e)}


@app.get("/api/residents/{resident_id}/history/simulated")
def get_resident_simulated_history(resident_id: str, days: int = 30, step_hours: int = 6):
    """Historique simule long terme pour tester un mois de scenarios sans attendre InfluxDB."""
    rows = _simulated_history_rows(resident_id, days=days, step_hours=step_hours)
    return {"resident_id": resident_id, "days": max(30, days), "step_hours": step_hours, "history": rows}


@app.get("/api/simulator/speed")
def get_simulator_speed():
    raw = redis_client.get("simulator:speed")
    return {"speed": float(raw) if raw else 1.0}


@app.post("/api/simulator/speed")
def set_simulator_speed(speed: float = 1.0):
    speed = max(0.25, min(60.0, float(speed)))
    redis_client.set("simulator:speed", speed)
    publish_mqtt_control("ehpad/control/speed", {"speed": speed, "updated_at": datetime.utcnow().isoformat() + "Z"})
    return {"ok": True, "speed": speed}


@app.get("/api/alerts")
def get_alerts():
    active = alert_engine.get_all_active()
    history = alert_engine.get_history(50)
    return {"active": active, "history": history}


@app.post("/api/alerts/{resident_id}/acknowledge")
def acknowledge_alert(resident_id: str, by: str = "soignant"):
    ok = alert_engine.acknowledge(resident_id, by)
    if not ok:
        raise HTTPException(404, "Pas d'alerte active pour ce résident")
    return {"ok": True, "message": f"Alerte acquittée par {by}"}


@app.get("/api/zones")
def get_zones():
    data = redis_client.hgetall("zones:all")
    zones = [json.loads(v) for v in data.values()]
    return {"zones": zones}


@app.get("/api/summary")
def get_summary():
    raw = redis_client.get("ehpad:summary")
    if raw:
        return json.loads(raw)
    return {"error": "Pas encore de données"}


@app.post("/api/reports/daily/generate")
def generate_daily_report(date: Optional[str] = None, force: bool = False):
    """Genere et stocke la fiche de transmission quotidienne globale."""
    report_date = _local_report_date(date)
    report = _build_global_daily_report(report_date, force=force)
    return {"ok": True, "date": report_date, "report": report}


@app.get("/api/reports/today")
def get_today_report():
    report_date = _local_report_date()
    return _build_global_daily_report(report_date, force=False)


@app.get("/api/reports/daily/{date}")
def get_daily_report(date: str):
    return _build_global_daily_report(date, force=False)


@app.get("/api/reports/daily/{date}/{resident_id}")
def get_daily_resident_report(date: str, resident_id: str):
    if resident_id not in RESIDENTS_MAP:
        raise HTTPException(404, "Resident non trouve")
    return _build_resident_daily_report(resident_id, report_date=date, force=False)


@app.get("/api/residents/{resident_id}/dpi")
def get_resident_dpi(resident_id: str, date: Optional[str] = None):
    """Mini DPI: profil, constantes, alertes, historique 30 jours et risque a venir."""
    if resident_id not in RESIDENTS_MAP:
        raise HTTPException(404, "Resident non trouve")
    report_date = _local_report_date(date)
    return {
        "resident_id": resident_id,
        "date": report_date,
        "mini_dpi": _build_resident_daily_report(resident_id, report_date=report_date, force=False),
    }


@app.get("/api/ml/metrics")
def get_ml_metrics():
    """Métriques de performance du modèle ML (accuracy, AUC, F1)."""
    if not ml_predictor.metrics:
        return {"status": "model_loaded_from_disk", "metrics": {}}
    return {"status": "ok", "metrics": ml_predictor.metrics}


@app.get("/api/alerts/elopement")
def get_elopement_alerts():
    alerts = redis_client.lrange("alerts:elopement", 0, 20)
    return {"alerts": [json.loads(a) for a in alerts]}


@app.get("/api/residents/{resident_id}/routine")
def get_resident_routine(resident_id: str):
    """Analyse comportementale C4 — baseline par période de journée."""
    profile = RESIDENTS_MAP.get(resident_id)
    if not profile:
        raise HTTPException(404, "Résident non trouvé")
    periods = ["lever_toilette", "petit_dej", "soins_matin", "animation_matin",
               "trajet_dejeuner", "dejeuner", "sieste", "animation_apres_midi",
               "gouter", "trajet_diner", "diner", "soiree", "coucher", "nuit"]
    routine = {}
    for tod in periods:
        key = f"routine:{resident_id}:{tod}"
        entries = redis_client.lrange(key, 0, -1)
        if len(entries) < 3:
            routine[tod] = {"samples": len(entries), "avg_hr": None, "std_hr": None}
            continue
        hrs = [json.loads(e)["hr"] for e in entries]
        routine[tod] = {
            "samples": len(hrs),
            "avg_hr": round(float(np.mean(hrs)), 1),
            "std_hr": round(float(np.std(hrs)), 1),
            "min_hr": int(min(hrs)),
            "max_hr": int(max(hrs)),
        }
    return {"resident_id": resident_id, "name": profile.get("name"), "routine": routine}


@app.get("/api/famille/{resident_id}")
def get_famille_view(resident_id: str, code: str = ""):
    """Interface famille C3 — vue générale sans détails médicaux."""
    if code != "FAMILLE":
        raise HTTPException(403, "Code famille invalide")
    raw = redis_client.get(f"resident:{resident_id}:state")
    if not raw:
        raise HTTPException(404, "Résident non trouvé")
    state = json.loads(raw)
    profile = RESIDENTS_MAP.get(resident_id, {})
    alert_raw = redis_client.get(f"alert:{resident_id}:active")
    alert_level = json.loads(alert_raw).get("level", 0) if alert_raw else 0
    if alert_level >= 4:
        general_status = "Surveillance renforcée"
    elif alert_level >= 2:
        general_status = "Sous surveillance"
    else:
        general_status = "Situation stable"
    return {
        "name": profile.get("name", resident_id),
        "room": state.get("room"),
        "floor": state.get("floor"),
        "general_status": general_status,
        "activity": state.get("routine_label", state.get("activity", "")),
        "last_update": state.get("timestamp", ""),
    }


@app.get("/api/llm/report/{resident_id}")
async def get_llm_report(resident_id: str):
    """Génère un rapport quotidien via Meditron:7b (Ollama local) — C2."""
    raw = redis_client.get(f"resident:{resident_id}:state")
    if not raw:
        raise HTTPException(404, "Résident non trouvé")
    state = json.loads(raw)
    profile = RESIDENTS_MAP.get(resident_id, {})

    v = state["vitals"]
    ml_risk = state.get("ml_risk", 0)
    ml_level = "élevé" if ml_risk > 0.7 else "modéré" if ml_risk > 0.4 else "faible"
    alerts_today = [a for a in alert_engine.get_history(100) if a["resident_id"] == resident_id]
    alert_lines = "\n".join(f"- {a['reason']}" for a in alerts_today[:5]) or "- Aucune alerte aujourd'hui"
    pathologies = ", ".join(profile.get("pathologies", [])) or "Aucune"

    prompt = f"""You are a medical AI assistant for a French nursing home (EHPAD). Write a concise daily clinical report in French for the following resident.

Resident: {profile.get('name', resident_id)}, {profile.get('age', '?')} ans
Room: {profile.get('room', '?')}
Pathologies: {pathologies}
Mobility: {profile.get('mobility', '?')}

Current vital signs:
- Heart rate: {v['heart_rate']:.0f} bpm
- SpO2: {v['spo2']:.1f}%
- Blood pressure: {v['blood_pressure_sys']:.0f} mmHg (systolic)
- Temperature: {v['temperature']:.1f}°C
- Respiratory rate: {v.get('respiratory_rate', 16):.0f} /min

AI malaise risk score: {ml_risk:.0%} ({ml_level})

Alerts today:
{alert_lines}

Write a 3-4 sentence clinical summary in French for the nursing staff, highlighting any concerns and recommended observations. Be concise and professional."""

    try:
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{OLLAMA_HOST}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            llm_text = resp.json().get("response", "").strip()
            source = "meditron:7b (Ollama local)"
    except Exception as e:
        log.warning(f"Ollama unavailable ({e}), using fallback summary")
        llm_text = (
            f"{profile.get('name', resident_id)} ({profile.get('age', '?')} ans) — "
            f"FC {v['heart_rate']:.0f} bpm, SpO2 {v['spo2']:.1f}%, "
            f"PA {v['blood_pressure_sys']:.0f} mmHg, T° {v['temperature']:.1f}°C. "
            f"Risque IA : {ml_level} ({ml_risk:.0%}). "
            f"{len(alerts_today)} alerte(s) aujourd'hui."
        )
        source = "fallback (Ollama non disponible)"

    return {
        "resident_id": resident_id,
        "resident_name": profile.get("name", resident_id),
        "date": datetime.utcnow().date().isoformat(),
        "report": llm_text,
        "model": source,
        "alerts_count_today": len(alerts_today),
        "ml_risk": round(ml_risk, 2),
        "ml_risk_level": ml_level,
    }


# ============================================================
# WebSocket endpoint
# ============================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        # Envoyer l'état initial
        residents_raw = redis_client.hgetall("residents:all")
        residents = [json.loads(v) for v in residents_raw.values()]
        await websocket.send_json({
            "type": "init",
            "data": {
                "residents": residents,
                "alerts": alert_engine.get_all_active()
            }
        })
        while True:
            # Attendre messages du client (acquittements)
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "acknowledge":
                    rid = msg.get("resident_id")
                    by = msg.get("by", "dashboard")
                    alert_engine.acknowledge(rid, by)
            except Exception:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# ============================================================
# Startup
# ============================================================

@app.on_event("startup")
async def startup():
    global _loop
    _loop = asyncio.get_event_loop()
    redis_client.delete("residents:all", "zones:all")

    # Connexion MQTT en thread séparé
    def mqtt_thread():
        client = mqtt.Client(client_id=f"ehpad_backend_{os.getpid()}")
        client.on_connect = on_connect
        client.on_message = on_message
        retries = 0
        while retries < 20:
            try:
                client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
                client.loop_forever()
                break
            except Exception as e:
                retries += 1
                log.warning(f"MQTT connexion impossible ({e}), retry {retries}/20...")
                time.sleep(3)

    threading.Thread(target=mqtt_thread, daemon=True).start()

    # Thread d'escalade
    threading.Thread(target=escalation_loop, daemon=True).start()
    threading.Thread(target=daily_report_loop, daemon=True).start()

    log.info("Backend EHPAD démarré ✓")
