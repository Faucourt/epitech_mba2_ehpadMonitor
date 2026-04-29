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

import redis
import paho.mqtt.client as mqtt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from alert_engine import AlertEngine, LEVEL_CONFIG
from ws_manager import WebSocketManager
from ml_model import MalaisePredictor
from a2a_agents import agent_card
from reports import DailyReportService
from routine_engine import update_and_detect, get_routine_summary

logging.basicConfig(level=logging.INFO, format='%(asctime)s [BACKEND] %(message)s')
log = logging.getLogger(__name__)

# --- Config ---
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
INFLUX_HOST = os.getenv("INFLUX_HOST", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "ehpad-super-secret-token")
INFLUX_ORG = os.getenv("INFLUX_ORG", "ehpad")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "residents")
DEMO_RESIDENT = os.getenv("DEMO_RESIDENT", "R005")
INFLUX_SAMPLE_INTERVAL_S = float(os.getenv("INFLUX_SAMPLE_INTERVAL_S", "5"))
WS_RESIDENT_MIN_INTERVAL_S = float(os.getenv("WS_RESIDENT_MIN_INTERVAL_S", "2"))
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "meditron:7b")
LLM_DAILY_AUTO_ENABLED = os.getenv("LLM_DAILY_AUTO_ENABLED", "true").lower() not in {"0", "false", "no"}
LLM_DAILY_TTL_DAYS = int(os.getenv("LLM_DAILY_TTL_DAYS", "45"))
FAMILLE_ADMIN_TOKEN = os.getenv("FAMILLE_ADMIN_TOKEN", "ADMIN_EHPAD_2024")
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-change-me-session-secret")
STAFF_DEMO_PASSWORD = os.getenv("STAFF_DEMO_PASSWORD", "EHPAD2024!")
ALLOWED_ORIGINS = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "http://localhost:3002,http://127.0.0.1:3002").split(",") if x.strip()]
HTTPS_REQUIRED = os.getenv("HTTPS_REQUIRED", "false").lower() in {"1", "true", "yes"}
RETENTION_ACCESS_LOG_DAYS = int(os.getenv("RETENTION_ACCESS_LOG_DAYS", "365"))
RETENTION_AUDIT_DAYS = int(os.getenv("RETENTION_AUDIT_DAYS", "365"))
PATIENT_DATA_DIR = Path(os.getenv("PATIENT_DATA_DIR", "/app/data/patients"))

# --- Web Push VAPID ---
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_CLAIMS_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "admin@ehpad.local")
WEBPUSH_ENABLED = bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)

SIMULATION_SCENARIOS = [
    "hypoxie", "tachycardie", "chute", "hypotension", "fievre",
    "chute_couloir", "chute_chambre", "malaise_salle_manger", "errance_nuit",
    "sortie_patio", "immobilite_salle_repos", "aller_toilettes_nuit",
    "desorientation_ascenseur", "agitation_couloir", "isolement_chambre",
    "retour_kine_fatigue", "promenade_jardin", "sortie_jardin_non_accompagnee",
    "chute_jardin", "fugue_hors_ehpad", "chute_trajet_repas",
    "desorientation_avant_repas", "malaise_retour_repas", "malaise_repas",
    "chute_salle_bain", "toilette_matinale_fatigue", "desorientation_patio",
    "regroupement_patio_fatigue", "retour_jardin_fatigue",
    "risque_nuit", "jardin",
]

# --- Profils résidents (importé depuis le simulateur, ou hardcodé)
from resident_profiles import RESIDENTS_MAP, RESIDENTS_LIST, FAMILY_CODE_MAP, CAREGIVERS
import auth as auth_module

# --- Init ---
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="EHPAD API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "X-Break-Glass-Reason"])


@app.middleware("http")
async def force_utf8_charset(request, call_next):
    if HTTPS_REQUIRED and request.url.scheme != "https" and request.client and request.client.host not in {"127.0.0.1", "localhost"}:
        raise HTTPException(426, "HTTPS requis")
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("application/json") and "charset" not in content_type:
        response.headers["content-type"] = "application/json; charset=utf-8"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD or None, decode_responses=True)
ws_manager = WebSocketManager()
alert_engine = AlertEngine(redis_client, ws_manager)
ml_predictor = MalaisePredictor()

# --- Web Push helpers ---
def _push_subscriptions_key(staff_id: str) -> str:
    return f"push:sub:{staff_id}"

def _push_subscriptions_for_staff(staff_id: str) -> list[dict]:
    raw = redis_client.get(_push_subscriptions_key(staff_id))
    if not raw:
        return []
    try:
        stored = json.loads(raw)
        subs = stored if isinstance(stored, list) else [stored]
        return [{**sub, "staff_id": staff_id} for sub in subs if isinstance(sub, dict)]
    except Exception:
        return []


def _all_push_subscriptions() -> list[dict]:
    """Récupère toutes les souscriptions push actives (tous les soignants)."""
    subs = []
    for key in redis_client.scan_iter("push:sub:*"):
        staff_id = key.split("push:sub:", 1)[-1]
        raw = redis_client.get(key)
        if raw:
            try:
                sub = json.loads(raw)
                if isinstance(sub, list):
                    subs.extend([{**s, "staff_id": staff_id} for s in sub if isinstance(s, dict)])
                else:
                    subs.append({**sub, "staff_id": staff_id})
            except Exception:
                pass
    return subs

def _send_web_push_sync(payload: dict, staff_ids: Optional[list[str]] = None) -> dict:
    """Envoie un push cible par personnel (synchrone, à appeler dans thread)."""
    target_ids = list(dict.fromkeys(staff_ids or []))
    result = {
        "enabled": WEBPUSH_ENABLED,
        "target_staff": target_ids,
        "expected_staff": len(target_ids),
        "subscriptions": 0,
        "sent": 0,
        "expired": 0,
        "errors": [],
        "staff": [],
    }
    if not WEBPUSH_ENABLED:
        return result
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        log.warning("pywebpush non installé, push désactivé")
        result["errors"].append("pywebpush non installe")
        return result

    import tempfile, base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    # Convertir la clé privée base64url -> PEM si nécessaire
    raw_key = VAPID_PRIVATE_KEY.replace("\\n", "\n").strip()
    if "BEGIN" not in raw_key:
        padding = "=" * ((4 - len(raw_key) % 4) % 4)
        key_bytes = base64.urlsafe_b64decode(raw_key + padding)
        private_value = int.from_bytes(key_bytes, "big")
        private_key_obj = ec.derive_private_key(private_value, ec.SECP256R1())
        pem = private_key_obj.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")
    else:
        pem = raw_key

    tmp = tempfile.NamedTemporaryFile(prefix="ehpad-vapid-", suffix=".pem", delete=False)
    tmp.write(pem.encode("utf-8"))
    tmp.flush()
    tmp.close()
    key_path = tmp.name

    try:
        subs = []
        if target_ids:
            for staff_id in target_ids:
                staff_subs = _push_subscriptions_for_staff(staff_id)
                result["staff"].append({
                    "staff_id": staff_id,
                    "status": "pending" if staff_subs else "not_subscribed",
                    "subscriptions": len(staff_subs),
                    "sent": 0,
                    "expired": 0,
                    "errors": [],
                })
                subs.extend(staff_subs)
        else:
            subs = _all_push_subscriptions()
            grouped = {}
            for sub in subs:
                grouped.setdefault(sub.get("staff_id", "unknown"), 0)
                grouped[sub.get("staff_id", "unknown")] += 1
            result["staff"] = [
                {"staff_id": staff_id, "status": "pending", "subscriptions": count, "sent": 0, "expired": 0, "errors": []}
                for staff_id, count in grouped.items()
            ]
        result["subscriptions"] = len(subs)

        staff_result = {row["staff_id"]: row for row in result["staff"]}
        for sub in subs:
            staff_id = sub.get("staff_id", "unknown")
            row = staff_result.get(staff_id)
            try:
                webpush(
                    subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                    data=json.dumps(payload, ensure_ascii=False),
                    vapid_private_key=key_path,
                    vapid_claims={"sub": f"mailto:{VAPID_CLAIMS_EMAIL}"},
                    ttl=120,
                )
                result["sent"] += 1
                if row:
                    row["sent"] += 1
                    row["status"] = "sent"
            except WebPushException as exc:
                code = getattr(getattr(exc, "response", None), "status_code", None)
                if code in {404, 410}:
                    result["expired"] += 1
                    if row:
                        row["expired"] += 1
                        row["status"] = "expired"
                    key = _push_subscriptions_key(staff_id)
                    raw = redis_client.get(key)
                    if raw:
                        try:
                            stored = json.loads(raw)
                            stored = [s for s in (stored if isinstance(stored, list) else [stored]) if s.get("endpoint") != sub["endpoint"]]
                            redis_client.set(key, json.dumps(stored))
                        except Exception:
                            pass
                else:
                    result["errors"].append(f"webpush {code or 'error'}")
                    if row:
                        row["errors"].append(f"webpush {code or 'error'}")
                        row["status"] = "error"
            except Exception:
                log.exception("Erreur envoi Web Push")
                result["errors"].append("erreur envoi webpush")
                if row:
                    row["errors"].append("erreur envoi webpush")
                    row["status"] = "error"
    finally:
        try:
            os.unlink(key_path)
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.warning(f"Impossible de supprimer le fichier VAPID temporaire {key_path}: {exc}")
    return result

async def _send_web_push_async(payload: dict, staff_ids: Optional[list[str]] = None) -> dict:
    return await asyncio.to_thread(_send_web_push_sync, payload, staff_ids)

def _push_payload_for_alert(alert: dict) -> dict:
    level = int(alert.get("level") or 0)
    labels = {2: "Attention", 3: "Alerte", 4: "URGENCE", 5: "DANGER VITAL"}
    return {
        "title": f"N{level} {labels.get(level, 'Alerte')} - {alert.get('resident_name') or alert.get('resident_id')}",
        "body": f"Ch.{alert.get('room', '?')} - {alert.get('reason', 'Alerte active')}",
        "level": level,
        "resident_id": alert.get("resident_id", ""),
        "alert_id": alert.get("id", ""),
    }

def _push_target_staff_ids(alert: dict) -> list[str]:
    """Retourne les destinataires smartphone reels selon les regles projet."""
    level = int(alert.get("level") or 0)
    if level < 2:
        return []
    ignored = {"dashboard", "samu_15", "son", "son_fort"}
    ids = []
    for item in alert.get("notified_staff") or []:
        if not isinstance(item, dict):
            continue
        staff_id = item.get("id")
        if staff_id and staff_id not in ignored and staff_id in CAREGIVERS and staff_id not in ids:
            ids.append(staff_id)
    if level in {2, 3}:
        caregiver = alert.get("caregiver")
        return [caregiver] if caregiver in CAREGIVERS else ids
    if level == 4:
        return [staff_id for staff_id in ("soignant_A", "soignant_B", "soignant_C", "chef_garde") if staff_id in CAREGIVERS]
    return [staff_id for staff_id in ("soignant_A", "soignant_B", "soignant_C", "chef_garde", "direction") if staff_id in CAREGIVERS]


def _push_delivery_key(alert_id: str) -> str:
    return f"push:delivery:{alert_id}"


def _record_push_delivery(alert: dict, result: dict, replay: bool = False) -> dict:
    alert_id = alert.get("id") or alert.get("alert_id")
    if not alert_id:
        return result
    delivered_staff = sum(1 for row in result.get("staff", []) if int(row.get("sent") or 0) > 0)
    summary = {
        "alert_id": alert_id,
        "resident_id": alert.get("resident_id"),
        "resident_name": alert.get("resident_name"),
        "level": int(alert.get("level") or 0),
        "target_staff": result.get("target_staff", []),
        "expected_staff": result.get("expected_staff", 0),
        "delivered_staff": delivered_staff,
        "subscriptions": result.get("subscriptions", 0),
        "sent": result.get("sent", 0),
        "expired": result.get("expired", 0),
        "errors": result.get("errors", []),
        "staff": result.get("staff", []),
        "replay": replay,
        "at": datetime.utcnow().isoformat() + "Z",
    }
    redis_client.setex(_push_delivery_key(alert_id), RETENTION_AUDIT_DAYS * 86400, json.dumps(summary, ensure_ascii=False))
    redis_client.lpush("push:audit", json.dumps(summary, ensure_ascii=False))
    redis_client.ltrim("push:audit", 0, 999)
    redis_client.expire("push:audit", RETENTION_AUDIT_DAYS * 86400)
    return summary


def _push_delivery_summary(alert_id: str) -> Optional[dict]:
    raw = redis_client.get(_push_delivery_key(alert_id))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _attach_push_delivery(alert: dict) -> dict:
    if not alert or not alert.get("id"):
        return alert
    delivery = _push_delivery_summary(alert["id"])
    if delivery:
        alert = dict(alert)
        alert["push_delivery"] = delivery
    return alert


def _dispatch_alert_push_sync(alert: dict, replay: bool = False, forced_staff_ids: Optional[list[str]] = None) -> dict:
    level = int(alert.get("level") or 0)
    if level < 2:
        return {"enabled": WEBPUSH_ENABLED, "target_staff": [], "expected_staff": 0, "subscriptions": 0, "sent": 0, "expired": 0, "errors": [], "staff": []}
    staff_ids = forced_staff_ids or _push_target_staff_ids(alert)
    result = _send_web_push_sync(_push_payload_for_alert(alert), staff_ids=staff_ids)
    return _record_push_delivery(alert, result, replay=replay)


async def _dispatch_alert_push_async(alert: dict, replay: bool = False, forced_staff_ids: Optional[list[str]] = None) -> dict:
    return await asyncio.to_thread(_dispatch_alert_push_sync, alert, replay, forced_staff_ids)


def _replay_active_push_alerts_for_staff(staff_id: str) -> int:
    """Renvoie les alertes actives quand un téléphone vient de s'inscrire."""
    sent = 0
    for alert in list(alert_engine.active_alerts.values()):
        data = alert.to_dict() if hasattr(alert, "to_dict") else dict(alert)
        if int(data.get("level") or 0) < 2:
            continue
        if staff_id not in _push_target_staff_ids(data):
            continue
        result = _dispatch_alert_push_sync(data, replay=True, forced_staff_ids=[staff_id])
        if result.get("sent", 0) > 0:
            sent += 1
    return sent

# InfluxDB
influx = InfluxDBClient(url=INFLUX_HOST, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = influx.write_api(write_options=SYNCHRONOUS)

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

RESIDENT_ARCHETYPES = {
    "autonome": {
        "label": "Autonome",
        "daily_focus": "vie sociale, activites, repas en salle",
        "main_risks": ["chute trajet", "malaise effort", "retard alerte si isolement"],
        "supervision": "surveillance standard",
    },
    "accompagne": {
        "label": "Deplacement accompagne",
        "daily_focus": "repas encadre, kine, trajets surveilles",
        "main_risks": ["chute couloir", "fatigue post-kine", "hypotension post-repas"],
        "supervision": "surveillance renforcee aux transferts",
    },
    "chambre": {
        "label": "Reste principalement en chambre",
        "daily_focus": "soins au lit, repas en chambre, prevention escarres",
        "main_risks": ["inactivite", "sortie de lit", "chute chambre"],
        "supervision": "passages soignants programmes",
    },
    "cognitif": {
        "label": "Troubles cognitifs / fugue",
        "daily_focus": "repas et activites securises, controle sorties",
        "main_risks": ["errance", "fugue", "desorientation escalier/ascenseur"],
        "supervision": "surveillance sorties et zones sensibles",
    },
    "respiratoire": {
        "label": "Fragilite respiratoire",
        "daily_focus": "tolerance effort, SpO2 personnalisee, repos",
        "main_risks": ["desaturation", "fatigue retour repas", "dyspnee nocturne"],
        "supervision": "seuils SpO2 adaptes au profil",
    },
    "cardio": {
        "label": "Fragilite cardio-metabolique",
        "daily_focus": "surveillance tension, FC, malaise postural",
        "main_risks": ["tachycardie", "hypotension", "malaise post-repas"],
        "supervision": "controle cardio rapproche si tendance monte",
    },
}


def _resident_archetype(profile: dict) -> str:
    pathologies = set(profile.get("pathologies", []))
    mobility = profile.get("mobility", "moyenne")
    risk = float(profile.get("risk_factor", 0.3))
    if pathologies.intersection({"alzheimer", "demence", "dementia"}):
        return "cognitif"
    if "bpco" in pathologies:
        return "respiratoire"
    if pathologies.intersection({"insuffisance_cardiaque", "hypertension"}) and risk >= 0.45:
        return "cardio"
    if mobility == "tres_faible" and risk >= 0.6:
        return "chambre"
    if mobility in {"faible", "tres_faible"}:
        return "accompagne"
    return "autonome"


PROJECT_READINESS = [
    {
        "axis": "20-50 residents",
        "status": "done",
        "proof": "25 residents actifs, extensible par NUM_RESIDENTS et profils",
        "improve": "tester une charge 50 residents avec seuils WebSocket/Influx adaptes",
    },
    {
        "axis": "Duree continue mois/annees",
        "status": "partial",
        "proof": "simulation continue Docker + historique simule 30 jours + InfluxDB",
        "improve": "ajouter politique retention InfluxDB et sauvegarde Redis planifiee",
    },
    {
        "axis": "IA prediction malaise",
        "status": "done",
        "proof": "ML/A2A relance toutes les 5 min, risque 30 et 60 min, memoire de tendance",
        "improve": "calibrer sur donnees reelles et mesurer recall/specifite par profil",
    },
    {
        "axis": "Alertes 5 niveaux",
        "status": "done",
        "proof": "moteur niveaux 1-5, anti-bruit, localisation, escalade et acquittement",
        "improve": "journaliser le delai d'intervention et les faux positifs par type d'alerte",
    },
    {
        "axis": "Capteurs vitaux + ambiants",
        "status": "done",
        "proof": "wearable, SpO2, FC, PA, temperature, respiration, PIR, radar, porte, sol, matelas, BLE/GPS",
        "improve": "suivre la qualite signal/batterie et les capteurs muets dans le temps",
    },
    {
        "axis": "Vue par resident",
        "status": "done",
        "proof": "detail live, mini DPI, historique 30 jours, prediction, transmission",
        "improve": "ajouter validation soignant et export PDF",
    },
    {
        "axis": "Complexite scale + prediction",
        "status": "partial",
        "proof": "MQTT QoS, Redis et WebSocket throttling, Influx echantillonne, LLM pas appele a chaque seconde",
        "improve": "benchmark 120 msg/s puis 300 msg/s avec p95 latence dashboard",
    },
]

STAFF_DEFAULTS = {
    "soignant_A": {"sector": "RDC + aile A", "shift": "jour", "status": "disponible"},
    "soignant_B": {"sector": "RDC + aile B", "shift": "jour", "status": "disponible"},
    "soignant_C": {"sector": "1er etage", "shift": "jour", "status": "disponible"},
    "chef_garde": {"sector": "tous secteurs", "shift": "astreinte", "status": "disponible"},
    "direction": {"sector": "administration", "shift": "astreinte", "status": "disponible"},
}


def _staff_status(caregiver_id: str) -> dict:
    base = {
        "id": caregiver_id,
        **CAREGIVERS.get(caregiver_id, {"name": caregiver_id, "role": "soignant", "phone": ""}),
        **STAFF_DEFAULTS.get(caregiver_id, {"sector": "non defini", "shift": "jour", "status": "disponible"}),
    }
    raw = redis_client.get(f"staff:{caregiver_id}:status")
    if raw:
        try:
            base.update(json.loads(raw))
        except Exception:
            pass
    return base


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def _require_staff_session(authorization: Optional[str] = None) -> dict:
    session = auth_module.validate_staff_token(redis_client, _bearer_token(authorization), SESSION_SECRET)
    if not session:
        raise HTTPException(401, "Session personnel expiree ou invalide")
    if session.get("sub") not in CAREGIVERS:
        raise HTTPException(403, "Personnel inconnu")
    return session


def _is_privileged_staff(staff_id: str, role: Optional[str] = None) -> bool:
    return staff_id in {"chef_garde", "direction"} or role in {"medecin", "direction", "admin"}


def _can_staff_access_resident(staff_id: str, resident_id: str, role: Optional[str] = None) -> bool:
    if _is_privileged_staff(staff_id, role):
        return True
    return _resident_caregiver(resident_id, RESIDENTS_MAP.get(resident_id, {})) == staff_id


def _log_access(user_id: str, role: str, resident_id: str, action: str, outcome: str, request: Optional[Request] = None, reason: Optional[str] = None):
    row = {
        "at": datetime.utcnow().isoformat() + "Z",
        "user_id": user_id,
        "role": role,
        "resident_id": resident_id,
        "resident_name": RESIDENTS_MAP.get(resident_id, {}).get("name", resident_id),
        "action": action,
        "outcome": outcome,
        "reason": reason,
        "ip": request.client.host if request and request.client else None,
        "path": str(request.url.path) if request else None,
    }
    redis_client.lpush("security:access_log", json.dumps(row, ensure_ascii=False))
    redis_client.ltrim("security:access_log", 0, 4999)
    redis_client.expire("security:access_log", RETENTION_ACCESS_LOG_DAYS * 86400)
    if outcome == "break_glass":
        redis_client.lpush("security:break_glass", json.dumps(row, ensure_ascii=False))
        redis_client.ltrim("security:break_glass", 0, 999)
        redis_client.expire("security:break_glass", RETENTION_ACCESS_LOG_DAYS * 86400)
    return row


def _require_resident_access(
    resident_id: str,
    authorization: Optional[str],
    request: Optional[Request],
    action: str,
    break_glass_reason: Optional[str] = None,
) -> dict:
    session = _require_staff_session(authorization)
    staff_id = session["sub"]
    role = session.get("role", "soignant")
    if _can_staff_access_resident(staff_id, resident_id, role):
        _log_access(staff_id, role, resident_id, action, "allowed", request)
        return session
    active = _active_alert_for_resident(resident_id)
    if break_glass_reason and len(break_glass_reason.strip()) >= 8 and active and int(active.get("level") or 0) >= 3:
        _log_access(staff_id, role, resident_id, action, "break_glass", request, break_glass_reason.strip())
        return session
    _log_access(staff_id, role, resident_id, action, "denied", request, break_glass_reason)
    raise HTTPException(403, "Acces refuse: resident non assigne. Bris de glace requis si urgence.")


def _require_security_admin(authorization: Optional[str] = None) -> dict:
    session = _require_staff_session(authorization)
    if not _is_privileged_staff(session["sub"], session.get("role")):
        raise HTTPException(403, "Acces reserve chef de garde / direction")
    return session


def _resident_caregiver(resident_id: str, profile: Optional[dict] = None) -> str:
    override = redis_client.get(f"resident:{resident_id}:caregiver")
    return override or (profile or RESIDENTS_MAP.get(resident_id, {})).get("caregiver", "")


def _resident_config(resident_id: str) -> dict:
    file_profile = _resident_file_profile(resident_id)
    if file_profile:
        return file_profile
    raw = redis_client.get(f"sim:profile:{resident_id}")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _effective_resident_profile(resident_id: str) -> dict:
    base = dict(RESIDENTS_MAP.get(resident_id, {}))
    cfg = _resident_config(resident_id)
    for key in [
        "age", "pathologies", "mobility", "risk_factor", "caregiver",
        "meal_mode", "care_level", "assigned_scenarios", "notes",
    ]:
        if key in cfg:
            base[key] = cfg[key]
    return base


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
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.publish(topic, json.dumps(payload), qos=1, retain=True)
    client.disconnect()


daily_reports = DailyReportService(
    redis_client=redis_client,
    alert_engine=alert_engine,
    residents_map=RESIDENTS_MAP,
    archetypes=RESIDENT_ARCHETYPES,
    effective_resident_profile=_effective_resident_profile,
    resident_caregiver=_resident_caregiver,
    resident_archetype=_resident_archetype,
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

def daily_report_loop():
    global _last_daily_report_date
    while True:
        try:
            today = _local_report_date()
            existing = redis_client.get(f"daily_report:v8:{today}:global")
            if today != _last_daily_report_date and not existing:
                _build_global_daily_report(today, force=False)
                _last_daily_report_date = today
                log.info(f"Rapport quotidien automatise genere pour {today}")
        except Exception as e:
            log.error(f"Rapport quotidien error: {e}")
        time.sleep(300)


def predictive_analysis_loop():
    """Relance l'analyse ML/A2A toutes les 5 minutes pour ne pas rater un risque montant."""
    while True:
        try:
            predictions = []
            for resident_id in RESIDENTS_MAP.keys():
                state = _safe_state_for_report(resident_id)
                hist = _history_summary(resident_id)
                active_alert = _active_alert_for_resident(resident_id)
                result = _a2a_prediction_for_resident(state, hist, active_alert=active_alert)
                _remember_prediction(resident_id, result)
                result = _a2a_prediction_for_resident(state, hist, active_alert=active_alert)
                redis_client.setex(f"a2a:prediction:{resident_id}", 600, json.dumps(result))
                pred = result["prediction"]
                predictions.append({
                    "resident_id": resident_id,
                    "resident_name": state.get("resident_name") or state.get("name"),
                    "room": state.get("room"),
                    "location": state.get("current_zone") or state.get("zone"),
                    **pred,
                })
            predictions.sort(key=lambda p: (p["recommended_level"], p["risk_60min"], p["risk_30min"]), reverse=True)
            payload = {
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "refresh_interval_s": 300,
                "count": len(predictions),
                "predictions": predictions,
            }
            redis_client.setex("a2a:predictions:all", 600, json.dumps(payload))
            log.info("Analyse predictive ML/A2A 30-60 min relancee pour tous les residents")
        except Exception as e:
            log.error(f"Analyse predictive loop error: {e}")
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
                "alert": alert.to_dict() if alert else None,
            }),
            _loop
        )
        if alert:
            a = alert.to_dict()
            if a.get("level", 0) >= 2 and WEBPUSH_ENABLED:
                asyncio.run_coroutine_threadsafe(
                    _dispatch_alert_push_async(a),
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


# ============================================================
# Escalade périodique
# ============================================================

def escalation_loop():
    while True:
        try:
            escalated = alert_engine.check_escalations()
            for alert_dict in escalated:
                if _loop and not _loop.is_closed():
                    if int(alert_dict.get("level") or 0) >= 2 and WEBPUSH_ENABLED:
                        asyncio.run_coroutine_threadsafe(
                            _dispatch_alert_push_async(alert_dict),
                            _loop,
                        )
                    asyncio.run_coroutine_threadsafe(
                        ws_manager.send_alert(alert_dict),
                        _loop,
                    )
        except Exception as e:
            log.error(f"Escalade error: {e}")
        time.sleep(15)


# ============================================================
# REST API
# ============================================================

# --- Web Push endpoints ---

class PushSubscribeRequest(BaseModel):
    staff_id: str = "soignant"
    endpoint: str
    p256dh: str
    auth: str

class PushTestRequest(BaseModel):
    staff_id: str = "soignant_A"
    resident_id: str = DEMO_RESIDENT
    level: int = 3
    title: Optional[str] = None
    body: Optional[str] = None

@app.get("/api/push/config")
def push_config():
    """Retourne la clé publique VAPID et si le push est activé."""
    return {"enabled": WEBPUSH_ENABLED, "public_key": VAPID_PUBLIC_KEY}

@app.get("/api/push/status")
def push_status(authorization: str = Header(None)):
    session = _require_staff_session(authorization)
    staff_id = session["sub"]
    raw = redis_client.get(_push_subscriptions_key(staff_id))
    subs = json.loads(raw) if raw else []
    return {"enabled": WEBPUSH_ENABLED, "staff_id": staff_id, "subscriptions": len(subs)}

@app.post("/api/push/subscribe")
def push_subscribe(body: PushSubscribeRequest, authorization: str = Header(None)):
    """Enregistre une souscription push pour un soignant."""
    session = _require_staff_session(authorization)
    if session["sub"] != body.staff_id and not _is_privileged_staff(session["sub"], session.get("role")):
        raise HTTPException(403, "Souscription refusee pour un autre personnel")
    key = _push_subscriptions_key(body.staff_id)
    raw = redis_client.get(key)
    subs: list[dict] = json.loads(raw) if raw else []
    # Évite les doublons d'endpoint
    subs = [s for s in subs if s.get("endpoint") != body.endpoint]
    subs.append({"endpoint": body.endpoint, "p256dh": body.p256dh, "auth": body.auth})
    redis_client.set(key, json.dumps(subs))
    redis_client.expire(key, 86400 * 30)  # expire après 30 jours
    replayed = _replay_active_push_alerts_for_staff(body.staff_id)
    log.info(f"Push subscribe: staff={body.staff_id} endpoint={body.endpoint[:40]} - replayed={replayed}")
    return {"status": "subscribed", "staff_id": body.staff_id, "subscriptions": len(subs), "replayed_active_alerts": replayed}

@app.delete("/api/push/subscribe")
def push_unsubscribe(endpoint: str, staff_id: str = "soignant"):
    """Supprime une souscription push."""
    key = _push_subscriptions_key(staff_id)
    raw = redis_client.get(key)
    if raw:
        subs = [s for s in json.loads(raw) if s.get("endpoint") != endpoint]
        redis_client.set(key, json.dumps(subs))
    return {"status": "unsubscribed"}

@app.post("/api/push/test")
async def push_test(body: PushTestRequest, authorization: str = Header(None)):
    """Envoie une notification de test au navigateur inscrit pour valider smartphone/PWA."""
    session = _require_staff_session(authorization)
    target_staff = body.staff_id
    if session["sub"] != target_staff and not _is_privileged_staff(session["sub"], session.get("role")):
        raise HTTPException(403, "Test push refuse pour un autre personnel")
    payload = {
        "title": body.title or f"Test push EHPAD - N{body.level}",
        "body": body.body or f"Notification test pour {body.resident_id}",
        "level": max(1, min(5, int(body.level or 3))),
        "resident_id": body.resident_id,
        "alert_id": f"test-{int(time.time())}",
    }
    result = await _send_web_push_async(payload, staff_ids=[target_staff])
    return {"ok": True, "payload": payload, "result": result}


@app.post("/api/push/test-all")
async def push_test_all(body: PushTestRequest, authorization: str = Header(None)):
    """Test admin: simule la diffusion large niveau 4/5 sur les telephones inscrits."""
    session = _require_staff_session(authorization)
    if not _is_privileged_staff(session["sub"], session.get("role")):
        raise HTTPException(403, "Test global reserve chef de garde/direction")
    level = max(4, min(5, int(body.level or 4)))
    staff_ids = ["soignant_A", "soignant_B", "soignant_C", "chef_garde"]
    if level >= 5:
        staff_ids.append("direction")
    payload = {
        "title": body.title or f"Test diffusion EHPAD - N{level}",
        "body": body.body or "Test de routage push collectif",
        "level": level,
        "resident_id": body.resident_id,
        "alert_id": f"test-all-{int(time.time())}",
    }
    result = await _send_web_push_async(payload, staff_ids=staff_ids)
    return {"ok": True, "payload": payload, "result": result}


@app.get("/")
def root():
    return {"service": "EHPAD Backend", "status": "ok"}


@app.get("/health")
def health():
    """Healthcheck pour Docker - vérifie Redis + compte les résidents actifs."""
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
            r["active_alert"] = _active_alert_for_resident(rid)
            residents.append(r)
        except Exception:
            pass
    return {"residents": residents, "count": len(residents)}


@app.get("/api/residents/{resident_id}")
def get_resident(resident_id: str, request: Request, authorization: str = Header(None), x_break_glass_reason: str = Header(None)):
    _require_resident_access(resident_id, authorization, request, "resident_live_view", x_break_glass_reason)
    raw = redis_client.get(f"resident:{resident_id}:state")
    if not raw:
        raise HTTPException(404, "Résident non trouvé")
    state = json.loads(raw)
    # Historique comportemental
    profile = _effective_resident_profile(resident_id)
    state["profile"] = profile
    state["avatar"] = state.get("avatar") or profile.get("avatar", "")
    return state


@app.get("/api/residents/{resident_id}/history")
def get_resident_history(resident_id: str, request: Request, minutes: int = 60, authorization: str = Header(None), x_break_glass_reason: str = Header(None)):
    _require_resident_access(resident_id, authorization, request, "resident_history_view", x_break_glass_reason)
    minutes = max(1, min(int(minutes or 30), 24 * 60))
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
        rows.sort(key=lambda r: r["time"])
        if not rows:
            rows = _fallback_recent_history(resident_id, minutes)
        return {"resident_id": resident_id, "minutes": minutes, "history": rows}
    except Exception as e:
        return {"resident_id": resident_id, "minutes": minutes, "history": _fallback_recent_history(resident_id, minutes), "error": str(e)}


def _fallback_recent_history(resident_id: str, minutes: int = 30) -> list[dict]:
    raw = redis_client.get(f"resident:{resident_id}:state")
    if not raw:
        return []
    state = json.loads(raw)
    vitals = state.get("vitals", {})
    risk = float(state.get("ml_risk", 0) or 0)
    now = datetime.now(timezone.utc)
    count = max(2, min(180, int(minutes)))
    seed = sum(ord(c) for c in resident_id)
    rows: list[dict] = []
    for i in range(count):
        age = count - 1 - i
        ts = now - timedelta(minutes=age)
        wave = np.sin((i + seed) / 4.0)
        slow = np.sin((i + seed) / 11.0)
        rows.append({
            "time": ts.isoformat(),
            "heart_rate": round(float(vitals.get("heart_rate", 72) or 72) + wave * 2.5 + slow, 1),
            "spo2": round(float(vitals.get("spo2", 96) or 96) + slow * 0.5, 1),
            "blood_pressure_sys": round(float(vitals.get("blood_pressure_sys", 130) or 130) + slow * 4, 1),
            "blood_pressure_dia": round(float(vitals.get("blood_pressure_dia", 75) or 75) + wave * 2, 1),
            "temperature": round(float(vitals.get("temperature", 36.8) or 36.8) + slow * 0.08, 2),
            "respiratory_rate": round(float(vitals.get("respiratory_rate", 16) or 16) + wave * 0.6, 1),
            "ml_risk": round(max(0, min(1, risk + slow * 0.03)), 2),
            "source": "fallback_recent_redis",
        })
    return rows


@app.get("/api/residents/{resident_id}/history/simulated")
def get_resident_simulated_history(resident_id: str, request: Request, days: int = 30, step_hours: int = 6, authorization: str = Header(None), x_break_glass_reason: str = Header(None)):
    _require_resident_access(resident_id, authorization, request, "resident_history_simulated_view", x_break_glass_reason)
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


@app.post("/api/simulator/scenario")
def trigger_simulator_scenario(resident_id: str = DEMO_RESIDENT, scenario: str = "hypoxie"):
    if resident_id not in RESIDENTS_MAP:
        raise HTTPException(404, "Resident non trouve")
    allowed = set(SIMULATION_SCENARIOS)
    if scenario not in allowed:
        raise HTTPException(400, f"Scenario inconnu: {scenario}")
    payload = {"resident_id": resident_id, "scenario": scenario, "updated_at": datetime.utcnow().isoformat() + "Z"}
    publish_mqtt_control("ehpad/control/scenario", payload)
    return {"ok": True, **payload}


class SimulatorProfileUpdate(BaseModel):
    age: Optional[int] = None
    pathologies: Optional[list[str]] = None
    mobility: Optional[str] = None
    risk_factor: Optional[float] = None
    caregiver: Optional[str] = None
    meal_mode: Optional[str] = None
    care_level: Optional[str] = None
    assigned_scenarios: Optional[list[str]] = None
    notes: Optional[str] = None


class HistoryGenerateRequest(BaseModel):
    resident_id: Optional[str] = None
    months: int = 12
    detailed_days: int = 30
    step_hours: int = 6
    overwrite: bool = True


def _profile_payload(resident_id: str) -> dict:
    base = dict(RESIDENTS_MAP.get(resident_id, {}))
    cfg = _resident_config(resident_id)
    effective = _effective_resident_profile(resident_id)
    return {
        "resident_id": resident_id,
        "base": base,
        "config": cfg,
        "effective": effective,
        "history": _patient_history_meta(resident_id),
    }


def _patient_dir(resident_id: str) -> Path:
    return PATIENT_DATA_DIR / resident_id


def _write_json_file(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _patient_file_paths(resident_id: str) -> dict:
    base = _patient_dir(resident_id)
    return {
        "folder": str(base),
        "profile": str(base / "profile.json"),
        "history_daily": str(base / "history_daily.json"),
        "history_detailed": str(base / "history_detailed.json"),
        "history_meta": str(base / "history_meta.json"),
    }


def _resident_file_profile(resident_id: str) -> dict:
    path = _patient_dir(resident_id) / "profile.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    # Ancien format export: {"base":..., "config":..., "effective":...}
    if isinstance(payload, dict) and isinstance(payload.get("effective"), dict):
        return payload["effective"]
    return payload if isinstance(payload, dict) else {}


def _export_patient_profile_files(resident_id: str) -> None:
    profile = _effective_resident_profile(resident_id)
    _write_json_file(_patient_dir(resident_id) / "profile.json", profile)


def _patient_history_meta(resident_id: str) -> dict:
    raw = redis_client.get(f"patient:{resident_id}:history:meta")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return {"status": "missing", "daily_days": 0, "detailed_days": 0}


def _daily_summary_from_rows(rows: list[dict]) -> list[dict]:
    by_day: dict[str, list[dict]] = {}
    for row in rows:
        day = str(row.get("time", ""))[:10]
        if day:
            by_day.setdefault(day, []).append(row)
    summaries = []
    for day, items in sorted(by_day.items()):
        alerts = [x for x in items if int(x.get("alert_level") or 0) > 0]
        zones = {}
        for x in items:
            z = x.get("zone") or "inconnue"
            zones[z] = zones.get(z, 0) + 1
        def avg(field: str):
            vals = [float(x[field]) for x in items if x.get(field) is not None]
            return round(sum(vals) / len(vals), 2) if vals else None
        summaries.append({
            "date": day,
            "samples": len(items),
            "avg_hr": avg("heart_rate"),
            "avg_spo2": avg("spo2"),
            "avg_bp_sys": avg("blood_pressure"),
            "avg_ml_risk": avg("ml_risk"),
            "max_alert_level": max([int(x.get("alert_level") or 0) for x in items] or [0]),
            "alert_count": len(alerts),
            "events": list(dict.fromkeys([x.get("event") for x in alerts if x.get("event")]))[:6],
            "dominant_zone": max(zones, key=zones.get) if zones else None,
            "zones": zones,
        })
    return summaries


def _generate_patient_history(resident_id: str, months: int, detailed_days: int, step_hours: int, overwrite: bool) -> dict:
    months = max(1, min(int(months or 12), 36))
    detailed_days = max(7, min(int(detailed_days or 30), 120))
    step_hours = max(1, min(int(step_hours or 6), 24))
    total_days = months * 30
    if not overwrite and redis_client.exists(f"patient:{resident_id}:history:meta"):
        return _patient_history_meta(resident_id)
    daily_rows = _simulated_history_rows(resident_id, days=total_days, step_hours=24)
    detailed_rows = _simulated_history_rows(resident_id, days=detailed_days, step_hours=step_hours)
    daily_summary = _daily_summary_from_rows(daily_rows)
    redis_client.set(f"patient:{resident_id}:history:daily", json.dumps(daily_summary, ensure_ascii=False))
    redis_client.set(f"patient:{resident_id}:history:detailed", json.dumps(detailed_rows, ensure_ascii=False))
    meta = {
        "status": "ready",
        "resident_id": resident_id,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "months": months,
        "daily_days": len(daily_summary),
        "detailed_days": detailed_days,
        "step_hours": step_hours,
        "storage": {
            "profiles": f"Redis sim:profile:{resident_id}",
            "daily_history": f"Redis patient:{resident_id}:history:daily",
            "detailed_history": f"Redis patient:{resident_id}:history:detailed",
            "live_timeseries": "InfluxDB bucket residents",
            "json_folder": str(_patient_dir(resident_id)),
        },
    }
    redis_client.set(f"patient:{resident_id}:history:meta", json.dumps(meta, ensure_ascii=False))
    paths = _patient_file_paths(resident_id)
    _export_patient_profile_files(resident_id)
    _write_json_file(Path(paths["history_daily"]), daily_summary)
    _write_json_file(Path(paths["history_detailed"]), detailed_rows)
    _write_json_file(Path(paths["history_meta"]), meta)
    return meta


@app.get("/api/simulator/config")
def get_simulator_config():
    return {
        "storage_policy": {
            "profiles": f"JSON source par resident dans {PATIENT_DATA_DIR}/Rxxx/profile.json + cache Redis sim:profile:{{resident_id}}",
            "live_state": "Redis court terme + WebSocket",
            "routine_baseline": "Redis 30 jours, cle routine:{resident_id}:{period}",
            "long_history": "Redis dossiers patient generes + InfluxDB pour les series live",
            "json_files": f"Source et exports lisibles sur disque dans {PATIENT_DATA_DIR}",
        },
        "data_dir": str(PATIENT_DATA_DIR),
        "scenarios": SIMULATION_SCENARIOS,
        "profiles": [_profile_payload(rid) for rid in RESIDENTS_MAP.keys()],
    }


@app.put("/api/simulator/config/residents/{resident_id}")
def update_simulator_profile(resident_id: str, body: SimulatorProfileUpdate):
    if resident_id not in RESIDENTS_MAP:
        raise HTTPException(404, "Resident inconnu")
    data = body.dict(exclude_unset=True)
    if "risk_factor" in data and data["risk_factor"] is not None:
        data["risk_factor"] = max(0.0, min(1.0, float(data["risk_factor"])))
    if "age" in data and data["age"] is not None:
        data["age"] = max(50, min(110, int(data["age"])))
    if "mobility" in data and data["mobility"] not in {"bonne", "moyenne", "faible", "tres_faible"}:
        raise HTTPException(400, "Mobilite invalide")
    if "assigned_scenarios" in data:
        unknown = [s for s in (data["assigned_scenarios"] or []) if s not in SIMULATION_SCENARIOS]
        if unknown:
            raise HTTPException(400, f"Scenarios inconnus: {', '.join(unknown)}")
    current = _effective_resident_profile(resident_id)
    current.update(data)
    current["updated_at"] = datetime.utcnow().isoformat() + "Z"
    redis_client.set(f"sim:profile:{resident_id}", json.dumps(current, ensure_ascii=False))
    if data.get("caregiver"):
        redis_client.set(f"resident:{resident_id}:caregiver", data["caregiver"])
    _write_json_file(_patient_dir(resident_id) / "profile.json", current)
    history_meta = _generate_patient_history(resident_id, 12, 30, 6, True)
    publish_mqtt_control("ehpad/control/profile", {
        "resident_id": resident_id,
        "profile": current,
        "updated_at": current["updated_at"],
    })
    return {"ok": True, "history_regenerated": history_meta, **_profile_payload(resident_id)}


@app.post("/api/simulator/config/history/generate")
def generate_simulator_history(body: HistoryGenerateRequest):
    targets = [body.resident_id] if body.resident_id else list(RESIDENTS_MAP.keys())
    for rid in targets:
        if rid not in RESIDENTS_MAP:
            raise HTTPException(404, f"Resident inconnu: {rid}")
    results = [
        _generate_patient_history(rid, body.months, body.detailed_days, body.step_hours, body.overwrite)
        for rid in targets
    ]
    return {"ok": True, "count": len(results), "histories": results}


@app.get("/api/residents/{resident_id}/dossier/history")
def get_patient_dossier_history(
    resident_id: str,
    request: Request,
    authorization: str = Header(None),
    x_break_glass_reason: str = Header(None),
):
    _require_resident_access(resident_id, authorization, request, "resident_dossier_history", x_break_glass_reason)
    if resident_id not in RESIDENTS_MAP:
        raise HTTPException(404, "Resident inconnu")
    daily = redis_client.get(f"patient:{resident_id}:history:daily")
    detailed = redis_client.get(f"patient:{resident_id}:history:detailed")
    return {
        "resident_id": resident_id,
        "profile": _effective_resident_profile(resident_id),
        "meta": _patient_history_meta(resident_id),
        "json_files": _patient_file_paths(resident_id),
        "daily": json.loads(daily) if daily else [],
        "detailed": json.loads(detailed) if detailed else [],
    }


@app.get("/api/alerts")
def get_alerts():
    active = [_attach_push_delivery(a) for a in alert_engine.get_all_active()]
    history = [_attach_push_delivery(a) for a in alert_engine.get_history(50)]
    return {"active": active, "history": history}


@app.get("/api/push/delivery/{alert_id}")
def get_push_delivery(alert_id: str, authorization: str = Header(None)):
    _require_staff_session(authorization)
    delivery = _push_delivery_summary(alert_id)
    if not delivery:
        raise HTTPException(404, "Trace push introuvable")
    return delivery


@app.get("/api/push/audit")
def get_push_audit(limit: int = 50, authorization: str = Header(None)):
    _require_staff_session(authorization)
    limit = max(1, min(limit, 200))
    rows = []
    for raw in redis_client.lrange("push:audit", 0, limit - 1):
        try:
            rows.append(json.loads(raw))
        except Exception:
            continue
    return {"count": len(rows), "audit": rows}


@app.get("/api/alerts/config")
def get_alert_config():
    return {
        "levels": [
            {
                "level": int(level),
                "name": config["name"],
                "color": config["color"],
                "action": config["action"],
                "escalation_delay_s": config.get("escalade_delay_s"),
                "notify": config.get("notify", []),
            }
            for level, config in sorted(LEVEL_CONFIG.items(), key=lambda item: int(item[0]))
        ],
        "routing_rules": {
            "level_1": "dashboard uniquement",
            "level_2_3": "soignant assigne",
            "level_4": "tous soignants + chef de garde",
            "level_5": "tous soignants + chef de garde + direction + SAMU 15 selon protocole",
        },
        "realism_policy": {
            "anti_noise": "Les niveaux 1-3 doivent persister avant creation.",
            "routine_ceiling": "Une alerte de routine non acquittee est plafonnee au niveau 3 sans signal clinique aggravant.",
            "critical_escalation": "Les niveaux 4 non acquittes et les signaux cliniques forts peuvent escalader jusqu'au niveau 5.",
        },
    }


@app.post("/api/alerts/{resident_id}/acknowledge")
def acknowledge_alert(resident_id: str, by: str = "soignant"):
    ok = alert_engine.acknowledge(resident_id, by)
    if not ok:
        raise HTTPException(404, "Pas d'alerte active pour ce résident")
    return {"ok": True, "message": f"Alerte acquittée par {by}"}


@app.get("/api/alerts/explain/{resident_id}")
def explain_alert(resident_id: str):
    alert = _active_alert_for_resident(resident_id)
    if not alert:
        for item in alert_engine.get_history(200):
            if item.get("resident_id") == resident_id:
                alert = item
                break
    if not alert:
        return {
            "resident_id": resident_id,
            "alert": None,
            "active": False,
            "known": False,
            "professional_summary": "Aucune alerte active ou recente pour ce resident.",
        }
    alert = _attach_push_delivery(alert)
    trigger = alert.get("trigger_data", {})
    return {
        "resident_id": resident_id,
        "alert_id": alert.get("id"),
        "level": alert.get("level"),
        "level_name": alert.get("level_name"),
        "reason": alert.get("reason"),
        "location": {
            "label": alert.get("location_label"),
            "zone": alert.get("current_zone"),
            "floor": alert.get("floor"),
            "position": alert.get("position"),
        },
        "clinical": {
            "news": trigger.get("news"),
            "ml_risk": trigger.get("ml_risk"),
            "vitals": trigger.get("vitals"),
            "movement": trigger.get("movement"),
        },
        "sensors": {
            "events": alert.get("sensor_events") or trigger.get("sensor_events", {}),
            "evidence": trigger.get("evidence", []),
        },
        "action": alert.get("action"),
        "acknowledged": alert.get("acknowledged"),
        "acknowledged_by": alert.get("acknowledged_by"),
        "taken_by": alert.get("taken_by"),
        "taken_at": alert.get("taken_at"),
        "resolved": alert.get("resolved"),
        "notified_staff": alert.get("notified_staff", []),
        "push_delivery": alert.get("push_delivery"),
        "professional_summary": (
            f"{alert.get('level_name')} pour {alert.get('resident_name')}: {alert.get('reason')} "
            f"a {alert.get('location_label') or alert.get('current_zone')}. "
            f"Verifier constantes, capteurs confirmants et acquitter apres prise en charge."
        ),
    }


@app.get("/api/zones")
def get_zones():
    data = redis_client.hgetall("zones:all")
    zones = [json.loads(v) for v in data.values()]
    return {"zones": zones}


@app.get("/api/sensors/health")
def get_sensors_health():
    raw = redis_client.hgetall("sensors:health")
    sensors = []
    for value in raw.values():
        try:
            sensors.append(json.loads(value))
        except Exception:
            pass
    sensors.sort(key=lambda s: (s.get("status") != "offline", s.get("quality_pct", 100), s.get("battery_pct", 100)))
    return {
        "count": len(sensors),
        "offline": sum(1 for s in sensors if s.get("status") == "offline"),
        "weak_signal": sum(1 for s in sensors if float(s.get("quality_pct", 100)) < 70),
        "low_battery": sum(1 for s in sensors if float(s.get("battery_pct", 100)) < 20),
        "sensors": sensors[:300],
    }


@app.get("/api/ops/scalability")
def get_scalability_metrics():
    uptime = max(1.0, time.time() - _started_at)
    now = time.time()
    residents_raw = redis_client.hgetall("residents:all")
    resident_count = len(residents_raw)
    target_messages_s = resident_count * 6
    while _mqtt_window and now - _mqtt_window[0][0] > 60:
        _mqtt_window.popleft()
    mqtt_window = list(_mqtt_window)
    window_total = len(mqtt_window)
    window_vitals = sum(1 for _, topic in mqtt_window if topic.endswith("/vitals"))
    window_ambient = sum(1 for _, topic in mqtt_window if "/ambient" in topic or "/door/" in topic)
    state_ages = []
    for raw in residents_raw.values():
        try:
            state = json.loads(raw)
            ts = state.get("timestamp")
            if ts:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                state_ages.append(max(0.0, now - dt.timestamp()))
        except Exception:
            pass
    max_state_age = max(state_ages) if state_ages else None
    avg_state_age = sum(state_ages) / len(state_ages) if state_ages else None
    theoretical_50 = 50 * 6
    actual_60s = window_total / 60
    return {
        "uptime_s": round(uptime),
        "resident_count": resident_count,
        "scale_targets": {
            "current_residents_constants_s": target_messages_s,
            "target_20_residents_6_constants_s": 120,
            "target_50_residents_6_constants_s": theoretical_50,
            "current_vs_50_target_pct": round((actual_60s / theoretical_50) * 100, 1) if theoretical_50 else 0,
        },
        "mqtt": {
            "messages_total": _mqtt_message_count,
            "messages_per_second_avg": round(_mqtt_message_count / uptime, 2),
            "messages_per_second_60s": round(actual_60s, 2),
            "window_60s_total": window_total,
            "window_60s_vitals": window_vitals,
            "window_60s_ambient": window_ambient,
            "vitals_total": _mqtt_vitals_count,
            "ambient_total": _mqtt_ambient_count,
            "last_message_age_s": round(time.time() - _last_mqtt_message_at, 1) if _last_mqtt_message_at else None,
            "target_20_residents_6_constants_s": 120,
            "current_theoretical_constants_s": target_messages_s,
        },
        "backend": {
            "influx_sample_interval_s": INFLUX_SAMPLE_INTERVAL_S,
            "ws_resident_min_interval_s": WS_RESIDENT_MIN_INTERVAL_S,
            "ws_push_total": _ws_push_count,
            "ws_push_per_second_avg": round(_ws_push_count / uptime, 2),
            "estimated_influx_points_per_second": round(resident_count / max(INFLUX_SAMPLE_INTERVAL_S, 0.1), 2),
            "estimated_ws_states_per_second": round(resident_count / max(WS_RESIDENT_MIN_INTERVAL_S, 0.1), 2),
            "state_age_avg_s": round(avg_state_age, 1) if avg_state_age is not None else None,
            "state_age_max_s": round(max_state_age, 1) if max_state_age is not None else None,
        },
        "prediction": {
            "refresh_interval_s": 300,
            "cache_ttl_s": 600,
            "llm_policy": "LLM hors boucle seconde; ML/A2A toutes les 5 minutes",
        },
        "pro_recommendations": [
            "tester NUM_RESIDENTS=50",
            "surveiller p95 latence API/WebSocket",
            "alerter si last_message_age_s > 10s pour un capteur critique",
            "conserver InfluxDB pour historique et Redis pour etat courant",
        ],
    }


def _staff_snapshot() -> dict:
    active_alerts = [_attach_push_delivery(a) for a in alert_engine.get_all_active()]
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


class NotificationAction(BaseModel):
    caregiver_id: str
    action: str
    notification_key: Optional[str] = None
    alert_id: Optional[str] = None
    resident_id: Optional[str] = None
    resident_name: Optional[str] = None
    level: Optional[int] = None
    reason: Optional[str] = None
    location: Optional[str] = None


class SamuCallAction(BaseModel):
    caregiver_id: str
    alert_id: Optional[str] = None
    action: str = "confirmed"


class StaffLoginBody(BaseModel):
    caregiver_id: str
    password: str


@app.post("/api/notifications/action")
def record_notification_action(payload: NotificationAction, authorization: str = Header(None)):
    session = _require_staff_session(authorization)
    if session["sub"] != payload.caregiver_id and not _is_privileged_staff(session["sub"], session.get("role")):
        raise HTTPException(403, "Action refusee pour un autre personnel")
    if payload.caregiver_id not in CAREGIVERS:
        raise HTTPException(404, "Personnel inconnu")
    action_map = {
        "seen": "vue",
        "vu": "vue",
        "taken": "prise_en_charge",
        "prise_en_charge": "prise_en_charge",
        "acknowledged": "acquittee",
        "acquitte": "acquittee",
        "resolved": "resolue",
        "resolu": "resolue",
        "escalated": "escalade",
        "escalade": "escalade",
    }
    action = action_map.get(payload.action)
    if not action:
        raise HTTPException(400, "Action notification invalide")

    now = datetime.utcnow().isoformat() + "Z"
    key = payload.notification_key or payload.alert_id or _notification_key(payload.dict())
    staff = _staff_status(payload.caregiver_id)
    row = {
        "notification_key": key,
        "alert_id": payload.alert_id,
        "caregiver_id": payload.caregiver_id,
        "caregiver_name": staff.get("name", payload.caregiver_id),
        "action": action,
        "status": action,
        "resident_id": payload.resident_id,
        "resident_name": payload.resident_name,
        "level": payload.level,
        "reason": payload.reason,
        "location": payload.location,
        "at": now,
    }
    redis_client.hset(f"notification:status:{payload.caregiver_id}", key, json.dumps(row))
    redis_client.lpush(f"notifications:audit:{payload.caregiver_id}", json.dumps(row))
    redis_client.ltrim(f"notifications:audit:{payload.caregiver_id}", 0, 199)
    redis_client.expire(f"notifications:audit:{payload.caregiver_id}", RETENTION_AUDIT_DAYS * 86400)
    redis_client.lpush("notifications:audit:global", json.dumps(row))
    redis_client.ltrim("notifications:audit:global", 0, 999)
    redis_client.expire("notifications:audit:global", RETENTION_AUDIT_DAYS * 86400)

    if action == "prise_en_charge" and payload.resident_id:
        alert_engine.take_in_charge(payload.resident_id, payload.caregiver_id)
    elif action == "resolue" and payload.resident_id:
        alert_engine.resolve(payload.resident_id, payload.caregiver_id)
    elif action == "acquittee" and payload.resident_id:
        alert_engine.acknowledge(payload.resident_id, payload.caregiver_id)

    return {"ok": True, "trace": row}


@app.get("/api/notifications/audit")
def get_notification_audit(caregiver_id: Optional[str] = None, limit: int = 50):
    limit = max(1, min(limit, 200))
    key = f"notifications:audit:{caregiver_id}" if caregiver_id else "notifications:audit:global"
    rows = []
    for raw in redis_client.lrange(key, 0, limit - 1):
        try:
            rows.append(json.loads(raw))
        except Exception:
            continue
    return {"count": len(rows), "audit": rows}


@app.get("/api/alerts/{resident_id}/samu-call")
def get_samu_call(resident_id: str, request: Request, authorization: str = Header(None)):
    _require_resident_access(resident_id, authorization, request, "samu_preappel_view")
    alert = _active_alert_for_resident(resident_id)
    if not alert:
        raise HTTPException(404, "Pas d'alerte active pour ce resident")
    if int(alert.get("level") or 0) < 5:
        raise HTTPException(400, "Le protocole SAMU simule est reserve au niveau 5")
    call = _ensure_samu_call(alert)
    return {"ok": True, "call": call}


@app.post("/api/alerts/{resident_id}/samu-call/simulate")
def simulate_samu_call(resident_id: str, payload: SamuCallAction, request: Request, authorization: str = Header(None)):
    session = _require_resident_access(resident_id, authorization, request, "samu_simulation")
    if session["sub"] != payload.caregiver_id and not _is_privileged_staff(session["sub"], session.get("role")):
        raise HTTPException(403, "Action SAMU refusee pour un autre personnel")
    if payload.caregiver_id not in CAREGIVERS:
        raise HTTPException(404, "Personnel inconnu")
    alert = _active_alert_for_resident(resident_id)
    if not alert:
        raise HTTPException(404, "Pas d'alerte active pour ce resident")
    if int(alert.get("level") or 0) < 5:
        raise HTTPException(400, "Le protocole SAMU simule est reserve au niveau 5")
    if payload.alert_id and payload.alert_id != alert.get("id"):
        raise HTTPException(409, "L'alerte active ne correspond plus a l'appel demande")

    call = _ensure_samu_call(alert, caregiver_id=payload.caregiver_id)
    staff = _staff_status(payload.caregiver_id)
    action = payload.action.lower()
    if action in {"cancelled", "annule", "cancel"}:
        call["status"] = "appel_annule_simulation"
        audit_action = "samu_annule"
    else:
        call["status"] = "appel_samu_simule_confirme"
        call["confirmed_at"] = datetime.utcnow().isoformat() + "Z"
        call["confirmed_by"] = payload.caregiver_id
        call["confirmed_by_name"] = staff.get("name", payload.caregiver_id)
        audit_action = "samu_confirme"

    redis_client.setex(_samu_call_key(alert["id"]), 86400, json.dumps(call, ensure_ascii=False))
    redis_client.lpush("samu:calls", json.dumps(call, ensure_ascii=False))
    redis_client.ltrim("samu:calls", 0, 199)

    row = {
        "notification_key": alert.get("id"),
        "alert_id": alert.get("id"),
        "caregiver_id": payload.caregiver_id,
        "caregiver_name": staff.get("name", payload.caregiver_id),
        "action": audit_action,
        "status": audit_action,
        "resident_id": resident_id,
        "resident_name": alert.get("resident_name"),
        "level": alert.get("level"),
        "reason": alert.get("reason"),
        "location": alert.get("location_label"),
        "samu_call_id": call["call_id"],
        "at": datetime.utcnow().isoformat() + "Z",
    }
    redis_client.hset(f"notification:status:{payload.caregiver_id}", alert.get("id"), json.dumps(row, ensure_ascii=False))
    redis_client.lpush(f"notifications:audit:{payload.caregiver_id}", json.dumps(row, ensure_ascii=False))
    redis_client.ltrim(f"notifications:audit:{payload.caregiver_id}", 0, 199)
    redis_client.lpush("notifications:audit:global", json.dumps(row, ensure_ascii=False))
    redis_client.ltrim("notifications:audit:global", 0, 999)
    redis_client.expire("notifications:audit:global", RETENTION_AUDIT_DAYS * 86400)

    return {"ok": True, "call": call, "trace": row}


@app.get("/api/staff")
def get_staff():
    snapshot = _staff_snapshot()
    return {
        "count": len(snapshot["staff"]),
        "staff": snapshot["staff"],
        "routing_rules": {
            "level_1": "dashboard",
            "level_2_3": "soignant assigne",
            "level_4": "tous soignants + chef de garde",
            "level_5": "tous soignants + chef de garde + direction",
        },
    }


@app.get("/api/security/policy")
def get_security_policy(authorization: str = Header(None)):
    _require_security_admin(authorization)
    return {
        "session": {"staff_ttl_s": auth_module.STAFF_TOKEN_TTL, "family_ttl_s": auth_module.TOKEN_TTL},
        "roles": {"privileged": ["chef_garde", "direction", "medecin", "admin"], "strict_backend": True},
        "cors": {"allowed_origins": ALLOWED_ORIGINS},
        "https_required": HTTPS_REQUIRED,
        "redis_password_enabled": bool(REDIS_PASSWORD),
        "retention": {
            "access_log_days": RETENTION_ACCESS_LOG_DAYS,
            "notification_audit_days": RETENTION_AUDIT_DAYS,
            "llm_daily_report_days": LLM_DAILY_TTL_DAYS,
        },
        "break_glass": {
            "enabled": True,
            "condition": "patient non assigne + justification + alerte active niveau >= 3",
            "trace_key": "security:break_glass",
        },
    }


@app.get("/api/security/access-logs")
def get_access_logs(limit: int = 100, authorization: str = Header(None)):
    _require_security_admin(authorization)
    limit = max(1, min(limit, 500))
    rows = []
    for raw in redis_client.lrange("security:access_log", 0, limit - 1):
        try:
            rows.append(json.loads(raw))
        except Exception:
            continue
    return {"count": len(rows), "logs": rows}


@app.get("/api/security/break-glass")
def get_break_glass_logs(limit: int = 100, authorization: str = Header(None)):
    _require_security_admin(authorization)
    limit = max(1, min(limit, 500))
    rows = []
    for raw in redis_client.lrange("security:break_glass", 0, limit - 1):
        try:
            rows.append(json.loads(raw))
        except Exception:
            continue
    return {"count": len(rows), "logs": rows}


@app.post("/api/staff/login")
@limiter.limit("5/minute")
def staff_login(request: Request, body: StaffLoginBody):
    result = auth_module.authenticate_staff(redis_client, body.caregiver_id, body.password, CAREGIVERS, SESSION_SECRET)
    if not result:
        redis_client.lpush("security:auth_failures", json.dumps({
            "at": datetime.utcnow().isoformat() + "Z",
            "user_id": body.caregiver_id,
            "ip": request.client.host if request.client else None,
            "type": "staff_login",
        }, ensure_ascii=False))
        redis_client.ltrim("security:auth_failures", 0, 999)
        redis_client.expire("security:auth_failures", RETENTION_ACCESS_LOG_DAYS * 86400)
        raise HTTPException(401, "Identifiants personnel incorrects")
    token, session = result
    staff = _staff_status(session["sub"])
    return {
        "token": token,
        "expires_in_s": auth_module.STAFF_TOKEN_TTL,
        "staff": staff,
        "security": {
            "role": session.get("role"),
            "session_expires_at": datetime.fromtimestamp(session["exp"], timezone.utc).isoformat().replace("+00:00", "Z"),
        },
    }


@app.post("/api/staff/logout")
def staff_logout(authorization: str = Header(None)):
    token = _bearer_token(authorization)
    if token:
        auth_module.revoke_staff_token(redis_client, token)
    return {"ok": True}


@app.get("/api/staff/session")
def staff_session(authorization: str = Header(None)):
    session = _require_staff_session(authorization)
    staff = _staff_status(session["sub"])
    return {
        "ok": True,
        "staff": staff,
        "security": {
            "role": session.get("role"),
            "session_expires_at": datetime.fromtimestamp(session["exp"], timezone.utc).isoformat().replace("+00:00", "Z"),
        },
    }


@app.post("/api/staff/{caregiver_id}/status")
def set_staff_status(caregiver_id: str, status: str = "disponible", sector: Optional[str] = None, shift: Optional[str] = None, authorization: str = Header(None)):
    session = _require_staff_session(authorization)
    if session["sub"] != caregiver_id and not _is_privileged_staff(session["sub"], session.get("role")):
        raise HTTPException(403, "Modification refusee pour un autre personnel")
    if caregiver_id not in CAREGIVERS:
        raise HTTPException(404, "Soignant inconnu")
    allowed = {"disponible", "occupe", "pause", "hors_service", "astreinte"}
    if status not in allowed:
        raise HTTPException(400, "Statut invalide")
    current = _staff_status(caregiver_id)
    current.update({
        "status": status,
        "sector": sector or current.get("sector"),
        "shift": shift or current.get("shift"),
        "updated_at": datetime.utcnow().isoformat() + "Z",
    })
    redis_client.set(f"staff:{caregiver_id}:status", json.dumps(current))
    return {"ok": True, "staff": current}


@app.post("/api/residents/{resident_id}/assign-caregiver")
def assign_caregiver(resident_id: str, caregiver_id: str, authorization: str = Header(None)):
    _require_security_admin(authorization)
    if resident_id not in RESIDENTS_MAP:
        raise HTTPException(404, "Resident non trouve")
    if caregiver_id not in CAREGIVERS:
        raise HTTPException(404, "Soignant inconnu")
    redis_client.set(f"resident:{resident_id}:caregiver", caregiver_id)
    raw = redis_client.hget("residents:all", resident_id)
    if raw:
        try:
            data = json.loads(raw)
            data["caregiver"] = caregiver_id
            data["caregiver_name"] = _staff_status(caregiver_id).get("name")
            redis_client.hset("residents:all", resident_id, json.dumps(data))
        except Exception:
            pass
    return {"ok": True, "resident_id": resident_id, "caregiver_id": caregiver_id, "caregiver": _staff_status(caregiver_id)}


@app.get("/api/summary")
def get_summary():
    raw = redis_client.get("ehpad:summary")
    if raw:
        return json.loads(raw)
    return {"error": "Pas encore de données"}


@app.get("/api/project/readiness")
def get_project_readiness():
    """Matrice de validation pour le rendu pro du projet EHPAD."""
    residents = []
    for profile in RESIDENTS_MAP.values():
        archetype = _resident_archetype(profile)
        residents.append({
            "resident_id": profile["id"],
            "name": profile["name"],
            "room": profile["room"],
            "archetype": archetype,
            **RESIDENT_ARCHETYPES[archetype],
        })
    counts = {}
    for item in residents:
        counts[item["archetype"]] = counts.get(item["archetype"], 0) + 1
    return {
        "project": "EHPAD Monitor",
        "target": "20-50 residents, surveillance continue, prediction malaise, alertes 5 niveaux",
        "readiness": PROJECT_READINESS,
        "resident_profile_counts": counts,
        "resident_profiles": residents,
        "validation_order": [
            "1. profils et scenarios de vie",
            "2. alertes et localisation",
            "3. prediction ML/A2A 30-60 min",
            "4. plan 2D/3D capteurs",
            "5. mini DPI et transmissions",
            "6. scalabilite MQTT/Redis/Influx/WebSocket",
        ],
    }


@app.get("/api/scenarios/life-plan")
def get_life_plan():
    return {
        "day_template": [
            {"time": "06:00-07:30", "period": "lever_toilette", "zones": ["chambre", "couloir"], "risk": "transfert, chute chambre"},
            {"time": "07:30-09:00", "period": "petit_dej", "zones": ["salle_manger", "chambre"], "risk": "trajet repas, hypotension posturale"},
            {"time": "09:00-10:00", "period": "soins_matin", "zones": ["infirmerie", "kinesitherapie", "chambre"], "risk": "fatigue soins"},
            {"time": "10:00-11:45", "period": "animation_matin", "zones": ["salle_commune", "activites", "jardin"], "risk": "effort, desorientation"},
            {"time": "11:45-13:15", "period": "trajet_dejeuner/dejeuner", "zones": ["couloirs", "ascenseur", "salle_manger"], "risk": "chute trajet, malaise repas"},
            {"time": "13:15-15:00", "period": "sieste", "zones": ["chambre", "salle_repos"], "risk": "inactivite normale vs anormale"},
            {"time": "15:00-16:45", "period": "animation_apres_midi/gouter", "zones": ["salle_commune", "jardin", "salle_manger"], "risk": "fatigue, regroupement"},
            {"time": "18:00-19:30", "period": "trajet_diner/diner", "zones": ["couloirs", "salle_manger"], "risk": "chute trajet, malaise retour repas"},
            {"time": "20:30-06:00", "period": "coucher/nuit", "zones": ["chambre", "couloir si errance"], "risk": "sortie de lit, errance, fugue"},
        ],
        "scenario_types": [
            "chute_chambre", "chute_couloir", "chute_trajet_repas", "chute_jardin",
            "malaise_salle_manger", "malaise_retour_repas", "retour_kine_fatigue",
            "errance_nuit", "desorientation_ascenseur", "fugue_hors_ehpad",
            "isolement_chambre", "immobilite_salle_repos", "promenade_jardin",
        ],
        "profile_logic": RESIDENT_ARCHETYPES,
    }


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
    return _build_resident_daily_report(resident_id, report_date=date, force=True)


@app.get("/api/residents/{resident_id}/dpi")
def get_resident_dpi(
    resident_id: str,
    request: Request,
    date: Optional[str] = None,
    authorization: str = Header(None),
    x_break_glass_reason: str = Header(None),
):
    """Mini DPI: profil, constantes, alertes, historique 30 jours et risque a venir."""
    _require_resident_access(resident_id, authorization, request, "resident_mini_dpi", x_break_glass_reason)
    if resident_id not in RESIDENTS_MAP:
        raise HTTPException(404, "Resident non trouve")
    report_date = _local_report_date(date)
    return {
        "resident_id": resident_id,
        "date": report_date,
        "mini_dpi": _build_resident_daily_report(resident_id, report_date=report_date, force=True),
    }


@app.get("/api/a2a/agents")
def get_a2a_agents():
    return agent_card()


@app.get("/api/a2a/predict/{resident_id}")
def get_a2a_prediction(
    resident_id: str,
    request: Request,
    authorization: str = Header(None),
    x_break_glass_reason: str = Header(None),
):
    _require_resident_access(resident_id, authorization, request, "resident_a2a_prediction", x_break_glass_reason)
    if resident_id not in RESIDENTS_MAP:
        raise HTTPException(404, "Resident non trouve")
    cached = redis_client.get(f"a2a:prediction:{resident_id}")
    if cached:
        data = json.loads(cached)
        data["source"] = "auto_refresh_5min"
        return data
    state = _safe_state_for_report(resident_id)
    hist = _history_summary(resident_id)
    active_alert = _active_alert_for_resident(resident_id)
    return _a2a_prediction_for_resident(state, hist, active_alert=active_alert)


@app.get("/api/a2a/predictions")
def get_a2a_predictions():
    cached = redis_client.get("a2a:predictions:all")
    if cached:
        data = json.loads(cached)
        data["source"] = "auto_refresh_5min"
        return data
    predictions = []
    for resident_id in RESIDENTS_MAP.keys():
        state = _safe_state_for_report(resident_id)
        hist = _history_summary(resident_id)
        active_alert = _active_alert_for_resident(resident_id)
        pred = _a2a_prediction_for_resident(state, hist, active_alert=active_alert)["prediction"]
        predictions.append({
            "resident_id": resident_id,
            "resident_name": state.get("resident_name") or state.get("name"),
            "room": state.get("room"),
            "location": state.get("current_zone") or state.get("zone"),
            **pred,
        })
    predictions.sort(key=lambda p: (p["recommended_level"], p["risk_60min"], p["risk_30min"]), reverse=True)
    return {"count": len(predictions), "predictions": predictions}


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
def get_resident_routine(
    resident_id: str,
    request: Request,
    authorization: str = Header(None),
    x_break_glass_reason: str = Header(None),
):
    """Analyse comportementale C4 - baseline multi-signaux par periode."""
    _require_resident_access(resident_id, authorization, request, "resident_routine_view", x_break_glass_reason)
    if resident_id not in RESIDENTS_MAP:
        raise HTTPException(404, "Resident non trouve")
    summary = get_routine_summary(redis_client, resident_id)
    summary["name"] = RESIDENTS_MAP[resident_id].get("name")
    return summary

from fastapi import Header as _Header
from pydantic import BaseModel as _BaseModel

class _LoginBody(_BaseModel):
    username: str
    password: str

class _CreateAccountBody(_BaseModel):
    username: str
    password: str
    resident_id: str


def _require_famille_token(authorization: str = _Header(None)) -> dict:
    """Extrait et valide le Bearer token famille. Leve 401 si invalide."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    session = auth_module.validate_token(redis_client, token)
    if not session:
        raise HTTPException(401, "Session expiree ou invalide")
    return session


def _require_admin(authorization: str = _Header(None)):
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token != FAMILLE_ADMIN_TOKEN:
        raise HTTPException(403, "Acces administrateur requis")


# ---------- Auth famille ----------

@app.post("/api/famille/login")
@limiter.limit("5/minute")
def famille_login(request: Request, body: _LoginBody):
    """Authentifie un compte famille, retourne un token de session 24h."""
    result = auth_module.authenticate(redis_client, body.username, body.password)
    if not result:
        raise HTTPException(401, "Identifiants incorrects")
    token, resident_id = result
    profile = RESIDENTS_MAP.get(resident_id, {})
    return {
        "token": token,
        "resident_id": resident_id,
        "name": profile.get("name", resident_id),
        "avatar": profile.get("avatar", ""),
    }


@app.post("/api/famille/logout")
def famille_logout(authorization: str = _Header(None)):
    """Invalide le token de session."""
    if authorization and authorization.lower().startswith("bearer "):
        auth_module.revoke_token(redis_client, authorization[7:].strip())
    return {"ok": True}


@app.get("/api/famille/{resident_id}")
def get_famille_view(resident_id: str, authorization: str = _Header(None)):
    """Vue famille C3 - etat general uniquement, sans donnees medicales."""
    session = _require_famille_token(authorization)
    if session["resident_id"] != resident_id:
        raise HTTPException(403, "Acces refuse a ce resident")
    profile = RESIDENTS_MAP.get(resident_id)
    if not profile:
        raise HTTPException(404, "Resident non trouve")
    raw = redis_client.get(f"resident:{resident_id}:state")
    state = json.loads(raw) if raw else _safe_state_for_report(resident_id)
    active_alert = _active_alert_for_resident(resident_id)
    alert_level = active_alert.get("level", 0) if active_alert else 0
    if alert_level >= 4:
        general_status = "Surveillance renforcee"
    elif alert_level >= 2:
        general_status = "Sous surveillance"
    else:
        general_status = "Situation stable"
    from resident_profiles import CAREGIVERS
    caregiver_name = CAREGIVERS.get(profile.get("caregiver", ""), {}).get("name", "")
    life_week = _resident_week_life(resident_id, state)
    return {
        "name": profile.get("name", resident_id),
        "avatar": profile.get("avatar", ""),
        "room": state.get("room"),
        "floor": state.get("floor"),
        "general_status": general_status,
        "alert_level": alert_level,
        "activity": state.get("routine_label") or state.get("time_label") or state.get("activity", ""),
        "caregiver": caregiver_name,
        "last_update": state.get("timestamp", ""),
        "privacy_scope": {
            "visible": ["etat general", "activite", "menu", "programme", "photos", "soignant referent"],
            "hidden": ["FC", "SpO2", "PA", "temperature", "scores cliniques", "alertes brutes"],
        },
        "life_week": life_week,
    }


# ---------- Admin comptes famille ----------

@app.get("/api/admin/famille/accounts")
def admin_list_accounts(authorization: str = _Header(None)):
    _require_admin(authorization)
    accounts = auth_module.list_accounts(redis_client)
    for acc in accounts:
        p = RESIDENTS_MAP.get(acc["resident_id"], {})
        acc["resident_name"] = p.get("name", acc["resident_id"])
        acc["room"] = p.get("room", "")
    return {"accounts": accounts}


@app.post("/api/admin/famille/accounts")
def admin_create_account(body: _CreateAccountBody, authorization: str = _Header(None)):
    _require_admin(authorization)
    if body.resident_id not in RESIDENTS_MAP:
        raise HTTPException(404, "Resident inconnu")
    ok = auth_module.create_account(redis_client, body.username, body.password, body.resident_id)
    if not ok:
        raise HTTPException(409, "Ce nom d'utilisateur existe deja")
    return {"ok": True, "username": body.username.lower()}


@app.delete("/api/admin/famille/accounts/{username}")
def admin_delete_account(username: str, authorization: str = _Header(None)):
    _require_admin(authorization)
    if not auth_module.delete_account(redis_client, username):
        raise HTTPException(404, "Compte introuvable")
    return {"ok": True}


@app.put("/api/admin/famille/accounts/{username}")
def admin_update_account(username: str, body: _CreateAccountBody, authorization: str = _Header(None)):
    _require_admin(authorization)
    ok = auth_module.update_account(redis_client, username,
                                    password=body.password or None,
                                    resident_id=body.resident_id or None)
    if not ok:
        raise HTTPException(404, "Compte introuvable")
    return {"ok": True}


# ---------- KB clinique ----------

@app.get("/api/kb/scenarios")
def kb_scenarios():
    """Liste tous les scenarios cliniques de la KB (15 scenarios HAS/RCP/WHO)."""
    import kb_loader
    scenarios = kb_loader.get_scenarios()
    return {
        "count": len(scenarios),
        "scenarios": [
            {
                "id": s["id"],
                "name": s["name"],
                "category": s["category"],
                "clinical_rationale": s.get("clinical_rationale", ""),
                "family_visibility": s.get("family_visibility", ""),
            }
            for s in scenarios
        ],
    }


@app.get("/api/kb/scenarios/{scenario_id}")
def kb_scenario_detail(scenario_id: str):
    """Detail complet d'un scenario KB."""
    import kb_loader
    s = kb_loader.get_scenario(scenario_id)
    if not s:
        raise HTTPException(404, "Scenario inconnu")
    return s


@app.get("/api/kb/archetypes")
def kb_archetypes():
    """Liste les archetypes residents de la KB avec baseline et scenarios associes."""
    import kb_loader
    return {"count": len(kb_loader.get_archetypes()), "archetypes": kb_loader.get_archetypes()}


@app.get("/api/kb/residents")
def kb_residents_enriched():
    """Residents enrichis : archetype KB, medicaments probables, scenarios preferes."""
    result = [
        {
            "id": r["id"],
            "name": r["name"],
            "room": r["room"],
            "pathologies": r["pathologies"],
            "archetype_id": r.get("archetype_id", ""),
            "likely_medications": r.get("likely_medications", []),
            "preferred_scenarios": r.get("preferred_scenarios", []),
            "risk_factor": r["risk_factor"],
        }
        for r in RESIDENTS_LIST
    ]
    return {"count": len(result), "residents": result}


from llm_service import run_report_sync, start_report_job, get_report_result


def _llm_daily_key(report_date: str, resident_id: str) -> str:
    return f"llm:daily:v1:{report_date}:{resident_id}"


def _llm_daily_index_key(report_date: str) -> str:
    return f"llm:daily:v1:{report_date}"


def _get_cached_daily_llm(report_date: str, resident_id: str) -> Optional[dict]:
    raw = redis_client.get(_llm_daily_key(report_date, resident_id))
    return json.loads(raw) if raw else None


def _llm_alerts_for_resident(resident_id: str) -> list[dict]:
    alerts = []
    seen = set()
    for alert in alert_engine.get_history(100):
        if alert.get("resident_id") == resident_id:
            key = alert.get("id") or f"{alert.get('created_at')}:{alert.get('reason')}"
            seen.add(key)
            alerts.append(alert)
    for raw in redis_client.lrange("alerts:history", 0, 199):
        try:
            alert = json.loads(raw)
        except Exception:
            continue
        if alert.get("resident_id") != resident_id:
            continue
        key = alert.get("id") or f"{alert.get('created_at')}:{alert.get('reason')}"
        if key not in seen:
            seen.add(key)
            alerts.append(alert)
    return alerts[:100]


@app.get("/api/llm/report/{resident_id}")
async def get_llm_report(resident_id: str, force: bool = False):
    """
    Rapport LLM quotidien - synchrone, attend le résultat.
    RAG KB clinique (HAS/RCP), sortie JSON structurée Pydantic, suivi latence.
    """
    report_date = _local_report_date()
    if not force:
        cached = _get_cached_daily_llm(report_date, resident_id)
        if cached:
            cached["cached"] = True
            return cached

    raw = redis_client.get(f"resident:{resident_id}:state")
    if not raw:
        raise HTTPException(404, "Résident non trouvé")
    state = json.loads(raw)
    profile = RESIDENTS_MAP.get(resident_id, {})
    alerts_today = _llm_alerts_for_resident(resident_id)
    clinical_history = _build_resident_daily_report(resident_id, report_date=report_date, force=False)

    result = await run_report_sync(
        resident_id=resident_id,
        resident_name=profile.get("name", resident_id),
        profile=profile,
        state=state,
        alerts_today=alerts_today,
        ollama_host=OLLAMA_HOST,
        ollama_model=OLLAMA_MODEL,
        redis_client=redis_client,
        clinical_history=clinical_history,
    )
    result["date"] = report_date
    result["generated_at"] = datetime.utcnow().isoformat() + "Z"
    ttl = LLM_DAILY_TTL_DAYS * 86400
    redis_client.setex(_llm_daily_key(report_date, resident_id), ttl, json.dumps(result, ensure_ascii=False))
    redis_client.hset(_llm_daily_index_key(report_date), resident_id, json.dumps(result, ensure_ascii=False))
    redis_client.expire(_llm_daily_index_key(report_date), ttl)
    return result


@app.post("/api/llm/report/{resident_id}/start")
async def start_llm_report(resident_id: str):
    """
    Lance la génération LLM en arrière-plan, retourne un job_id immédiatement.
    Utiliser GET /api/llm/result/{job_id} pour récupérer le résultat.
    """
    raw = redis_client.get(f"resident:{resident_id}:state")
    if not raw:
        raise HTTPException(404, "Résident non trouvé")
    state = json.loads(raw)
    profile = RESIDENTS_MAP.get(resident_id, {})
    alerts_today = _llm_alerts_for_resident(resident_id)
    clinical_history = _build_resident_daily_report(resident_id, force=False)

    job_id = start_report_job(
        redis_client=redis_client,
        resident_id=resident_id,
        resident_name=profile.get("name", resident_id),
        profile=profile,
        state=state,
        alerts_today=alerts_today,
        ollama_host=OLLAMA_HOST,
        ollama_model=OLLAMA_MODEL,
        clinical_history=clinical_history,
    )
    return {"job_id": job_id, "status": "pending", "resident_id": resident_id}


@app.get("/api/llm/daily/{date}")
async def get_daily_llm_reports(date: str):
    report_date = _local_report_date(date)
    raw_map = redis_client.hgetall(_llm_daily_index_key(report_date))
    reports = [json.loads(v) for v in raw_map.values()]
    reports.sort(key=lambda r: (r.get("report", {}).get("niveau_risque") == "eleve", r.get("ml_risk", 0)), reverse=True)
    return {
        "date": report_date,
        "count": len(reports),
        "expected": len(RESIDENTS_MAP),
        "complete": len(reports) >= len(RESIDENTS_MAP),
        "reports": reports,
    }


@app.get("/api/llm/daily/{date}/{resident_id}")
async def get_daily_llm_report_for_resident(date: str, resident_id: str, generate_if_missing: bool = True):
    report_date = _local_report_date(date)
    cached = _get_cached_daily_llm(report_date, resident_id)
    if cached:
        cached["cached"] = True
        return cached
    if not generate_if_missing:
        raise HTTPException(404, "Rapport LLM quotidien non genere")
    return await get_llm_report(resident_id, force=True)


def daily_llm_report_loop():
    """Genere automatiquement un rapport LLM quotidien par resident."""
    if not LLM_DAILY_AUTO_ENABLED:
        log.info("Rapport LLM quotidien automatique desactive")
        return
    last_attempt_date = None
    while True:
        try:
            today = _local_report_date()
            index_key = _llm_daily_index_key(today)
            generated = redis_client.hlen(index_key)
            if generated < len(RESIDENTS_MAP) or last_attempt_date != today:
                last_attempt_date = today
                for resident_id in RESIDENTS_MAP.keys():
                    if redis_client.exists(_llm_daily_key(today, resident_id)):
                        continue
                    try:
                        asyncio.run(get_llm_report(resident_id, force=False))
                        time.sleep(1.0)
                    except Exception as exc:
                        log.warning(f"Rapport LLM quotidien ignore pour {resident_id}: {exc}")
                final_count = redis_client.hlen(index_key)
                redis_client.setex(
                    f"llm:daily:v1:{today}:status",
                    LLM_DAILY_TTL_DAYS * 86400,
                    json.dumps({
                        "date": today,
                        "generated": final_count,
                        "expected": len(RESIDENTS_MAP),
                        "complete": final_count >= len(RESIDENTS_MAP),
                        "updated_at": datetime.utcnow().isoformat() + "Z",
                    }),
                )
                log.info(f"Rapports LLM quotidiens: {final_count}/{len(RESIDENTS_MAP)} pour {today}")
        except Exception as e:
            log.error(f"Rapport LLM quotidien loop error: {e}")
        time.sleep(300)


@app.get("/api/llm/result/{job_id}")
async def get_llm_result(job_id: str):
    """Résultat d'un job LLM lancé via /start - retourne pending ou done."""
    return get_report_result(redis_client, job_id)


@app.get("/api/llm/audit")
async def get_llm_audit():
    """Historique des 200 derniers appels LLM : latence, modèle, niveau risque."""
    raw_entries = redis_client.lrange("llm:audit", 0, 199)
    entries = [json.loads(e) for e in raw_entries]
    avg_ms = int(sum(e.get("duration_ms", 0) for e in entries) / len(entries)) if entries else 0
    return {"count": len(entries), "avg_duration_ms": avg_ms, "entries": entries}


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
    threading.Thread(target=predictive_analysis_loop, daemon=True).start()
    threading.Thread(target=daily_llm_report_loop, daemon=True).start()

    log.info("Backend EHPAD démarré OK")
