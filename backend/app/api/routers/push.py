import json
import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.core.runtime import runtime as rt

router = APIRouter(tags=["Push"])


class PushSubscribeRequest(BaseModel):
    staff_id: str = "soignant"
    endpoint: str
    p256dh: str
    auth: str


class PushTestRequest(BaseModel):
    staff_id: str = "soignant_A"
    resident_id: str = "R005"
    level: int = 3
    title: Optional[str] = None
    body: Optional[str] = None


@router.get("/api/push/config")
def push_config():
    return {"enabled": rt.push_service.enabled, "public_key": rt.push_service.vapid_public_key}


@router.get("/api/push/status")
def push_status(authorization: str = Header(None)):
    session = rt.require_staff_session(authorization)
    staff_id = session["sub"]
    subs = rt.push_service.subscriptions_for_staff(staff_id)
    return {"enabled": rt.push_service.enabled, "staff_id": staff_id, "subscriptions": len(subs)}


@router.post("/api/push/subscribe")
def push_subscribe(body: PushSubscribeRequest, authorization: str = Header(None)):
    session = rt.require_staff_session(authorization)
    if session["sub"] != body.staff_id and not rt.is_privileged_staff(session["sub"], session.get("role")):
        raise HTTPException(403, "Souscription refusee pour un autre personnel")
    return rt.push_service.register_subscription(body.staff_id, body.endpoint, body.p256dh, body.auth)


@router.delete("/api/push/subscribe")
def push_unsubscribe(endpoint: str, staff_id: str = "soignant"):
    return rt.push_service.unregister_subscription(staff_id, endpoint)


@router.post("/api/push/test")
async def push_test(body: PushTestRequest, authorization: str = Header(None)):
    session = rt.require_staff_session(authorization)
    target_staff = body.staff_id
    if session["sub"] != target_staff and not rt.is_privileged_staff(session["sub"], session.get("role")):
        raise HTTPException(403, "Test push refuse pour un autre personnel")
    payload = {
        "title": body.title or f"Test push EHPAD - N{body.level}",
        "body": body.body or f"Notification test pour {body.resident_id}",
        "level": max(1, min(5, int(body.level or 3))),
        "resident_id": body.resident_id,
        "alert_id": f"test-{int(time.time())}",
    }
    result = await rt.push_service.send_web_push_async(payload, staff_ids=[target_staff])
    return {"ok": True, "payload": payload, "result": result}


@router.post("/api/push/test-all")
async def push_test_all(body: PushTestRequest, authorization: str = Header(None)):
    session = rt.require_staff_session(authorization)
    if not rt.is_privileged_staff(session["sub"], session.get("role")):
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
    result = await rt.push_service.send_web_push_async(payload, staff_ids=staff_ids)
    return {"ok": True, "payload": payload, "result": result}


@router.get("/api/push/delivery/{alert_id}")
def get_push_delivery(alert_id: str, authorization: str = Header(None)):
    rt.require_staff_session(authorization)
    delivery = rt.push_service.delivery_summary(alert_id)
    if not delivery:
        raise HTTPException(404, "Trace push introuvable")
    return delivery


@router.get("/api/push/audit")
def get_push_audit(limit: int = 50, authorization: str = Header(None)):
    rt.require_staff_session(authorization)
    limit = max(1, min(limit, 200))
    rows = []
    for raw in rt.redis_client.lrange("push:audit", 0, limit - 1):
        try:
            rows.append(json.loads(raw))
        except Exception:
            continue
    return {"count": len(rows), "audit": rows}
