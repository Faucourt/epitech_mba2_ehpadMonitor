import json

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from app.core.runtime import runtime as rt

router = APIRouter(tags=["Famille"])


class LoginBody(BaseModel):
    username: str
    password: str


class CreateAccountBody(BaseModel):
    username: str
    password: str
    resident_id: str


def require_famille_token(authorization: str = Header(None)) -> dict:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    session = rt.auth_module.validate_token(rt.redis_client, token)
    if not session:
        raise HTTPException(401, "Session expiree ou invalide")
    return session


def require_admin(authorization: str = Header(None)):
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token != rt.famille_admin_token:
        raise HTTPException(403, "Acces administrateur requis")


@router.post("/api/famille/login")
def famille_login(request: Request, body: LoginBody):
    """Authentifie un compte famille, retourne un token de session 24h."""
    result = rt.auth_module.authenticate(rt.redis_client, body.username, body.password)
    if not result:
        raise HTTPException(401, "Identifiants incorrects")
    token, resident_id = result
    profile = rt.residents_map.get(resident_id, {})
    return {
        "token": token,
        "resident_id": resident_id,
        "name": profile.get("name", resident_id),
        "avatar": profile.get("avatar", ""),
    }


@router.post("/api/famille/logout")
def famille_logout(authorization: str = Header(None)):
    """Invalide le token de session."""
    if authorization and authorization.lower().startswith("bearer "):
        rt.auth_module.revoke_token(rt.redis_client, authorization[7:].strip())
    return {"ok": True}


@router.get("/api/famille/{resident_id}")
def get_famille_view(resident_id: str, authorization: str = Header(None)):
    """Vue famille C3 - etat general uniquement, sans donnees medicales."""
    session = require_famille_token(authorization)
    if session["resident_id"] != resident_id:
        raise HTTPException(403, "Acces refuse a ce resident")
    profile = rt.residents_map.get(resident_id)
    if not profile:
        raise HTTPException(404, "Resident non trouve")
    raw = rt.redis_client.get(f"resident:{resident_id}:state")
    state = json.loads(raw) if raw else rt.safe_state_for_report(resident_id)
    active_alert = rt.active_alert_for_resident(resident_id)
    alert_level = active_alert.get("level", 0) if active_alert else 0
    if alert_level >= 4:
        general_status = "Surveillance renforcee"
    elif alert_level >= 2:
        general_status = "Sous surveillance"
    else:
        general_status = "Situation stable"
    caregiver_name = rt.caregivers.get(profile.get("caregiver", ""), {}).get("name", "")
    life_week = rt.resident_week_life(resident_id, state)
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


@router.get("/api/admin/famille/accounts")
def admin_list_accounts(authorization: str = Header(None)):
    require_admin(authorization)
    accounts = rt.auth_module.list_accounts(rt.redis_client)
    for account in accounts:
        profile = rt.residents_map.get(account["resident_id"], {})
        account["resident_name"] = profile.get("name", account["resident_id"])
        account["room"] = profile.get("room", "")
    return {"accounts": accounts}


@router.post("/api/admin/famille/accounts")
def admin_create_account(body: CreateAccountBody, authorization: str = Header(None)):
    require_admin(authorization)
    if body.resident_id not in rt.residents_map:
        raise HTTPException(404, "Resident inconnu")
    ok = rt.auth_module.create_account(rt.redis_client, body.username, body.password, body.resident_id)
    if not ok:
        raise HTTPException(409, "Ce nom d'utilisateur existe deja")
    return {"ok": True, "username": body.username.lower()}


@router.delete("/api/admin/famille/accounts/{username}")
def admin_delete_account(username: str, authorization: str = Header(None)):
    require_admin(authorization)
    if not rt.auth_module.delete_account(rt.redis_client, username):
        raise HTTPException(404, "Compte introuvable")
    return {"ok": True}


@router.put("/api/admin/famille/accounts/{username}")
def admin_update_account(username: str, body: CreateAccountBody, authorization: str = Header(None)):
    require_admin(authorization)
    ok = rt.auth_module.update_account(
        rt.redis_client,
        username,
        password=body.password or None,
        resident_id=body.resident_id or None,
    )
    if not ok:
        raise HTTPException(404, "Compte introuvable")
    return {"ok": True}
