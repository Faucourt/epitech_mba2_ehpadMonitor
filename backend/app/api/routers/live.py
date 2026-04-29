import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Header, HTTPException, Request

from app.core.runtime import runtime as rt
from app.services.resident_service import get_live_resident, list_live_residents

router = APIRouter(tags=["Live"])


@router.get("/api/residents")
def get_all_residents():
    return list_live_residents(rt.active_alert_for_resident)


@router.get("/api/residents/{resident_id}")
def get_resident(
    resident_id: str,
    request: Request,
    authorization: str = Header(None),
    x_break_glass_reason: str = Header(None),
):
    rt.require_resident_access(resident_id, authorization, request, "resident_live_view", x_break_glass_reason)
    state = get_live_resident(resident_id, rt.effective_resident_profile)
    if not state:
        raise HTTPException(404, "Resident non trouve")
    return state


@router.get("/api/residents/{resident_id}/history")
def get_resident_history(
    resident_id: str,
    request: Request,
    minutes: int = 60,
    authorization: str = Header(None),
    x_break_glass_reason: str = Header(None),
):
    rt.require_resident_access(resident_id, authorization, request, "resident_history_view", x_break_glass_reason)
    minutes = max(1, min(int(minutes or 30), 24 * 60))
    try:
        query = f'''
        from(bucket: "{rt.influx_bucket}")
          |> range(start: -{minutes}m)
          |> filter(fn: (r) => r["resident_id"] == "{resident_id}")
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        '''
        result = rt.influx_query_api.query(query)
        rows = []
        for table in result:
            for record in table.records:
                rows.append({
                    "time": record.get_time().isoformat(),
                    "heart_rate": record.values.get("heart_rate"),
                    "spo2": record.values.get("spo2"),
                    "blood_pressure_sys": record.values.get("blood_pressure_sys"),
                    "blood_pressure_dia": record.values.get("blood_pressure_dia"),
                    "temperature": record.values.get("temperature"),
                    "respiratory_rate": record.values.get("respiratory_rate"),
                    "ml_risk": record.values.get("ml_risk"),
                })
        rows.sort(key=lambda row: row["time"])
        if not rows:
            rows = _fallback_recent_history(resident_id, minutes)
        return {"resident_id": resident_id, "minutes": minutes, "history": rows}
    except Exception as exc:
        return {"resident_id": resident_id, "minutes": minutes, "history": _fallback_recent_history(resident_id, minutes), "error": str(exc)}


def _fallback_recent_history(resident_id: str, minutes: int = 30) -> list[dict]:
    raw = rt.redis_client.get(f"resident:{resident_id}:state")
    if not raw:
        return []
    state = json.loads(raw)
    vitals = state.get("vitals", {})
    risk = float(state.get("ml_risk", 0) or 0)
    now = datetime.now(timezone.utc)
    count = max(2, min(180, int(minutes)))
    seed = sum(ord(char) for char in resident_id)
    rows: list[dict] = []
    for i in range(count):
        age = count - 1 - i
        ts = now - timedelta(minutes=age)
        wave = np.sin((i + seed) / 4.0)
        slow = np.sin((i + seed) / 11.0)
        rows.append({
            "time": ts.isoformat(),
            "heart_rate": round(float(vitals.get("heart_rate", 72) or 72) + wave * 2.5 + slow, 1),
            "spo2": round(float(vitals.get("spo2", 96) or 96) + slow * 0.5, 1),
            "blood_pressure_sys": round(float(vitals.get("blood_pressure_sys", 130) or 130) + slow * 4, 1),
            "blood_pressure_dia": round(float(vitals.get("blood_pressure_dia", 75) or 75) + wave * 2, 1),
            "temperature": round(float(vitals.get("temperature", 36.8) or 36.8) + slow * 0.08, 2),
            "respiratory_rate": round(float(vitals.get("respiratory_rate", 16) or 16) + wave * 0.6, 1),
            "ml_risk": round(max(0, min(1, risk + slow * 0.03)), 2),
            "source": "fallback_recent_redis",
        })
    return rows


@router.get("/api/residents/{resident_id}/history/simulated")
def get_resident_simulated_history(
    resident_id: str,
    request: Request,
    days: int = 30,
    step_hours: int = 6,
    authorization: str = Header(None),
    x_break_glass_reason: str = Header(None),
):
    rt.require_resident_access(resident_id, authorization, request, "resident_history_simulated_view", x_break_glass_reason)
    days = max(30, min(days, 730))
    try:
        from history_injector import _MEASUREMENT

        minutes = days * 24 * 60
        query = f'''
from(bucket: "{rt.influx_bucket}")
  |> range(start: -{minutes}m)
  |> filter(fn: (r) => r._measurement == "{_MEASUREMENT}")
  |> filter(fn: (r) => r.resident_id == "{resident_id}")
  |> pivot(rowKey: ["_time", "resident_id", "event"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
'''
        tables = rt.influx_query_api.query(query)
        rows = []
        for table in tables:
            for record in table.records:
                value = record.values
                rows.append({
                    "time": record.get_time().isoformat().replace("+00:00", "Z"),
                    "resident_id": resident_id,
                    "zone": value.get("zone", ""),
                    "event": value.get("event", "routine"),
                    "alert_level": int(value.get("alert_level") or 0),
                    "heart_rate": value.get("heart_rate"),
                    "spo2": value.get("spo2"),
                    "blood_pressure_sys": value.get("blood_pressure_sys"),
                    "blood_pressure_dia": value.get("blood_pressure_dia"),
                    "temperature": value.get("temperature"),
                    "respiratory_rate": value.get("respiratory_rate"),
                    "ml_risk": value.get("ml_risk"),
                })
        if len(rows) >= 10:
            return {"resident_id": resident_id, "days": days, "step_hours": step_hours, "history": rows, "source": "influxdb"}
    except Exception:
        pass
    rows = rt.simulated_history_rows(resident_id, days=days, step_hours=step_hours)
    return {"resident_id": resident_id, "days": days, "step_hours": step_hours, "history": rows, "source": "simulated"}


@router.get("/api/residents/{resident_id}/dossier/history")
def get_patient_dossier_history(
    resident_id: str,
    request: Request,
    authorization: str = Header(None),
    x_break_glass_reason: str = Header(None),
):
    rt.require_resident_access(resident_id, authorization, request, "resident_dossier_history", x_break_glass_reason)
    if resident_id not in rt.residents_map:
        raise HTTPException(404, "Resident inconnu")
    daily = rt.redis_client.get(f"patient:{resident_id}:history:daily")
    detailed = rt.redis_client.get(f"patient:{resident_id}:history:detailed")
    paths = _patient_file_paths(resident_id)
    daily_rows = json.loads(daily) if daily else _read_json_file(Path(paths["history_daily"]), [])
    detailed_rows = json.loads(detailed) if detailed else _read_json_file(Path(paths["history_detailed"]), [])
    return {
        "resident_id": resident_id,
        "profile": rt.effective_resident_profile(resident_id),
        "meta": rt.patient_history_meta(resident_id),
        "json_files": paths,
        "daily": daily_rows,
        "detailed": detailed_rows,
    }


def _patient_file_paths(resident_id: str) -> dict:
    base = rt.patient_dir(resident_id)
    return {
        "folder": str(base),
        "profile": str(base / "profile.json"),
        "history_daily": str(base / "history_daily.json"),
        "history_detailed": str(base / "history_detailed.json"),
        "history_meta": str(base / "history_meta.json"),
    }


def _read_json_file(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


@router.get("/api/zones")
def get_zones():
    data = rt.redis_client.hgetall("zones:all")
    return {"zones": [json.loads(value) for value in data.values()]}


@router.get("/api/sensors/health")
def get_sensors_health():
    raw = rt.redis_client.hgetall("sensors:health")
    sensors = []
    for value in raw.values():
        try:
            sensors.append(json.loads(value))
        except Exception:
            pass
    sensors.sort(key=lambda sensor: (sensor.get("status") != "offline", sensor.get("quality_pct", 100), sensor.get("battery_pct", 100)))
    return {
        "count": len(sensors),
        "offline": sum(1 for sensor in sensors if sensor.get("status") == "offline"),
        "weak_signal": sum(1 for sensor in sensors if float(sensor.get("quality_pct", 100)) < 70),
        "low_battery": sum(1 for sensor in sensors if float(sensor.get("battery_pct", 100)) < 20),
        "sensors": sensors[:300],
    }


@router.get("/api/ops/scalability")
def get_scalability_metrics():
    return rt.scalability_metrics()


@router.get("/api/summary")
def get_summary():
    raw = rt.redis_client.get("ehpad:summary")
    if raw:
        return json.loads(raw)
    return {"error": "Pas encore de donnees"}
