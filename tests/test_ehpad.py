"""
Tests automatisés — moteur d'alertes, ML, simulateur.
Lance avec : python -m pytest tests/ -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import asyncio
import json
import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch
from contextlib import contextmanager


API_BASE_URL = os.getenv("EHPAD_API_URL", "http://localhost:8001")


@contextmanager
def get_api_client():
    httpx = pytest.importorskip("httpx")
    with httpx.Client(base_url=API_BASE_URL, timeout=5.0) as client:
        try:
            client.get("/health")
        except httpx.HTTPError as exc:
            pytest.fail(f"API EHPAD non disponible sur {API_BASE_URL}: {exc}")
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


def evaluate_until_alert(engine, state, attempts=5):
    """Le moteur anti-bruit attend une persistance avant les alertes non urgentes."""
    alert = None
    for _ in range(attempts):
        alert = engine.evaluate(state)
        if alert is not None:
            return alert
    return alert


class TestAlertEngine:

    def test_no_alert_normal_state(self):
        engine = make_alert_engine()
        state = make_state()
        alert = evaluate_until_alert(engine, state)
        assert alert is None, "Pas d'alerte pour constantes normales"

    def test_level_2_attention_spo2(self):
        engine = make_alert_engine()
        state = make_state(spo2=93)
        alert = evaluate_until_alert(engine, state)
        assert alert is not None
        assert alert.level == 2, f"Attendu niveau 2, obtenu {alert.level}"

    def test_level_3_alert_spo2(self):
        engine = make_alert_engine()
        state = make_state(spo2=91)
        alert = evaluate_until_alert(engine, state)
        assert alert is not None
        assert alert.level == 3, f"Attendu niveau 3, obtenu {alert.level}"

    def test_level_4_urgence_fall(self):
        engine = make_alert_engine()
        state = make_state(is_fall=True)
        alert = evaluate_until_alert(engine, state)
        assert alert is not None
        assert alert.level == 4, "Chute doit déclencher niveau 4"

    def test_fall_with_tachycardia_and_immobility_is_level_5(self):
        engine = make_alert_engine()
        state = make_state(hr=124, last_mv=180, is_fall=True)
        state["sensor_events"] = {
            "fall_confirmed_by_room_sensor": True,
            "floor_pressure_event": True,
        }
        alert = evaluate_until_alert(engine, state)
        assert alert is not None
        assert alert.level == 5
        assert "Chute confirmee avec immobilite" in alert.reason
        assert "combinaison=chute_confirmee+immobilite+constantes_aggravees" in alert.trigger_data["evidence"]

    def test_level_5_danger_vital(self):
        engine = make_alert_engine()
        state = make_state(spo2=84, hr=135)  # SpO2 < 85 ET FC > 130 → niveau 5
        alert = evaluate_until_alert(engine, state)
        assert alert is not None
        assert alert.level == 5, f"Attendu niveau 5, obtenu {alert.level}"

    def test_level_4_critical_hr(self):
        engine = make_alert_engine()
        state = make_state(hr=142)  # > 140 → niveau 4
        alert = evaluate_until_alert(engine, state)
        assert alert is not None
        assert alert.level == 4

    def test_ml_risk_triggers_alert(self):
        engine = make_alert_engine()
        state = make_state(ml_risk=0.86, spo2=93)
        alert = evaluate_until_alert(engine, state)
        assert alert is not None
        assert alert.level >= 3

    def test_meal_return_malaise_reason_is_explicit(self):
        engine = make_alert_engine()
        state = make_state(ml_risk=0.70)
        state["movement_scenario"] = "malaise_retour_repas"
        state["routine_analysis"] = {
            "score": 0.45,
            "alert_level": 2,
            "flags": ["malaise retour repas"],
        }
        alert = evaluate_until_alert(engine, state)
        assert alert is not None
        assert alert.level == 4
        assert "Malaise suspecte" in alert.reason
        assert "risque de chute ou immobilite" in alert.reason
        assert "risque IA 70%" in alert.reason

    def test_meal_room_malaise_is_level_4(self):
        engine = make_alert_engine()
        state = make_state()
        state["movement_scenario"] = "malaise_salle_manger"
        alert = evaluate_until_alert(engine, state)
        assert alert is not None
        assert alert.level == 4
        assert "Malaise suspecte" in alert.reason

    def test_fall_scenario_is_level_4_even_before_sensor_confirmation(self):
        engine = make_alert_engine()
        state = make_state()
        state["movement_scenario"] = "chute_couloir"
        alert = evaluate_until_alert(engine, state)
        assert alert is not None
        assert alert.level == 4
        assert "Scenario de chute" in alert.reason

    def test_night_toilet_frail_is_level_3(self):
        engine = make_alert_engine()
        state = make_state(time_of_day="nuit")
        state["movement_scenario"] = "aller_toilettes_nuit"
        state["mobility"] = "tres_faible"
        alert = evaluate_until_alert(engine, state)
        assert alert is not None
        assert alert.level == 3
        assert "toilettes nuit" in alert.reason

    def test_high_risk_disorientation_is_level_4(self):
        engine = make_alert_engine()
        state = make_state()
        state["movement_scenario"] = "desorientation_ascenseur"
        state["pathologies"] = ["alzheimer"]
        state["current_zone"] = "ascenseur"
        alert = evaluate_until_alert(engine, state)
        assert alert is not None
        assert alert.level == 4
        assert "Desorientation a haut risque" in alert.reason

    def test_unaccompanied_garden_exit_cognitive_is_level_4(self):
        engine = make_alert_engine()
        state = make_state()
        state["movement_scenario"] = "sortie_jardin_non_accompagnee"
        state["pathologies"] = ["demence"]
        alert = evaluate_until_alert(engine, state)
        assert alert is not None
        assert alert.level == 4
        assert "Sortie non accompagnee" in alert.reason

    @pytest.mark.parametrize("scenario,zone,expected_level,reason_part,extra", [
        ("chute_chambre", "ch103", 4, "Scenario de chute", {}),
        ("chute_salle_bain", "ch103", 4, "Scenario de chute", {}),
        ("chute_couloir", "couloir_principal", 4, "Scenario de chute", {}),
        ("chute_trajet_repas", "couloir_principal", 4, "Scenario de chute", {}),
        ("chute_jardin", "jardin", 4, "Scenario de chute", {}),
        ("malaise_salle_manger", "salle_manger", 4, "Malaise suspecte", {"ml_risk": 0.65}),
        ("malaise_retour_repas", "couloir_principal", 4, "Malaise suspecte", {"ml_risk": 0.65}),
        ("desorientation_ascenseur", "ascenseur", 4, "Desorientation a haut risque", {"pathologies": ["alzheimer"]}),
        ("aller_toilettes_nuit", "couloir_principal", 3, "toilettes nuit", {"mobility": "tres_faible", "time_of_day": "nuit"}),
        ("sortie_jardin_non_accompagnee", "jardin", 4, "Sortie non accompagnee", {"pathologies": ["demence"]}),
        ("fugue_hors_ehpad", "hors_ehpad", 4, "Fugue detectee", {}),
    ])
    def test_scenario_alert_matrix_is_coherent(self, scenario, zone, expected_level, reason_part, extra):
        engine = make_alert_engine()
        state = make_state(
            ml_risk=extra.get("ml_risk", 0.1),
            time_of_day=extra.get("time_of_day", "animation_matin"),
        )
        state["movement_scenario"] = scenario
        state["current_zone"] = zone
        state["sensor_events"] = extra.get("sensor_events", {})
        if "pathologies" in extra:
            state["pathologies"] = extra["pathologies"]
        if "mobility" in extra:
            state["mobility"] = extra["mobility"]

        alert = evaluate_until_alert(engine, state)

        assert alert is not None
        assert int(alert.level) == expected_level
        assert reason_part in alert.reason
        assert alert.current_zone == zone

    def test_acknowledge_alert(self):
        engine = make_alert_engine()
        state = make_state(spo2=91)
        evaluate_until_alert(engine, state)
        ok = engine.acknowledge("R001", "soignant_test")
        assert ok is True

    def test_acknowledge_nonexistent(self):
        engine = make_alert_engine()
        ok = engine.acknowledge("R999", "soignant_test")
        assert ok is False

    def test_escalation_timer(self):
        engine = make_alert_engine()
        state = make_state(spo2=93)
        alert = evaluate_until_alert(engine, state)
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
        state = make_state(spo2=91)
        evaluate_until_alert(engine, state)
        active = engine.get_all_active()
        assert isinstance(active, list)
        assert len(active) == 1

    def test_alert_has_required_fields(self):
        engine = make_alert_engine()
        state = make_state(spo2=91)
        alert = evaluate_until_alert(engine, state)
        d = alert.to_dict()
        for field in ['id', 'resident_id', 'level', 'reason', 'created_at', 'acknowledged']:
            assert field in d, f"Champ manquant: {field}"

    def test_inactivity_level_1(self):
        engine = make_alert_engine()
        state = make_state(last_mv=2000)  # > 1800s → niveau 1
        alert = evaluate_until_alert(engine, state)
        # Niveau 1 Info, ou None selon le seuil exact
        if alert:
            assert alert.level <= 2

    def test_fever_triggers_alert(self):
        engine = make_alert_engine()
        state = make_state(temp=40.1)  # > 39.5 → niveau 3+
        alert = evaluate_until_alert(engine, state)
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
        sim.start_scenario("chute", duration=30)
        state = None
        for _ in range(4):
            state = sim.tick()
            if state["movement"]["is_fall_detected"]:
                break
        assert state["movement"]["is_fall_detected"] is True

    def test_chute_chambre_does_not_activate_bathroom_sensor(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'simulator'))
        from main import ResidentSimulator
        profile = {
            "id": "T103", "name": "Test chambre", "age": 86, "room": "103",
            "zone": "ch103", "floor": 0,
            "room_sensors": ["pir", "radar", "porte", "sdb_pir", "matelas", "sol"],
            "pathologies": ["parkinson"], "mobility": "tres_faible",
            "base_hr": 72, "base_spo2": 96, "base_bp_sys": 130, "base_temp": 36.7,
            "risk_factor": 0.9, "caregiver": "soignant_A"
        }
        sim = ResidentSimulator(profile)
        sim.movement_scenario = "chute_chambre"
        state = sim.tick()

        assert state["current_zone"] == "ch103"
        assert state["sensor_events"]["bathroom_motion"] is False

    def test_chute_salle_bain_activates_bathroom_sensor(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'simulator'))
        from main import ResidentSimulator
        profile = {
            "id": "T104", "name": "Test salle bain", "age": 86, "room": "104",
            "zone": "ch104", "floor": 0,
            "room_sensors": ["pir", "radar", "porte", "sdb_pir", "matelas", "sol"],
            "pathologies": ["parkinson"], "mobility": "tres_faible",
            "base_hr": 72, "base_spo2": 96, "base_bp_sys": 130, "base_temp": 36.7,
            "risk_factor": 0.9, "caregiver": "soignant_A"
        }
        sim = ResidentSimulator(profile)
        sim.movement_scenario = "chute_salle_bain"
        state = sim.tick()

        assert state["current_zone"] == "ch104"
        assert state["sensor_events"]["bathroom_motion"] is True

    def test_chute_couloir_routes_before_freezing_alert(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'simulator'))
        from main import ResidentSimulator
        profile = {
            "id": "T105", "name": "Test couloir", "age": 82, "room": "105",
            "zone": "ch105", "floor": 0,
            "room_sensors": ["pir", "radar", "porte", "matelas", "sol"],
            "pathologies": [], "mobility": "faible",
            "base_hr": 72, "base_spo2": 96, "base_bp_sys": 130, "base_temp": 36.7,
            "risk_factor": 0.5, "caregiver": "soignant_A"
        }
        sim = ResidentSimulator(profile)
        sim.movement_scenario = "chute_couloir"
        state = sim.tick()

        assert state["current_zone"] == "ch105"
        assert sim.route, "Le scenario couloir doit router avant de figer l'alerte en chambre"
        assert sim.target_zone != "ch105"


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
        alert = evaluate_until_alert(engine, state)
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
        alert = evaluate_until_alert(engine, state)
        # Niveau 3 de jour (spo2 < 93), mais pas la nuit (seuil = 89)
        if alert:
            assert alert.level < 3, f"Nuit: spo2=93 ne doit pas déclencher niveau 3, obtenu {alert.level}"

    def test_night_inactivity_no_level1(self):
        """Inactivité 30 min pendant le sommeil = normal, pas d'alerte."""
        engine = make_alert_engine()
        state = make_state(last_mv=2000, time_of_day="nuit")
        state["movement"]["is_sleeping"] = True
        alert = evaluate_until_alert(engine, state)
        # Niveau 1 ne doit pas déclencher si le résident dort
        assert alert is None or alert.level > 1


# ============================================================
# Tests endpoints API (nécessitent la stack Docker)
# ============================================================

@pytest.fixture(scope="session")
def staff_auth_headers():
    """Token chef_garde partagé sur toute la session — 1 seul login staff."""
    httpx = pytest.importorskip("httpx")
    with httpx.Client(base_url=API_BASE_URL, timeout=5.0) as client:
        r = client.post("/api/staff/login",
                        json={"caregiver_id": "chef_garde", "password": "EHPAD2024!"})
        if r.status_code != 200:
            pytest.fail(f"Connexion staff échouée : {r.status_code} {r.text}")
        return {"Authorization": f"Bearer {r.json()['token']}"}


class TestAPINewEndpoints:

    def test_api_routine_endpoint(self, staff_auth_headers):
        with get_api_client() as client:
            r = client.get("/api/residents/R001/routine", headers=staff_auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "current_analysis" in data
        assert "name" in data

    def test_api_famille_requires_code(self):
        with get_api_client() as client:
            r = client.get("/api/famille/R001")
        assert r.status_code == 401

    def test_api_famille_login_then_view(self, curie_token):
        with get_api_client() as client:
            r = client.get("/api/famille/R001", headers={"Authorization": f"Bearer {curie_token}"})
        assert r.status_code == 200
        data = r.json()
        assert "name" in data
        assert "general_status" in data
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


    def test_api_project_readiness(self):
        with get_api_client() as client:
            r = client.get("/api/project/readiness")
        assert r.status_code == 200
        data = r.json()
        assert "readiness" in data
        assert "resident_profile_counts" in data

    def test_api_life_plan(self):
        with get_api_client() as client:
            r = client.get("/api/scenarios/life-plan")
        assert r.status_code == 200
        data = r.json()
        assert "day_template" in data
        assert "fugue_hors_ehpad" in data["scenario_types"]

    def test_api_sensors_health(self):
        with get_api_client() as client:
            r = client.get("/api/sensors/health")
        assert r.status_code == 200
        data = r.json()
        assert "count" in data
        assert "sensors" in data

    def test_api_scalability_metrics(self):
        with get_api_client() as client:
            r = client.get("/api/ops/scalability")
        assert r.status_code == 200
        data = r.json()
        assert "mqtt" in data
        assert data["mqtt"]["target_20_residents_6_constants_s"] == 120

    def test_api_trigger_validation_scenario(self):
        with get_api_client() as client:
            r = client.post("/api/simulator/scenario?resident_id=R005&scenario=jardin")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_api_staff_roster(self):
        with get_api_client() as client:
            r = client.get("/api/staff")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] >= 3
        assert "routing_rules" in data
        assert any(s["id"] == "soignant_A" for s in data["staff"])

    def test_api_staff_status_update(self, staff_auth_headers):
        with get_api_client() as client:
            r = client.post("/api/staff/soignant_A/status?status=occupe",
                            headers=staff_auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["staff"]["status"] == "occupe"

    def test_api_assign_caregiver(self, staff_auth_headers):
        with get_api_client() as client:
            r = client.post("/api/residents/R005/assign-caregiver?caregiver_id=soignant_C",
                            headers=staff_auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["caregiver_id"] == "soignant_C"

    def test_api_notification_traceability(self, staff_auth_headers):
        payload = {
            "caregiver_id": "soignant_C",
            "action": "seen",
            "notification_key": "test-trace-r005",
            "resident_id": "R005",
            "resident_name": "Edith Piaf",
            "level": 3,
            "reason": "test notification",
            "location": "couloir principal",
        }
        with get_api_client() as client:
            r = client.post("/api/notifications/action", json=payload,
                            headers=staff_auth_headers)
            assert r.status_code == 200
            data = r.json()
            assert data["ok"] is True
            assert data["trace"]["action"] == "vue"

            audit = client.get("/api/notifications/audit?caregiver_id=soignant_C&limit=5")
            assert audit.status_code == 200
            rows = audit.json()["audit"]
            assert any(row["notification_key"] == "test-trace-r005" for row in rows)


# ============================================================
# Tests authentification famille (C3)
# ============================================================

# Comptes demo attendus apres seed — reference pour tous les tests famille
FAMILLE_DEMO_ACCOUNTS = [
    ("curie",      "curie101",      "R001"),
    ("pasteur",    "pasteur102",    "R002"),
    ("veil",       "veil103",       "R003"),
    ("coubertin",  "coubertin104",  "R004"),
    ("piaf",       "piaf105",       "R005"),
    ("gabin",      "gabin106",      "R006"),
    ("girardot",   "girardot107",   "R007"),
    ("bourvil",    "bourvil108",    "R008"),
    ("chanel",     "chanel201",     "R009"),
    ("montand",    "montand202",    "R010"),
    ("moreau",     "moreau203",     "R011"),
    ("aznavour",   "aznavour204",   "R012"),
    ("bardot",     "bardot208",     "R013"),
    ("depardieu",  "depardieu209",  "R014"),
    ("mathieu",    "mathieu210",    "R015"),
    ("francois",   "francois211",   "R016"),
    ("baker",      "baker212",      "R017"),
    ("fernandel",  "fernandel213",  "R018"),
    ("dalida",     "dalida214",     "R019"),
    ("ventura",    "ventura215",    "R020"),
    ("schneider",  "schneider216",  "R021"),
    ("belmondo",   "belmondo217",   "R022"),
    ("marceau",    "marceau218",    "R023"),
    ("sardou",     "sardou219",     "R024"),
    ("adjani",     "adjani220",     "R025"),
]


class _FakeRedis:
    """Redis minimaliste en memoire pour les tests unitaires."""
    def __init__(self):
        self._d = {}

    def get(self, k):
        return self._d.get(k)

    def set(self, k, v):
        self._d[k] = v

    def setex(self, k, ttl, v):
        self._d[k] = v

    def exists(self, k):
        return int(k in self._d)

    def delete(self, k):
        removed = k in self._d
        self._d.pop(k, None)
        return int(removed)

    def keys(self, pattern):
        import fnmatch
        return [x for x in self._d if fnmatch.fnmatch(x, pattern)]


class TestFamilleAuth:
    """Tests unitaires sur auth.py — pas d'API necessaire."""

    def setup_method(self):
        import auth
        self.auth = auth
        self.rc = _FakeRedis()

    def test_create_account_ok(self):
        ok = self.auth.create_account(self.rc, "testuser", "motdepasse", "R001")
        assert ok is True

    def test_create_account_duplicate(self):
        self.auth.create_account(self.rc, "testuser", "motdepasse", "R001")
        ok = self.auth.create_account(self.rc, "testuser", "autremot", "R002")
        assert ok is False

    def test_authenticate_valid(self):
        self.auth.create_account(self.rc, "testuser", "motdepasse", "R001")
        result = self.auth.authenticate(self.rc, "testuser", "motdepasse")
        assert result is not None
        token, rid = result
        assert rid == "R001"
        assert len(token) > 20

    def test_authenticate_wrong_password(self):
        self.auth.create_account(self.rc, "testuser", "motdepasse", "R001")
        result = self.auth.authenticate(self.rc, "testuser", "mauvais")
        assert result is None

    def test_authenticate_unknown_user(self):
        result = self.auth.authenticate(self.rc, "inconnu", "n'importe")
        assert result is None

    def test_token_validation(self):
        self.auth.create_account(self.rc, "testuser", "motdepasse", "R001")
        token, _ = self.auth.authenticate(self.rc, "testuser", "motdepasse")
        session = self.auth.validate_token(self.rc, token)
        assert session is not None
        assert session["resident_id"] == "R001"
        assert session["username"] == "testuser"

    def test_token_invalid_after_revoke(self):
        self.auth.create_account(self.rc, "testuser", "motdepasse", "R001")
        token, _ = self.auth.authenticate(self.rc, "testuser", "motdepasse")
        self.auth.revoke_token(self.rc, token)
        assert self.auth.validate_token(self.rc, token) is None

    def test_delete_account(self):
        self.auth.create_account(self.rc, "testuser", "motdepasse", "R001")
        assert self.auth.delete_account(self.rc, "testuser") is True
        assert self.auth.authenticate(self.rc, "testuser", "motdepasse") is None

    def test_password_is_not_stored_in_clear(self):
        """Le mot de passe ne doit jamais apparaitre en clair dans Redis."""
        self.auth.create_account(self.rc, "testuser", "motdepasse_secret", "R001")
        stored = str(self.rc._d)
        assert "motdepasse_secret" not in stored

    def test_seed_creates_all_25_accounts(self):
        from resident_profiles import RESIDENTS_LIST
        self.auth.seed_demo_accounts(self.rc, RESIDENTS_LIST)
        accounts = self.auth.list_accounts(self.rc)
        assert len(accounts) == 25

    @pytest.mark.parametrize("username,password,resident_id", FAMILLE_DEMO_ACCOUNTS)
    def test_seed_account_credentials(self, username, password, resident_id):
        """Verifie que chaque compte demo est utilisable avec les bons identifiants."""
        from resident_profiles import RESIDENTS_LIST
        self.auth.seed_demo_accounts(self.rc, RESIDENTS_LIST)
        result = self.auth.authenticate(self.rc, username, password)
        assert result is not None, f"Echec auth pour {username}/{password}"
        token, rid = result
        assert rid == resident_id, f"{username} devrait pointer vers {resident_id}, obtenu {rid}"

    def test_username_case_insensitive(self):
        self.auth.create_account(self.rc, "Curie", "curie101", "R001")
        result = self.auth.authenticate(self.rc, "CURIE", "curie101")
        assert result is not None

    def test_wrong_resident_cannot_access_other(self):
        """Un token R001 ne doit pas valider une session R002."""
        self.auth.create_account(self.rc, "user1", "pass1", "R001")
        self.auth.create_account(self.rc, "user2", "pass2", "R002")
        token1, _ = self.auth.authenticate(self.rc, "user1", "pass1")
        session = self.auth.validate_token(self.rc, token1)
        assert session["resident_id"] != "R002"


@pytest.fixture(scope="session")
def curie_token():
    """Token curie partagé pour toute la classe — évite de dépasser le rate limit."""
    httpx = pytest.importorskip("httpx")
    with httpx.Client(base_url=API_BASE_URL, timeout=5.0) as client:
        r = client.post("/api/famille/login", json={"username": "curie", "password": "curie101"})
        if r.status_code != 200:
            pytest.fail(f"Setup famille login échoué : {r.status_code} {r.text}")
        return r.json()["token"]


class TestFamilleAPI:
    """Tests d'integration sur les endpoints famille — necessite l'API en cours."""

    def _login(self, client, username, password):
        r = client.post("/api/famille/login", json={"username": username, "password": password})
        return r

    def test_login_valid(self, curie_token):
        assert curie_token is not None and len(curie_token) > 20

    def test_login_wrong_password(self):
        with get_api_client() as client:
            r = self._login(client, "curie", "mauvais")
        assert r.status_code == 401

    def test_login_unknown_user(self):
        with get_api_client() as client:
            r = self._login(client, "inconnu_xyz_test", "motdepasse")
        assert r.status_code == 401

    def test_view_requires_token(self):
        with get_api_client() as client:
            r = client.get("/api/famille/R001")
        assert r.status_code == 401

    def test_view_correct_resident(self, curie_token):
        with get_api_client() as client:
            r = client.get("/api/famille/R001", headers={"Authorization": f"Bearer {curie_token}"})
        assert r.status_code == 200
        data = r.json()
        assert "name" in data
        assert "general_status" in data
        assert "heart_rate" not in data
        assert "spo2" not in data

    def test_view_wrong_resident_forbidden(self, curie_token):
        """curie (R001) ne peut pas acceder a R002."""
        with get_api_client() as client:
            r = client.get("/api/famille/R002", headers={"Authorization": f"Bearer {curie_token}"})
        assert r.status_code == 403

    def test_logout_invalidates_token(self):
        """Login dédié pour tester l'invalidation — token isolé pour ne pas casser curie_token."""
        httpx = pytest.importorskip("httpx")
        with httpx.Client(base_url=API_BASE_URL, timeout=5.0) as client:
            login = client.post("/api/famille/login",
                                json={"username": "piaf", "password": "piaf105"})
            if login.status_code != 200:
                pytest.fail(f"Login piaf échoué (rate limit?) : {login.status_code}")
            token = login.json()["token"]
            client.post("/api/famille/logout", headers={"Authorization": f"Bearer {token}"})
            r = client.get("/api/famille/R005", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

    def test_admin_list_accounts(self):
        with get_api_client() as client:
            r = client.get("/api/admin/famille/accounts",
                           headers={"Authorization": "Bearer ADMIN_EHPAD_2024"})
        assert r.status_code == 200
        data = r.json()
        assert len(data["accounts"]) >= 25

    def test_admin_create_and_delete(self):
        with get_api_client() as client:
            admin_hdrs = {"Authorization": "Bearer ADMIN_EHPAD_2024"}
            # Nettoyage préventif si le compte traîne d'un run précédent
            client.delete("/api/admin/famille/accounts/test_tmp", headers=admin_hdrs)
            r = client.post("/api/admin/famille/accounts", headers=admin_hdrs,
                            json={"username": "test_tmp", "password": "azerty99", "resident_id": "R010"})
            assert r.status_code == 200
            client.delete("/api/admin/famille/accounts/test_tmp", headers=admin_hdrs)
            login2 = self._login(client, "test_tmp", "azerty99")
            assert login2.status_code == 401

    def test_admin_wrong_token_forbidden(self):
        with get_api_client() as client:
            r = client.get("/api/admin/famille/accounts",
                           headers={"Authorization": "Bearer MAUVAIS_TOKEN"})
        assert r.status_code == 403


# ============================================================
# Tests WebSocketManager
# ============================================================

class TestWebSocketManager:

    def setup_method(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
        from ws_manager import WebSocketManager
        self.WebSocketManager = WebSocketManager

    def _make_ws(self, fail_on_send=False):
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock(side_effect=Exception("mort")) if fail_on_send else AsyncMock()
        return ws

    def test_connect_adds_to_connections(self):
        mgr = self.WebSocketManager()
        ws = self._make_ws()
        asyncio.run(mgr.connect(ws))
        assert ws in mgr.connections

    def test_disconnect_removes_from_connections(self):
        mgr = self.WebSocketManager()
        ws = self._make_ws()
        asyncio.run(mgr.connect(ws))
        mgr.disconnect(ws)
        assert ws not in mgr.connections

    def test_disconnect_unknown_noop(self):
        mgr = self.WebSocketManager()
        mgr.disconnect(MagicMock())  # pas d'exception

    def test_broadcast_sends_to_all_connections(self):
        mgr = self.WebSocketManager()
        ws1, ws2 = self._make_ws(), self._make_ws()
        asyncio.run(mgr.connect(ws1))
        asyncio.run(mgr.connect(ws2))
        asyncio.run(mgr.broadcast({"type": "test"}))
        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()

    def test_broadcast_removes_dead_connections(self):
        mgr = self.WebSocketManager()
        alive = self._make_ws()
        dead = self._make_ws(fail_on_send=True)
        asyncio.run(mgr.connect(alive))
        asyncio.run(mgr.connect(dead))
        asyncio.run(mgr.broadcast({"type": "test"}))
        assert dead not in mgr.connections
        assert alive in mgr.connections

    def test_broadcast_empty_connections_noop(self):
        asyncio.run(self.WebSocketManager().broadcast({"type": "test"}))

    def test_send_alert_wraps_type(self):
        mgr = self.WebSocketManager()
        ws = self._make_ws()
        asyncio.run(mgr.connect(ws))
        asyncio.run(mgr.send_alert({"level": 3, "reason": "chute"}))
        payload = json.loads(ws.send_text.call_args[0][0])
        assert payload["type"] == "alert"
        assert payload["data"]["level"] == 3

    def test_send_state_update_wraps_type(self):
        mgr = self.WebSocketManager()
        ws = self._make_ws()
        asyncio.run(mgr.connect(ws))
        asyncio.run(mgr.send_state_update({"resident_id": "R001"}))
        payload = json.loads(ws.send_text.call_args[0][0])
        assert payload["type"] == "resident_update"
        assert payload["data"]["resident_id"] == "R001"


# ============================================================
# Tests RoutineEngine
# ============================================================

class _FakeRedisLists(_FakeRedis):
    """FakeRedis étendu avec les opérations de liste pour routine_engine."""

    def __init__(self):
        super().__init__()
        self._lists = {}

    def lpush(self, key, *values):
        self._lists.setdefault(key, [])
        for v in reversed(values):
            self._lists[key].insert(0, v)
        return len(self._lists[key])

    def lrange(self, key, start, end):
        lst = self._lists.get(key, [])
        return lst[start:] if end < 0 else lst[start:end + 1]

    def ltrim(self, key, start, end):
        lst = self._lists.get(key, [])
        self._lists[key] = lst[start:end + 1]

    def expire(self, key, ttl):
        return True


def _routine_state(period="animation_matin", spo2=96, hr=72, last_mv=60,
                   zone="chambre_101", scenario=None):
    state = {
        "resident_id": "R001",
        "time_of_day": period,
        "current_zone": zone,
        "activity": "animation",
        "vitals": {"heart_rate": hr, "spo2": spo2, "blood_pressure_sys": 130,
                   "temperature": 36.7, "respiratory_rate": 14},
        "movement": {"last_movement_ago_s": last_mv, "is_fall_detected": False,
                     "is_sleeping": False},
    }
    if scenario:
        state["movement_scenario"] = scenario
    return state


class TestRoutineEngine:

    def setup_method(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
        from routine_engine import update_and_detect
        self.update_and_detect = update_and_detect

    def test_missing_resident_id_returns_flag(self):
        rc = _FakeRedisLists()
        result = self.update_and_detect(rc, {"vitals": {}, "movement": {}})
        assert "resident_id absent" in result["flags"][0]
        assert result["score"] == 0

    def test_learning_phase_below_20_samples(self):
        rc = _FakeRedisLists()
        result = self.update_and_detect(rc, _routine_state())
        assert result["status"] == "learning"
        assert result["score"] == 0.0
        assert result["alert_level"] == 0

    def test_status_ok_after_20_samples(self):
        rc = _FakeRedisLists()
        for _ in range(22):
            result = self.update_and_detect(rc, _routine_state())
        assert result["status"] == "ok"

    def test_consistent_routine_gives_low_score(self):
        rc = _FakeRedisLists()
        for _ in range(25):
            result = self.update_and_detect(rc, _routine_state())
        assert result["score"] < 0.3, f"Routine stable devrait scorer bas, obtenu {result['score']}"

    def test_inactivity_outside_rest_period_raises_flag(self):
        rc = _FakeRedisLists()
        for _ in range(25):
            self.update_and_detect(rc, _routine_state(last_mv=60))
        result = self.update_and_detect(rc, _routine_state(last_mv=4000, period="animation_matin"))
        assert any("mouvement" in f.lower() or "inactivit" in f.lower() for f in result["flags"])
        assert result["score"] > 0

    def test_known_scenario_raises_flag(self):
        rc = _FakeRedisLists()
        for _ in range(25):
            self.update_and_detect(rc, _routine_state())
        result = self.update_and_detect(rc, _routine_state(scenario="errance_nuit"))
        assert any("sc" in f.lower() for f in result["flags"])
        assert result["score"] > 0

    def test_result_has_all_required_keys(self):
        rc = _FakeRedisLists()
        for _ in range(22):
            result = self.update_and_detect(rc, _routine_state())
        for key in ("score", "alert_level", "flags", "baseline", "entry", "period"):
            assert key in result, f"Clé manquante : {key}"

    def test_alert_level_scales_with_score(self):
        rc = _FakeRedisLists()
        for _ in range(25):
            self.update_and_detect(rc, _routine_state(last_mv=60))
        result = self.update_and_detect(rc, _routine_state(last_mv=4000, scenario="errance_nuit"))
        assert result["alert_level"] >= 1


# ============================================================
# Tests KBLoader
# ============================================================

class TestKBLoader:

    def setup_method(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

    def test_load_kb_returns_dict(self):
        from kb_loader import load_kb
        assert isinstance(load_kb(), dict)

    def test_scenarios_is_nonempty_list(self):
        from kb_loader import get_scenarios
        scenarios = get_scenarios()
        assert isinstance(scenarios, list)
        assert len(scenarios) > 0

    def test_get_existing_scenario(self):
        from kb_loader import get_scenarios, get_scenario
        first_id = get_scenarios()[0]["id"]
        result = get_scenario(first_id)
        assert result is not None
        assert result["id"] == first_id

    def test_get_nonexistent_scenario_returns_none(self):
        from kb_loader import get_scenario
        assert get_scenario("SCN_INEXISTANT_XYZ_999") is None

    def test_get_alert_levels_returns_dict(self):
        from kb_loader import get_alert_levels
        assert isinstance(get_alert_levels(), dict)

    def test_infer_archetype_alzheimer(self):
        from kb_loader import infer_archetype
        assert infer_archetype(["alzheimer"], "bonne", 0.5) == "ARCH_ALZ_FALL"

    def test_infer_archetype_bpco(self):
        from kb_loader import infer_archetype
        assert infer_archetype(["bpco"], "bonne", 0.3) == "ARCH_BPCO"

    def test_infer_archetype_hypertension(self):
        from kb_loader import infer_archetype
        assert infer_archetype(["hypertension"], "bonne", 0.2) == "ARCH_STROKE_RISK"

    def test_infer_medications_hypertension(self):
        from kb_loader import infer_medications
        assert "antihypertensives" in infer_medications(["hypertension"])

    def test_infer_medications_alzheimer(self):
        from kb_loader import infer_medications
        assert "anticholinergics" in infer_medications(["alzheimer"])

    def test_infer_medications_dedup(self):
        from kb_loader import infer_medications
        meds = infer_medications(["insuffisance_cardiaque"])
        assert len(meds) == len(set(meds)), "Médicaments dupliqués"

    def test_medication_boost_unknown_class_returns_zero(self):
        from kb_loader import medication_boost
        assert medication_boost("classe_inconnue_xyz", "chute") == 0.0

    def test_official_kb_has_sources(self):
        from kb_loader import get_official_sources
        assert isinstance(get_official_sources(), list)

    def test_scenario_for_archetype_returns_list(self):
        from kb_loader import scenario_for_archetype
        result = scenario_for_archetype("ARCH_ALZ_FALL")
        assert isinstance(result, list)


# ============================================================
# Tests LLMService (fonctions pures, sans Ollama)
# ============================================================

class TestLLMService:

    def setup_method(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

    def _profile(self, pathologies=None):
        return {
            "name": "Test Résident", "age": 82, "room": "101",
            "pathologies": pathologies or ["hypertension"],
            "mobility": "moyenne", "archetype_id": "ARCH_STROKE_RISK",
        }

    def _state(self, spo2=96, hr=72, sys_bp=130, temp=36.7, ml_risk=0.1):
        return {
            "vitals": {"heart_rate": hr, "spo2": spo2, "blood_pressure_sys": sys_bp,
                       "blood_pressure_dia": 80, "temperature": temp, "respiratory_rate": 14},
            "movement": {"last_movement_ago_s": 60, "is_sleeping": False, "is_fall_detected": False},
            "ml_risk": ml_risk,
            "current_zone": "chambre",
        }

    def test_fallback_report_low_risk_vitals(self):
        from llm_service import _structured_fallback_report
        report = _structured_fallback_report("Test", self._profile(), self._state(), [])
        assert report.niveau_risque == "faible"

    def test_fallback_report_high_risk_spo2_and_alert(self):
        from llm_service import _structured_fallback_report
        report = _structured_fallback_report(
            "Test", self._profile(),
            self._state(spo2=87, ml_risk=0.8),
            [{"level": 4, "reason": "SpO2 critique"}]
        )
        assert report.niveau_risque == "eleve"

    def test_fallback_report_has_required_fields(self):
        from llm_service import _structured_fallback_report
        report = _structured_fallback_report("Test", self._profile(), self._state(), [])
        assert report.resume
        assert isinstance(report.points_vigilance, list)
        assert isinstance(report.actions_soignants, list)
        assert report.niveau_risque in ("faible", "modere", "eleve")

    def test_fallback_report_spo2_low_adds_evidence(self):
        from llm_service import _structured_fallback_report
        report = _structured_fallback_report("Test", self._profile(), self._state(spo2=88), [])
        signals = [p["signal"] for p in report.preuves]
        assert any("SpO2" in s or "spo2" in s.lower() for s in signals)

    def test_parse_valid_llm_json(self):
        from llm_service import parse_llm_output
        valid = json.dumps({
            "resume": "Résident stable.",
            "points_vigilance": ["surveiller SpO2"],
            "actions_soignants": ["contrôler constantes"],
            "niveau_risque": "modere",
        })
        report = parse_llm_output(valid, "Test", self._profile(), self._state(), [])
        assert report.niveau_risque == "modere"

    def test_parse_invalid_json_uses_fallback(self):
        from llm_service import parse_llm_output
        report = parse_llm_output("pas du json ici", "Test", self._profile(), self._state(), [])
        assert report.niveau_risque in ("faible", "modere", "eleve")
        assert report.resume

    def test_build_prompt_contains_resident_name(self):
        from llm_service import build_kb_context, build_prompt
        kb_ctx = build_kb_context(["hypertension"], "ARCH_STROKE_RISK", 0.1, 0)
        prompt = build_prompt(self._profile(), self._state(), [], kb_ctx)
        assert "Test" in prompt
        assert "EHPAD" in prompt

    def test_risk_level_eleve_on_high_ml(self):
        from llm_service import _risk_level
        assert _risk_level(0.8, 0) == "eleve"

    def test_risk_level_faible_on_low_everything(self):
        from llm_service import _risk_level
        assert _risk_level(0.1, 0) == "faible"

    def test_risk_level_alert_4_is_eleve(self):
        from llm_service import _risk_level
        assert _risk_level(0.1, 4) == "eleve"

    def test_risk_level_modere_on_mid_ml(self):
        from llm_service import _risk_level
        assert _risk_level(0.5, 0) == "modere"


# ============================================================
# Tests A2AAgents
# ============================================================

class TestA2AAgents:

    def setup_method(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

    def _state(self, ml_risk=0.3, fall=False, spo2=96, hr=72, zone="salle_animation", scenario=None):
        s = {
            "resident_id": "R001",
            "time_of_day": "animation_matin",
            "current_zone": zone,
            "activity": "animation",
            "vitals": {"heart_rate": hr, "spo2": spo2, "blood_pressure_sys": 130,
                       "blood_pressure_dia": 80, "temperature": 36.7, "respiratory_rate": 14},
            "movement": {"last_movement_ago_s": 60, "is_sleeping": False, "is_fall_detected": fall},
            "ml_risk": ml_risk,
        }
        if scenario:
            s["movement_scenario"] = scenario
        return s

    def test_agent_card_has_required_agents(self):
        from a2a_agents import agent_card
        card = agent_card()
        assert "agents" in card
        ids = [a["id"] for a in card["agents"]]
        for expected in ("realtime", "ml", "behavior", "alerts"):
            assert expected in ids, f"Agent '{expected}' manquant"

    def test_realtime_agent_extracts_vitals(self):
        from a2a_agents import realtime_agent
        result = realtime_agent(self._state())
        assert result["agent"] == "realtime"
        assert result["resident_id"] == "R001"
        assert "vitals" in result
        assert result["ml_risk_live"] == 0.3

    def test_realtime_agent_fall_flag(self):
        from a2a_agents import realtime_agent
        result = realtime_agent(self._state(fall=True))
        assert result["movement"]["is_fall_detected"] is True

    def test_ml_agent_returns_clamped_risk(self):
        from a2a_agents import ml_agent
        result = ml_agent(self._state(ml_risk=0.6), {"risk_trend": "hausse", "max_ml_risk": 0.7})
        assert 0.0 <= result["risk_30min"] <= 0.98
        assert 0.0 <= result["risk_60min"] <= 0.98
        assert result["agent"] == "ml"

    def test_ml_agent_hausse_trend_increases_risk(self):
        from a2a_agents import ml_agent
        stable = ml_agent(self._state(ml_risk=0.5), {"risk_trend": "stable", "max_ml_risk": 0.5})
        hausse = ml_agent(self._state(ml_risk=0.5), {"risk_trend": "hausse", "max_ml_risk": 0.5})
        assert hausse["risk_60min"] >= stable["risk_60min"]

    def test_behavior_agent_inactivity_flag(self):
        from a2a_agents import behavior_agent
        state = self._state()
        state["movement"]["last_movement_ago_s"] = 2000
        result = behavior_agent(state, [])
        assert any("inactiv" in f.lower() for f in result["flags"])
        assert result["score"] > 0

    def test_behavior_agent_sensitive_zone_flag(self):
        from a2a_agents import behavior_agent
        result = behavior_agent(self._state(zone="hors_ehpad"), [])
        assert any("zone" in f.lower() for f in result["flags"])

    def test_behavior_agent_normal_state_no_flags(self):
        from a2a_agents import behavior_agent
        result = behavior_agent(self._state(), [])
        assert result["score"] == 0.0

    def test_alert_agent_high_risk_recommends_level(self):
        from a2a_agents import ml_agent, behavior_agent, alert_agent
        ml = ml_agent(self._state(ml_risk=0.9), {"risk_trend": "hausse", "max_ml_risk": 0.9})
        beh = behavior_agent(self._state(ml_risk=0.9, scenario="errance_nuit"), [])
        result = alert_agent(ml, beh, None)
        assert result["recommended_level"] >= 2

    def test_alert_agent_active_alert_4_preserved(self):
        from a2a_agents import ml_agent, behavior_agent, alert_agent
        ml = ml_agent(self._state(ml_risk=0.1), {"risk_trend": "stable", "max_ml_risk": 0.1})
        beh = behavior_agent(self._state(), [])
        result = alert_agent(ml, beh, {"level": 4})
        assert result["recommended_level"] == 4
        assert result["uses_active_alert"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
