import json
import time
from datetime import datetime
from typing import Callable


class ScalabilityService:
    def __init__(
        self,
        *,
        redis_client,
        started_at: float,
        mqtt_window,
        counters: Callable[[], dict],
        influx_sample_interval_s: float,
        ws_resident_min_interval_s: float,
    ) -> None:
        self.redis = redis_client
        self.started_at = started_at
        self.mqtt_window = mqtt_window
        self.counters = counters
        self.influx_sample_interval_s = influx_sample_interval_s
        self.ws_resident_min_interval_s = ws_resident_min_interval_s

    def metrics(self) -> dict:
        uptime = max(1.0, time.time() - self.started_at)
        now = time.time()
        counts = self.counters()
        residents_raw = self.redis.hgetall("residents:all")
        resident_count = len(residents_raw)
        target_messages_s = resident_count * 6
        while self.mqtt_window and now - self.mqtt_window[0][0] > 60:
            self.mqtt_window.popleft()
        mqtt_window = list(self.mqtt_window)
        window_total = len(mqtt_window)
        window_vitals = sum(1 for _, topic in mqtt_window if topic.endswith("/vitals"))
        window_ambient = sum(1 for _, topic in mqtt_window if "/ambient" in topic or "/door/" in topic)
        state_ages = []
        for raw in residents_raw.values():
            try:
                state = json.loads(raw)
                ts = state.get("timestamp")
                if ts:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    state_ages.append(max(0.0, now - dt.timestamp()))
            except Exception:
                pass
        max_state_age = max(state_ages) if state_ages else None
        avg_state_age = sum(state_ages) / len(state_ages) if state_ages else None
        theoretical_50 = 50 * 6
        actual_60s = window_total / 60
        last_mqtt_message_at = counts.get("last_mqtt_message_at")
        mqtt_message_count = counts.get("mqtt_message_count", 0)
        return {
            "uptime_s": round(uptime),
            "resident_count": resident_count,
            "scale_targets": {
                "current_residents_constants_s": target_messages_s,
                "target_20_residents_6_constants_s": 120,
                "target_50_residents_6_constants_s": theoretical_50,
                "current_vs_50_target_pct": round((actual_60s / theoretical_50) * 100, 1) if theoretical_50 else 0,
            },
            "mqtt": {
                "messages_total": mqtt_message_count,
                "messages_per_second_avg": round(mqtt_message_count / uptime, 2),
                "messages_per_second_60s": round(actual_60s, 2),
                "window_60s_total": window_total,
                "window_60s_vitals": window_vitals,
                "window_60s_ambient": window_ambient,
                "vitals_total": counts.get("mqtt_vitals_count", 0),
                "ambient_total": counts.get("mqtt_ambient_count", 0),
                "last_message_age_s": round(time.time() - last_mqtt_message_at, 1) if last_mqtt_message_at else None,
                "target_20_residents_6_constants_s": 120,
                "current_theoretical_constants_s": target_messages_s,
            },
            "backend": {
                "influx_sample_interval_s": self.influx_sample_interval_s,
                "ws_resident_min_interval_s": self.ws_resident_min_interval_s,
                "ws_push_total": counts.get("ws_push_count", 0),
                "ws_push_per_second_avg": round(counts.get("ws_push_count", 0) / uptime, 2),
                "estimated_influx_points_per_second": round(resident_count / max(self.influx_sample_interval_s, 0.1), 2),
                "estimated_ws_states_per_second": round(resident_count / max(self.ws_resident_min_interval_s, 0.1), 2),
                "state_age_avg_s": round(avg_state_age, 1) if avg_state_age is not None else None,
                "state_age_max_s": round(max_state_age, 1) if max_state_age is not None else None,
            },
            "prediction": {
                "refresh_interval_s": 300,
                "cache_ttl_s": 600,
                "llm_policy": "LLM hors boucle seconde; ML/A2A toutes les 5 minutes",
            },
            "pro_recommendations": [
                "tester NUM_RESIDENTS=50",
                "surveiller p95 latence API/WebSocket",
                "alerter si last_message_age_s > 10s pour un capteur critique",
                "conserver InfluxDB pour historique et Redis pour etat courant",
            ],
        }
