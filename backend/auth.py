"""
Gestion des comptes famille : creation, authentification, tokens de session.
Stockage dans Redis — pas de base de donnees supplementaire necessaire.
"""

import hashlib
import json
import secrets
from datetime import datetime, timezone

TOKEN_TTL = 86400  # 24 h


# --- Hachage mot de passe ---

def _hash(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


# --- CRUD comptes ---

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


# --- Authentification ---

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


# --- Amorçage demo ---

def seed_demo_accounts(rc, residents_list: list):
    """Cree les comptes demo au premier demarrage (ignore si deja presents)."""
    for r in residents_list:
        parts = r["name"].split()
        username = parts[-1].lower() if len(parts) >= 2 else r["id"].lower()
        # Supprime les accents simples pour le username
        username = _strip_accents(username)
        password = r["family_code"].lower()
        create_account(rc, username, password, r["id"])


def _strip_accents(s: str) -> str:
    replacements = {
        "é": "e", "è": "e", "ê": "e", "ë": "e",
        "à": "a", "â": "a", "ä": "a",
        "î": "i", "ï": "i",
        "ô": "o", "ö": "o",
        "ù": "u", "û": "u", "ü": "u",
        "ç": "c",
    }
    return "".join(replacements.get(c, c) for c in s)
