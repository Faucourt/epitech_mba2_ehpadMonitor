import asyncio
import json
import logging
import os
import secrets
import time
from typing import Any

import httpx

from app.services.llm.models import LLMReport
from app.services.llm.kb_context import build_kb_context
from app.services.llm.parser import (
    _json_from_llm_text,
    _merge_report_from_partial,
    _sanitize_fast_summary,
    parse_llm_output,
)
from app.services.llm.prompts import (
    _build_clinical_router_prompt,
    _build_fast_summary_prompt,
    build_prompt,
)
from app.services.llm.report_builder import _structured_fallback_report

log = logging.getLogger(__name__)


_JOB_TTL = 3600

LLM_ROUTING_ENABLED = os.getenv("LLM_ROUTING_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}

LLM_FAST_MODEL = os.getenv("LLM_FAST_MODEL", "llama3.2:3b")

LLM_CLINICAL_MODEL = os.getenv("LLM_CLINICAL_MODEL", "qwen2.5:7b")

LLM_MEDICAL_MODEL = os.getenv("LLM_MEDICAL_MODEL", "meditron:7b")

async def _call_ollama(ollama_host: str, model: str, prompt: str, timeout_s: float = 90.0) -> tuple[str, float]:
    return await _call_ollama_limited(ollama_host, model, prompt, timeout_s=timeout_s)

async def _call_ollama_limited(
    ollama_host: str,
    model: str,
    prompt: str,
    timeout_s: float = 90.0,
    num_predict: int = 900,
    temperature: float = 0.1,
) -> tuple[str, float]:
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(
            f"{ollama_host}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": temperature,
                    "num_predict": num_predict,
                },
            },
        )
        resp.raise_for_status()
        text = resp.json().get("response", "").strip()
    return text, time.monotonic() - t0

def _build_result(
    job_id: str | None,
    resident_id: str,
    resident_name: str,
    report: LLMReport,
    source: str,
    duration_ms: int,
    state: dict,
    alerts_today: list[dict],
    clinical_history: dict | None,
    kb_ctx: str,
) -> dict:
    result = {
        "resident_id": resident_id,
        "resident_name": resident_name,
        "report": report.model_dump(),
        "model": source,
        "duration_ms": duration_ms,
        "ml_risk": round(float(state.get("ml_risk", 0) or 0), 2),
        "alerts_count_today": len(alerts_today),
        "kb_context_injected": bool(kb_ctx),
        "scenario_kb_links": scenario_kb_links_for_state(state)[:12],
        "rag_enabled": True,
        "clinical_decision_support": True,
        "uses_patient_history": bool(clinical_history),
    }
    if job_id:
        result["status"] = "done"
        result["job_id"] = job_id
    return result

async def _generate_report_core(
    resident_id: str,
    resident_name: str,
    profile: dict,
    state: dict,
    alerts_today: list[dict],
    ollama_host: str,
    ollama_model: str,
    clinical_history: dict | None = None,
) -> tuple[LLMReport, str, int, str]:
    pathologies = profile.get("pathologies", [])
    archetype_id = profile.get("archetype_id", "ARCH_NUTRITION")
    ml_risk = float(state.get("ml_risk", 0) or 0)
    alert_level = max((int(a.get("level", 0) or 0) for a in alerts_today), default=0)
    kb_ctx = build_kb_context(pathologies, archetype_id, ml_risk, alert_level, state=state, profile=profile)

    if LLM_ROUTING_ENABLED:
        return await _generate_report_core_routed(
            resident_id=resident_id,
            resident_name=resident_name,
            profile=profile,
            state=state,
            alerts_today=alerts_today,
            ollama_host=ollama_host,
            ollama_model=ollama_model,
            clinical_history=clinical_history,
            kb_ctx=kb_ctx,
        )

    prompt = build_prompt(profile, state, alerts_today, kb_ctx, clinical_history=clinical_history)

    source = ollama_model
    duration_ms = 0
    raw_text = ""
    source_note = ""
    try:
        raw_text, duration_s = await _call_ollama(ollama_host, ollama_model, prompt)
        duration_ms = int(duration_s * 1000)
        log.info("LLM report %s - %s ms - prompt %s chars", resident_id, duration_ms, len(prompt))
    except Exception as exc:
        log.warning("LLM Ollama indisponible pour %s: %s", resident_id, exc)
        source = "fallback structure (Ollama indisponible)"
        source_note = "Ollama indisponible"

    report = parse_llm_output(raw_text, resident_name, profile, state, alerts_today, clinical_history=clinical_history, source_note=source_note)
    return report, source, duration_ms, kb_ctx

async def _generate_report_core_routed(
    resident_id: str,
    resident_name: str,
    profile: dict,
    state: dict,
    alerts_today: list[dict],
    ollama_host: str,
    ollama_model: str,
    clinical_history: dict | None,
    kb_ctx: str,
) -> tuple[LLMReport, str, int, str]:
    base = _structured_fallback_report(
        resident_name,
        profile,
        state,
        alerts_today,
        clinical_history=clinical_history,
        source_note="base deterministe completee par routage LLM",
    )
    report = base
    duration_ms = 0
    used_models: list[str] = []
    failed_models: list[str] = []
    trace_steps: list[dict[str, Any]] = []
    allowed_sources = _allowed_source_ids(profile, state, alerts_today)

    fast_model = LLM_FAST_MODEL or ollama_model
    clinical_model = LLM_CLINICAL_MODEL or ollama_model
    medical_model = LLM_MEDICAL_MODEL or ollama_model

    fast_prompt = _build_fast_summary_prompt(resident_name, profile, state, alerts_today, clinical_history)
    try:
        raw_fast, fast_duration = await _call_ollama_limited(
            ollama_host,
            fast_model,
            fast_prompt,
            timeout_s=50.0,
            num_predict=420,
            temperature=0.1,
        )
        duration_ms += int(fast_duration * 1000)
        fast_data = _json_from_llm_text(raw_fast)
        fast_data = _sanitize_fast_summary(fast_data, state)
        report = _merge_report_from_partial(report, fast_data, allowed_sources=allowed_sources)
        used_models.append(f"fast={fast_model}")
        trace_steps.append({
            "agent": "Synthese rapide",
            "model": fast_model,
            "role": "Resume soignant, points de vigilance courts, message famille",
            "status": "ok",
            "duration_ms": int(fast_duration * 1000),
            "fields": sorted([k for k in fast_data.keys() if k in {"resume", "synthese_clinique", "points_vigilance", "actions_soignants", "message_famille"}]),
        })
        log.info("LLM fast summary %s - %s ms - prompt %s chars", resident_id, int(fast_duration * 1000), len(fast_prompt))
    except Exception as exc:
        failed_models.append(f"fast={fast_model}")
        trace_steps.append({
            "agent": "Synthese rapide",
            "model": fast_model,
            "role": "Resume soignant, points de vigilance courts, message famille",
            "status": "failed",
            "error": str(exc)[:180],
        })
        log.warning("LLM fast indisponible pour %s (%s): %s", resident_id, fast_model, exc)

    clinical_prompt = _build_clinical_router_prompt(profile, state, alerts_today, kb_ctx, clinical_history)
    try:
        raw_clinical, clinical_duration = await _call_ollama_limited(
            ollama_host,
            clinical_model,
            clinical_prompt,
            timeout_s=95.0,
            num_predict=950,
            temperature=0.05,
        )
        duration_ms += int(clinical_duration * 1000)
        clinical_data = _json_from_llm_text(raw_clinical)
        report = _merge_report_from_partial(report, clinical_data, allowed_sources=allowed_sources)
        used_models.append(f"clinical={clinical_model}")
        trace_steps.append({
            "agent": "Analyse clinique KB",
            "model": clinical_model,
            "role": "Hypotheses differentielles, conduite a tenir, surveillance, sources KB",
            "status": "ok",
            "duration_ms": int(clinical_duration * 1000),
            "fields": sorted([k for k in clinical_data.keys() if k in {"niveau_risque", "hypotheses", "actions_prioritaires", "donnees_a_verifier", "conduite_a_tenir_kb", "sources_kb"}]),
        })
        log.info("LLM clinical %s - %s ms - prompt %s chars", resident_id, int(clinical_duration * 1000), len(clinical_prompt))
    except Exception as exc:
        failed_models.append(f"clinical={clinical_model}")
        trace_steps.append({
            "agent": "Analyse clinique KB",
            "model": clinical_model,
            "role": "Hypotheses differentielles, conduite a tenir, surveillance, sources KB",
            "status": "failed",
            "error": str(exc)[:180],
        })
        log.warning("LLM clinique indisponible pour %s (%s): %s", resident_id, clinical_model, exc)

    if not used_models and medical_model not in {fast_model, clinical_model}:
        prompt = build_prompt(profile, state, alerts_today, kb_ctx, clinical_history=clinical_history)
        try:
            raw_medical, medical_duration = await _call_ollama_limited(
                ollama_host,
                medical_model,
                prompt,
                timeout_s=95.0,
                num_predict=1300,
                temperature=0.05,
            )
            duration_ms += int(medical_duration * 1000)
            report = parse_llm_output(
                raw_medical,
                resident_name,
                profile,
                state,
                alerts_today,
                clinical_history=clinical_history,
                source_note="",
            )
            used_models.append(f"medical={medical_model}")
            trace_steps.append({
                "agent": "Rapport medical complet",
                "model": medical_model,
                "role": "Fallback complet quand les agents specialises ne suffisent pas",
                "status": "ok",
                "duration_ms": int(medical_duration * 1000),
                "fields": ["rapport complet LLMReport"],
            })
            log.info("LLM medical fallback %s - %s ms - prompt %s chars", resident_id, int(medical_duration * 1000), len(prompt))
        except Exception as exc:
            failed_models.append(f"medical={medical_model}")
            trace_steps.append({
                "agent": "Rapport medical complet",
                "model": medical_model,
                "role": "Fallback complet quand les agents specialises ne suffisent pas",
                "status": "failed",
                "error": str(exc)[:180],
            })
            log.warning("LLM medical indisponible pour %s (%s): %s", resident_id, medical_model, exc)

    if used_models:
        source = "router(" + ", ".join(used_models) + ")"
        if failed_models:
            source += " + fallback partiel"
    else:
        source = "fallback structure (routage LLM indisponible: " + ", ".join(failed_models or ["aucun modele"]) + ")"
    trace_steps.insert(0, {
        "agent": "Base deterministe",
        "model": "rules+KB+ML",
        "role": "Garantit un rapport minimal avec constantes, alertes, historique et KB meme sans LLM",
        "status": "ok",
        "fields": ["preuves", "hypotheses", "actions_prioritaires", "conduite_a_tenir_kb"],
    })
    merged = _filter_partial_sources(report.model_dump(), allowed_sources)
    merged["sources_kb"] = _filter_source_list(merged.get("sources_kb"), allowed_sources)
    merged["llm_trace"] = {
        "routing_enabled": True,
        "source": source,
        "steps": trace_steps,
        "failed_models": failed_models,
    }
    report = LLMReport(**merged)
    return report, source, duration_ms, kb_ctx

async def _generate_and_store(
    job_id: str,
    resident_id: str,
    resident_name: str,
    profile: dict,
    state: dict,
    alerts_today: list[dict],
    clinical_history: dict | None,
    ollama_host: str,
    ollama_model: str,
    redis_client,
) -> None:
    report, source, duration_ms, kb_ctx = await _generate_report_core(
        resident_id, resident_name, profile, state, alerts_today, ollama_host, ollama_model, clinical_history=clinical_history
    )
    result = _build_result(job_id, resident_id, resident_name, report, source, duration_ms, state, alerts_today, clinical_history, kb_ctx)
    redis_client.setex(f"llm:job:{job_id}", _JOB_TTL, json.dumps(result, ensure_ascii=False))
    _audit(redis_client, resident_id, source, duration_ms, report)

def _audit(redis_client, resident_id: str, source: str, duration_ms: int, report: LLMReport, job_id: str | None = None) -> None:
    audit = {
        "job_id": job_id,
        "resident_id": resident_id,
        "model": source,
        "duration_ms": duration_ms,
        "niveau_risque": report.niveau_risque,
        "preuves": len(report.preuves),
        "ts": time.time(),
    }
    redis_client.lpush("llm:audit", json.dumps(audit, ensure_ascii=False))
    redis_client.ltrim("llm:audit", 0, 199)

def start_report_job(
    redis_client,
    resident_id: str,
    resident_name: str,
    profile: dict,
    state: dict,
    alerts_today: list[dict],
    ollama_host: str,
    ollama_model: str,
    clinical_history: dict | None = None,
) -> str:
    job_id = secrets.token_hex(10)
    redis_client.setex(
        f"llm:job:{job_id}",
        _JOB_TTL,
        json.dumps({"status": "pending", "job_id": job_id, "resident_id": resident_id}),
    )
    asyncio.create_task(
        _generate_and_store(
            job_id, resident_id, resident_name, profile, state, alerts_today,
            clinical_history, ollama_host, ollama_model, redis_client,
        )
    )
    return job_id

def get_report_result(redis_client, job_id: str) -> dict:
    raw = redis_client.get(f"llm:job:{job_id}")
    if not raw:
        return {"status": "not_found", "job_id": job_id}
    return json.loads(raw)

async def run_report_sync(
    resident_id: str,
    resident_name: str,
    profile: dict,
    state: dict,
    alerts_today: list[dict],
    ollama_host: str,
    ollama_model: str,
    redis_client=None,
    clinical_history: dict | None = None,
) -> dict:
    report, source, duration_ms, kb_ctx = await _generate_report_core(
        resident_id, resident_name, profile, state, alerts_today, ollama_host, ollama_model, clinical_history=clinical_history
    )
    result = _build_result(None, resident_id, resident_name, report, source, duration_ms, state, alerts_today, clinical_history, kb_ctx)
    if redis_client:
        _audit(redis_client, resident_id, source, duration_ms, report)
    return result
