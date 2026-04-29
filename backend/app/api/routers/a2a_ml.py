import json

from fastapi import APIRouter, Header, HTTPException, Request

from app.core.runtime import runtime as rt

router = APIRouter(tags=["A2A / ML"])


@router.get("/api/a2a/agents")
def get_a2a_agents():
    return rt.agent_card()


@router.get("/api/a2a/predict/{resident_id}")
def get_a2a_prediction(
    resident_id: str,
    request: Request,
    authorization: str = Header(None),
    x_break_glass_reason: str = Header(None),
):
    rt.require_resident_access(resident_id, authorization, request, "resident_a2a_prediction", x_break_glass_reason)
    if resident_id not in rt.residents_map:
        raise HTTPException(404, "Resident non trouve")
    cached = rt.redis_client.get(f"a2a:prediction:{resident_id}")
    if cached:
        data = json.loads(cached)
        data["source"] = "auto_refresh_5min"
        return data
    state = rt.safe_state_for_report(resident_id)
    hist = rt.history_summary(resident_id)
    active_alert = rt.active_alert_for_resident(resident_id)
    return rt.a2a_prediction_for_resident(state, hist, active_alert=active_alert)


@router.get("/api/a2a/predictions")
def get_a2a_predictions():
    cached = rt.redis_client.get("a2a:predictions:all")
    if cached:
        data = json.loads(cached)
        data["source"] = "auto_refresh_5min"
        return data
    predictions = []
    for resident_id in rt.residents_map.keys():
        state = rt.safe_state_for_report(resident_id)
        hist = rt.history_summary(resident_id)
        active_alert = rt.active_alert_for_resident(resident_id)
        pred = rt.a2a_prediction_for_resident(state, hist, active_alert=active_alert)["prediction"]
        predictions.append({
            "resident_id": resident_id,
            "resident_name": state.get("resident_name") or state.get("name"),
            "room": state.get("room"),
            "location": state.get("current_zone") or state.get("zone"),
            **pred,
        })
    predictions.sort(key=lambda p: (p["recommended_level"], p["risk_60min"], p["risk_30min"]), reverse=True)
    return {"count": len(predictions), "predictions": predictions}


@router.get("/api/ml/metrics")
def get_ml_metrics():
    """Metriques de performance du modele ML."""
    if not rt.ml_predictor.metrics:
        return {"status": "model_loaded_from_disk", "metrics": {}}
    return {"status": "ok", "metrics": rt.ml_predictor.metrics}


@router.get("/api/alerts/elopement")
def get_elopement_alerts():
    alerts = rt.redis_client.lrange("alerts:elopement", 0, 20)
    return {"alerts": [json.loads(alert) for alert in alerts]}


@router.get("/api/residents/{resident_id}/routine")
def get_resident_routine(
    resident_id: str,
    request: Request,
    authorization: str = Header(None),
    x_break_glass_reason: str = Header(None),
):
    """Analyse comportementale C4 - baseline multi-signaux par periode."""
    rt.require_resident_access(resident_id, authorization, request, "resident_routine_view", x_break_glass_reason)
    if resident_id not in rt.residents_map:
        raise HTTPException(404, "Resident non trouve")
    summary = rt.get_routine_summary(rt.redis_client, resident_id)
    summary["name"] = rt.residents_map[resident_id].get("name")
    return summary
