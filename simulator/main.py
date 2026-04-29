"""
Simulateur EHPAD - Génère les données de 25 résidents et capteurs ambiants.
Publie sur MQTT : vitaux, accéléromètre, capteurs ambiants (mouvement/portes).
"""

import json
import time
import random
import math
import os
import threading
import logging
from datetime import datetime, timedelta, timezone
import paho.mqtt.client as mqtt
import numpy as np
from profiles import RESIDENTS, ZONES, CAREGIVERS, ROOM_ASSIGNMENTS, RESIDENT_ARCHETYPES, resident_archetype
from facility_map import DINING_SEATS, ROUTINE_LABELS, ROUTINE_TARGETS, SCENARIO_LIBRARY, shortest_path, zone_position
from scenario_scheduler import SCENARIO_RULES, VITAL_SCENARIOS, ScenarioScheduler, resolve_alias

logging.basicConfig(level=logging.INFO, format='%(asctime)s [SIM] %(message)s')
log = logging.getLogger(__name__)

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
NUM_RESIDENTS = int(os.getenv("NUM_RESIDENTS", 25))
DEMO_RESIDENT = os.getenv("DEMO_RESIDENT")
FACILITY_ROOM_COUNT = len(ROOM_ASSIGNMENTS)
SIM_SPEED = float(os.getenv("SIM_SPEED", "1"))
SIM_START_DATETIME = os.getenv("SIM_START_DATETIME", "2026-01-01T07:00:00+01:00")
PUBLISH_LEGACY_TOPICS = os.getenv("PUBLISH_LEGACY_TOPICS", "false").lower() == "true"
ROOM_AMBIENT_INTERVAL_TICKS = int(os.getenv("ROOM_AMBIENT_INTERVAL_TICKS", "10"))


def _parse_sim_start(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        log.warning(f"SIM_START_DATETIME invalide ({value}), fallback 2026-01-01T07:00:00+01:00")
        return datetime(2026, 1, 1, 7, 0, tzinfo=timezone(timedelta(hours=1)))


SIM_START = _parse_sim_start(SIM_START_DATETIME)
SIM_WEEKDAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def sensor_health(sensor_id, sensor_type, active, tick, critical=False):
    """Etat qualite/batterie simule pour rendre les capteurs auditables."""
    offline = (tick + sum(ord(c) for c in sensor_id)) % (1800 if critical else 2400) == 0
    battery = max(8, 100 - ((tick // 90) + sum(ord(c) for c in sensor_id)) % 92)
    quality = 0 if offline else max(58, 99 - ((tick + len(sensor_id) * 7) % 36))
    return {
        "id": sensor_id,
        "type": sensor_type,
        "active": bool(active) and not offline,
        "status": "offline" if offline else "active" if active else "standby",
        "quality_pct": int(quality),
        "battery_pct": int(battery),
        "last_seen_s": None if offline else 0 if active else min(600, (tick * 3 + len(sensor_id)) % 180),
        "critical": critical,
    }


def _load_residents():
    """Charge les profils cliniques JSON si disponibles, sinon utilise profiles.py."""
    patients_path = os.path.join(os.path.dirname(__file__), "patients.json")
    if not os.path.exists(patients_path):
        return RESIDENTS

    try:
        with open(patients_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log.warning(f"Impossible de charger patients.json ({e}); profils Python utilises")
        return RESIDENTS

    residents = []
    for index, patient in enumerate(data.get("residents", [])[:FACILITY_ROOM_COUNT]):
        source_path = os.path.join(os.getenv("PATIENT_DATA_DIR", "/app/data/patients"), patient["id"], "profile.json")
        if os.path.exists(source_path):
            try:
                with open(source_path, encoding="utf-8") as f:
                    source_profile = json.load(f)
                if isinstance(source_profile, dict) and isinstance(source_profile.get("effective"), dict):
                    source_profile = source_profile["effective"]
                if isinstance(source_profile, dict):
                    patient.update(source_profile)
            except Exception as e:
                log.warning(f"[{patient['id']}] Profil JSON source ignore ({e})")
        baseline = patient.get("baseline", {})
        room_plan = ROOM_ASSIGNMENTS[index]
        residents.append({
            "id": patient["id"],
            "name": patient["name"],
            "age": patient.get("age", 80),
            "room": room_plan["room"],
            "floor": room_plan["floor"],
            "zone": room_plan["zone"],
            "wing": room_plan["wing"],
            "room_sensors": room_plan["room_sensors"],
            "pathologies": patient.get("pathologies", []),
            "mobility": patient.get("mobility", "moyenne"),
            "base_hr": baseline.get("heart_rate", 72),
            "base_spo2": baseline.get("spo2", 96),
            "base_bp_sys": baseline.get("blood_pressure_sys", 130),
            "base_bp_dia": baseline.get("blood_pressure_dia", 80),
            "base_temp": baseline.get("temperature", 36.7),
            "base_resp_rate": baseline.get("respiratory_rate", 15),
            "risk_factor": patient.get("risk_factor", 0.3),
            "caregiver": patient.get("caregiver", ""),
            "family_code": patient.get("family_code", ""),
            "avatar": patient.get("avatar", ""),
        })
        archetype = resident_archetype(residents[-1])
        residents[-1]["archetype"] = archetype
        residents[-1]["archetype_label"] = RESIDENT_ARCHETYPES[archetype]["label"]

    log.info(f"{len(residents)} profils residents charges depuis patients.json et affectes au plan {FACILITY_ROOM_COUNT} lits")
    return residents or RESIDENTS


class ResidentSimulator:
    """Simule un résident avec ses constantes vitales et comportements."""

    def __init__(self, profile):
        self.p = profile
        self.id = profile["id"]
        # État interne
        self.malaise_scenario = None   # None | dict en cours
        self.scenario_step = 0
        self.last_movement_time = time.time()
        self.is_sleeping = False
        self.current_location = profile.get("zone", f"ch{profile['room']}")
        self.home_zone = self.current_location
        self.current_zone = self.current_location
        self.target_zone = self.current_zone
        self.route = []
        self.zone_progress = 1.0
        self.position = list(zone_position(self.current_zone))
        self.routine_history = []
        seat = DINING_SEATS[(int(self.id[1:]) - 1) % len(DINING_SEATS)] if self.id[1:].isdigit() else DINING_SEATS[0]
        self.dining_table = seat["table"]
        self.dining_seat = seat["seat"]
        self.dining_position = seat["position"]
        self.care_level = self._care_level()
        self.meal_mode = "chambre" if self.care_level == "chambre" else ("accompagne" if self.care_level == "accompagne" else "salle")
        self.life_archetype = profile.get("archetype") or resident_archetype(profile)
        self.life_profile = RESIDENT_ARCHETYPES.get(self.life_archetype, RESIDENT_ARCHETYPES["autonome"])
        self.last_routine_period = None
        self.last_meal_risk_tick = -9999
        # Paramètres courants (dérivent progressivement)
        self.hr = profile["base_hr"]
        self.spo2 = profile["base_spo2"]
        self.bp_sys = profile["base_bp_sys"]
        self.bp_dia = profile.get("base_bp_dia", 80)
        self.temp = profile["base_temp"]
        self.resp_rate = profile.get("base_resp_rate", 15)
        self.accel_magnitude = 0.1
        self.gyro_magnitude = 0.0
        self.altitude_drop_cm = 0
        self.door_open = False
        self.sos_pressed = False
        self.ambient_fall_confirmed = False
        self.current_activity = "repos"
        self.movement_scenario = None
        self.scenario_scheduler = ScenarioScheduler()
        self.assigned_scenarios = self._scenario_pool_for_profile()
        self.assigned_movement_scenario = self.assigned_scenarios[0]
        self.next_forced_movement_tick = random.randint(900, 2400)
        self.fall_started_tick = None
        self._tick = 0
        if DEMO_RESIDENT == self.id:
            self.start_scenario("hypoxie", duration=3600)

    def _scenario_pool_for_profile(self):
        """Construit plusieurs scenarios plausibles pour le resident."""
        known = {item["type"] for item in SCENARIO_LIBRARY}
        configured = [s for s in self.p.get("assigned_scenarios", []) if s in known]
        scenarios = list(configured)

        scenario_index = (int(self.id[1:]) - 1) % len(SCENARIO_LIBRARY) if self.id[1:].isdigit() else 0
        scenarios.append(SCENARIO_LIBRARY[scenario_index]["type"])
        scenarios += ["sortie_patio", "promenade_jardin", "isolement_chambre"]

        pathologies = set(self.p.get("pathologies", []))
        mobility = self.p.get("mobility", "moyenne")
        risk = float(self.p.get("risk_factor", 0.3))

        if self.care_level == "chambre":
            scenarios += ["isolement_chambre", "chute_chambre", "chute_salle_bain", "toilette_matinale_fatigue"]
        if mobility in {"faible", "tres_faible"}:
            scenarios += ["chute_couloir", "chute_trajet_repas", "aller_toilettes_nuit", "desorientation_ascenseur"]
        if "alzheimer" in pathologies or "demence" in pathologies:
            scenarios += ["errance_nuit", "fugue_hors_ehpad", "desorientation_ascenseur", "desorientation_patio", "isolement_chambre"]
        if "bpco" in pathologies:
            scenarios += ["retour_kine_fatigue", "malaise_retour_repas", "regroupement_patio_fatigue", "promenade_jardin"]
        if "insuffisance_cardiaque" in pathologies or "hypertension" in pathologies:
            scenarios += ["malaise_salle_manger", "malaise_retour_repas", "retour_kine_fatigue", "chute_trajet_repas"]
        if risk >= 0.55:
            scenarios += ["chute_chambre", "immobilite_salle_repos", "sortie_jardin_non_accompagnee"]
        if mobility == "bonne" and risk < 0.3:
            scenarios += ["promenade_jardin", "sortie_patio", "desorientation_patio"]

        deduped = []
        for scenario in scenarios:
            if scenario in known and scenario not in deduped:
                deduped.append(scenario)
        return deduped[:6] or [SCENARIO_LIBRARY[scenario_index]["type"]]

    def _care_level(self):
        """Autonomie de deplacement: certains residents restent en chambre."""
        mobility = self.p.get("mobility", "moyenne")
        risk = float(self.p.get("risk_factor", 0.3))
        pathologies = set(self.p.get("pathologies", []))
        rid_num = int(self.id[1:]) if self.id[1:].isdigit() else 0
        very_fragile = mobility == "tres_faible" and (risk >= 0.65 or {"parkinson", "insuffisance_cardiaque"} & pathologies or rid_num % 3 == 0)
        if very_fragile:
            return "chambre"
        if mobility in {"tres_faible", "faible"}:
            return "accompagne"
        return "autonome"

    def _meal_target(self):
        return self.home_zone if self.meal_mode == "chambre" else "salle_manger"

    def start_scenario(self, scenario_type, duration=None):
        """Demarre explicitement un scenario de malaise pour ce resident."""
        scenario_type = resolve_alias(scenario_type)
        self.malaise_scenario = {
            "type": scenario_type,
            "start_tick": self._tick,
            "duration": duration or random.randint(120, 600),
        }
        self.scenario_scheduler.register_forced(scenario_type, self._tick)
        log.warning(f"[{self.id}] Scenario declenche: {scenario_type}")

    def force_validation_scenario(self, scenario_type):
        """Commande de demo depuis le dashboard."""
        if scenario_type in {"hypoxie", "tachycardie", "chute", "hypotension", "fievre"}:
            self.start_scenario(scenario_type, duration=360 if scenario_type != "chute" else 90)
            return
        mapping = {
            "chute_couloir": "chute_couloir",
            "fugue_hors_ehpad": "fugue_hors_ehpad",
            "malaise_repas": "malaise_salle_manger",
            "risque_nuit": "aller_toilettes_nuit",
            "jardin": "promenade_jardin",
            "chute_jardin": "chute_jardin",
        }
        self.movement_scenario = resolve_alias(mapping.get(scenario_type, scenario_type))
        self.scenario_scheduler.register_forced(self.movement_scenario, self._tick)
        self.fall_started_tick = None
        self.next_forced_movement_tick = self._tick
        log.warning(f"[{self.id}] Scenario validation force: {self.movement_scenario}")

    def apply_profile_update(self, profile_update):
        """Applique une configuration live envoyee par le backend."""
        allowed = {
            "age", "pathologies", "mobility", "risk_factor", "caregiver",
            "meal_mode", "care_level", "assigned_scenarios", "notes",
        }
        for key, value in (profile_update or {}).items():
            if key in allowed and value is not None:
                self.p[key] = value
        self.care_level = self.p.get("care_level") or self._care_level()
        self.meal_mode = self.p.get("meal_mode") or ("chambre" if self.care_level == "chambre" else ("accompagne" if self.care_level == "accompagne" else "salle"))
        self.life_archetype = resident_archetype(self.p)
        self.life_profile = RESIDENT_ARCHETYPES.get(self.life_archetype, RESIDENT_ARCHETYPES["autonome"])
        self.assigned_scenarios = self._scenario_pool_for_profile()
        self.assigned_movement_scenario = self.assigned_scenarios[0]
        self.p["assigned_scenarios"] = self.assigned_scenarios
        log.info(f"[{self.id}] Profil simulateur mis a jour: mobilite={self.p.get('mobility')} risque={self.p.get('risk_factor')} scenarios={self.assigned_scenarios}")

    def _simulated_minute(self):
        """Minute dans la journee simulee; la date simulee continue d'avancer."""
        dt = self._simulated_datetime()
        return dt.hour * 60 + dt.minute

    def _simulated_datetime(self):
        """Une minute simulee par tick, sans reboucler sur la meme date."""
        return SIM_START + timedelta(minutes=self._tick)

    def _simulated_calendar(self):
        dt = self._simulated_datetime()
        day_index = max(0, (dt.date() - SIM_START.date()).days)
        return {
            "timestamp_simulated": dt.isoformat(),
            "simulated_datetime": dt.isoformat(),
            "simulated_date": dt.date().isoformat(),
            "simulated_time": f"{dt.hour:02d}:{dt.minute:02d}",
            "simulated_weekday": SIM_WEEKDAYS_FR[dt.weekday()],
            "simulated_day_index": day_index,
            "simulated_label": f"J+{day_index} · {SIM_WEEKDAYS_FR[dt.weekday()]} {dt.strftime('%d/%m/%Y')} {dt.strftime('%H:%M')}",
        }

    def _time_of_day_factor(self):
        """Phase de vie quotidienne inspiree d'une journee type en EHPAD."""
        m = self._simulated_minute()
        if 6 * 60 <= m < 7 * 60 + 30: return "lever_toilette"
        if 7 * 60 + 30 <= m < 9 * 60: return "petit_dej"
        if 9 * 60 <= m < 10 * 60: return "soins_matin"
        if 10 * 60 <= m < 11 * 60 + 45: return "animation_matin"
        if 11 * 60 + 45 <= m < 12 * 60: return "trajet_dejeuner"
        if 12 * 60 <= m < 13 * 60 + 15: return "dejeuner"
        if 13 * 60 + 15 <= m < 15 * 60: return "sieste"
        if 15 * 60 <= m < 16 * 60: return "animation_apres_midi"
        if 16 * 60 <= m < 16 * 60 + 45: return "gouter"
        if 16 * 60 + 45 <= m < 18 * 60: return "animation_apres_midi"
        if 18 * 60 <= m < 18 * 60 + 30: return "trajet_diner"
        if 18 * 60 + 30 <= m < 19 * 60 + 30: return "diner"
        if 19 * 60 + 30 <= m < 20 * 60 + 30: return "soiree"
        if 20 * 60 + 30 <= m < 22 * 60: return "coucher"
        return "nuit"

    def _simulated_clock_label(self):
        return self._simulated_calendar()["simulated_time"]

    def _routine_label(self):
        tod = self._time_of_day_factor()
        label = ROUTINE_LABELS.get(tod, tod)
        if self.meal_mode == "chambre" and tod in {"petit_dej", "dejeuner", "gouter", "diner", "trajet_dejeuner", "trajet_diner"}:
            return {
                "petit_dej": "Petit dejeuner en chambre",
                "dejeuner": "Dejeuner en chambre",
                "gouter": "Gouter en chambre",
                "diner": "Diner en chambre",
                "trajet_dejeuner": "Preparation du repas en chambre",
                "trajet_diner": "Preparation du diner en chambre",
            }[tod]
        if self.meal_mode == "accompagne" and tod in {"petit_dej", "dejeuner", "gouter", "diner", "trajet_dejeuner", "trajet_diner"}:
            return f"{label} accompagne"
        return label

    def _routine_context(self):
        tod = self._time_of_day_factor()
        meal_periods = {"petit_dej", "dejeuner", "gouter", "diner"}
        transfer_periods = {"lever_toilette", "trajet_dejeuner", "trajet_diner", "coucher"}
        if tod in meal_periods:
            grouping = "repas_chambre" if self.meal_mode == "chambre" else "regroupement_repas"
        elif tod in {"animation_matin", "animation_apres_midi"}:
            grouping = "animation_groupe"
        elif tod in {"nuit", "sieste", "coucher"}:
            grouping = "repos_chambre"
        elif tod in transfer_periods:
            grouping = "transfert_zone_sensible"
        else:
            grouping = "routine_soins"
        sim_calendar = self._simulated_calendar()
        real_timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "period": tod,
            "label": self._routine_label(),
            "grouping": grouping,
            "archetype": self.life_archetype,
            "archetype_label": self.life_profile["label"],
            "daily_focus": self.life_profile["daily_focus"],
            "main_risks": self.life_profile["main_risks"],
            "supervision": self.life_profile["supervision"],
            "meal_mode": self.meal_mode,
        }

    def _maybe_trigger_scenario(self):
        """Declenche un scenario vital rare, pondere par profil et heure."""
        if self.malaise_scenario:
            return
        chosen = self.scenario_scheduler.choose(
            self.p,
            sorted(VITAL_SCENARIOS),
            self._time_of_day_factor(),
            self._tick,
            kind="vital",
        )
        if chosen:
            self.start_scenario(chosen)
            log.warning(f"[{self.id}] Scenario vital pondere: {chosen}")
    def _apply_scenario(self):
        """Dégrade progressivement les constantes selon le scénario actif."""
        if not self.malaise_scenario:
            return
        s = self.malaise_scenario
        elapsed = self._tick - s["start_tick"]
        progress = min(elapsed / s["duration"], 1.0)

        if s["type"] == "hypoxie":
            severe_demo = DEMO_RESIDENT == self.id
            self.spo2 = max(82 if severe_demo else 88, self.p["base_spo2"] - progress * (15 if severe_demo else 7))
            self.hr = min(130 if severe_demo else 112, self.p["base_hr"] + progress * (40 if severe_demo else 18))
            self.resp_rate = min(32 if severe_demo else 23, self.p.get("base_resp_rate", 15) + progress * (10 if severe_demo else 4))
        elif s["type"] == "tachycardie":
            self.hr = min(138, self.p["base_hr"] + progress * 45)
            self.bp_sys = min(185, self.p["base_bp_sys"] + progress * 35)
        elif s["type"] == "chute":
            if progress > 0.05:
                self.accel_magnitude = random.uniform(8.0, 15.0) if progress < 0.1 else 0.0
                self.gyro_magnitude = random.uniform(180, 420) if progress < 0.1 else 0.0
                self.altitude_drop_cm = random.randint(60, 115) if progress < 0.1 else 0
                if progress >= 0.1:
                    self.last_movement_time = min(self.last_movement_time, time.time() - 45)
            self.hr = min(120, self.p["base_hr"] + progress * 30)
        elif s["type"] == "hypotension":
            self.bp_sys = max(85, self.p["base_bp_sys"] - progress * 38)
            self.hr = min(112, self.p["base_hr"] + progress * 16)
        elif s["type"] == "fievre":
            self.temp = min(39.2, self.p["base_temp"] + progress * 2.0)
            self.hr = min(118, self.p["base_hr"] + progress * 22)

        # Fin du scénario : récupération progressive
        if progress >= 1.0:
            log.info(f"[{self.id}] Scénario {s['type']} terminé")
            self.malaise_scenario = None

    def _circadian_offsets(self):
        """Modulation circadienne realiste des constantes vitales sur 24h."""
        m = self._simulated_minute()
        h = m / 60.0
        # PA: pic matinal 8h (+12 mmHg), creux nocturne 4h (-10 mmHg)
        bp_off = (
            12 * math.exp(-0.5 * ((h - 8) / 2.0) ** 2)
            + 6 * math.exp(-0.5 * ((h - 14) / 2.0) ** 2)
            - 10 * math.exp(-0.5 * ((h - 4) / 1.5) ** 2)
        )
        # FC: creux nocturne 4h (-8 bpm), pics post-repas midi/soir (+5 bpm)
        hr_off = (
            -8 * math.exp(-0.5 * ((h - 4) / 2.0) ** 2)
            + 5 * math.exp(-0.5 * ((h - 12.5) / 1.2) ** 2)
            + 4 * math.exp(-0.5 * ((h - 18.5) / 1.2) ** 2)
        )
        # Temperature: creux 4h (-0.4C), pic 17h (+0.4C)
        if 4 <= h < 17:
            temp_off = 0.4 * math.sin(math.pi * (h - 4) / 13.0)
        else:
            ref = h - 4 if h < 12 else h - 28
            temp_off = -0.3 * math.exp(-0.5 * (ref / 2.0) ** 2)
        # SpO2: apnee du sommeil pour residents a risque (cycles ~7 min)
        spo2_off = 0.0
        if self.is_sleeping and self.p.get("risk_factor", 0) > 0.4:
            cycle = math.sin(2 * math.pi * m / 7.0)
            spo2_off = -2.5 * max(0.0, -cycle) * min(1.0, self.p["risk_factor"] * 1.5)
        return hr_off, bp_off, temp_off, spo2_off

    def _recover_to_baseline(self):
        """Retour progressif aux valeurs de base, avec rythme circadien."""
        factor = 0.05
        hr_off, bp_off, temp_off, spo2_off = self._circadian_offsets()
        self.hr += (self.p["base_hr"] + hr_off - self.hr) * factor
        self.spo2 += (self.p["base_spo2"] + spo2_off - self.spo2) * factor
        self.bp_sys += (self.p["base_bp_sys"] + bp_off - self.bp_sys) * factor
        self.bp_dia += (self.p.get("base_bp_dia", 80) + bp_off * 0.5 - self.bp_dia) * factor
        self.temp += (self.p["base_temp"] + temp_off - self.temp) * factor
        rr_base = self.p.get("base_resp_rate", 15) + (1.5 if self.is_sleeping and self.p.get("risk_factor", 0) > 0.5 else 0)
        self.resp_rate += (rr_base - self.resp_rate) * factor
        self.gyro_magnitude *= 0.75
        self.altitude_drop_cm = 0
        self.sos_pressed = random.random() < self.p["risk_factor"] * 0.00008

    def _add_noise(self, value, sigma):
        return value + np.random.normal(0, sigma)

    def _choose_destination(self):
        tod = self._time_of_day_factor()
        targets = ROUTINE_TARGETS.get(tod, ["home"])
        pathologies = self.p["pathologies"]

        if self.care_level == "chambre":
            return self.home_zone

        if tod == "nuit" and "alzheimer" in pathologies and random.random() < 0.012:
            self.movement_scenario = "errance_nuit"
            return random.choice(["couloir_principal", "entree", "patio"])

        if self.movement_scenario in {
            "chute_couloir", "malaise_salle_manger", "sortie_patio", "immobilite_salle_repos",
            "aller_toilettes_nuit", "desorientation_ascenseur", "agitation_couloir",
            "isolement_chambre", "retour_kine_fatigue", "promenade_jardin",
            "sortie_jardin_non_accompagnee", "chute_jardin", "fugue_hors_ehpad",
            "chute_trajet_repas", "desorientation_avant_repas", "malaise_retour_repas",
            "chute_salle_bain", "toilette_matinale_fatigue", "desorientation_patio",
            "regroupement_patio_fatigue", "retour_jardin_fatigue",
        }:
            return {
                "chute_couloir": random.choice(["couloir_aile_rdc", "couloir_principal", "couloir_aile_a_etage", "couloir_aile_b_etage"]),
                "chute_salle_bain": self.home_zone,
                "toilette_matinale_fatigue": self.home_zone,
                "malaise_salle_manger": "salle_manger",
                "sortie_patio": "patio",
                "desorientation_patio": "patio",
                "regroupement_patio_fatigue": "patio",
                "immobilite_salle_repos": "salle_repos",
                "aller_toilettes_nuit": random.choice(["couloir_principal", "couloir_aile_rdc", "couloir_aile_a_etage", "couloir_aile_b_etage"]),
                "desorientation_ascenseur": random.choice(["ascenseur", "palier_etage", "escalier"]),
                "agitation_couloir": random.choice(["couloir_principal", "couloir_aile_rdc", "couloir_aile_a_etage", "couloir_aile_b_etage"]),
                "isolement_chambre": self.home_zone,
                "retour_kine_fatigue": random.choice(["kinesitherapie", "salle_repos"]),
                "promenade_jardin": "jardin",
                "retour_jardin_fatigue": random.choice(["patio", "salle_commune"]),
                "sortie_jardin_non_accompagnee": random.choice(["jardin", "entree"]),
                "chute_jardin": "jardin",
                "fugue_hors_ehpad": "hors_ehpad",
                "chute_trajet_repas": random.choice(["couloir_principal", "couloir_aile_rdc", "couloir_aile_a_etage", "couloir_aile_b_etage", "ascenseur"]),
                "desorientation_avant_repas": random.choice(["ascenseur", "palier_etage", "couloir_principal"]),
                "malaise_retour_repas": random.choice(["salle_manger", "couloir_principal"]),
            }[self.movement_scenario]

        target = random.choice(targets)
        if target == "home":
            return self.home_zone
        if target in ["kinesitherapie", "salle_repos"] and self.p.get("floor", 0) == 0 and random.random() < 0.55:
            return "salle_commune"
        if target in ["patio", "jardin"] and self.p["mobility"] in ["faible", "tres_faible"] and random.random() < 0.65:
            return "salle_commune"
        return target

    def _maybe_start_movement_scenario(self):
        """Declenche un scenario de mouvement selon un scheduler pondere."""
        if self.movement_scenario or self.malaise_scenario:
            return
        chosen = self.scenario_scheduler.choose(
            self.p,
            self.assigned_scenarios,
            self._time_of_day_factor(),
            self._tick,
            kind="movement",
        )
        if not chosen:
            return
        self.movement_scenario = chosen
        self.assigned_movement_scenario = chosen
        self.next_forced_movement_tick = self._tick + random.randint(900, 2400)
        log.info(f"[{self.id}] Scenario mouvement pondere: {self.movement_scenario}")
    def _set_route_to(self, target):
        self.target_zone = target
        self.route = shortest_path(self.current_zone, target)[1:]
        self.zone_progress = 0.0

    def _update_navigation(self):
        self._maybe_start_movement_scenario()
        tod = self._time_of_day_factor()
        if self.care_level == "chambre":
            if self.movement_scenario == "chute_chambre" and self.fall_started_tick is None:
                self.start_scenario("chute", duration=90)
                self.fall_started_tick = self._tick
            elif self.movement_scenario == "chute_salle_bain" and self.fall_started_tick is None:
                self.current_activity = "toilette"
                self.start_scenario("chute", duration=90)
                self.fall_started_tick = self._tick
            elif self.movement_scenario == "toilette_matinale_fatigue":
                self.current_activity = "toilette"
                self.hr = min(112, self.hr + random.randint(6, 14))
                self.last_movement_time = time.time()
            elif self.movement_scenario == "isolement_chambre":
                self.last_movement_time = time.time() - random.randint(2100, 5400)
            self.current_zone = self.home_zone
            self.current_location = self.home_zone
            self.target_zone = self.home_zone
            self.route = []
            self.zone_progress = 1.0
            self.position = list(zone_position(self.home_zone))
            self.current_activity = "repas_en_chambre" if tod in {"petit_dej", "dejeuner", "gouter", "diner"} else ("immobile" if self.is_sleeping else "repos_chambre")
            return
        if tod != self.last_routine_period:
            self.last_routine_period = tod
            if tod in {"petit_dej", "trajet_dejeuner", "dejeuner", "gouter", "trajet_diner", "diner"}:
                self._set_route_to(self._meal_target())
            elif tod in {"sieste", "coucher", "nuit"}:
                self._set_route_to(self.home_zone)
            elif tod == "soins_matin" and self.p["mobility"] in {"faible", "tres_faible"} and random.random() < 0.45:
                self._set_route_to(random.choice(["infirmerie_rdc", "kinesitherapie"]))
            elif tod in {"animation_matin", "animation_apres_midi"} and random.random() < 0.38:
                self._set_route_to("patio")
            return
        if self.movement_scenario in {"chute_salle_bain", "toilette_matinale_fatigue"} and self.current_zone == self.home_zone:
            self.current_activity = "toilette"
            self.position = list(zone_position(self.home_zone))
            self._on_arrival()
            return
        if not self.route and random.random() < 0.035:
            self._set_route_to(self._choose_destination())

        if not self.route:
            self.position = list(self.dining_position if self.current_zone == "salle_manger" else zone_position(self.current_zone))
            if self.current_zone == self.home_zone and tod in {"petit_dej", "dejeuner", "gouter", "diner"} and self.meal_mode == "chambre":
                self.current_activity = "repas_en_chambre"
            else:
                self.current_activity = "immobile" if self.is_sleeping else "repos"
            return

        next_zone = self.route[0]
        start = zone_position(self.current_zone)
        end = zone_position(next_zone)
        speed_factor = {"bonne": 0.18, "moyenne": 0.12, "faible": 0.08, "tres_faible": 0.045}.get(self.p["mobility"], 0.1)
        self.zone_progress = min(1.0, self.zone_progress + speed_factor)
        self.position = [
            start[0] + (end[0] - start[0]) * self.zone_progress,
            start[1] + (end[1] - start[1]) * self.zone_progress,
            round(start[2] + (end[2] - start[2]) * self.zone_progress),
        ]
        self.current_activity = "deplacement"
        self.last_movement_time = time.time()

        if self.zone_progress >= 1.0:
            self.current_zone = next_zone
            self.current_location = next_zone
            if self.current_zone == "salle_manger":
                self.position = list(self.dining_position)
            self.route.pop(0)
            self.zone_progress = 0.0
            if not self.route:
                self._on_arrival()

    def _on_arrival(self):
        if self.movement_scenario in ["chute_couloir", "chute_chambre", "chute_salle_bain"] and self.fall_started_tick is None:
            self.start_scenario("chute", duration=90)
            self.fall_started_tick = self._tick
        elif self.movement_scenario == "malaise_salle_manger":
            self.start_scenario(random.choice(["hypoxie", "hypotension", "tachycardie"]), duration=420)
        elif self.movement_scenario == "immobilite_salle_repos":
            self.last_movement_time = time.time() - random.randint(1900, 4200)
            self.current_activity = "immobilite_anormale"
        elif self.movement_scenario == "sortie_patio":
            self.sos_pressed = random.random() < 0.1
        elif self.movement_scenario == "desorientation_patio":
            self.hr = min(118, self.hr + random.randint(8, 16))
            self.sos_pressed = random.random() < 0.06
        elif self.movement_scenario == "regroupement_patio_fatigue":
            self.hr = min(116, self.hr + random.randint(6, 14))
            self.spo2 = max(90, self.spo2 - random.uniform(0.8, 2.2))
        elif self.movement_scenario == "aller_toilettes_nuit":
            self.last_movement_time = time.time()
        elif self.movement_scenario == "desorientation_ascenseur":
            self.sos_pressed = random.random() < 0.04
        elif self.movement_scenario == "agitation_couloir":
            self.hr = min(125, self.hr + random.randint(8, 18))
            self.accel_magnitude = max(self.accel_magnitude, random.uniform(2.0, 4.5))
        elif self.movement_scenario == "isolement_chambre":
            self.last_movement_time = time.time() - random.randint(2100, 5400)
        elif self.movement_scenario == "retour_kine_fatigue":
            self.hr = min(118, self.hr + random.randint(10, 22))
            self.spo2 = max(90, self.spo2 - random.uniform(1.0, 3.0))
        elif self.movement_scenario == "promenade_jardin":
            self.last_movement_time = time.time()
        elif self.movement_scenario == "retour_jardin_fatigue":
            self.hr = min(120, self.hr + random.randint(8, 20))
            self.spo2 = max(89, self.spo2 - random.uniform(1.0, 3.0))
        elif self.movement_scenario == "sortie_jardin_non_accompagnee":
            self.sos_pressed = random.random() < 0.08
        elif self.movement_scenario == "chute_jardin":
            self.start_scenario("chute", duration=90)
            self.fall_started_tick = self._tick
        elif self.movement_scenario == "fugue_hors_ehpad":
            self.sos_pressed = False
        elif self.movement_scenario == "chute_trajet_repas":
            self.start_scenario("chute", duration=90)
            self.fall_started_tick = self._tick
        elif self.movement_scenario in ["desorientation_avant_repas", "malaise_retour_repas"]:
            if random.random() < 0.55:
                self.start_scenario(random.choice(["hypotension", "tachycardie", "hypoxie"]), duration=360)
        self.movement_scenario = None

    def _compute_movement(self):
        """Simule les mouvements selon l'heure et l'état."""
        tod = self._time_of_day_factor()
        mobility_factor = {"bonne": 1.0, "moyenne": 0.6, "faible": 0.3, "tres_faible": 0.1}
        mob = mobility_factor.get(self.p["mobility"], 0.5)

        if tod in ["nuit", "sieste"]:
            self.is_sleeping = True
            if not (self.malaise_scenario and self.malaise_scenario.get("type") == "chute"):
                self.accel_magnitude = abs(np.random.normal(0, 0.05))
                self.gyro_magnitude = abs(np.random.normal(0, 1.5))
        else:
            self.is_sleeping = False
            if self.malaise_scenario and self.malaise_scenario.get("type") == "chute":
                return
            if random.random() < mob * 0.1:
                self.accel_magnitude = np.random.uniform(0.2, 2.5)
                self.gyro_magnitude = np.random.uniform(8, 80)
                self.last_movement_time = time.time()
            else:
                self.accel_magnitude = max(0, self.accel_magnitude * 0.8 + np.random.normal(0, 0.02))
                self.gyro_magnitude = max(0, self.gyro_magnitude * 0.8 + np.random.normal(0, 0.5))

    def tick(self):
        """Calcule l'état pour ce tick."""
        self._tick += 1
        self._maybe_trigger_scenario()

        if self.malaise_scenario:
            self._apply_scenario()
        else:
            self._recover_to_baseline()

        self._update_navigation()
        self._compute_movement()

        # Détection de chute : pic d'accélération brutal
        is_fall = self.accel_magnitude > 7.0
        room_sensors = self.p.get("room_sensors", [])
        is_in_room = self.current_zone == self.home_zone
        in_bathroom_risk_period = self._time_of_day_factor() in {"lever_toilette", "coucher", "nuit"}
        bathroom_motion = bool("sdb_pir" in room_sensors and is_in_room and (
            self.current_activity == "deplacement"
            or self.current_activity == "toilette"
            or self.movement_scenario in {"aller_toilettes_nuit", "chute_chambre", "chute_salle_bain", "toilette_matinale_fatigue"}
            or (in_bathroom_risk_period and random.random() < 0.08)
        ))
        sensor_events = {
            "room_pir_motion": bool("pir" in room_sensors and is_in_room and (self.current_activity == "deplacement" or self.accel_magnitude > 0.35)),
            "room_radar_presence": bool("radar" in room_sensors and is_in_room),
            "bed_occupied": bool("matelas" in room_sensors and is_in_room and self.is_sleeping and not is_fall),
            "mattress_exit": bool("matelas" in room_sensors and not is_in_room),
            "door_open": bool("porte" in room_sensors and (self.current_activity == "deplacement" or not is_in_room)),
            "bathroom_motion": bathroom_motion,
            "floor_pressure_event": bool(("sol" in room_sensors or "sol_intelligent" in room_sensors or "matelas" in room_sensors) and is_fall),
            "fall_confirmed_by_room_sensor": bool(is_fall and (("radar" in room_sensors) or ("matelas" in room_sensors) or bathroom_motion)),
        }
        sensor_health_items = [
            sensor_health(f"{self.id}-wearable", "wearable_vitaux", True, self._tick, critical=True),
            sensor_health(f"ch{self.p['room']}-pir", "pir_presence", sensor_events["room_pir_motion"], self._tick),
            sensor_health(f"ch{self.p['room']}-radar", "radar_presence", sensor_events["room_radar_presence"], self._tick),
            sensor_health(f"ch{self.p['room']}-porte", "porte", sensor_events["door_open"], self._tick),
            sensor_health(f"ch{self.p['room']}-sdb-pir", "sdb_pir", sensor_events["bathroom_motion"], self._tick, critical=True),
            sensor_health(f"ch{self.p['room']}-matelas", "matelas_lit", sensor_events["bed_occupied"] or sensor_events["mattress_exit"], self._tick, critical=True),
            sensor_health(f"ch{self.p['room']}-sol", "sol_pression", sensor_events["floor_pressure_event"], self._tick, critical=True),
        ]
        routine_context = self._routine_context()
        self.ambient_fall_confirmed = bool(is_fall and self.current_zone in {
            "couloir_principal", "couloir_aile_rdc", "couloir_aile_a_etage",
            "couloir_aile_b_etage", "salle_commune", "salle_manger", "salle_repos", "jardin", "patio"
        }) or sensor_events["fall_confirmed_by_room_sensor"]
        sim_calendar = self._simulated_calendar()
        real_timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        return {
            "resident_id": self.id,
            "name": self.p["name"],
            "avatar": self.p.get("avatar", ""),
            "room": self.p["room"],
            "floor": self.p.get("floor", 0),
            "zone": self.p.get("zone", f"ch{self.p['room']}"),
            "wing": self.p.get("wing", "rdc"),
            "room_sensors": self.p.get("room_sensors", ["wearable"]),
            "pathologies": self.p.get("pathologies", []),
            "mobility": self.p.get("mobility", "moyenne"),
            "risk_factor": self.p.get("risk_factor", 0.3),
            "life_profile": routine_context,
            "baseline": {
                "heart_rate": self.p.get("base_hr"),
                "spo2": self.p.get("base_spo2"),
                "blood_pressure_sys": self.p.get("base_bp_sys"),
                "temperature": self.p.get("base_temp"),
                "respiratory_rate": self.p.get("base_resp_rate"),
            },
            "current_zone": self.current_zone,
            "target_zone": self.target_zone,
            "position": {"x": round(self.position[0], 2), "z": round(self.position[1], 2), "floor": int(self.position[2])},
            "activity": self.current_activity,
            "sensor_events": sensor_events,
            "sensor_health": sensor_health_items,
            "timestamp": real_timestamp,
            "timestamp_real": real_timestamp,
            **sim_calendar,
            "vitals": {
                "heart_rate": round(self._add_noise(self.hr, 1.5)),
                "spo2": round(min(100, max(70, self._add_noise(self.spo2, 0.3))), 1),
                "blood_pressure_sys": round(self._add_noise(self.bp_sys, 3)),
                "blood_pressure_dia": round(self._add_noise(self.bp_dia, 2)),
                "temperature": round(self._add_noise(self.temp, 0.05), 1),
                "respiratory_rate": round(self._add_noise(self.resp_rate, 0.8)),
                "ecg_rhythm": "atrial_fibrillation" if self.hr > 130 and random.random() < 0.08 else "sinus",
            },
            "movement": {
                "accel_magnitude": round(self.accel_magnitude, 3),
                "gyro_magnitude_dps": round(self.gyro_magnitude, 1),
                "altitude_drop_cm": self.altitude_drop_cm,
                "is_fall_detected": is_fall,
                "ambient_fall_confirmed": self.ambient_fall_confirmed,
                "last_movement_ago_s": round(time.time() - self.last_movement_time),
                "is_sleeping": self.is_sleeping,
                "sos_pressed": self.sos_pressed,
                "sensor_events": sensor_events,
                "sensor_health": sensor_health_items,
            },
            "location": self.current_location,
            "scenario_active": self.malaise_scenario["type"] if self.malaise_scenario else None,
            "movement_scenario": self.movement_scenario,
            "assigned_movement_scenario": self.assigned_movement_scenario,
            "assigned_scenarios": self.assigned_scenarios,
            "time_of_day": self._time_of_day_factor(),
            "time_label": self._simulated_clock_label(),
            "routine_label": routine_context["label"],
            "routine_context": routine_context,
            "care_level": self.care_level,
            "meal_mode": self.meal_mode,
            "dining_table": self.dining_table,
            "dining_seat": self.dining_seat,
            "caregiver": self.p["caregiver"],
        }


class AmbientSensorSimulator:
    """Simule les capteurs ambiants : mouvement zones, portes, activité."""

    def __init__(self, zones):
        self.zones = zones
        self.zone_occupancy = {z["id"]: 0 for z in zones}
        self.door_states = {}

    def tick(self, residents_states):
        """Met a jour les capteurs selon les residents reellement presents."""
        results = []
        sim_ref = residents_states[0] if residents_states else {}
        timestamp_real = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for z in self.zones:
            sensors = z.get("sensors", [])
            present = [s for s in residents_states if s.get("current_zone") == z["id"] or s.get("location") == z["id"]]
            moving = [s for s in present if s.get("activity") == "deplacement"]
            fallen = [s for s in present if s.get("movement", {}).get("is_fall_detected")]
            immobile_low = [
                s for s in present
                if s.get("movement", {}).get("ambient_fall_confirmed")
                or s.get("movement", {}).get("last_movement_ago_s", 0) > 1800
            ]
            occ = len(present)
            door_open = bool("porte" in sensors and (moving or (z["type"] in ["entree", "exterieur", "exterieur_hors_site"] and present)))
            self.zone_occupancy[z["id"]] = occ
            results.append({
                "zone_id": z["id"],
                "zone_name": z["name"],
                "zone_type": z["type"],
                "floor": z["floor"],
            "sensors": sensors,
            "sensor_health": [
                sensor_health(
                    f"{z['id']}-{sensor}",
                    sensor,
                    bool(door_open if sensor == "porte" else occ > 0 or sensor in {"co2", "son", "temperature"}),
                    int(time.time()) + len(z["id"]),
                    critical=(sensor == "porte"),
                )
                for sensor in sensors
            ],
            "timestamp": timestamp_real,
            "timestamp_real": timestamp_real,
            "timestamp_simulated": sim_ref.get("timestamp_simulated"),
            "simulated_datetime": sim_ref.get("simulated_datetime"),
            "simulated_date": sim_ref.get("simulated_date"),
            "simulated_time": sim_ref.get("simulated_time"),
            "simulated_weekday": sim_ref.get("simulated_weekday"),
            "simulated_day_index": sim_ref.get("simulated_day_index"),
                "occupancy": occ,
                "resident_ids": [s["resident_id"] for s in present],
                "ble_seen": [s["resident_id"] for s in present] if any("ble" in sensor or "badge" in sensor for sensor in sensors) else [],
                "motion_detected": bool(moving or occ > 0),
                "last_motion_ago_s": random.randint(0, 60) if occ > 0 else random.randint(60, 3600),
                "floor_pressure_event": bool(fallen and any(sensor in sensors for sensor in ["sol", "sol_intelligent", "sol_capteur"])),
                "radar_immobile_low": bool(immobile_low and any("radar" in sensor for sensor in sensors)),
                "fall_confirmed": bool(fallen and (any(sensor in sensors for sensor in ["sol", "sol_intelligent", "sol_capteur"]) or any("radar" in sensor for sensor in sensors))),
                "temperature_c": round(random.uniform(19.0, 24.5), 1),
                "humidity_pct": round(random.uniform(35, 58), 1),
                "co2_ppm": random.randint(450, 1350 if z["type"] in ["salle_commune", "restaurant"] else 950),
                "voc_index": random.randint(40, 180),
                "smoke_ppm": 0 if z["type"] != "cuisine" else random.choice([0, 0, 1]),
                "co_ppm": 0 if z["type"] != "cuisine" else random.choice([0, 0, 8]),
                "sound_db": round(random.uniform(32, 68), 1),
                "door_open": door_open,
            })
        return results


class EHPADSimulator:
    """Orchestrateur principal du simulateur."""

    def __init__(self):
        self.client = mqtt.Client(client_id="ehpad_simulator", clean_session=True)
        if MQTT_USERNAME:
            self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.residents = [ResidentSimulator(p) for p in _load_residents()[:NUM_RESIDENTS]]
        self.ambient = AmbientSensorSimulator(ZONES)
        self.running = False
        self.speed_multiplier = max(0.25, min(60.0, SIM_SPEED))
        self._room_ambient_cache = {}

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            log.info(f"Connecté au broker MQTT {MQTT_HOST}:{MQTT_PORT}")
            client.subscribe("ehpad/control/speed", qos=1)
            client.subscribe("ehpad/control/scenario", qos=1)
            client.subscribe("ehpad/control/profile", qos=1)
        else:
            log.error(f"Erreur connexion MQTT: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        log.warning(f"Déconnexion MQTT (rc={rc}), reconnexion...")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            if msg.topic == "ehpad/control/speed":
                speed = float(payload.get("speed", 1))
                self.speed_multiplier = max(0.25, min(60.0, speed))
                log.info(f"Vitesse simulateur ajustee: x{self.speed_multiplier:g}")
            elif msg.topic == "ehpad/control/scenario":
                resident_id = payload.get("resident_id")
                scenario = payload.get("scenario")
                target = next((r for r in self.residents if r.id == resident_id), None)
                if target and scenario:
                    target.force_validation_scenario(scenario)
            elif msg.topic == "ehpad/control/profile":
                resident_id = payload.get("resident_id")
                target = next((r for r in self.residents if r.id == resident_id), None)
                if target:
                    target.apply_profile_update(payload.get("profile") or {})
        except Exception as e:
            log.warning(f"Commande simulateur invalide: {e}")

    def _publish(self, topic, payload, qos=1):
        msg = json.dumps(payload)
        self.client.publish(topic, msg, qos=qos)

    def _publish_resident(self, state, tick_count):
        rid = state["resident_id"]
        zone = state.get("zone", f"ch{state['room']}")
        current_zone = state.get("current_zone") or zone
        sensor_events = state.get("sensor_events", {})
        # Topic principal complet : QoS 1 garantit la livraison au moins une fois.
        self._publish(f"ehpad/residents/{rid}/vitals", state, qos=1)

        # Événements critiques (chute) → QoS 2 : livraison exactement une fois.
        if state["movement"].get("is_fall_detected"):
            self._publish(f"ehpad/residents/{rid}/critical", {
                "resident_id": rid,
                "room": state["room"],
                "timestamp": state["timestamp"],
                "event": "fall_detected",
                "accel_magnitude": state["movement"].get("accel_magnitude"),
                "location": state.get("location"),
            }, qos=2)
        if PUBLISH_LEGACY_TOPICS:
            self._publish(f"ehpad/{zone}/{rid}/vitals", state, qos=0)
            self._publish(f"ehpad/{zone}/{rid}/motion", {
                "resident_id": rid,
                "room": state["room"],
                "zone": zone,
                "current_zone": current_zone,
                "timestamp": state["timestamp"],
                "sensor_events": sensor_events,
                **state["movement"],
            }, qos=1)
            self._publish(f"ehpad/{zone}/{rid}/bp_temp", {
                "resident_id": rid,
                "room": state["room"],
                "zone": zone,
                "timestamp": state["timestamp"],
                "blood_pressure_sys": state["vitals"]["blood_pressure_sys"],
                "blood_pressure_dia": state["vitals"].get("blood_pressure_dia"),
                "temperature": state["vitals"]["temperature"],
            }, qos=0)
        if state["movement"].get("sos_pressed"):
            self._publish(f"ehpad/{zone}/{rid}/sos", {
                "resident_id": rid,
                "room": state["room"],
                "zone": zone,
                "current_zone": current_zone,
                "timestamp": state["timestamp"],
                "pressed": True,
            }, qos=2)
        if PUBLISH_LEGACY_TOPICS:
            self._publish(f"ehpad/residents/{rid}/movement", {
                "resident_id": rid,
                "timestamp": state["timestamp"],
                "room": state["room"],
                "zone": zone,
                "current_zone": current_zone,
                "sensor_events": sensor_events,
                **state["movement"]
            }, qos=0)
            self._publish(f"ehpad/residents/{rid}/location", {
                "resident_id": rid,
                "timestamp": state["timestamp"],
                "location": state["location"],
                "current_zone": state.get("current_zone"),
                "target_zone": state.get("target_zone"),
                "position": state.get("position"),
                "activity": state.get("activity"),
                "caregiver": state["caregiver"],
            }, qos=0)
        room_ambient = {
            "zone_id": zone,
            "zone_name": f"Chambre {state['room']}",
            "zone_type": "chambre",
            "floor": state.get("floor", 0),
            "sensors": state.get("room_sensors", []),
            "timestamp": state["timestamp"],
            "occupancy": 1 if current_zone == zone else 0,
            "resident_ids": [rid] if current_zone == zone else [],
            "motion_detected": sensor_events.get("room_pir_motion", False),
            "door_open": sensor_events.get("door_open", False),
            "bed_occupied": sensor_events.get("bed_occupied", False),
            "mattress_exit": sensor_events.get("mattress_exit", False),
            "radar_presence": sensor_events.get("room_radar_presence", False),
            "floor_pressure_event": sensor_events.get("floor_pressure_event", False),
            "fall_confirmed": sensor_events.get("fall_confirmed_by_room_sensor", False),
            "sensor_health": [
                sensor_health(f"{zone}-wearable-rx", "reception_wearable", current_zone == zone, tick_count, critical=True),
                sensor_health(f"{zone}-pir", "pir_presence", sensor_events.get("room_pir_motion", False), tick_count),
                sensor_health(f"{zone}-porte", "porte", sensor_events.get("door_open", False), tick_count),
                sensor_health(f"{zone}-matelas", "matelas_lit", sensor_events.get("bed_occupied", False) or sensor_events.get("mattress_exit", False), tick_count, critical=True),
                sensor_health(f"{zone}-sol", "sol_pression", sensor_events.get("floor_pressure_event", False), tick_count, critical=True),
            ],
        }
        ambient_signature = json.dumps({
            "occupancy": room_ambient["occupancy"],
            "motion_detected": room_ambient["motion_detected"],
            "door_open": room_ambient["door_open"],
            "bed_occupied": room_ambient["bed_occupied"],
            "mattress_exit": room_ambient["mattress_exit"],
            "radar_presence": room_ambient["radar_presence"],
            "floor_pressure_event": room_ambient["floor_pressure_event"],
            "fall_confirmed": room_ambient["fall_confirmed"],
        }, sort_keys=True)
        should_publish_ambient = (
            self._room_ambient_cache.get(zone) != ambient_signature
            or tick_count % ROOM_AMBIENT_INTERVAL_TICKS == 0
            or room_ambient["door_open"]
            or room_ambient["floor_pressure_event"]
            or room_ambient["fall_confirmed"]
        )
        if should_publish_ambient:
            self._room_ambient_cache[zone] = ambient_signature
            self._publish(f"ehpad/zones/{zone}/ambient", room_ambient, qos=0)
            if PUBLISH_LEGACY_TOPICS:
                self._publish(f"ehpad/{zone}/ambient/env", room_ambient, qos=0)
        if room_ambient["door_open"]:
            self._publish(f"ehpad/{zone}/door/ambient", room_ambient, qos=1)

    def _publish_ambient(self, zone_data):
        for z in zone_data:
            self._publish(f"ehpad/zones/{z['zone_id']}/ambient", z, qos=0)
            if PUBLISH_LEGACY_TOPICS:
                self._publish(f"ehpad/{z['zone_id']}/ambient/env", z, qos=0)
            if z.get("door_open"):
                self._publish(f"ehpad/{z['zone_id']}/door/ambient", z, qos=1)

    def _publish_summary(self, all_states):
        """Topic agrégé pour le dashboard."""
        ref = all_states[0] if all_states else {}
        real_timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        summary = {
            "timestamp": real_timestamp,
            "timestamp_real": real_timestamp,
            "timestamp_simulated": ref.get("timestamp_simulated"),
            "simulated_datetime": ref.get("simulated_datetime"),
            "simulated_date": ref.get("simulated_date"),
            "simulated_time": ref.get("simulated_time"),
            "simulated_weekday": ref.get("simulated_weekday"),
            "simulated_day_index": ref.get("simulated_day_index"),
            "simulated_label": ref.get("simulated_label"),
            "total_residents": len(all_states),
            "active_scenarios": sum(1 for s in all_states if s.get("scenario_active") or s.get("movement_scenario")),
            "residents": [
                {
                    "id": s["resident_id"],
                    "name": s["name"],
                    "avatar": s.get("avatar", ""),
                    "room": s["room"],
                    "floor": s.get("floor"),
                    "zone": s.get("zone"),
                    "current_zone": s.get("current_zone"),
                    "target_zone": s.get("target_zone"),
                    "position": s.get("position"),
                    "activity": s.get("activity"),
                    "room_sensors": s.get("room_sensors", []),
                    "vitals": s["vitals"],
                    "movement": s["movement"],
                    "scenario": s.get("scenario_active"),
                    "movement_scenario": s.get("movement_scenario"),
                    "assigned_movement_scenario": s.get("assigned_movement_scenario"),
                    "timestamp_simulated": s.get("timestamp_simulated"),
                    "simulated_datetime": s.get("simulated_datetime"),
                    "simulated_date": s.get("simulated_date"),
                    "simulated_time": s.get("simulated_time"),
                    "simulated_weekday": s.get("simulated_weekday"),
                    "simulated_day_index": s.get("simulated_day_index"),
                    "simulated_label": s.get("simulated_label"),
                    "time_of_day": s.get("time_of_day"),
                    "time_label": s.get("time_label"),
                    "routine_label": s.get("routine_label"),
                    "caregiver": s["caregiver"],
                }
                for s in all_states
            ]
        }
        self._publish("ehpad/summary", summary, qos=0)

    def connect(self):
        retries = 0
        while retries < 10:
            try:
                self.client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
                self.client.loop_start()
                time.sleep(1)
                return True
            except Exception as e:
                retries += 1
                log.warning(f"Connexion impossible ({e}), retry {retries}/10...")
                time.sleep(3)
        return False

    def run(self):
        if not self.connect():
            log.error("Impossible de se connecter au broker MQTT. Abandon.")
            return

        self.running = True
        log.info(f"Simulateur démarré avec {len(self.residents)} résidents, vitesse x{self.speed_multiplier:g}")
        tick_count = 0

        while self.running:
            start = time.time()
            publish_interval_ticks = max(1, int(round(self.speed_multiplier)))
            should_publish_residents = tick_count % publish_interval_ticks == 0

            # Tick tous les résidents
            all_states = []
            for r in self.residents:
                state = r.tick()
                critical = bool(state.get("movement", {}).get("is_fall_detected") or state.get("movement", {}).get("sos_pressed"))
                if should_publish_residents or critical:
                    self._publish_resident(state, tick_count)
                all_states.append(state)

            # Capteurs ambiants (toutes les 5 secondes)
            if tick_count % 5 == 0:
                zone_data = self.ambient.tick(all_states)
                self._publish_ambient(zone_data)

            # Résumé global (toutes les secondes)
            self._publish_summary(all_states)

            tick_count += 1
            elapsed = time.time() - start
            sleep_time = max(0, (1.0 / self.speed_multiplier) - elapsed)
            time.sleep(sleep_time)


if __name__ == "__main__":
    sim = EHPADSimulator()
    sim.run()
