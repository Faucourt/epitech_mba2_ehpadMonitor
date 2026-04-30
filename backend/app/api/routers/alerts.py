import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from app.core.runtime import runtime as rt

router = APIRouter(tags=["Alerts"])


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


@router.get("/api/alerts")
def get_alerts():
    active = [rt.attach_push_delivery(a) for a in rt.alert_engine.get_all_active()]
    history = [rt.attach_push_delivery(a) for a in rt.alert_engine.get_history(50)]
    return {"active": active, "history": history}


@router.get("/api/alerts/config")
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
            for level, config in sorted(rt.level_config.items(), key=lambda item: int(item[0]))
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


@router.post("/api/alerts/{resident_id}/acknowledge")
def acknowledge_alert(resident_id: str, by: str = "soignant"):
    ok = rt.alert_engine.acknowledge(resident_id, by)
    if not ok:
        raise HTTPException(404, "Pas d'alerte active pour ce résident")
    return {"ok": True, "message": f"Alerte acquittée par {by}"}


@router.post("/api/alerts/{resident_id}/take")
def take_alert(resident_id: str, by: str = "soignant"):
    ok = rt.alert_engine.take_in_charge(resident_id, by)
    if not ok:
        raise HTTPException(404, "Pas d'alerte active pour ce resident")
    return {"ok": True, "message": f"Alerte prise en charge par {by}"}


@router.post("/api/alerts/{resident_id}/resolve")
def resolve_alert(resident_id: str, by: str = "soignant"):
    ok = rt.alert_engine.resolve(resident_id, by)
    if not ok:
        raise HTTPException(404, "Pas d'alerte active pour ce resident")
    return {"ok": True, "message": f"Alerte cloturee par {by}"}


@router.get("/api/alerts/explain/{resident_id}")
def explain_alert(resident_id: str):
    alert = rt.active_alert_for_resident(resident_id)
    if not alert:
        for item in rt.alert_engine.get_history(200):
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
    alert = rt.attach_push_delivery(alert)
    trigger = alert.get("trigger_data", {})
    reason_label = alert.get("reason_label") or str(alert.get("reason") or "").split("]", 1)[-1].strip()
    routine = trigger.get("routine_analysis") or {}
    routine_baseline = routine.get("baseline") or {}
    routine_entry = routine.get("entry") or {}
    sensor_events = dict(alert.get("sensor_events") or trigger.get("sensor_events", {}) or {})
    evidence = list(trigger.get("evidence", []) or [])
    if "chute_chambre" in str(alert.get("reason")):
        sensor_events["bathroom_motion"] = False
        evidence = [
            item.replace("capteurs_actifs=bathroom_motion", "capteurs_actifs=aucun")
            for item in evidence
        ]
    return {
        "resident_id": resident_id,
        "alert_id": alert.get("id"),
        "level": alert.get("level"),
        "level_name": alert.get("level_name"),
        "reason": alert.get("reason"),
        "reason_label": reason_label,
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
            "baseline": routine_baseline,
            "routine_entry": routine_entry,
        },
        "routine": {
            "score": routine.get("score"),
            "flags": routine.get("flags", []),
            "baseline": routine_baseline,
            "entry": routine_entry,
        },
        "kb_context": trigger.get("kb_context") or {},
        "sensors": {
            "events": sensor_events,
            "evidence": evidence,
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
            f"{alert.get('level_name')} pour {alert.get('resident_name')}: {reason_label} "
            f"a {alert.get('location_label') or alert.get('current_zone')}. "
            f"{(trigger.get('kb_context') or {}).get('action_hint') or 'Verifier constantes, capteurs confirmants et acquitter apres prise en charge.'}"
        ),
    }


@router.post("/api/notifications/action")
def record_notification_action(payload: NotificationAction, authorization: str = Header(None)):
    session = rt.require_staff_session(authorization)
    if session["sub"] != payload.caregiver_id and not rt.is_privileged_staff(session["sub"], session.get("role")):
        raise HTTPException(403, "Action refusee pour un autre personnel")
    if payload.caregiver_id not in rt.caregivers:
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
        "resolue": "resolue",
        "escalated": "escalade",
        "escalade": "escalade",
    }
    action = action_map.get(payload.action)
    if not action:
        raise HTTPException(400, "Action notification invalide")

    now = datetime.utcnow().isoformat() + "Z"
    key = payload.notification_key or payload.alert_id or rt.notification_key(payload.dict())
    staff = rt.staff_status(payload.caregiver_id)
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
    rt.redis_client.hset(f"notification:status:{payload.caregiver_id}", key, json.dumps(row))
    rt.redis_client.lpush(f"notifications:audit:{payload.caregiver_id}", json.dumps(row))
    rt.redis_client.ltrim(f"notifications:audit:{payload.caregiver_id}", 0, 199)
    rt.redis_client.expire(f"notifications:audit:{payload.caregiver_id}", rt.retention_audit_days * 86400)
    rt.redis_client.lpush("notifications:audit:global", json.dumps(row))
    rt.redis_client.ltrim("notifications:audit:global", 0, 999)
    rt.redis_client.expire("notifications:audit:global", rt.retention_audit_days * 86400)

    if action == "prise_en_charge" and payload.resident_id:
        rt.alert_engine.take_in_charge(payload.resident_id, payload.caregiver_id)
    elif action == "resolue" and payload.resident_id:
        rt.alert_engine.resolve(payload.resident_id, payload.caregiver_id)
    elif action == "acquittee" and payload.resident_id:
        rt.alert_engine.acknowledge(payload.resident_id, payload.caregiver_id)

    return {"ok": True, "trace": row}


@router.get("/api/notifications/audit")
def get_notification_audit(caregiver_id: Optional[str] = None, limit: int = 50):
    limit = max(1, min(limit, 200))
    key = f"notifications:audit:{caregiver_id}" if caregiver_id else "notifications:audit:global"
    rows = []
    for raw in rt.redis_client.lrange(key, 0, limit - 1):
        try:
            rows.append(json.loads(raw))
        except Exception:
            continue
    return {"count": len(rows), "audit": rows}


@router.get("/api/alerts/{resident_id}/samu-call")
def get_samu_call(resident_id: str, request: Request, authorization: str = Header(None)):
    rt.require_resident_access(resident_id, authorization, request, "samu_preappel_view")
    alert = rt.active_alert_for_resident(resident_id)
    if not alert:
        raise HTTPException(404, "Pas d'alerte active pour ce resident")
    if int(alert.get("level") or 0) < 5:
        raise HTTPException(400, "Le protocole SAMU simule est reserve au niveau 5")
    call = rt.ensure_samu_call(alert)
    return {"ok": True, "call": call}


@router.post("/api/alerts/{resident_id}/samu-call/simulate")
def simulate_samu_call(resident_id: str, payload: SamuCallAction, request: Request, authorization: str = Header(None)):
    session = rt.require_resident_access(resident_id, authorization, request, "samu_simulation")
    if session["sub"] != payload.caregiver_id and not rt.is_privileged_staff(session["sub"], session.get("role")):
        raise HTTPException(403, "Action SAMU refusee pour un autre personnel")
    if payload.caregiver_id not in rt.caregivers:
        raise HTTPException(404, "Personnel inconnu")
    alert = rt.active_alert_for_resident(resident_id)
    if not alert:
        raise HTTPException(404, "Pas d'alerte active pour ce resident")
    if int(alert.get("level") or 0) < 5:
        raise HTTPException(400, "Le protocole SAMU simule est reserve au niveau 5")
    if payload.alert_id and payload.alert_id != alert.get("id"):
        raise HTTPException(409, "L'alerte active ne correspond plus a l'appel demande")

    call = rt.ensure_samu_call(alert, caregiver_id=payload.caregiver_id)
    staff = rt.staff_status(payload.caregiver_id)
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

    rt.redis_client.setex(rt.samu_call_key(alert["id"]), 86400, json.dumps(call, ensure_ascii=False))
    rt.redis_client.lpush("samu:calls", json.dumps(call, ensure_ascii=False))
    rt.redis_client.ltrim("samu:calls", 0, 199)

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
    rt.redis_client.hset(f"notification:status:{payload.caregiver_id}", alert.get("id"), json.dumps(row, ensure_ascii=False))
    rt.redis_client.lpush(f"notifications:audit:{payload.caregiver_id}", json.dumps(row, ensure_ascii=False))
    rt.redis_client.ltrim(f"notifications:audit:{payload.caregiver_id}", 0, 199)
    rt.redis_client.lpush("notifications:audit:global", json.dumps(row, ensure_ascii=False))
    rt.redis_client.ltrim("notifications:audit:global", 0, 999)
    rt.redis_client.expire("notifications:audit:global", rt.retention_audit_days * 86400)

    return {"ok": True, "call": call, "trace": row}
