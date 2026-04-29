import json

from app.db.redis_client import redis_client


STAFF_DEFAULTS = {
    "soignant_A": {"sector": "RDC + aile A", "shift": "jour", "status": "disponible"},
    "soignant_B": {"sector": "RDC + aile B", "shift": "jour", "status": "disponible"},
    "soignant_C": {"sector": "1er etage", "shift": "jour", "status": "disponible"},
    "chef_garde": {"sector": "tous secteurs", "shift": "astreinte", "status": "disponible"},
    "direction": {"sector": "administration", "shift": "astreinte", "status": "disponible"},
}


def staff_status(caregiver_id: str, caregivers: dict) -> dict:
    base = {
        "id": caregiver_id,
        **caregivers.get(caregiver_id, {"name": caregiver_id, "role": "soignant", "phone": ""}),
        **STAFF_DEFAULTS.get(caregiver_id, {"sector": "non defini", "shift": "jour", "status": "disponible"}),
    }
    raw = redis_client.get(f"staff:{caregiver_id}:status")
    if raw:
        try:
            base.update(json.loads(raw))
        except Exception:
            pass
    return base
