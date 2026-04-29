import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from app.core.config import settings
from app.core.middleware import create_limiter
from app.core.runtime import runtime as rt

router = APIRouter(tags=["Staff"])
limiter = create_limiter()


class StaffLoginBody(BaseModel):
    caregiver_id: str
    password: str


@router.get("/api/staff")
def get_staff():
    snapshot = rt.staff_snapshot()
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


@router.post("/api/staff/login")
@limiter.limit("5/minute")
def staff_login(request: Request, body: StaffLoginBody):
    result = rt.auth_module.authenticate_staff(
        rt.redis_client,
        body.caregiver_id,
        body.password,
        rt.caregivers,
        rt.session_secret,
    )
    if not result:
        rt.redis_client.lpush("security:auth_failures", json.dumps({
            "at": datetime.utcnow().isoformat() + "Z",
            "user_id": body.caregiver_id,
            "ip": request.client.host if request.client else None,
            "type": "staff_login",
        }, ensure_ascii=False))
        rt.redis_client.ltrim("security:auth_failures", 0, 999)
        rt.redis_client.expire("security:auth_failures", rt.retention_access_log_days * 86400)
        raise HTTPException(401, "Identifiants personnel incorrects")
    token, session = result
    staff = rt.staff_status(session["sub"])
    return {
        "token": token,
        "expires_in_s": rt.auth_module.STAFF_TOKEN_TTL,
        "staff": staff,
        "security": {
            "role": session.get("role"),
            "session_expires_at": datetime.fromtimestamp(session["exp"], timezone.utc).isoformat().replace("+00:00", "Z"),
        },
    }


@router.get("/api/security/policy")
def get_security_policy(authorization: str = Header(None)):
    rt.require_security_admin(authorization)
    return {
        "session": {"staff_ttl_s": rt.auth_module.STAFF_TOKEN_TTL, "family_ttl_s": rt.auth_module.TOKEN_TTL},
        "roles": {"privileged": ["chef_garde", "direction", "medecin", "admin"], "strict_backend": True},
        "cors": {"allowed_origins": rt.allowed_origins},
        "https_required": rt.https_required,
        "redis_password_enabled": bool(settings.redis_password),
        "retention": {
            "access_log_days": rt.retention_access_log_days,
            "notification_audit_days": rt.retention_audit_days,
            "llm_daily_report_days": rt.llm_daily_ttl_days,
        },
        "break_glass": {
            "enabled": True,
            "condition": "patient non assigne + justification + alerte active niveau >= 3",
            "trace_key": "security:break_glass",
        },
    }


@router.get("/api/security/access-logs")
def get_access_logs(limit: int = 100, authorization: str = Header(None)):
    rt.require_security_admin(authorization)
    limit = max(1, min(limit, 500))
    rows = []
    for raw in rt.redis_client.lrange("security:access_log", 0, limit - 1):
        try:
            rows.append(json.loads(raw))
        except Exception:
            continue
    return {"count": len(rows), "logs": rows}


@router.get("/api/security/break-glass")
def get_break_glass_logs(limit: int = 100, authorization: str = Header(None)):
    rt.require_security_admin(authorization)
    limit = max(1, min(limit, 500))
    rows = []
    for raw in rt.redis_client.lrange("security:break_glass", 0, limit - 1):
        try:
            rows.append(json.loads(raw))
        except Exception:
            continue
    return {"count": len(rows), "logs": rows}


@router.post("/api/staff/logout")
def staff_logout(authorization: str = Header(None)):
    token = rt.bearer_token(authorization)
    if token:
        rt.auth_module.revoke_staff_token(rt.redis_client, token)
    return {"ok": True}


@router.get("/api/staff/session")
def staff_session(authorization: str = Header(None)):
    session = rt.require_staff_session(authorization)
    staff = rt.staff_status(session["sub"])
    return {
        "ok": True,
        "staff": staff,
        "security": {
            "role": session.get("role"),
            "session_expires_at": datetime.fromtimestamp(session["exp"], timezone.utc).isoformat().replace("+00:00", "Z"),
        },
    }


@router.post("/api/staff/{caregiver_id}/status")
def set_staff_status(
    caregiver_id: str,
    status: str = "disponible",
    sector: Optional[str] = None,
    shift: Optional[str] = None,
    authorization: str = Header(None),
):
    session = rt.require_staff_session(authorization)
    if session["sub"] != caregiver_id and not rt.is_privileged_staff(session["sub"], session.get("role")):
        raise HTTPException(403, "Modification refusee pour un autre personnel")
    if caregiver_id not in rt.caregivers:
        raise HTTPException(404, "Soignant inconnu")
    allowed = {"disponible", "occupe", "pause", "hors_service", "astreinte"}
    if status not in allowed:
        raise HTTPException(400, "Statut invalide")
    current = rt.staff_status(caregiver_id)
    current.update({
        "status": status,
        "sector": sector or current.get("sector"),
        "shift": shift or current.get("shift"),
        "updated_at": datetime.utcnow().isoformat() + "Z",
    })
    rt.redis_client.set(f"staff:{caregiver_id}:status", json.dumps(current))
    return {"ok": True, "staff": current}


@router.post("/api/residents/{resident_id}/assign-caregiver")
def assign_caregiver(resident_id: str, caregiver_id: str, authorization: str = Header(None)):
    rt.require_security_admin(authorization)
    if resident_id not in rt.residents_map:
        raise HTTPException(404, "Resident non trouve")
    if caregiver_id not in rt.caregivers:
        raise HTTPException(404, "Soignant inconnu")
    rt.redis_client.set(f"resident:{resident_id}:caregiver", caregiver_id)
    raw = rt.redis_client.hget("residents:all", resident_id)
    if raw:
        try:
            data = json.loads(raw)
            data["caregiver"] = caregiver_id
            data["caregiver_name"] = rt.staff_status(caregiver_id).get("name")
            rt.redis_client.hset("residents:all", resident_id, json.dumps(data))
        except Exception:
            pass
    return {
        "ok": True,
        "resident_id": resident_id,
        "caregiver_id": caregiver_id,
        "caregiver": rt.staff_status(caregiver_id),
    }
