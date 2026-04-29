"""
Facade de compatibilite pour le service LLM.

La logique est decoupee dans app/services/llm/. Les imports historiques depuis
llm_service restent supportes pour le backend, les jobs et les tests.
"""

from app.services.llm.client import get_report_result, run_report_sync, start_report_job
from app.services.llm.kb_context import (
    _profile_antecedent_kb_links,
    build_kb_context,
)
from app.services.llm.models import LLMReport
from app.services.llm.parser import parse_llm_output
from app.services.llm.prompts import build_prompt
from app.services.llm.report_builder import _risk_level, _structured_fallback_report

__all__ = [
    "LLMReport",
    "_profile_antecedent_kb_links",
    "_risk_level",
    "_structured_fallback_report",
    "build_kb_context",
    "build_prompt",
    "get_report_result",
    "parse_llm_output",
    "run_report_sync",
    "start_report_job",
]
