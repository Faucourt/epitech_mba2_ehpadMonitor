import json
from collections.abc import Callable

from app.core.config import settings
from app.db.redis_client import redis_client


def list_live_residents(active_alert_for_resident: Callable[[str], dict | None]) -> dict:
    data = redis_client.hgetall("residents:all")
    residents = []
    for resident_id, raw in data.items():
        try:
            resident = json.loads(raw)
            resident["active_alert"] = active_alert_for_resident(resident_id)
            residents.append(resident)
        except Exception:
            pass
    return {"residents": residents, "count": len(residents)}


def get_live_resident(resident_id: str, profile_builder: Callable[[str], dict]) -> dict | None:
    raw = redis_client.get(f"resident:{resident_id}:state")
    if not raw:
        return None
    state = json.loads(raw)
    profile = profile_builder(resident_id)
    state["profile"] = profile
    state["avatar"] = state.get("avatar") or profile.get("avatar", "")
    return state


def resident_file_profile(resident_id: str) -> dict:
    path = settings.patient_data_dir / resident_id / "profile.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(payload, dict) and isinstance(payload.get("effective"), dict):
        return payload["effective"]
    return payload if isinstance(payload, dict) else {}


def resident_config(resident_id: str) -> dict:
    file_profile = resident_file_profile(resident_id)
    if file_profile:
        return file_profile
    raw = redis_client.get(f"sim:profile:{resident_id}")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def effective_resident_profile(resident_id: str, residents_map: dict) -> dict:
    base = dict(residents_map.get(resident_id, {}))
    cfg = resident_config(resident_id)
    for key in [
        "age", "pathologies", "mobility", "risk_factor", "caregiver",
        "meal_mode", "care_level", "assigned_scenarios", "notes",
    ]:
        if key in cfg:
            base[key] = cfg[key]
    return base


def resident_caregiver(resident_id: str, residents_map: dict, profile: dict | None = None) -> str:
    override = redis_client.get(f"resident:{resident_id}:caregiver")
    return override or (profile or residents_map.get(resident_id, {})).get("caregiver", "")
