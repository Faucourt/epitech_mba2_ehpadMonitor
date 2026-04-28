"""
Gestion des comptes famille : creation, authentification, tokens de session.
Stockage dans Redis, sans base de donnees supplementaire.
"""

import hashlib
import hmac
import json
import secrets
import unicodedata
import base64
from datetime import datetime, timezone

TOKEN_TTL = 86400  # 24 h
STAFF_TOKEN_TTL = 8 * 3600

LEGACY_DEMO_USERNAMES = {
    "dupont", "moreau", "bernard", "leroy", "martin", "petit", "durand",
    "thomas", "robert", "richard", "simon", "michel", "lefebvre", "leblanc",
    "fontaine", "rousseau", "morel", "garnier", "chevalier", "mercier",
    "blanc", "caron", "fournier", "girard", "perrin",
}


def _hash(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


def create_account(rc, username: str, password: str, resident_id: str) -> bool:
    """Retourne False si le compte existe deja."""
    key = f"famille:account:{username.lower()}"
    if rc.exists(key):
        return False
    salt = secrets.token_hex(16)
    rc.set(key, json.dumps({
        "password_hash": _hash(password, salt),
        "salt": salt,
        "resident_id": resident_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }))
    return True


def update_account(rc, username: str, password: str = None, resident_id: str = None) -> bool:
    key = f"famille:account:{username.lower()}"
    raw = rc.get(key)
    if not raw:
        return False
    data = json.loads(raw)
    if password:
        salt = secrets.token_hex(16)
        data["password_hash"] = _hash(password, salt)
        data["salt"] = salt
    if resident_id:
        data["resident_id"] = resident_id
    rc.set(key, json.dumps(data))
    return True


def delete_account(rc, username: str) -> bool:
    return bool(rc.delete(f"famille:account:{username.lower()}"))


def list_accounts(rc) -> list:
    keys = rc.keys("famille:account:*")
    result = []
    for k in keys:
        raw = rc.get(k)
        if raw:
            data = json.loads(raw)
            result.append({
                "username": k.replace("famille:account:", ""),
                "resident_id": data.get("resident_id"),
                "created_at": data.get("created_at", ""),
            })
    result.sort(key=lambda x: x["username"])
    return result


def authenticate(rc, username: str, password: str):
    """Retourne (token, resident_id) ou None si echec."""
    key = f"famille:account:{username.lower()}"
    raw = rc.get(key)
    if not raw:
        return None
    data = json.loads(raw)
    if _hash(password, data["salt"]) != data["password_hash"]:
        return None
    token = secrets.token_urlsafe(32)
    rc.setex(f"famille:token:{token}", TOKEN_TTL, json.dumps({
        "resident_id": data["resident_id"],
        "username": username.lower(),
    }))
    return token, data["resident_id"]


def validate_token(rc, token: str) -> dict | None:
    """Retourne {"resident_id": ..., "username": ...} ou None."""
    if not token:
        return None
    raw = rc.get(f"famille:token:{token}")
    return json.loads(raw) if raw else None


def revoke_token(rc, token: str):
    rc.delete(f"famille:token:{token}")


def create_staff_accounts(rc, caregivers: dict, default_password: str) -> None:
    """Cree des comptes demo personnel si absents. En prod: provisionning IAM/e-CPS."""
    for staff_id, info in caregivers.items():
        key = f"staff:account:{staff_id}"
        if rc.exists(key):
            continue
        salt = secrets.token_hex(16)
        rc.set(key, json.dumps({
            "password_hash": _hash(default_password, salt),
            "salt": salt,
            "role": info.get("role", "soignant"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "password_policy": "demo_env",
        }))


def authenticate_staff(rc, staff_id: str, password: str, caregivers: dict, session_secret: str):
    staff_id = (staff_id or "").strip()
    if staff_id not in caregivers:
        return None
    raw = rc.get(f"staff:account:{staff_id}")
    if not raw:
        return None
    data = json.loads(raw)
    if _hash(password, data["salt"]) != data["password_hash"]:
        return None
    now = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "sub": staff_id,
        "role": data.get("role") or caregivers[staff_id].get("role", "soignant"),
        "iat": now,
        "exp": now + STAFF_TOKEN_TTL,
    }
    token = _sign_session(payload, session_secret)
    rc.setex(f"staff:session:{token}", STAFF_TOKEN_TTL, json.dumps(payload))
    return token, payload


def validate_staff_token(rc, token: str, session_secret: str) -> dict | None:
    if not token:
        return None
    payload = _verify_session(token, session_secret)
    if not payload:
        return None
    raw = rc.get(f"staff:session:{token}")
    if not raw:
        return None
    stored = json.loads(raw)
    if int(stored.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
        revoke_staff_token(rc, token)
        return None
    return stored


def revoke_staff_token(rc, token: str):
    rc.delete(f"staff:session:{token}")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _sign_session(payload: dict, secret: str) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(sig)}"


def _verify_session(token: str, secret: str) -> dict | None:
    try:
        body, sig = token.split(".", 1)
        expected = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64decode(body))
        if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
            return None
        return payload
    except Exception:
        return None


def seed_demo_accounts(rc, residents_list: list):
    """Synchronise les comptes demo avec la liste courante des residents."""
    expected_usernames = {_demo_username(r) for r in residents_list}
    for username in LEGACY_DEMO_USERNAMES - expected_usernames:
        delete_account(rc, username)

    for r in residents_list:
        username = _demo_username(r)
        password = r["family_code"].lower()
        if not create_account(rc, username, password, r["id"]):
            update_account(rc, username, password, r["id"])


def _demo_username(resident: dict) -> str:
    parts = resident["name"].replace("-", " ").split()
    username = parts[-1].lower() if parts else resident["id"].lower()
    return _strip_accents(username)


def _strip_accents(s: str) -> str:
    normalized = unicodedata.normalize("NFKD", s)
    return "".join(c for c in normalized if not unicodedata.combining(c))
