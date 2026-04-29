import json
from collections.abc import Callable
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, Request

import auth as auth_module


class SecurityService:
    def __init__(
        self,
        *,
        redis_client,
        caregivers: dict,
        residents_map: dict,
        session_secret: str,
        retention_access_log_days: int,
        resident_caregiver: Callable[[str, Optional[dict]], str],
        active_alert_for_resident: Callable[[str], Optional[dict]],
    ) -> None:
        self.redis = redis_client
        self.caregivers = caregivers
        self.residents_map = residents_map
        self.session_secret = session_secret
        self.retention_access_log_days = retention_access_log_days
        self.resident_caregiver = resident_caregiver
        self.active_alert_for_resident = active_alert_for_resident

    @staticmethod
    def bearer_token(authorization: Optional[str]) -> Optional[str]:
        if authorization and authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
        return None

    def require_staff_session(self, authorization: Optional[str] = None) -> dict:
        session = auth_module.validate_staff_token(
            self.redis,
            self.bearer_token(authorization),
            self.session_secret,
        )
        if not session:
            raise HTTPException(401, "Session personnel expiree ou invalide")
        if session.get("sub") not in self.caregivers:
            raise HTTPException(403, "Personnel inconnu")
        return session

    @staticmethod
    def is_privileged_staff(staff_id: str, role: Optional[str] = None) -> bool:
        return staff_id in {"chef_garde", "direction"} or role in {"medecin", "direction", "admin"}

    def can_staff_access_resident(self, staff_id: str, resident_id: str, role: Optional[str] = None) -> bool:
        if self.is_privileged_staff(staff_id, role):
            return True
        return self.resident_caregiver(resident_id, self.residents_map.get(resident_id, {})) == staff_id

    def log_access(
        self,
        user_id: str,
        role: str,
        resident_id: str,
        action: str,
        outcome: str,
        request: Optional[Request] = None,
        reason: Optional[str] = None,
    ) -> dict:
        row = {
            "at": datetime.utcnow().isoformat() + "Z",
            "user_id": user_id,
            "role": role,
            "resident_id": resident_id,
            "resident_name": self.residents_map.get(resident_id, {}).get("name", resident_id),
            "action": action,
            "outcome": outcome,
            "reason": reason,
            "ip": request.client.host if request and request.client else None,
            "path": str(request.url.path) if request else None,
        }
        self.redis.lpush("security:access_log", json.dumps(row, ensure_ascii=False))
        self.redis.ltrim("security:access_log", 0, 4999)
        self.redis.expire("security:access_log", self.retention_access_log_days * 86400)
        if outcome == "break_glass":
            self.redis.lpush("security:break_glass", json.dumps(row, ensure_ascii=False))
            self.redis.ltrim("security:break_glass", 0, 999)
            self.redis.expire("security:break_glass", self.retention_access_log_days * 86400)
        return row

    def require_resident_access(
        self,
        resident_id: str,
        authorization: Optional[str],
        request: Optional[Request],
        action: str,
        break_glass_reason: Optional[str] = None,
    ) -> dict:
        session = self.require_staff_session(authorization)
        staff_id = session["sub"]
        role = session.get("role", "soignant")
        if self.can_staff_access_resident(staff_id, resident_id, role):
            self.log_access(staff_id, role, resident_id, action, "allowed", request)
            return session
        active = self.active_alert_for_resident(resident_id)
        reason = break_glass_reason.strip() if break_glass_reason else None
        if reason and len(reason) >= 8 and active and int(active.get("level") or 0) >= 3:
            self.log_access(staff_id, role, resident_id, action, "break_glass", request, reason)
            return session
        self.log_access(staff_id, role, resident_id, action, "denied", request, break_glass_reason)
        raise HTTPException(403, "Acces refuse: resident non assigne. Bris de glace requis si urgence.")

    def require_security_admin(self, authorization: Optional[str] = None) -> dict:
        session = self.require_staff_session(authorization)
        if not self.is_privileged_staff(session["sub"], session.get("role")):
            raise HTTPException(403, "Acces reserve chef de garde / direction")
        return session
