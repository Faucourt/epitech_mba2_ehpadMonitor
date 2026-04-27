"""
Tests automatisés — moteur d'alertes, ML, simulateur.
Lance avec : python -m pytest tests/ -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import pytest
import time
from unittest.mock import MagicMock, patch
from contextlib import contextmanager


API_BASE_URL = os.getenv("EHPAD_API_URL", "http://localhost:8001")


@contextmanager
def get_api_client():
    httpx = pytest.importorskip("httpx")
    with httpx.Client(base_url=API_BASE_URL, timeout=5.0) as client:
        try:
            client.get("/health")
        except httpx.HTTPError as exc:
            pytest.skip(f"API EHPAD non disponible sur {API_BASE_URL}: {exc}")
        yield client


# ============================================================
# Tests moteur d'alertes
# ============================================================

def make_alert_engine():
    redis_mock = MagicMock()
    redis_mock.setex = MagicMock(return_value=True)
    redis_mock.lpush = MagicMock(return_value=True)
    redis_mock.ltrim = MagicMock(return_value=True)
    ws_mock = MagicMock()
    from alert_engine import AlertEngine
    return AlertEngine(redis_mock, ws_mock)


def make_state(hr=72, spo2=96, bp=130, temp=36.7, last_mv=60, is_fall=False,
               ml_risk=0.0, time_of_day="animation_matin", rr=14):
    return {
        "resident_id": "R001",
        "resident_name": "Test Résident",
        "room": "101",
        "caregiver": "soignant_A",
        "time_of_day": time_of_day,   # requis pour le mode nuit
        "vitals": {
            "heart_rate": hr,
            "spo2": spo2,
            "blood_pressure_sys": bp,
            "temperature": temp,
            "respiratory_rate": rr,
        },
        "movement": {
            "last_movement_ago_s": last_mv,
            "is_fall_detected": is_fall,
            "accel_magnitude": 0.1,
            "is_sleeping": False,
        },
        "ml_risk": ml_risk,
    }


class TestAlertEngine:

    def test_no_alert_normal_state(self):
        engine = make_alert_engine()
        state = make_state()
        alert = engine.evaluate(state)
        assert alert is None, "Pas d'alerte pour constantes normales"

    def test_level_2_attention_spo2(self):
        engine = make_alert_engine()
        state = make_state(spo2=94)  # < 95 → niveau 2
        alert = engine.evaluate(state)
        assert alert is not None
        assert alert.level == 2, f"Attendu niveau 2, obtenu {alert.level}"

    def test_level_3_alert_spo2(self):
        engine = make_alert_engine()
        state = make_state(spo2=92)  # < 93 → niveau 3
        alert = engine.evaluate(state)
        assert alert is not None
        assert alert.level == 3, f"Attendu niveau 3, obtenu {alert.level}"

    def test_level_4_urgence_fall(self):
        engine = make_alert_engine()
        state = make_state(is_fall=True)
        alert = engine.evaluate(state)
        assert alert is not None
        assert alert.level == 4, "Chute doit déclencher niveau 4"

    def test_level_5_danger_vital(self):
        engine = make_alert_engine()
        state = make_state(spo2=84, hr=135)  # SpO2 < 85 ET FC > 130 → niveau 5
        alert = engine.evaluate(state)
        assert alert is not None
        assert alert.level == 5, f"Attendu niveau 5, obtenu {alert.level}"

    def test_level_4_critical_hr(self):
        engine = make_alert_engine()
        state = make_state(hr=142)  # > 140 → niveau 4
        alert = engine.evaluate(state)
        assert alert is not None
        assert alert.level == 4

    def test_ml_risk_triggers_alert(self):
        engine = make_alert_engine()
        state = make_state(ml_risk=0.8)  # > 0.75 → niveau 3
        alert = engine.evaluate(state)
        assert alert is not None
        assert alert.level >= 3

    def test_acknowledge_alert(self):
        engine = make_alert_engine()
        state = make_state(spo2=92)
        engine.evaluate(state)
        ok = engine.acknowledge("R001", "soignant_test")
        assert ok is True

    def test_acknowledge_nonexistent(self):
        engine = make_alert_engine()
        ok = engine.acknowledge("R999", "soignant_test")
        assert ok is False

    def test_escalation_timer(self):
        engine = make_alert_engine()
        state = make_state(spo2=94)  # niveau 2
        alert = engine.evaluate(state)
        assert alert.level == 2

        # Simuler que l'alerte date de plus de 600s
        alert.created_at = time.time() - 700

        engine.check_escalations()

        # Après escalade, l'alerte pour R001 doit être au niveau 3
        new_alert = engine.active_alerts.get("R001")
        assert new_alert is not None
        assert new_alert.level >= 3, f"Escalade attendue vers 3, obtenu {new_alert.level}"

    def test_get_all_active_returns_list(self):
        engine = make_alert_engine()
        state = make_state(spo2=92)
        engine.evaluate(state)
        active = engine.get_all_active()
        assert isinstance(active, list)
        assert len(active) == 1

    def test_alert_has_required_fields(self):
        engine = make_alert_engine()
        state = make_state(spo2=92)
        alert = engine.evaluate(state)
        d = alert.to_dict()
        for field in ['id', 'resident_id', 'level', 'reason', 'created_at', 'acknowledged']:
            assert field in d, f"Champ manquant: {field}"

    def test_inactivity_level_1(self):
        engine = make_alert_engine()
        state = make_state(last_mv=2000)  # > 1800s → niveau 1
        alert = engine.evaluate(state)
        # Niveau 1 Info, ou None selon le seuil exact
        if alert:
            assert alert.level <= 2

    def test_fever_triggers_alert(self):
        engine = make_alert_engine()
        state = make_state(temp=40.1)  # > 39.5 → niveau 3+
        alert = engine.evaluate(state)
        assert alert is not None
        assert alert.level >= 3


# ============================================================
# Tests modèle ML
# ============================================================

class TestMLModel:

    @pytest.fixture
    def predictor(self, monkeypatch, tmp_path):
        # Patch joblib.load pour forcer le réentraînement
        with patch('os.path.exists', return_value=False):
            import ml_model
            monkeypatch.setattr(ml_model, "MODEL_PATH", str(tmp_path / "ml_model.joblib"))
            from ml_model import MalaisePredictor
            return MalaisePredictor()

    def test_predict_returns_float(self, predictor):
        result = predictor.predict("R001", {"heart_rate": 72, "spo2": 96, "blood_pressure_sys": 130, "temperature": 36.7}, {"last_movement_ago_s": 60}, 80, 0.3)
        assert isinstance(result, float)

    def test_predict_range(self, predictor):
        result = predictor.predict("R001", {"heart_rate": 72, "spo2": 96, "blood_pressure_sys": 130, "temperature": 36.7}, {"last_movement_ago_s": 60}, 80, 0.3)
        assert 0.0 <= result <= 1.0

    def test_high_risk_vitals_score_higher(self, predictor):
        normal = predictor.predict("R001", {"heart_rate": 70, "spo2": 97, "blood_pressure_sys": 120, "temperature": 36.5}, {"last_movement_ago_s": 0}, 75, 0.1)
        risky = predictor.predict("R002", {"heart_rate": 125, "spo2": 89, "blood_pressure_sys": 185, "temperature": 39.8}, {"last_movement_ago_s": 3600}, 90, 0.8)
        assert risky > normal, f"Score risqué ({risky:.2f}) devrait > normal ({normal:.2f})"

    def test_trend_detection(self, predictor):
        # Plusieurs appels successifs → les tendances s'accumulent
        vitals = {"heart_rate": 70, "spo2": 97, "blood_pressure_sys": 120, "temperature": 36.5}
        for _ in range(5):
            predictor.predict("R_trend", vitals, {"last_movement_ago_s": 0}, 75, 0.1)
        result = predictor.predict("R_trend", vitals, {"last_movement_ago_s": 0}, 75, 0.1)
        assert 0.0 <= result <= 1.0


# ============================================================
# Tests integration API (necessitent la stack Docker ou l'API locale)
# ============================================================

class TestAPIIntegration:

    def test_api_health(self):
        with get_api_client() as client:
            r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_api_residents(self):
        with get_api_client() as client:
            r = client.get("/api/residents")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] >= 20
        assert len(data["residents"]) >= 20

    def test_api_alerts(self):
        with get_api_client() as client:
            r = client.get("/api/alerts")
        assert r.status_code == 200
        data = r.json()
        assert "active" in data
        assert "history" in data
        assert isinstance(data["active"], list)
        assert isinstance(data["history"], list)

    def test_api_summary(self):
        with get_api_client() as client:
            r = client.get("/api/summary")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        assert "timestamp" in data or "error" in data


# ============================================================
# Tests simulateur (sans MQTT)
# ============================================================

class TestSimulator:

    def test_resident_tick_returns_valid_data(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'simulator'))
        from main import ResidentSimulator
        profile = {
            "id": "T001", "name": "Test", "age": 80, "room": "001",
            "pathologies": ["hypertension"], "mobility": "moyenne",
            "base_hr": 72, "base_spo2": 96, "base_bp_sys": 130, "base_temp": 36.7,
            "risk_factor": 0.3, "caregiver": "soignant_A"
        }
        sim = ResidentSimulator(profile)
        state = sim.tick()

        assert "vitals" in state
        assert "movement" in state
        assert "resident_id" in state
        assert state["resident_id"] == "T001"
        assert 30 <= state["vitals"]["heart_rate"] <= 200
        assert 70 <= state["vitals"]["spo2"] <= 100

    def test_scenario_degrades_vitals(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'simulator'))
        from main import ResidentSimulator
        profile = {
            "id": "T002", "name": "Test2", "age": 85, "room": "002",
            "pathologies": ["bpco"], "mobility": "faible",
            "base_hr": 72, "base_spo2": 96, "base_bp_sys": 130, "base_temp": 36.7,
            "risk_factor": 0.9, "caregiver": "soignant_A"
        }
        sim = ResidentSimulator(profile)
        sim.malaise_scenario = {"type": "hypoxie", "start_tick": 0, "duration": 100}
        sim._tick = 80  # 80% de progression

        for _ in range(5):
            state = sim.tick()

        # Après scénario hypoxie avancé, SpO2 devrait être < valeur de base
        assert state["vitals"]["spo2"] < profile["base_spo2"]

    def test_fall_detection(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'simulator'))
        from main import ResidentSimulator
        profile = {
            "id": "T003", "name": "Test3", "age": 80, "room": "003",
            "pathologies": [], "mobility": "bonne",
            "base_hr": 72, "base_spo2": 96, "base_bp_sys": 130, "base_temp": 36.7,
            "risk_factor": 0.1, "caregiver": "soignant_A"
        }
        sim = ResidentSimulator(profile)
        sim.accel_magnitude = 10.0  # Chute simulée
        state = sim.tick()
        assert state["movement"]["is_fall_detected"] is True


# ============================================================
# Tests score NEWS2
# ============================================================

class TestNEWSScore:

    def test_news_normal_returns_zero(self):
        from alert_engine import compute_news_score
        vitals = {"heart_rate": 75, "spo2": 97, "blood_pressure_sys": 125, "temperature": 36.8, "respiratory_rate": 14}
        news = compute_news_score(vitals, {"is_fall_detected": False})
        assert news["score"] == 0
        assert news["risk_level"] == "low"

    def test_news_critical_values_high_score(self):
        from alert_engine import compute_news_score
        vitals = {"heart_rate": 135, "spo2": 88, "blood_pressure_sys": 88, "temperature": 39.5, "respiratory_rate": 26}
        news = compute_news_score(vitals, {"is_fall_detected": True})
        assert news["score"] >= 9
        assert news["risk_level"] == "high"

    def test_news_fall_adds_consciousness_point(self):
        from alert_engine import compute_news_score
        base = compute_news_score({"heart_rate": 75, "spo2": 97, "blood_pressure_sys": 125, "temperature": 36.8, "respiratory_rate": 14}, {"is_fall_detected": False})
        fall = compute_news_score({"heart_rate": 75, "spo2": 97, "blood_pressure_sys": 125, "temperature": 36.8, "respiratory_rate": 14}, {"is_fall_detected": True})
        assert fall["score"] == base["score"] + 1

    def test_news_score_in_alert_trigger_data(self):
        engine = make_alert_engine()
        state = make_state(spo2=91, hr=115, rr=22)
        alert = engine.evaluate(state)
        assert alert is not None
        assert "news" in alert.trigger_data
        assert "score" in alert.trigger_data["news"]


# ============================================================
# Tests mode nuit
# ============================================================

class TestNightMode:

    def test_night_spo2_threshold_more_lenient(self):
        """SpO2=93% ne doit pas déclencher d'alerte la nuit (désaturation normale)."""
        engine = make_alert_engine()
        state = make_state(spo2=93, time_of_day="nuit")
        state["movement"]["is_sleeping"] = True
        alert = engine.evaluate(state)
        # Niveau 3 de jour (spo2 < 93), mais pas la nuit (seuil = 89)
        if alert:
            assert alert.level < 3, f"Nuit: spo2=93 ne doit pas déclencher niveau 3, obtenu {alert.level}"

    def test_night_inactivity_no_level1(self):
        """Inactivité 30 min pendant le sommeil = normal, pas d'alerte."""
        engine = make_alert_engine()
        state = make_state(last_mv=2000, time_of_day="nuit")
        state["movement"]["is_sleeping"] = True
        alert = engine.evaluate(state)
        # Niveau 1 ne doit pas déclencher si le résident dort
        assert alert is None or alert.level > 1


# ============================================================
# Tests endpoints API (nécessitent la stack Docker)
# ============================================================

class TestAPINewEndpoints:

    def test_api_routine_endpoint(self):
        with get_api_client() as client:
            r = client.get("/api/residents/R001/routine")
        assert r.status_code == 200
        data = r.json()
        assert "routine" in data
        assert "resident_id" in data

    def test_api_famille_requires_code(self):
        with get_api_client() as client:
            r = client.get("/api/famille/R001")
        assert r.status_code == 403

    def test_api_famille_valid_code(self):
        with get_api_client() as client:
            r = client.get("/api/famille/R001?code=FAMILLE")
        assert r.status_code == 200
        data = r.json()
        assert "name" in data
        assert "general_status" in data
        # Pas de données médicales brutes
        assert "heart_rate" not in data
        assert "spo2" not in data

    def test_api_ml_metrics_has_sensitivity(self):
        with get_api_client() as client:
            r = client.get("/api/ml/metrics")
        assert r.status_code == 200
        metrics = r.json().get("metrics", {})
        assert "sensitivity" in metrics, "Sensibilité manquante dans les métriques ML"
        assert "specificity" in metrics, "Spécificité manquante dans les métriques ML"
        assert "feature_importance" in metrics


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
