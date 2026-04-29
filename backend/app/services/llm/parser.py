import json
from typing import Any

from pydantic import ValidationError

from app.services.llm.models import LLMReport
from app.services.llm.kb_context import (
    _allowed_source_ids,
    _fall_detected,
    _filter_partial_sources,
    _filter_source_list,
    _human_action,
    _human_signal,
)
from app.services.llm.report_builder import _structured_fallback_report


def _extract_json_block(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        return text[start:end]
    return text

def parse_llm_output(
    raw: str,
    resident_name: str,
    profile: dict,
    state: dict,
    alerts_today: list[dict],
    clinical_history: dict | None = None,
    source_note: str = "",
) -> LLMReport:
    try:
        data = json.loads(_extract_json_block(raw))
        data = _filter_partial_sources(data, _allowed_source_ids(profile, state, alerts_today))
        report = LLMReport(**data)
        fallback = _structured_fallback_report(resident_name, profile, state, alerts_today, clinical_history=clinical_history, source_note="analyse structuree completee automatiquement")
        merged = fallback.model_dump()
        merged.update({k: v for k, v in report.model_dump().items() if v not in (None, [], {})})
        allowed_sources = _allowed_source_ids(profile, state, alerts_today)
        if report.sources_kb and fallback.sources_kb:
            merged["sources_kb"] = _filter_source_list(list(dict.fromkeys(report.sources_kb + fallback.sources_kb)), allowed_sources)
        merged = _filter_partial_sources(merged, allowed_sources)
        return LLMReport(**merged)
    except (json.JSONDecodeError, ValidationError, Exception):
        return _structured_fallback_report(resident_name, profile, state, alerts_today, clinical_history=clinical_history, source_note=source_note or "sortie LLM invalide, repli clinique structure")

def _json_from_llm_text(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(_extract_json_block(raw))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _normalize_risk_label(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    cleaned = (
        value.strip().lower()
        .replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("ë", "e")
        .replace("à", "a")
        .replace("ù", "u")
    )
    aliases = {
        "bas": "faible",
        "basse": "faible",
        "low": "faible",
        "moyen": "modere",
        "moyenne": "modere",
        "moderee": "modere",
        "modere": "modere",
        "moderate": "modere",
        "haut": "eleve",
        "haute": "eleve",
        "elevee": "eleve",
        "eleve": "eleve",
        "high": "eleve",
    }
    return aliases.get(cleaned, cleaned)

def _normalize_check_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    prefixes = ("Rechercher/valider:", "Verifier cliniquement:", "A verifier:")
    for prefix in prefixes:
        if text.startswith(prefix):
            raw = text[len(prefix):].strip()
            return f"Verifier cliniquement: {_human_signal(raw)}"
    if "_" in text and len(text.split()) <= 4:
        return f"Verifier cliniquement: {_human_signal(text)}"
    return text

def _normalize_action_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return _human_action(text)

def _max_risk_label(left: Any, right: Any) -> str:
    order = {"faible": 0, "modere": 1, "eleve": 2}
    left_norm = _normalize_risk_label(left)
    right_norm = _normalize_risk_label(right)
    if order.get(str(right_norm), -1) > order.get(str(left_norm), -1):
        return str(right_norm)
    return str(left_norm if left_norm in order else right_norm if right_norm in order else "faible")

def _normalize_report_partial(partial: dict[str, Any]) -> dict[str, Any]:
    if "niveau_risque" in partial:
        partial["niveau_risque"] = _normalize_risk_label(partial.get("niveau_risque"))
    if isinstance(partial.get("donnees_a_verifier"), list):
        partial["donnees_a_verifier"] = [
            item for item in (_normalize_check_text(v) for v in partial["donnees_a_verifier"]) if item
        ]
    for field in ("actions_prioritaires", "conduite_a_tenir_kb"):
        if isinstance(partial.get(field), list):
            normalized = []
            for item in partial[field]:
                if isinstance(item, dict):
                    item = dict(item)
                    if "action" in item:
                        item["action"] = _normalize_action_text(item.get("action"))
                    normalized.append(item)
                else:
                    normalized.append(_normalize_action_text(item))
            partial[field] = normalized
    if isinstance(partial.get("hypotheses"), list):
        normalized_hypotheses = []
        for item in partial["hypotheses"]:
            if isinstance(item, dict):
                item = dict(item)
                if isinstance(item.get("a_verifier"), list):
                    item["a_verifier"] = [
                        check for check in (_normalize_check_text(v) for v in item["a_verifier"]) if check
                    ]
                if isinstance(item.get("conduite_soignant"), list):
                    item["conduite_soignant"] = [
                        action for action in (_normalize_action_text(v) for v in item["conduite_soignant"]) if action
                    ]
            normalized_hypotheses.append(item)
        partial["hypotheses"] = normalized_hypotheses
    return partial

def _sanitize_fast_summary(partial: dict[str, Any], state: dict) -> dict[str, Any]:
    if not isinstance(partial, dict):
        return {}
    partial = dict(partial)
    if _fall_detected(state):
        return partial

    fall_tokens = ("chute", "fall", "traumatisme")
    for field in ("resume", "synthese_clinique", "message_famille"):
        value = partial.get(field)
        if isinstance(value, str) and any(token in value.lower() for token in fall_tokens):
            partial.pop(field, None)
            continue
        if isinstance(value, str):
            lowered = value.lower()
            if ("fréquence cardiaque" in lowered or "frequence cardiaque" in lowered or "fc" in lowered) and "mmhg" in lowered:
                partial.pop(field, None)
    for field in ("points_vigilance", "actions_soignants"):
        values = partial.get(field)
        if isinstance(values, list):
            partial[field] = [
                item for item in values
                if not any(token in str(item).lower() for token in fall_tokens)
            ]
    return partial

def _summary_is_specific(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    return any(token in lowered for token in ("spo2", "fc", "pa", "risque", "alerte", "chute", "temp", "%", "news"))

def _merge_report_from_partial(base: LLMReport, partial: dict[str, Any], allowed_sources: set[str] | None = None) -> LLMReport:
    partial = _filter_partial_sources(partial, allowed_sources)
    partial = _normalize_report_partial(dict(partial))
    merged = base.model_dump()
    allowed = set(merged.keys())
    merge_list_fields = {
        "preuves",
        "hypotheses",
        "actions_prioritaires",
        "plan_surveillance",
        "complications_possibles",
        "donnees_a_verifier",
        "conduite_a_tenir_kb",
        "points_vigilance",
        "actions_soignants",
        "incertitudes",
    }
    for key, value in partial.items():
        if key not in allowed or value in (None, "", [], {}):
            continue
        if key in {"resume", "synthese_clinique"} and not _summary_is_specific(value):
            continue
        if key in merge_list_fields and isinstance(merged.get(key), list) and isinstance(value, list):
            combined: list[Any] = []
            seen: set[str] = set()
            deterministic_first = {
                "hypotheses",
                "actions_prioritaires",
                "plan_surveillance",
                "donnees_a_verifier",
                "conduite_a_tenir_kb",
            }
            ordered_items = (
                [*merged.get(key, []), *value]
                if key in deterministic_first
                else [*value, *merged.get(key, [])]
            )
            for item in ordered_items:
                marker = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, (dict, list)) else str(item)
                if marker in seen:
                    continue
                seen.add(marker)
                combined.append(item)
            limits = {
                "preuves": 8,
                "hypotheses": 6,
                "actions_prioritaires": 12,
                "plan_surveillance": 8,
                "complications_possibles": 8,
                "donnees_a_verifier": 16,
                "conduite_a_tenir_kb": 16,
                "points_vigilance": 10,
                "actions_soignants": 8,
                "incertitudes": 6,
            }
            merged[key] = combined[:limits.get(key, 10)]
        elif isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = value
        elif key == "niveau_risque":
            merged[key] = _max_risk_label(merged.get(key), value)
        elif not isinstance(merged.get(key), (list, dict)):
            merged[key] = value
    if base.sources_kb and isinstance(partial.get("sources_kb"), list):
        merged["sources_kb"] = list(dict.fromkeys([*partial["sources_kb"], *base.sources_kb]))
    if allowed_sources:
        merged["sources_kb"] = _filter_source_list(merged.get("sources_kb"), allowed_sources)
    return LLMReport(**merged)
