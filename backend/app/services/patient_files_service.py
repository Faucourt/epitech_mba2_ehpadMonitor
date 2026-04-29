import json
from datetime import datetime
from pathlib import Path
from typing import Callable


class PatientFilesService:
    def __init__(
        self,
        *,
        patient_data_dir: Path,
        redis_client,
        residents_map: dict,
        resident_config: Callable[[str], dict],
        effective_resident_profile: Callable[[str], dict],
        simulated_history_rows: Callable,
    ) -> None:
        self.patient_data_dir = patient_data_dir
        self.redis = redis_client
        self.residents_map = residents_map
        self.resident_config = resident_config
        self.effective_resident_profile = effective_resident_profile
        self.simulated_history_rows = simulated_history_rows

    def patient_dir(self, resident_id: str) -> Path:
        return self.patient_data_dir / resident_id

    @staticmethod
    def write_json_file(path: Path, payload) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def read_json_file(path: Path, default):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return default

    def patient_file_paths(self, resident_id: str) -> dict:
        base = self.patient_dir(resident_id)
        return {
            "folder": str(base),
            "profile": str(base / "profile.json"),
            "history_daily": str(base / "history_daily.json"),
            "history_detailed": str(base / "history_detailed.json"),
            "history_meta": str(base / "history_meta.json"),
        }

    def export_patient_profile_files(self, resident_id: str) -> None:
        self.write_json_file(self.patient_dir(resident_id) / "profile.json", self.effective_resident_profile(resident_id))

    def patient_history_meta(self, resident_id: str) -> dict:
        raw = self.redis.get(f"patient:{resident_id}:history:meta")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return {"status": "missing", "daily_days": 0, "detailed_days": 0}

    def profile_payload(self, resident_id: str) -> dict:
        return {
            "resident_id": resident_id,
            "base": dict(self.residents_map.get(resident_id, {})),
            "config": self.resident_config(resident_id),
            "effective": self.effective_resident_profile(resident_id),
            "history": self.patient_history_meta(resident_id),
        }

    @staticmethod
    def daily_summary_from_rows(rows: list[dict]) -> list[dict]:
        by_day: dict[str, list[dict]] = {}
        for row in rows:
            day = str(row.get("time", ""))[:10]
            if day:
                by_day.setdefault(day, []).append(row)
        summaries = []
        for day, items in sorted(by_day.items()):
            alerts = [item for item in items if int(item.get("alert_level") or 0) > 0]
            zones = {}
            for item in items:
                zone = item.get("zone") or "inconnue"
                zones[zone] = zones.get(zone, 0) + 1

            def avg(field: str):
                vals = [float(item[field]) for item in items if item.get(field) is not None]
                return round(sum(vals) / len(vals), 2) if vals else None

            summaries.append({
                "date": day,
                "samples": len(items),
                "avg_hr": avg("heart_rate"),
                "avg_spo2": avg("spo2"),
                "avg_bp_sys": avg("blood_pressure_sys"),
                "avg_ml_risk": avg("ml_risk"),
                "max_alert_level": max([int(item.get("alert_level") or 0) for item in items] or [0]),
                "alert_count": len(alerts),
                "events": list(dict.fromkeys([item.get("event") for item in alerts if item.get("event")]))[:6],
                "dominant_zone": max(zones, key=zones.get) if zones else None,
                "zones": zones,
            })
        return summaries

    def generate_patient_history(self, resident_id: str, months: int, detailed_days: int, step_hours: int, overwrite: bool) -> dict:
        months = max(1, min(int(months or 12), 36))
        detailed_days = max(7, min(int(detailed_days or 30), 120))
        step_hours = max(1, min(int(step_hours or 6), 24))
        total_days = months * 30
        if not overwrite and self.redis.exists(f"patient:{resident_id}:history:meta"):
            return self.patient_history_meta(resident_id)
        daily_rows = self.simulated_history_rows(resident_id, days=total_days, step_hours=24)
        detailed_rows = self.simulated_history_rows(resident_id, days=detailed_days, step_hours=step_hours)
        daily_summary = self.daily_summary_from_rows(daily_rows)
        self.redis.set(f"patient:{resident_id}:history:daily", json.dumps(daily_summary, ensure_ascii=False))
        self.redis.set(f"patient:{resident_id}:history:detailed", json.dumps(detailed_rows, ensure_ascii=False))
        meta = {
            "status": "ready",
            "resident_id": resident_id,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "months": months,
            "daily_days": len(daily_summary),
            "detailed_days": detailed_days,
            "step_hours": step_hours,
            "storage": {
                "profiles": f"Redis sim:profile:{resident_id}",
                "daily_history": f"Redis patient:{resident_id}:history:daily",
                "detailed_history": f"Redis patient:{resident_id}:history:detailed",
                "live_timeseries": "InfluxDB bucket residents",
                "json_folder": str(self.patient_dir(resident_id)),
            },
        }
        self.redis.set(f"patient:{resident_id}:history:meta", json.dumps(meta, ensure_ascii=False))
        paths = self.patient_file_paths(resident_id)
        self.export_patient_profile_files(resident_id)
        self.write_json_file(Path(paths["history_daily"]), daily_summary)
        self.write_json_file(Path(paths["history_detailed"]), detailed_rows)
        self.write_json_file(Path(paths["history_meta"]), meta)
        return meta
