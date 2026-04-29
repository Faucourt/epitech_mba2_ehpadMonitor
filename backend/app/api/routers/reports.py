from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request

from app.core.runtime import runtime as rt

router = APIRouter(tags=["Reports"])


@router.post("/api/reports/daily/generate")
def generate_daily_report(date: Optional[str] = None, force: bool = False):
    """Genere et stocke la fiche de transmission quotidienne globale."""
    report_date = rt.local_report_date(date)
    report = rt.build_global_daily_report(report_date, force=force)
    return {"ok": True, "date": report_date, "report": report}


@router.get("/api/reports/today")
def get_today_report():
    report_date = rt.local_report_date()
    return rt.build_global_daily_report(report_date, force=False)


@router.get("/api/reports/daily/{date}")
def get_daily_report(date: str):
    return rt.build_global_daily_report(date, force=False)


@router.get("/api/reports/daily/{date}/{resident_id}")
def get_daily_resident_report(date: str, resident_id: str):
    if resident_id not in rt.residents_map:
        raise HTTPException(404, "Resident non trouve")
    return rt.build_resident_daily_report(resident_id, report_date=date, force=True)


@router.get("/api/residents/{resident_id}/dpi")
def get_resident_dpi(
    resident_id: str,
    request: Request,
    date: Optional[str] = None,
    authorization: str = Header(None),
    x_break_glass_reason: str = Header(None),
):
    """Mini DPI: profil, constantes, alertes, historique 30 jours et risque a venir."""
    rt.require_resident_access(resident_id, authorization, request, "resident_mini_dpi", x_break_glass_reason)
    if resident_id not in rt.residents_map:
        raise HTTPException(404, "Resident non trouve")
    report_date = rt.local_report_date(date)
    mini_dpi = rt.build_resident_daily_report(resident_id, report_date=report_date, force=True)
    medical_document = rt.ensure_medical_report_document(resident_id, report_date, mini_dpi)
    return {
        "resident_id": resident_id,
        "date": report_date,
        "mini_dpi": mini_dpi,
        "medical_document": medical_document,
    }


@router.get("/api/residents/{resident_id}/medical-reports/latest")
def get_latest_resident_medical_report(
    resident_id: str,
    request: Request,
    authorization: str = Header(None),
    x_break_glass_reason: str = Header(None),
):
    rt.require_resident_access(resident_id, authorization, request, "resident_medical_report", x_break_glass_reason)
    if resident_id not in rt.residents_map:
        raise HTTPException(404, "Resident non trouve")
    document = rt.get_medical_report_document(resident_id)
    if not document:
        raise HTTPException(404, "Rapport medical structure non genere")
    return document


@router.get("/api/residents/{resident_id}/medical-reports/{date}")
def get_resident_medical_report_by_date(
    resident_id: str,
    date: str,
    request: Request,
    authorization: str = Header(None),
    x_break_glass_reason: str = Header(None),
):
    rt.require_resident_access(resident_id, authorization, request, "resident_medical_report", x_break_glass_reason)
    if resident_id not in rt.residents_map:
        raise HTTPException(404, "Resident non trouve")
    document = rt.get_medical_report_document(resident_id, date)
    if not document:
        raise HTTPException(404, "Rapport medical structure non genere pour cette date")
    return document
