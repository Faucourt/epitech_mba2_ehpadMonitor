import asyncio
import json
import logging
import time
from datetime import datetime


log = logging.getLogger(__name__)


class SchedulerService:
    def __init__(
        self,
        *,
        redis_client,
        residents_map: dict,
        alert_engine,
        ws_manager,
        push_service,
        local_report_date,
        build_global_daily_report,
        safe_state_for_report,
        history_summary,
        active_alert_for_resident,
        a2a_prediction_for_resident,
        remember_prediction,
        llm_report_service,
        loop_getter,
        run_on_main_loop,
    ) -> None:
        self.redis = redis_client
        self.residents_map = residents_map
        self.alert_engine = alert_engine
        self.ws_manager = ws_manager
        self.push_service = push_service
        self.local_report_date = local_report_date
        self.build_global_daily_report = build_global_daily_report
        self.safe_state_for_report = safe_state_for_report
        self.history_summary = history_summary
        self.active_alert_for_resident = active_alert_for_resident
        self.a2a_prediction_for_resident = a2a_prediction_for_resident
        self.remember_prediction = remember_prediction
        self.llm_report_service = llm_report_service
        self.loop_getter = loop_getter
        self.run_on_main_loop = run_on_main_loop
        self.last_daily_report_date = None

    def daily_report_loop(self) -> None:
        while True:
            try:
                today = self.local_report_date(None)
                existing = self.redis.get(f"daily_report:v8:{today}:global")
                if today != self.last_daily_report_date and not existing:
                    self.build_global_daily_report(today, force=False)
                    self.last_daily_report_date = today
                    log.info("Rapport quotidien automatise genere pour %s", today)
            except Exception as exc:
                log.error("Rapport quotidien error: %s", exc)
            time.sleep(300)

    def predictive_analysis_loop(self) -> None:
        while True:
            try:
                predictions = []
                for resident_id in self.residents_map.keys():
                    state = self.safe_state_for_report(resident_id)
                    hist = self.history_summary(resident_id)
                    active_alert = self.active_alert_for_resident(resident_id)
                    result = self.a2a_prediction_for_resident(state, hist, active_alert=active_alert)
                    self.remember_prediction(resident_id, result)
                    self.redis.setex(f"a2a:prediction:{resident_id}", 600, json.dumps(result))
                    pred = result["prediction"]
                    predictions.append({
                        "resident_id": resident_id,
                        "resident_name": state.get("resident_name") or state.get("name"),
                        "room": state.get("room"),
                        "location": state.get("current_zone") or state.get("zone"),
                        **pred,
                    })
                predictions.sort(key=lambda item: (item["recommended_level"], item["risk_60min"], item["risk_30min"]), reverse=True)
                payload = {
                    "generated_at": datetime.utcnow().isoformat() + "Z",
                    "refresh_interval_s": 300,
                    "count": len(predictions),
                    "predictions": predictions,
                }
                self.redis.setex("a2a:predictions:all", 600, json.dumps(payload))
                log.info("Analyse predictive ML/A2A 30-60 min relancee pour tous les residents")
            except Exception as exc:
                log.error("Analyse predictive loop error: %s", exc)
            time.sleep(300)

    def escalation_loop(self) -> None:
        while True:
            try:
                escalated = self.alert_engine.check_escalations()
                loop = self.loop_getter()
                for alert_dict in escalated:
                    if loop and not loop.is_closed():
                        if int(alert_dict.get("level") or 0) >= 2 and self.push_service.enabled:
                            asyncio.run_coroutine_threadsafe(
                                self.push_service.dispatch_alert_push_async(alert_dict),
                                loop,
                            )
                        asyncio.run_coroutine_threadsafe(
                            self.ws_manager.send_alert(alert_dict),
                            loop,
                        )
            except Exception as exc:
                log.error("Escalade error: %s", exc)
            time.sleep(15)

    def daily_llm_report_loop(self) -> None:
        self.llm_report_service.daily_loop(self.run_on_main_loop)
