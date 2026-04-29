import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from fastapi import HTTPException

from llm_service import (
    _profile_antecedent_kb_links,
    _structured_fallback_report,
    get_report_result,
    run_report_sync,
    start_report_job,
)


log = logging.getLogger(__name__)


def _fmt_bp(vitals: dict) -> str:
    sys = vitals.get("blood_pressure_sys") or vitals.get("systolic")
    dia = vitals.get("blood_pressure_dia") or vitals.get("diastolic")
    if sys and dia:
        return f"{sys}/{dia} mmHg"
    if sys:
        return f"{sys} mmHg"
    return "-"


class LLMReportService:
    def __init__(
        self,
        *,
        redis_client,
        alert_engine,
        residents_map: dict,
        patient_data_dir: Path,
        local_report_date: Callable[[Optional[str]], str],
        safe_state_for_report: Callable[[str], dict],
        build_resident_daily_report: Callable,
        llm_daily_ttl_days: int,
        llm_daily_auto_enabled: bool,
        ollama_host: str,
        ollama_model: str,
    ) -> None:
        self.redis = redis_client
        self.alert_engine = alert_engine
        self.residents_map = residents_map
        self.patient_data_dir = patient_data_dir
        self.local_report_date = local_report_date
        self.safe_state_for_report = safe_state_for_report
        self.build_resident_daily_report = build_resident_daily_report
        self.llm_daily_ttl_days = llm_daily_ttl_days
        self.llm_daily_auto_enabled = llm_daily_auto_enabled
        self.ollama_host = ollama_host
        self.ollama_model = ollama_model

    def daily_key(self, report_date: str, resident_id: str) -> str:
        return f"llm:daily:v1:{report_date}:{resident_id}"

    def daily_index_key(self, report_date: str) -> str:
        return f"llm:daily:v1:{report_date}"

    def cached_daily(self, report_date: str, resident_id: str) -> Optional[dict]:
        raw = self.redis.get(self.daily_key(report_date, resident_id))
        return json.loads(raw) if raw else None

    def profile_with_patient_file(self, resident_id: str, fallback: dict) -> dict:
        profile = dict(fallback or {})
        profile_path = self.patient_data_dir / resident_id / "profile.json"
        if profile_path.exists():
            try:
                with profile_path.open("r", encoding="utf-8") as f:
                    file_profile = json.load(f)
                if isinstance(file_profile.get("effective"), dict):
                    file_profile = file_profile["effective"]
                if isinstance(file_profile, dict):
                    profile.update(file_profile)
            except Exception as exc:
                log.warning("Profil patient %s non fusionne pour LLM: %s", resident_id, exc)
        return profile

    @staticmethod
    def medical_report_key(report_date: str, resident_id: str) -> str:
        return f"medical_report:v1:{report_date}:{resident_id}"

    @staticmethod
    def medical_report_latest_key(resident_id: str) -> str:
        return f"medical_report:v1:latest:{resident_id}"

    @staticmethod
    def medical_report_index_key(resident_id: str) -> str:
        return f"medical_report:v1:index:{resident_id}"

    @staticmethod
    def medical_report_summary(document: dict) -> dict:
        meta = document.get("metadata", {})
        return {
            "document_id": document.get("document_id"),
            "date": document.get("date"),
            "title": document.get("title"),
            "status": document.get("status"),
            "risk_level": document.get("risk_level"),
            "generated_at": document.get("generated_at"),
            "model": meta.get("model"),
            "standard_hint": meta.get("standard_hint"),
        }

    def build_structured_medical_report_document(self, llm_result: dict, mini_dpi: dict) -> dict:
        report = llm_result.get("report", {}) or {}
        resident_id = llm_result.get("resident_id") or mini_dpi.get("resident_id")
        report_date = llm_result.get("date") or mini_dpi.get("date") or self.local_report_date(None)
        generated_at = llm_result.get("generated_at") or datetime.utcnow().isoformat() + "Z"
        profile = llm_result.get("patient_profile") or mini_dpi.get("profile", {}) or {}
        current = mini_dpi.get("current", {}) or {}
        vitals = current.get("vitals", {}) or {}
        risk = mini_dpi.get("risk", {}) or {}
        document_id = f"MR-{resident_id}-{report_date}"
        resident_name = llm_result.get("resident_name") or mini_dpi.get("resident_name") or resident_id
        title = "Rapport clinique structure d'aide a la transmission"
        summary = report.get("synthese_clinique") or report.get("resume") or mini_dpi.get("transmission_summary") or ""
        actions = report.get("actions_prioritaires") or [
            {"delai": "selon surveillance", "action": action, "responsable": "equipe de soins"}
            for action in mini_dpi.get("next_actions", [])
        ]
        sections = [
            {
                "id": "identity_context",
                "title": "Identification et contexte",
                "entries": [
                    f"Resident: {resident_name} ({resident_id})",
                    f"Chambre: {mini_dpi.get('room', '-')}",
                    f"Age: {profile.get('age', '-')} ans",
                    f"Pathologies connues: {', '.join(profile.get('pathologies', [])) or '-'}",
                    f"Localisation actuelle: {current.get('location', '-')}",
                ],
            },
            {
                "id": "antecedents_kb_care",
                "title": "Antecedents relies a la KB et conduite a tenir",
                "entries": _profile_antecedent_kb_links(profile)[:8],
            },
            {
                "id": "objective_data",
                "title": "Donnees objectives",
                "entries": [
                    f"FC: {vitals.get('heart_rate', '-')} bpm",
                    f"SpO2: {vitals.get('spo2', '-')}%",
                    f"PA: {_fmt_bp(vitals)}",
                    f"Temperature: {vitals.get('temperature', '-')} C",
                    f"Risque ML: {round(float(llm_result.get('ml_risk', risk.get('ml_risk', 0)) or 0) * 100)}%",
                    f"Alertes du jour: {llm_result.get('alerts_count_today', len(mini_dpi.get('alerts_today', [])))}",
                ],
            },
            {"id": "clinical_synthesis", "title": "Synthese clinique", "entries": [summary]},
            {"id": "evidence", "title": "Preuves et signaux utilises", "entries": report.get("preuves", [])[:6]},
            {
                "id": "differential_hypotheses",
                "title": "Hypotheses differentielles a confirmer",
                "entries": report.get("hypotheses", [])[:5],
            },
            {"id": "care_plan", "title": "Conduite a tenir soignant", "entries": actions[:8]},
            {"id": "monitoring_plan", "title": "Plan de surveillance", "entries": report.get("plan_surveillance", [])[:6]},
            {
                "id": "escalation_checks",
                "title": "Elements a verifier et criteres d'escalade",
                "entries": list(dict.fromkeys((report.get("donnees_a_verifier", []) or []) + (report.get("points_vigilance", []) or [])))[:10],
            },
            {
                "id": "sources_traceability",
                "title": "Sources KB et tracabilite LLM",
                "entries": [{"type": "llm_routing", **(report.get("llm_trace", {}) or {})}, *report.get("sources_kb", [])[:12]],
            },
            {
                "id": "limits",
                "title": "Limites",
                "entries": [
                    "Support pedagogique d'aide a la transmission, non diagnostic medical autonome.",
                    "A valider par un professionnel habilite selon le protocole de l'etablissement.",
                    "Les capteurs, le ML et le LLM ne remplacent pas l'examen clinique.",
                ],
            },
        ]
        return {
            "document_id": document_id,
            "date": report_date,
            "generated_at": generated_at,
            "title": title,
            "status": "preliminary_ai_assisted",
            "resident_id": resident_id,
            "resident_name": resident_name,
            "risk_level": report.get("niveau_risque", "faible"),
            "summary": summary,
            "metadata": {
                "model": llm_result.get("model"),
                "duration_ms": llm_result.get("duration_ms"),
                "standard_hint": "FHIR-like DiagnosticReport + Composition sections; inspiration DMP/CI-SIS pour document de coordination",
                "stored_in": "Redis medical_report:v1 + Mini DPI",
                "author": "EHPAD Monitor - LLM router",
            },
            "fhir_like": {
                "resourceType": "DiagnosticReport",
                "id": document_id,
                "status": "preliminary",
                "code": {"text": title},
                "subject": {"reference": f"Patient/{resident_id}", "display": resident_name},
                "effectiveDateTime": report_date,
                "issued": generated_at,
                "conclusion": summary,
                "presentedForm": [{"contentType": "application/json", "title": title}],
            },
            "composition_like": {
                "resourceType": "Composition",
                "status": "preliminary",
                "type": {"text": title},
                "subject": {"reference": f"Patient/{resident_id}", "display": resident_name},
                "date": generated_at,
                "section": [{"title": section["title"], "code": {"text": section["id"]}} for section in sections],
            },
            "rapport_medical": report.get("rapport_medical", {}),
            "sections": sections,
        }

    def store_medical_report_document(self, llm_result: dict, mini_dpi: dict) -> dict:
        document = self.build_structured_medical_report_document(llm_result, mini_dpi)
        ttl = self.llm_daily_ttl_days * 86400
        report_date = document["date"]
        resident_id = document["resident_id"]
        payload = json.dumps(document, ensure_ascii=False)
        self.redis.setex(self.medical_report_key(report_date, resident_id), ttl, payload)
        self.redis.setex(self.medical_report_latest_key(resident_id), ttl, payload)
        self.redis.hset(self.medical_report_index_key(resident_id), report_date, json.dumps(self.medical_report_summary(document), ensure_ascii=False))
        self.redis.expire(self.medical_report_index_key(resident_id), ttl)
        return document

    def get_medical_report_document(self, resident_id: str, report_date: Optional[str] = None) -> Optional[dict]:
        key = self.medical_report_key(self.local_report_date(report_date), resident_id) if report_date else self.medical_report_latest_key(resident_id)
        raw = self.redis.get(key)
        return json.loads(raw) if raw else None

    def ensure_medical_report_document(self, resident_id: str, report_date: str, mini_dpi: dict) -> dict:
        document = self.get_medical_report_document(resident_id, report_date)
        if document and document.get("rapport_medical"):
            return document

        profile = self.profile_with_patient_file(resident_id, self.residents_map.get(resident_id, {}))
        current = mini_dpi.get("current", {}) or {}
        routine_analysis = current.get("routine_analysis")
        if not isinstance(routine_analysis, dict):
            routine_analysis = {}
        state = {
            "resident_id": resident_id,
            "name": mini_dpi.get("resident_name") or profile.get("name") or resident_id,
            "room": mini_dpi.get("room") or profile.get("room"),
            "vitals": current.get("vitals", {}) or {},
            "movement": current.get("movement", {}) or {},
            "location": current.get("location"),
            "location_label": current.get("location"),
            "activity": current.get("activity"),
            "routine_analysis": routine_analysis,
            "ml_risk": (mini_dpi.get("risk", {}) or {}).get("ml_risk", 0),
            "prediction_30_60min": (mini_dpi.get("a2a_prediction", {}) or {}).get("prediction", {}),
        }
        fallback = _structured_fallback_report(
            resident_name=profile.get("name", resident_id),
            profile=profile,
            state=state,
            alerts_today=mini_dpi.get("alerts_today", []) or [],
            clinical_history=mini_dpi,
            source_note="rapport structure automatique avant generation LLM",
        )
        llm_result = {
            "resident_id": resident_id,
            "resident_name": profile.get("name", resident_id),
            "date": report_date,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "patient_profile": profile,
            "model": "rules+KB+ML:auto",
            "duration_ms": 0,
            "ml_risk": state.get("ml_risk", 0),
            "alerts_count_today": len(mini_dpi.get("alerts_today", []) or []),
            "report": fallback.model_dump(),
        }
        return self.store_medical_report_document(llm_result, mini_dpi)

    def alerts_for_resident(self, resident_id: str) -> list[dict]:
        alerts = []
        seen = set()
        for alert in self.alert_engine.get_history(100):
            if alert.get("resident_id") == resident_id:
                key = alert.get("id") or f"{alert.get('created_at')}:{alert.get('reason')}"
                seen.add(key)
                alerts.append(alert)
        for raw in self.redis.lrange("alerts:history", 0, 199):
            try:
                alert = json.loads(raw)
            except Exception:
                continue
            if alert.get("resident_id") != resident_id:
                continue
            key = alert.get("id") or f"{alert.get('created_at')}:{alert.get('reason')}"
            if key not in seen:
                seen.add(key)
                alerts.append(alert)
        return alerts[:100]

    async def get_llm_report(self, resident_id: str, force: bool = False) -> dict:
        report_date = self.local_report_date(None)
        if not force:
            cached = self.cached_daily(report_date, resident_id)
            if cached:
                mini_dpi = self.build_resident_daily_report(resident_id, report_date=report_date, force=False)
                cached.setdefault("patient_profile", self.profile_with_patient_file(resident_id, self.residents_map.get(resident_id, {})))
                document = self.get_medical_report_document(resident_id, report_date) or self.store_medical_report_document(cached, mini_dpi)
                cached["medical_document"] = self.medical_report_summary(document)
                cached["cached"] = True
                return cached

        raw = self.redis.get(f"resident:{resident_id}:state")
        state = json.loads(raw) if raw else self.safe_state_for_report(resident_id)
        profile = self.profile_with_patient_file(resident_id, self.residents_map.get(resident_id, {}))
        alerts_today = self.alerts_for_resident(resident_id)
        clinical_history = self.build_resident_daily_report(resident_id, report_date=report_date, force=False)

        result = await run_report_sync(
            resident_id=resident_id,
            resident_name=profile.get("name", resident_id),
            profile=profile,
            state=state,
            alerts_today=alerts_today,
            ollama_host=self.ollama_host,
            ollama_model=self.ollama_model,
            redis_client=self.redis,
            clinical_history=clinical_history,
        )
        result["date"] = report_date
        result["generated_at"] = datetime.utcnow().isoformat() + "Z"
        result["patient_profile"] = profile
        document = self.store_medical_report_document(result, clinical_history)
        result["medical_document"] = self.medical_report_summary(document)
        ttl = self.llm_daily_ttl_days * 86400
        self.redis.setex(self.daily_key(report_date, resident_id), ttl, json.dumps(result, ensure_ascii=False))
        self.redis.hset(self.daily_index_key(report_date), resident_id, json.dumps(result, ensure_ascii=False))
        self.redis.expire(self.daily_index_key(report_date), ttl)
        return result

    def start_llm_report(self, resident_id: str) -> dict:
        raw = self.redis.get(f"resident:{resident_id}:state")
        state = json.loads(raw) if raw else self.safe_state_for_report(resident_id)
        profile = self.residents_map.get(resident_id, {})
        alerts_today = self.alerts_for_resident(resident_id)
        clinical_history = self.build_resident_daily_report(resident_id, force=False)
        job_id = start_report_job(
            redis_client=self.redis,
            resident_id=resident_id,
            resident_name=profile.get("name", resident_id),
            profile=profile,
            state=state,
            alerts_today=alerts_today,
            ollama_host=self.ollama_host,
            ollama_model=self.ollama_model,
            clinical_history=clinical_history,
        )
        return {"job_id": job_id, "status": "pending", "resident_id": resident_id}

    def daily_reports(self, date: str) -> dict:
        report_date = self.local_report_date(date)
        raw_map = self.redis.hgetall(self.daily_index_key(report_date))
        reports = [json.loads(v) for v in raw_map.values()]
        reports.sort(key=lambda r: (r.get("report", {}).get("niveau_risque") == "eleve", r.get("ml_risk", 0)), reverse=True)
        return {
            "date": report_date,
            "count": len(reports),
            "expected": len(self.residents_map),
            "complete": len(reports) >= len(self.residents_map),
            "reports": reports,
        }

    async def daily_report_for_resident(self, date: str, resident_id: str, generate_if_missing: bool = True) -> dict:
        report_date = self.local_report_date(date)
        cached = self.cached_daily(report_date, resident_id)
        if cached:
            cached["cached"] = True
            return cached
        if not generate_if_missing:
            raise HTTPException(404, "Rapport LLM quotidien non genere")
        return await self.get_llm_report(resident_id, force=True)

    def result(self, job_id: str) -> dict:
        result = get_report_result(self.redis, job_id)
        if result.get("status") != "done":
            return result

        resident_id = result.get("resident_id")
        if not resident_id:
            return result

        report_date = self.local_report_date(None)
        result.setdefault("date", report_date)
        result.setdefault("generated_at", datetime.utcnow().isoformat() + "Z")
        result.setdefault("patient_profile", self.profile_with_patient_file(resident_id, self.residents_map.get(resident_id, {})))

        clinical_history = self.build_resident_daily_report(resident_id, report_date=report_date, force=False)
        document = self.store_medical_report_document(result, clinical_history)
        result["medical_document"] = self.medical_report_summary(document)

        ttl = self.llm_daily_ttl_days * 86400
        self.redis.setex(self.daily_key(report_date, resident_id), ttl, json.dumps(result, ensure_ascii=False))
        self.redis.hset(self.daily_index_key(report_date), resident_id, json.dumps(result, ensure_ascii=False))
        self.redis.expire(self.daily_index_key(report_date), ttl)
        self.redis.setex(f"llm:job:{job_id}", ttl, json.dumps(result, ensure_ascii=False))
        return result

    def audit(self) -> dict:
        raw_entries = self.redis.lrange("llm:audit", 0, 199)
        entries = [json.loads(entry) for entry in raw_entries]
        avg_ms = int(sum(entry.get("duration_ms", 0) for entry in entries) / len(entries)) if entries else 0
        return {"count": len(entries), "avg_duration_ms": avg_ms, "entries": entries}

    def daily_loop(self, run_on_main_loop: Callable, sleep_s: float = 300) -> None:
        if not self.llm_daily_auto_enabled:
            log.info("Rapport LLM quotidien automatique desactive")
            return
        last_attempt_date = None
        while True:
            try:
                today = self.local_report_date(None)
                lock_key = f"llm:daily:lock:{today}"
                if not self.redis.set(lock_key, "1", nx=True, ex=3600):
                    log.info("Rapport LLM quotidien deja pris en charge par un autre process")
                    time.sleep(sleep_s)
                    continue
                index_key = self.daily_index_key(today)
                generated = self.redis.hlen(index_key)
                if generated < len(self.residents_map) or last_attempt_date != today:
                    last_attempt_date = today
                    for resident_id in self.residents_map.keys():
                        if self.redis.exists(self.daily_key(today, resident_id)):
                            continue
                        try:
                            run_on_main_loop(self.get_llm_report(resident_id, force=False), timeout=180)
                            time.sleep(1.0)
                        except Exception as exc:
                            log.warning("Rapport LLM quotidien ignore pour %s: %s", resident_id, exc)
                    final_count = self.redis.hlen(index_key)
                    self.redis.setex(
                        f"llm:daily:v1:{today}:status",
                        self.llm_daily_ttl_days * 86400,
                        json.dumps({
                            "date": today,
                            "generated": final_count,
                            "expected": len(self.residents_map),
                            "complete": final_count >= len(self.residents_map),
                            "updated_at": datetime.utcnow().isoformat() + "Z",
                        }),
                    )
                    log.info("Rapports LLM quotidiens: %s/%s pour %s", final_count, len(self.residents_map), today)
            except Exception as exc:
                log.error("Rapport LLM quotidien loop error: %s", exc)
            time.sleep(sleep_s)
