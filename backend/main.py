"""
Backend EHPAD - FastAPI
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
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np

import paho.mqtt.client as mqtt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Header
from influxdb_client import Point, WritePrecision

from app.api import register_routers
from app.api.routers import a2a_ml as a2a_ml_router
from app.api.routers import alerts as alerts_router
from app.api.routers import famille as famille_router
from app.api.routers import kb as kb_router
from app.api.routers import live as live_router
from app.api.routers import llm as llm_router
from app.api.routers import push as push_router
from app.api.routers import reports as reports_router
from app.api.routers import simulator as simulator_router
from app.api.routers import staff as staff_router
from app.core.config import settings
from app.core.middleware import create_limiter, setup_middlewares
from app.core.runtime import runtime
from app.core.security import SecurityService
from app.db.redis_client import redis_client
from app.db.influx_client import influx, write_api, query_api
from app.domain.residents import RESIDENT_ARCHETYPES, resident_archetype as _resident_archetype
from app.domain.scenarios import SIMULATION_SCENARIOS
from app.services.resident_service import (
    effective_resident_profile,
    get_live_resident,
    list_live_residents,
    resident_caregiver,
    resident_config,
    resident_file_profile,
)
from app.services.staff_service import staff_status
from app.services.push_service import PushService
from app.services.llm_report_service import LLMReportService
from app.services.patient_files_service import PatientFilesService
from app.services.scalability_service import ScalabilityService
from app.services.scheduler_service import SchedulerService
from alert_engine import AlertEngine, LEVEL_CONFIG
from ws_manager import WebSocketManager
from ml_model import MalaisePredictor
from a2a_agents import agent_card
from reports import DailyReportService
from routine_engine import update_and_detect, get_routine_summary

logging.basicConfig(level=logging.INFO, format='%(asctime)s [BACKEND] %(message)s')
log = logging.getLogger(__name__)

# --- Config ---
MQTT_HOST = settings.mqtt_host
MQTT_PORT = settings.mqtt_port
MQTT_USERNAME = settings.mqtt_username
MQTT_PASSWORD = settings.mqtt_password
INFLUX_BUCKET = settings.influx_bucket
DEMO_RESIDENT = settings.demo_resident
INFLUX_SAMPLE_INTERVAL_S = settings.influx_sample_interval_s
WS_RESIDENT_MIN_INTERVAL_S = settings.ws_resident_min_interval_s
OLLAMA_HOST = settings.ollama_host
OLLAMA_MODEL = settings.ollama_model
LLM_DAILY_AUTO_ENABLED = settings.llm_daily_auto_enabled
LLM_DAILY_TTL_DAYS = settings.llm_daily_ttl_days
FAMILLE_ADMIN_TOKEN = settings.famille_admin_token
SESSION_SECRET = settings.session_secret
STAFF_DEMO_PASSWORD = settings.staff_demo_password
ALLOWED_ORIGINS = settings.allowed_origins
HTTPS_REQUIRED = settings.https_required
RETENTION_ACCESS_LOG_DAYS = settings.retention_access_log_days
RETENTION_AUDIT_DAYS = settings.retention_audit_days
PATIENT_DATA_DIR = settings.patient_data_dir


def _fmt_bp(vitals: dict) -> str:
    sys = vitals.get("blood_pressure_sys")
    dia = vitals.get("blood_pressure_dia")
    if sys is None:
        return "-"
    try:
        sys_txt = f"{float(sys):.0f}"
    except (TypeError, ValueError):
        sys_txt = str(sys)
    if dia is None:
        return f"{sys_txt} mmHg"
    try:
        dia_txt = f"{float(dia):.0f}"
    except (TypeError, ValueError):
        dia_txt = str(dia)
    return f"{sys_txt}/{dia_txt} mmHg"

# --- Web Push VAPID ---
VAPID_PUBLIC_KEY = settings.vapid_public_key
VAPID_PRIVATE_KEY = settings.vapid_private_key
VAPID_CLAIMS_EMAIL = settings.vapid_claims_email
WEBPUSH_ENABLED = settings.webpush_enabled

# --- Profils résidents (importé depuis le simulateur, ou hardcodé)
from resident_profiles import RESIDENTS_MAP, RESIDENTS_LIST, FAMILY_CODE_MAP, CAREGIVERS
import auth as auth_module

# --- Init ---
limiter = create_limiter()
app = FastAPI(title="EHPAD API", version="1.0.0")
setup_middlewares(app, limiter)
register_routers(app)

ws_manager = WebSocketManager()
alert_engine = AlertEngine(redis_client, ws_manager)
ml_predictor = MalaisePredictor()
security_service = SecurityService(
    redis_client=redis_client,
    caregivers=CAREGIVERS,
    residents_map=RESIDENTS_MAP,
    session_secret=SESSION_SECRET,
    retention_access_log_days=RETENTION_ACCESS_LOG_DAYS,
    resident_caregiver=lambda resident_id, profile=None: _resident_caregiver(resident_id, profile),
    active_alert_for_resident=lambda resident_id: _active_alert_for_resident(resident_id),
)
push_service = PushService(
    redis_client=redis_client,
    caregivers=CAREGIVERS,
    alert_engine=alert_engine,
    retention_audit_days=RETENTION_AUDIT_DAYS,
    webpush_enabled=WEBPUSH_ENABLED,
    vapid_public_key=VAPID_PUBLIC_KEY,
    vapid_private_key=VAPID_PRIVATE_KEY,
    vapid_claims_email=VAPID_CLAIMS_EMAIL,
)

# InfluxDB

# Loop asyncio partagée
_loop: Optional[asyncio.AbstractEventLoop] = None
_last_influx_write: dict[str, float] = {}
_last_ws_push: dict[str, float] = {}
_last_daily_report_date: Optional[str] = None
_started_at = time.time()
_mqtt_message_count = 0
_mqtt_vitals_count = 0
_mqtt_ambient_count = 0
_ws_push_count = 0
_last_mqtt_message_at: Optional[float] = None
_mqtt_window: deque[tuple[float, str]] = deque(maxlen=20000)

def _staff_status(caregiver_id: str) -> dict:
    return staff_status(caregiver_id, CAREGIVERS)


def _resident_caregiver(resident_id: str, profile: Optional[dict] = None) -> str:
    return resident_caregiver(resident_id, RESIDENTS_MAP, profile)


def _resident_config(resident_id: str) -> dict:
    return resident_config(resident_id)


def _effective_resident_profile(resident_id: str) -> dict:
    return effective_resident_profile(resident_id, RESIDENTS_MAP)


def _staff_notification_preview(caregiver_id: str, level: int) -> list[dict]:
    targets = []
    def add(cid: str, reason: str):
        if cid and cid not in {t["id"] for t in targets}:
            staff = _staff_status(cid)
            targets.append({
                "id": cid,
                "name": staff.get("name", cid),
                "role": staff.get("role"),
                "status": staff.get("status"),
                "sector": staff.get("sector"),
                "reason": reason,
            })
    add("dashboard", "affichage central")
    if level >= 2:
        add(caregiver_id, "soignant assigne")
    if level >= 4:
        for cid in ["soignant_A", "soignant_B", "soignant_C", "chef_garde"]:
            add(cid, "urgence tous soignants")
    if level >= 5:
        add("direction", "danger vital direction")
    return targets


def publish_mqtt_control(topic: str, payload: dict):
    client = mqtt.Client(client_id=f"ehpad_backend_control_{os.getpid()}_{int(time.time() * 1000)}")
    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.publish(topic, json.dumps(payload), qos=1, retain=True)
    client.disconnect()


scalability_service = ScalabilityService(
    redis_client=redis_client,
    started_at=_started_at,
    mqtt_window=_mqtt_window,
    counters=lambda: {
        "mqtt_message_count": _mqtt_message_count,
        "mqtt_vitals_count": _mqtt_vitals_count,
        "mqtt_ambient_count": _mqtt_ambient_count,
        "ws_push_count": _ws_push_count,
        "last_mqtt_message_at": _last_mqtt_message_at,
    },
    influx_sample_interval_s=INFLUX_SAMPLE_INTERVAL_S,
    ws_resident_min_interval_s=WS_RESIDENT_MIN_INTERVAL_S,
)


daily_reports = DailyReportService(
    redis_client=redis_client,
    alert_engine=alert_engine,
    residents_map=RESIDENTS_MAP,
    archetypes=RESIDENT_ARCHETYPES,
    effective_resident_profile=_effective_resident_profile,
    resident_caregiver=_resident_caregiver,
    resident_archetype=_resident_archetype,
    influx_query_api=query_api,
    influx_bucket=INFLUX_BUCKET,
)

_simulated_history_rows = daily_reports.simulated_history_rows
_local_report_date = daily_reports.local_report_date
_alert_level_name = daily_reports.alert_level_name
_risk_label = daily_reports.risk_label
_safe_state_for_report = daily_reports.safe_state_for_report
_alerts_for_resident_on_date = daily_reports.alerts_for_resident_on_date
_active_alert_for_resident = daily_reports.active_alert_for_resident
_history_summary = daily_reports.history_summary
_prediction_memory_for_resident = daily_reports.prediction_memory_for_resident
_remember_prediction = daily_reports.remember_prediction
_zone_label = daily_reports.zone_label
_routine_label_for_family = daily_reports.routine_label_for_family
_resident_week_life = daily_reports.resident_week_life
_forecast_points = daily_reports.forecast_points
_a2a_prediction_for_resident = daily_reports.a2a_prediction_for_resident
_build_resident_daily_report = daily_reports.build_resident_daily_report
_build_global_daily_report = daily_reports.build_global_daily_report

patient_files_service = PatientFilesService(
    patient_data_dir=PATIENT_DATA_DIR,
    redis_client=redis_client,
    residents_map=RESIDENTS_MAP,
    resident_config=_resident_config,
    effective_resident_profile=_effective_resident_profile,
    simulated_history_rows=_simulated_history_rows,
)

llm_report_service = LLMReportService(
    redis_client=redis_client,
    alert_engine=alert_engine,
    residents_map=RESIDENTS_MAP,
    patient_data_dir=PATIENT_DATA_DIR,
    local_report_date=_local_report_date,
    safe_state_for_report=_safe_state_for_report,
    build_resident_daily_report=_build_resident_daily_report,
    llm_daily_ttl_days=LLM_DAILY_TTL_DAYS,
    llm_daily_auto_enabled=LLM_DAILY_AUTO_ENABLED,
    ollama_host=OLLAMA_HOST,
    ollama_model=OLLAMA_MODEL,
)


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
    global _mqtt_message_count, _mqtt_vitals_count, _mqtt_ambient_count, _last_mqtt_message_at
    try:
        _mqtt_message_count += 1
        now = time.time()
        _last_mqtt_message_at = now
        _mqtt_window.append((now, msg.topic))
        if msg.topic.endswith("/vitals"):
            _mqtt_vitals_count += 1
        if "/ambient" in msg.topic or "/door/" in msg.topic:
            _mqtt_ambient_count += 1
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
    global _ws_push_count
    rid = state.get("resident_id")
    if not rid:
        return
    now = time.time()

    # Enrichir avec profil résident
    profile = RESIDENTS_MAP.get(rid, {})
    state["caregiver"] = _resident_caregiver(rid, profile)
    caregiver_info = _staff_status(state["caregiver"])
    state["caregiver_name"] = caregiver_info.get("name")
    state["staff_directory"] = {cid: _staff_status(cid) for cid in CAREGIVERS.keys()}
    age = profile.get("age", 80)
    base_risk = profile.get("risk_factor", 0.3)

    # Prédiction ML
    ml_prediction = ml_predictor.predict_horizons(
        rid, state["vitals"], state.get("movement", {}), age, base_risk
    )
    ml_risk = ml_prediction["risk_60min"]
    if rid == DEMO_RESIDENT and state.get("scenario_active") == "hypoxie":
        ml_risk = max(ml_risk, 0.72)
        ml_prediction["risk_30min"] = max(ml_prediction["risk_30min"], 0.62)
        ml_prediction["risk_60min"] = ml_risk
        ml_prediction["signals"] = list(dict.fromkeys(["hypoxie progressive demo"] + ml_prediction.get("signals", [])))
    state["ml_risk"] = ml_risk
    state["ml_prediction"] = ml_prediction
    state["resident_name"] = state.get("name", profile.get("name", rid))
    room_zone = f"ch{state.get('room')}" if state.get("room") else state.get("zone")
    for sensor in state.get("sensor_health", []):
        sensor_key = sensor.get("id") or f"{rid}-{sensor.get('type', 'sensor')}"
        fixed_room_sensor = room_zone and str(sensor_key).startswith(f"{room_zone}-")
        redis_client.hset("sensors:health", sensor_key, json.dumps({
            **sensor,
            "resident_id": rid,
            "resident_name": state.get("resident_name"),
            "room": state.get("room"),
            "zone_id": room_zone if fixed_room_sensor else state.get("current_zone") or state.get("zone"),
            "updated_at": state.get("timestamp") or datetime.utcnow().isoformat() + "Z",
        }))
        redis_client.expire("sensors:health", 3600)

    # Analyse de routine C4 : détecter déviations comportementales
    routine_analysis = update_and_detect(redis_client, state)
    state["routine_analysis"] = routine_analysis
    if routine_analysis.get("alert_level", 0) >= 2:
        state["routine_deviation"] = " ; ".join(routine_analysis.get("flags", [])[:3])

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
        "sensor_health": state.get("sensor_health", []),
        "life_profile": state.get("life_profile"),
        "routine_context": state.get("routine_context"),
        "routine_analysis": state.get("routine_analysis"),
        "room_sensors": state.get("room_sensors", []),
        "vitals": state["vitals"],
        "movement": state.get("movement", {}),
        "ml_risk": ml_risk,
        "ml_prediction": ml_prediction,
        "scenario": state.get("scenario_active"),
        "movement_scenario": state.get("movement_scenario"),
        "assigned_movement_scenario": state.get("assigned_movement_scenario"),
        "assigned_scenarios": state.get("assigned_scenarios"),
        "time_of_day": state.get("time_of_day"),
        "time_label": state.get("time_label"),
        "routine_label": state.get("routine_label"),
        "timestamp_real": state.get("timestamp_real") or state.get("timestamp"),
        "timestamp_simulated": state.get("timestamp_simulated"),
        "simulated_datetime": state.get("simulated_datetime"),
        "simulated_date": state.get("simulated_date"),
        "simulated_time": state.get("simulated_time"),
        "simulated_weekday": state.get("simulated_weekday"),
        "simulated_day_index": state.get("simulated_day_index"),
        "simulated_label": state.get("simulated_label"),
        "care_level": state.get("care_level"),
        "meal_mode": state.get("meal_mode"),
        "dining_table": state.get("dining_table"),
        "dining_seat": state.get("dining_seat"),
        "caregiver": state.get("caregiver", ""),
        "caregiver_name": state.get("caregiver_name"),
        "last_update": datetime.utcnow().isoformat() + "Z",
    }))

    # Évaluer alertes
    alert = alert_engine.evaluate(state)
    active_alert = alert or alert_engine.active_alerts.get(rid)
    active_alert_payload = active_alert.to_dict() if active_alert else None

    # Écrire dans InfluxDB
    if now - _last_influx_write.get(rid, 0) >= INFLUX_SAMPLE_INTERVAL_S:
        _last_influx_write[rid] = now
        _write_influx(state)

    # Notifier dashboard via WebSocket
    if _loop and not _loop.is_closed() and (alert is not None or now - _last_ws_push.get(rid, 0) >= WS_RESIDENT_MIN_INTERVAL_S):
        _last_ws_push[rid] = now
        _ws_push_count += 1
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
                "sensor_health": state.get("sensor_health", []),
                "life_profile": state.get("life_profile"),
                "routine_context": state.get("routine_context"),
                "routine_analysis": state.get("routine_analysis"),
                "room_sensors": state.get("room_sensors", []),
                "vitals": state["vitals"],
                "movement": state.get("movement", {}),
                "ml_risk": ml_risk,
                "ml_prediction": ml_prediction,
                "scenario": state.get("scenario_active"),
                "movement_scenario": state.get("movement_scenario"),
                "assigned_movement_scenario": state.get("assigned_movement_scenario"),
                "assigned_scenarios": state.get("assigned_scenarios"),
                "time_of_day": state.get("time_of_day"),
                "time_label": state.get("time_label"),
                "routine_label": state.get("routine_label"),
                "timestamp_real": state.get("timestamp_real") or state.get("timestamp"),
                "timestamp_simulated": state.get("timestamp_simulated"),
                "simulated_datetime": state.get("simulated_datetime"),
                "simulated_date": state.get("simulated_date"),
                "simulated_time": state.get("simulated_time"),
                "simulated_weekday": state.get("simulated_weekday"),
                "simulated_day_index": state.get("simulated_day_index"),
                "simulated_label": state.get("simulated_label"),
                "care_level": state.get("care_level"),
                "meal_mode": state.get("meal_mode"),
                "dining_table": state.get("dining_table"),
                "dining_seat": state.get("dining_seat"),
                "caregiver": state.get("caregiver", ""),
                "caregiver_name": state.get("caregiver_name"),
                "alert": active_alert_payload,
            }),
            _loop
        )
        if alert:
            a = alert.to_dict()
            if a.get("level", 0) >= 2 and push_service.enabled:
                asyncio.run_coroutine_threadsafe(
                    push_service.dispatch_alert_push_async(a),
                    _loop
                )
            asyncio.run_coroutine_threadsafe(
                ws_manager.send_alert(a),
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
        for sensor in data.get("sensor_health", []):
            sensor_key = sensor.get("id") or f"{zone_id}-{sensor.get('type', 'sensor')}"
            redis_client.hset("sensors:health", sensor_key, json.dumps({
                **sensor,
                "zone_id": zone_id,
                "zone_name": data.get("zone_name"),
                "updated_at": data.get("timestamp") or datetime.utcnow().isoformat() + "Z",
            }))
            redis_client.expire("sensors:health", 3600)

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


def _staff_snapshot() -> dict:
    active_alerts = [push_service.attach_delivery(a) for a in alert_engine.get_all_active()]
    residents_raw = redis_client.hgetall("residents:all")
    live_residents = {}
    for rid, raw in residents_raw.items():
        try:
            live_residents[rid] = json.loads(raw)
        except Exception:
            pass

    staff_history = _staff_simulated_history(days=30, step_hours=6)

    staff = []
    for caregiver_id in CAREGIVERS.keys():
        info = _staff_status(caregiver_id)
        assigned = []
        for rid, profile in RESIDENTS_MAP.items():
            if _resident_caregiver(rid, profile) == caregiver_id:
                live = live_residents.get(rid, {})
                assigned.append({
                    "resident_id": rid,
                    "name": profile.get("name"),
                    "room": profile.get("room"),
                    "current_zone": live.get("current_zone"),
                    "ml_risk": live.get("ml_risk", profile.get("risk_factor", 0)),
                    "alert_level": (_active_alert_for_resident(rid) or {}).get("level", 0),
                })
        notified_alerts = [
            a for a in active_alerts
            if caregiver_id in {t.get("id") for t in a.get("notified_staff", [])}
        ]
        max_level = max([a.get("level", 0) for a in notified_alerts] + [0])
        history = staff_history.get(caregiver_id, [])
        audit_recent = _notification_audit_for_staff(caregiver_id, limit=8)
        staff.append({
            **info,
            "assigned_count": len(assigned),
            "assigned_residents": assigned,
            "active_alerts_count": len(notified_alerts),
            "max_alert_level": max_level,
            "history_count_30d": len(history),
            "recent_history": history[:8],
            "audit_recent": audit_recent,
            "workload_score": len(assigned) + len(notified_alerts) * 3 + max_level,
            "notifications": [
                {
                    "alert_id": a.get("id"),
                    "notification_key": _notification_key(a),
                    "resident_id": a.get("resident_id"),
                    "resident_name": a.get("resident_name"),
                    "level": a.get("level"),
                    "reason": a.get("reason"),
                    "location": a.get("location_label"),
                    "status": _notification_status(caregiver_id, _notification_key(a)).get("action", "envoyee"),
                    "status_at": _notification_status(caregiver_id, _notification_key(a)).get("at"),
                    "push_delivery": a.get("push_delivery"),
                    "samu_status": (_ensure_samu_call(a) or {}).get("status") if int(a.get("level") or 0) >= 5 else None,
                }
                for a in notified_alerts
            ],
        })
    staff.sort(key=lambda s: (s["max_alert_level"], s["workload_score"]), reverse=True)
    return {"staff": staff, "active_alerts": active_alerts}


def _staff_simulated_history(days: int = 30, step_hours: int = 6) -> dict[str, list[dict]]:
    """Historique exploitable par soignant, base sur la simulation 30 jours."""
    cache_key = f"staff:simulated_history:{days}:{step_hours}:v1"
    cached = redis_client.get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    by_staff: dict[str, list[dict]] = {cid: [] for cid in CAREGIVERS.keys()}
    for rid, profile in RESIDENTS_MAP.items():
        caregiver_id = _resident_caregiver(rid, profile)
        try:
            rows = _simulated_history_rows(rid, days=days, step_hours=step_hours)
        except Exception:
            continue
        for row in rows:
            level = int(row.get("alert_level") or 0)
            if level <= 0:
                continue
            targets = _staff_notification_preview(caregiver_id, level)
            target_ids = {t.get("id") for t in targets if t.get("id") != "dashboard"}
            for staff_id in target_ids:
                by_staff.setdefault(staff_id, []).append({
                    "time": row.get("time"),
                    "resident_id": rid,
                    "resident_name": profile.get("name", rid),
                    "room": profile.get("room"),
                    "level": level,
                    "level_name": _alert_level_name(level),
                    "event": row.get("event"),
                    "routine": row.get("routine"),
                    "zone": row.get("zone"),
                    "ml_risk": row.get("ml_risk"),
                })
    for events in by_staff.values():
        events.sort(key=lambda item: item.get("time") or "", reverse=True)
    redis_client.setex(cache_key, 60, json.dumps(by_staff, ensure_ascii=False))
    return by_staff


def _notification_key(alert_or_event: dict) -> str:
    if alert_or_event.get("alert_id"):
        return str(alert_or_event["alert_id"])
    if alert_or_event.get("id"):
        return str(alert_or_event["id"])
    parts = [
        alert_or_event.get("resident_id", "resident"),
        str(alert_or_event.get("level", 0)),
        alert_or_event.get("time") or alert_or_event.get("created_at") or "",
        alert_or_event.get("event") or alert_or_event.get("reason") or "",
    ]
    return ":".join(str(p).replace(" ", "_") for p in parts)


def _notification_status(caregiver_id: str, notification_key: str) -> dict:
    raw = redis_client.hget(f"notification:status:{caregiver_id}", notification_key)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _notification_audit_for_staff(caregiver_id: str, limit: int = 20) -> list[dict]:
    rows = []
    for raw in redis_client.lrange(f"notifications:audit:{caregiver_id}", 0, max(0, limit - 1)):
        try:
            rows.append(json.loads(raw))
        except Exception:
            continue
    return rows


def _samu_call_key(alert_id: str) -> str:
    return f"samu:call:{alert_id}"


def _build_samu_call(alert: dict, caregiver_id: str = "systeme", status: str = "preappel_prepare") -> dict:
    resident_id = alert.get("resident_id")
    profile = RESIDENTS_MAP.get(resident_id, {})
    trigger = alert.get("trigger_data") or {}
    vitals = trigger.get("vitals") or {}
    movement = trigger.get("movement") or {}
    news = trigger.get("news") or {}
    staff = _staff_status(caregiver_id) if caregiver_id in CAREGIVERS else {"name": caregiver_id}
    now = datetime.utcnow().isoformat() + "Z"
    return {
        "call_id": f"SAMU-{alert.get('id')}",
        "alert_id": alert.get("id"),
        "resident_id": resident_id,
        "resident_name": alert.get("resident_name") or profile.get("name"),
        "age": profile.get("age"),
        "room": alert.get("room") or profile.get("room"),
        "location": alert.get("location_label") or alert.get("current_zone"),
        "floor": alert.get("floor"),
        "position": alert.get("position"),
        "level": alert.get("level"),
        "reason": alert.get("reason"),
        "status": status,
        "prepared_at": now,
        "prepared_by": caregiver_id,
        "prepared_by_name": staff.get("name", caregiver_id),
        "confirmed_at": None,
        "confirmed_by": None,
        "confirmed_by_name": None,
        "vitals": {
            "heart_rate": vitals.get("heart_rate"),
            "spo2": vitals.get("spo2"),
            "blood_pressure_sys": vitals.get("blood_pressure_sys"),
            "blood_pressure_dia": vitals.get("blood_pressure_dia"),
            "temperature": vitals.get("temperature"),
            "respiratory_rate": vitals.get("respiratory_rate"),
        },
        "movement": {
            "is_fall_detected": movement.get("is_fall_detected"),
            "ambient_fall_confirmed": movement.get("ambient_fall_confirmed"),
            "sos_pressed": movement.get("sos_pressed"),
            "last_movement_ago_s": movement.get("last_movement_ago_s"),
        },
        "clinical_context": {
            "news_score": news.get("score"),
            "news_response": news.get("clinical_response"),
            "ml_risk": trigger.get("ml_risk"),
            "pathologies": profile.get("pathologies", []),
            "mobility": profile.get("mobility"),
            "likely_medications": profile.get("likely_medications", []),
        },
        "message_samu": (
            f"Simulation appel SAMU 15: {alert.get('resident_name') or profile.get('name')}, "
            f"{profile.get('age', '?')} ans, chambre {alert.get('room') or profile.get('room')}, "
            f"{alert.get('location_label') or alert.get('current_zone')}. "
            f"Niveau 5 danger vital. Motif: {alert.get('reason')}. "
            f"Constantes: FC {vitals.get('heart_rate')}, SpO2 {vitals.get('spo2')}%, "
            f"PA {vitals.get('blood_pressure_sys')}/{vitals.get('blood_pressure_dia')}, "
            f"T {vitals.get('temperature')}C, FR {vitals.get('respiratory_rate')}."
        ),
    }


def _ensure_samu_call(alert: dict, caregiver_id: str = "systeme") -> Optional[dict]:
    if not alert or int(alert.get("level") or 0) < 5 or not alert.get("id"):
        return None
    key = _samu_call_key(alert["id"])
    raw = redis_client.get(key)
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    call = _build_samu_call(alert, caregiver_id=caregiver_id, status="preappel_prepare")
    redis_client.setex(key, 86400, json.dumps(call, ensure_ascii=False))
    redis_client.lpush("samu:calls", json.dumps(call, ensure_ascii=False))
    redis_client.ltrim("samu:calls", 0, 199)
    return call


runtime.redis_client = redis_client
runtime.alert_engine = alert_engine
runtime.level_config = LEVEL_CONFIG
runtime.caregivers = CAREGIVERS
runtime.residents_map = RESIDENTS_MAP
runtime.residents_list = RESIDENTS_LIST
runtime.demo_resident = DEMO_RESIDENT
runtime.simulation_scenarios = SIMULATION_SCENARIOS
runtime.patient_data_dir = PATIENT_DATA_DIR
runtime.auth_module = auth_module
runtime.session_secret = SESSION_SECRET
runtime.famille_admin_token = FAMILLE_ADMIN_TOKEN
runtime.allowed_origins = ALLOWED_ORIGINS
runtime.https_required = HTTPS_REQUIRED
runtime.retention_access_log_days = RETENTION_ACCESS_LOG_DAYS
runtime.retention_audit_days = RETENTION_AUDIT_DAYS
runtime.llm_daily_ttl_days = LLM_DAILY_TTL_DAYS
runtime.scalability_metrics = scalability_service.metrics
runtime.influx_query_api = query_api
runtime.influx_bucket = INFLUX_BUCKET
runtime.simulated_history_rows = _simulated_history_rows
runtime.llm_report_service = llm_report_service
runtime.push_service = push_service
runtime.attach_push_delivery = push_service.attach_delivery
runtime.active_alert_for_resident = _active_alert_for_resident
runtime.bearer_token = security_service.bearer_token
runtime.require_staff_session = security_service.require_staff_session
runtime.require_security_admin = security_service.require_security_admin
runtime.require_resident_access = security_service.require_resident_access
runtime.is_privileged_staff = security_service.is_privileged_staff
runtime.notification_key = _notification_key
runtime.staff_status = _staff_status
runtime.staff_snapshot = _staff_snapshot
runtime.local_report_date = _local_report_date
runtime.build_global_daily_report = _build_global_daily_report
runtime.build_resident_daily_report = _build_resident_daily_report
runtime.get_medical_report_document = llm_report_service.get_medical_report_document
runtime.ensure_medical_report_document = llm_report_service.ensure_medical_report_document
runtime.safe_state_for_report = _safe_state_for_report
runtime.resident_week_life = _resident_week_life
runtime.agent_card = agent_card
runtime.history_summary = _history_summary
runtime.a2a_prediction_for_resident = _a2a_prediction_for_resident
runtime.ml_predictor = ml_predictor
runtime.get_routine_summary = get_routine_summary
runtime.publish_mqtt_control = publish_mqtt_control
runtime.profile_payload = patient_files_service.profile_payload
runtime.effective_resident_profile = _effective_resident_profile
runtime.patient_dir = patient_files_service.patient_dir
runtime.patient_history_meta = patient_files_service.patient_history_meta
runtime.write_json_file = patient_files_service.write_json_file
runtime.generate_patient_history = patient_files_service.generate_patient_history
runtime.json_dumps = lambda value: json.dumps(value, ensure_ascii=False)
runtime.ensure_samu_call = _ensure_samu_call
runtime.samu_call_key = _samu_call_key
app.include_router(alerts_router.router)
app.include_router(a2a_ml_router.router)
app.include_router(famille_router.router)
app.include_router(kb_router.router)
app.include_router(live_router.router)
app.include_router(llm_router.router)
app.include_router(push_router.router)
app.include_router(reports_router.router)
app.include_router(simulator_router.router)
app.include_router(staff_router.router)


def _run_on_main_loop(coro, timeout: float = 120):
    if not _loop or _loop.is_closed():
        raise RuntimeError("Boucle FastAPI indisponible")
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=timeout)


scheduler_service = SchedulerService(
    redis_client=redis_client,
    residents_map=RESIDENTS_MAP,
    alert_engine=alert_engine,
    ws_manager=ws_manager,
    push_service=push_service,
    local_report_date=_local_report_date,
    build_global_daily_report=_build_global_daily_report,
    safe_state_for_report=_safe_state_for_report,
    history_summary=_history_summary,
    active_alert_for_resident=_active_alert_for_resident,
    a2a_prediction_for_resident=_a2a_prediction_for_resident,
    remember_prediction=_remember_prediction,
    llm_report_service=llm_report_service,
    loop_getter=lambda: _loop,
    run_on_main_loop=_run_on_main_loop,
)


def daily_llm_report_loop():
    scheduler_service.daily_llm_report_loop()

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
    try:
        auth_module.seed_demo_accounts(redis_client, RESIDENTS_LIST)
        log.info("Comptes famille demo amorces")
    except Exception as e:
        log.warning(f"Seed comptes famille echoue : {e}")
    try:
        auth_module.create_staff_accounts(redis_client, CAREGIVERS, STAFF_DEMO_PASSWORD)
        log.info("Comptes personnel demo amorces")
    except Exception as e:
        log.warning(f"Seed comptes personnel echoue : {e}")

    # Connexion MQTT en thread séparé
    def mqtt_thread():
        client = mqtt.Client(client_id=f"ehpad_backend_{os.getpid()}")
        if MQTT_USERNAME:
            client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
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

    # Injection historique InfluxDB (une seule fois, en arrière-plan)
    def _history_injection_thread():
        try:
            from history_injector import inject_all_history
            inject_all_history(
                write_api=write_api,
                influx_bucket=INFLUX_BUCKET,
                residents_map=RESIDENTS_MAP,
                effective_profile_fn=_effective_resident_profile,
                redis_client=redis_client,
                simulated_rows_fn=daily_reports.simulated_history_rows,
            )
        except Exception as exc:
            log.warning("Injection historique echouee : %s", exc)

    threading.Thread(target=_history_injection_thread, daemon=True).start()

    # Threads de supervision hors boucle temps reel
    threading.Thread(target=scheduler_service.escalation_loop, daemon=True).start()
    threading.Thread(target=scheduler_service.daily_report_loop, daemon=True).start()
    threading.Thread(target=scheduler_service.predictive_analysis_loop, daemon=True).start()
    threading.Thread(target=daily_llm_report_loop, daemon=True).start()

    log.info("Backend EHPAD démarré OK")







