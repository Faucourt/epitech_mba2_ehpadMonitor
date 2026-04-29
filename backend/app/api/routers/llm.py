from fastapi import APIRouter

from app.core.runtime import runtime as rt

router = APIRouter(tags=["LLM"])


@router.get("/api/llm/report/{resident_id}")
async def get_llm_report(resident_id: str, force: bool = False):
    """
    Rapport LLM quotidien - synchrone, attend le resultat.
    RAG KB clinique, sortie JSON structuree, suivi latence.
    """
    return await rt.llm_report_service.get_llm_report(resident_id, force=force)


@router.post("/api/llm/report/{resident_id}/start")
async def start_llm_report(resident_id: str):
    """
    Lance la generation LLM en arriere-plan, retourne un job_id immediatement.
    Utiliser GET /api/llm/result/{job_id} pour recuperer le resultat.
    """
    return rt.llm_report_service.start_llm_report(resident_id)


@router.get("/api/llm/daily/{date}")
async def get_daily_llm_reports(date: str):
    return rt.llm_report_service.daily_reports(date)


@router.get("/api/llm/daily/{date}/{resident_id}")
async def get_daily_llm_report_for_resident(date: str, resident_id: str, generate_if_missing: bool = True):
    return await rt.llm_report_service.daily_report_for_resident(date, resident_id, generate_if_missing)


@router.get("/api/llm/result/{job_id}")
async def get_llm_result(job_id: str):
    """Resultat d'un job LLM lance via /start - retourne pending ou done."""
    return rt.llm_report_service.result(job_id)


@router.get("/api/llm/audit")
async def get_llm_audit():
    """Historique des 200 derniers appels LLM : latence, modele, niveau risque."""
    return rt.llm_report_service.audit()
