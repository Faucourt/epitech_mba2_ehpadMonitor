from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.runtime import runtime as rt

router = APIRouter(tags=["Simulator"])


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


@router.get("/api/simulator/speed")
def get_simulator_speed():
    raw = rt.redis_client.get("simulator:speed")
    return {"speed": float(raw) if raw else 1.0}


@router.post("/api/simulator/speed")
def set_simulator_speed(speed: float = 1.0):
    speed = max(0.25, min(60.0, float(speed)))
    rt.redis_client.set("simulator:speed", speed)
    rt.publish_mqtt_control("ehpad/control/speed", {"speed": speed, "updated_at": datetime.utcnow().isoformat() + "Z"})
    return {"ok": True, "speed": speed}


@router.post("/api/simulator/scenario")
def trigger_simulator_scenario(resident_id: str = None, scenario: str = "hypoxie"):
    resident_id = resident_id or rt.demo_resident
    if resident_id not in rt.residents_map:
        raise HTTPException(404, "Resident non trouve")
    allowed = set(rt.simulation_scenarios)
    if scenario not in allowed:
        raise HTTPException(400, f"Scenario inconnu: {scenario}")
    payload = {"resident_id": resident_id, "scenario": scenario, "updated_at": datetime.utcnow().isoformat() + "Z"}
    rt.publish_mqtt_control("ehpad/control/scenario", payload)
    return {"ok": True, **payload}


@router.get("/api/simulator/config")
def get_simulator_config():
    return {
        "storage_policy": {
            "profiles": f"JSON source par resident dans {rt.patient_data_dir}/Rxxx/profile.json + cache Redis sim:profile:{{resident_id}}",
            "live_state": "Redis court terme + WebSocket",
            "routine_baseline": "Redis 30 jours, cle routine:{resident_id}:{period}",
            "long_history": "Redis dossiers patient generes + InfluxDB pour les series live",
            "json_files": f"Source et exports lisibles sur disque dans {rt.patient_data_dir}",
        },
        "data_dir": str(rt.patient_data_dir),
        "scenarios": rt.simulation_scenarios,
        "profiles": [rt.profile_payload(rid) for rid in rt.residents_map.keys()],
    }


@router.put("/api/simulator/config/residents/{resident_id}")
def update_simulator_profile(resident_id: str, body: SimulatorProfileUpdate):
    if resident_id not in rt.residents_map:
        raise HTTPException(404, "Resident inconnu")
    data = body.dict(exclude_unset=True)
    if "risk_factor" in data and data["risk_factor"] is not None:
        data["risk_factor"] = max(0.0, min(1.0, float(data["risk_factor"])))
    if "age" in data and data["age"] is not None:
        data["age"] = max(50, min(110, int(data["age"])))
    if "mobility" in data and data["mobility"] not in {"bonne", "moyenne", "faible", "tres_faible"}:
        raise HTTPException(400, "Mobilite invalide")
    if "assigned_scenarios" in data:
        unknown = [s for s in (data["assigned_scenarios"] or []) if s not in rt.simulation_scenarios]
        if unknown:
            raise HTTPException(400, f"Scenarios inconnus: {', '.join(unknown)}")
    current = rt.effective_resident_profile(resident_id)
    current.update(data)
    current["updated_at"] = datetime.utcnow().isoformat() + "Z"
    rt.redis_client.set(f"sim:profile:{resident_id}", rt.json_dumps(current))
    if data.get("caregiver"):
        rt.redis_client.set(f"resident:{resident_id}:caregiver", data["caregiver"])
    rt.write_json_file(rt.patient_dir(resident_id) / "profile.json", current)
    history_meta = rt.generate_patient_history(resident_id, 12, 30, 6, True)
    rt.publish_mqtt_control("ehpad/control/profile", {
        "resident_id": resident_id,
        "profile": current,
        "updated_at": current["updated_at"],
    })
    return {"ok": True, "history_regenerated": history_meta, **rt.profile_payload(resident_id)}


@router.post("/api/simulator/config/history/generate")
def generate_simulator_history(body: HistoryGenerateRequest):
    targets = [body.resident_id] if body.resident_id else list(rt.residents_map.keys())
    for rid in targets:
        if rid not in rt.residents_map:
            raise HTTPException(404, f"Resident inconnu: {rid}")
    results = [
        rt.generate_patient_history(rid, body.months, body.detailed_days, body.step_hours, body.overwrite)
        for rid in targets
    ]
    return {"ok": True, "count": len(results), "histories": results}
