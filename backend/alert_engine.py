"""
Moteur d'alertes 5 niveaux avec escalade automatique.
Niveau 1 (Info) → 2 (Attention) → 3 (Alerte) → 4 (Urgence) → 5 (Danger vital)
"""

import time
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional
from enum import IntEnum

import kb_loader as _kb_loader

log = logging.getLogger(__name__)


def compute_news_score(vitals: dict, movement: dict) -> dict:
    """National Early Warning Score 2 (NEWS2) — standard clinique UK/EHPAD."""
    hr = vitals.get("heart_rate", 72)
    rr = vitals.get("respiratory_rate", 14)
    spo2 = vitals.get("spo2", 96)
    bp = vitals.get("blood_pressure_sys", 120)
    temp = vitals.get("temperature", 36.5)
    is_fall = movement.get("is_fall_detected", False)

    if hr <= 40: hr_pts = 3
    elif hr <= 50: hr_pts = 1
    elif hr <= 90: hr_pts = 0
    elif hr <= 110: hr_pts = 1
    elif hr <= 130: hr_pts = 2
    else: hr_pts = 3

    if rr <= 8: rr_pts = 3
    elif rr <= 11: rr_pts = 1
    elif rr <= 20: rr_pts = 0
    elif rr <= 24: rr_pts = 2
    else: rr_pts = 3

    if spo2 <= 91: spo2_pts = 3
    elif spo2 <= 93: spo2_pts = 2
    elif spo2 <= 95: spo2_pts = 1
    else: spo2_pts = 0

    if bp <= 90: bp_pts = 3
    elif bp <= 100: bp_pts = 2
    elif bp <= 110: bp_pts = 1
    elif bp <= 219: bp_pts = 0
    else: bp_pts = 3

    if temp <= 35.0: temp_pts = 3
    elif temp <= 36.0: temp_pts = 1
    elif temp <= 38.0: temp_pts = 0
    elif temp <= 39.0: temp_pts = 1
    else: temp_pts = 2

    # Conscience altérée → chute détectée approxée comme AVPU=V (1 pt)
    consciousness_pts = 1 if is_fall else 0

    score = hr_pts + rr_pts + spo2_pts + bp_pts + temp_pts + consciousness_pts

    if score <= 4:
        risk_level, response = "low", "Surveillance routine"
    elif score <= 6:
        risk_level, response = "medium", "Evaluation urgente soignant"
    else:
        risk_level, response = "high", "Appel SAMU / reanimation"

    return {
        "score": score,
        "risk_level": risk_level,
        "clinical_response": response,
        "breakdown": {
            "heart_rate": hr_pts, "resp_rate": rr_pts, "spo2": spo2_pts,
            "blood_pressure": bp_pts, "temperature": temp_pts, "consciousness": consciousness_pts,
        },
    }


def format_bp(vitals: dict) -> str:
    sys = vitals.get("blood_pressure_sys")
    dia = vitals.get("blood_pressure_dia")
    if sys is None:
        return "?"
    try:
        sys_txt = f"{float(sys):.0f}"
    except (TypeError, ValueError):
        sys_txt = str(sys)
    if dia is None:
        return sys_txt
    try:
        dia_txt = f"{float(dia):.0f}"
    except (TypeError, ValueError):
        dia_txt = str(dia)
    return f"{sys_txt}/{dia_txt}"


class AlertLevel(IntEnum):
    INFO = 1
    ATTENTION = 2
    ALERT = 3
    URGENCE = 4
    DANGER_VITAL = 5


LEVEL_CONFIG = {
    AlertLevel.INFO: {
        "name": "Information",
        "color": "blue",
        "action": "Log + icone dashboard",
        "escalade_delay_s": None,  # Pas d'escalade depuis niveau 1
        "notify": ["dashboard"],
    },
    AlertLevel.ATTENTION: {
        "name": "Attention",
        "color": "yellow",
        "action": "Notification soignant assigne",
        "escalade_delay_s": 600,  # 10 min → niveau 3
        "notify": ["dashboard", "soignant_assigne"],
    },
    AlertLevel.ALERT: {
        "name": "Alerte",
        "color": "orange",
        "action": "Notification + alerte sonore poste",
        "escalade_delay_s": 300,  # 5 min → niveau 4
        "notify": ["dashboard", "soignant_assigne", "son"],
    },
    AlertLevel.URGENCE: {
        "name": "Urgence",
        "color": "red",
        "action": "Tous soignants + alerte sonore forte",
        "escalade_delay_s": 180,  # 3 min → niveau 5
        "notify": ["dashboard", "tous_soignants", "son_fort"],
    },
    AlertLevel.DANGER_VITAL: {
        "name": "Danger vital",
        "color": "black",
        "action": "SAMU 15 + direction + tous soignants",
        "escalade_delay_s": None,
        "notify": ["dashboard", "tous_soignants", "son_fort", "samu", "direction"],
    },
}

ZONE_LABELS = {
    "entree": "Entree / Accueil",
    "hors_ehpad": "Sortie hors EHPAD",
    "infirmerie_rdc": "Infirmerie RDC",
    "pharmacie_admin": "Pharmacie / Admin",
    "couloir_principal": "Couloir principal",
    "salle_commune": "Salle commune / TV",
    "patio": "Patio couvert",
    "jardin": "Jardin therapeutique",
    "salle_activites": "Salle d'activites",
    "salle_manger": "Salle a manger",
    "office_cuisine": "Office / Cuisine",
    "couloir_aile_rdc": "Couloir aile RDC",
    "escalier": "Escalier securise",
    "ascenseur": "Ascenseur",
    "poste_infirmier_etage": "Poste infirmier etage",
    "kinesitherapie": "Kinesitherapie",
    "salle_repos": "Salle de repos",
    "couloir_aile_a_etage": "Couloir aile A",
    "couloir_aile_b_etage": "Couloir aile B",
    "palier_etage": "Palier escalier / ascenseur",
}


def location_label(zone_id: str, room: str = "") -> str:
    if zone_id in ZONE_LABELS:
        return ZONE_LABELS[zone_id]
    if zone_id and zone_id.startswith("ch"):
        return f"Chambre {zone_id[2:]}"
    return f"Chambre {room}" if room else "Position inconnue"


@dataclass
class Alert:
    id: str
    resident_id: str
    resident_name: str
    room: str
    caregiver: str
    current_zone: str
    location_label: str
    floor: Optional[int]
    position: dict
    sensor_events: dict
    level: AlertLevel
    reason: str
    trigger_data: dict
    notified_staff: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    acknowledged: bool = False
    acknowledged_at: Optional[float] = None
    acknowledged_by: Optional[str] = None
    taken_at: Optional[float] = None
    taken_by: Optional[str] = None
    escalation_paused_until: Optional[float] = None
    escalated_from: Optional[int] = None
    resolved: bool = False

    def to_dict(self):
        now = time.time()
        elapsed = round(now - self.created_at)
        cfg = LEVEL_CONFIG[self.level]
        delay = cfg.get("escalade_delay_s")
        escalates_in_s = None
        if delay and not self.acknowledged and not self.resolved:
            remaining = delay - elapsed
            if self.escalation_paused_until and self.escalation_paused_until > now:
                remaining = max(remaining, self.escalation_paused_until - now)
            escalates_in_s = max(0, round(remaining))
        return {
            "id": self.id,
            "resident_id": self.resident_id,
            "resident_name": self.resident_name,
            "room": self.room,
            "caregiver": self.caregiver,
            "current_zone": self.current_zone,
            "location_label": self.location_label,
            "floor": self.floor,
            "position": self.position,
            "sensor_events": self.sensor_events,
            "level": int(self.level),
            "level_name": cfg["name"],
            "color": cfg["color"],
            "action": cfg["action"],
            "reason": self.reason,
            "trigger_data": self.trigger_data,
            "notified_staff": self.notified_staff,
            "created_at": datetime.fromtimestamp(self.created_at, timezone.utc).isoformat().replace("+00:00", "Z"),
            "acknowledged": self.acknowledged,
            "acknowledged_by": self.acknowledged_by,
            "taken_at": datetime.fromtimestamp(self.taken_at, timezone.utc).isoformat().replace("+00:00", "Z") if self.taken_at else None,
            "taken_by": self.taken_by,
            "escalation_paused_until": datetime.fromtimestamp(self.escalation_paused_until, timezone.utc).isoformat().replace("+00:00", "Z") if self.escalation_paused_until else None,
            "escalated_from": self.escalated_from,
            "resolved": self.resolved,
            "time_since_s": elapsed,
            "escalates_in_s": escalates_in_s,
            "escalation_delay_s": delay,
        }


class AlertEngine:
    """Évalue les constantes vitales et génère des alertes graduées."""

    def __init__(self, redis_client, websocket_manager):
        self.redis = redis_client
        self.ws = websocket_manager
        self.active_alerts: dict[str, Alert] = {}  # keyed by resident_id
        self.alert_history: list[Alert] = []
        self._alert_counter = 0
        self._escalation_thread_running = False
        self._pending: dict[str, dict] = {}
        self._resolved_recently: dict[str, float] = {}
        self._synergy_rules: list[dict] = _kb_loader.get_epidor_ml_rule_weights().get("synergy_bonus", [])

    def _new_id(self):
        self._alert_counter += 1
        return f"ALT-{int(time.time())}-{self._alert_counter:04d}"

    def _sync_alert_location(self, alert: Alert, state: dict):
        alert.current_zone = state.get("current_zone") or state.get("zone") or f"ch{state.get('room', alert.room)}"
        alert.location_label = location_label(alert.current_zone, state.get("room", alert.room))
        alert.floor = state.get("position", {}).get("floor", state.get("floor", alert.floor))
        alert.position = state.get("position") or alert.position
        alert.sensor_events = state.get("sensor_events") or alert.sensor_events
        if alert.trigger_data is not None:
            alert.trigger_data["sensor_events"] = alert.sensor_events
        self._save_to_redis(alert)

    def _notification_targets(self, state: dict, level: AlertLevel) -> list[dict]:
        staff_directory = state.get("staff_directory") or {}
        caregiver = state.get("caregiver", "")
        targets = []

        def add(staff_id: str, reason: str):
            if not staff_id or staff_id in {t["id"] for t in targets}:
                return
            staff = staff_directory.get(staff_id, {})
            targets.append({
                "id": staff_id,
                "name": staff.get("name", staff_id),
                "role": staff.get("role"),
                "status": staff.get("status"),
                "sector": staff.get("sector"),
                "reason": reason,
            })

        add("dashboard", "affichage central")
        if level >= AlertLevel.ATTENTION:
            add(caregiver, "soignant assigne")
        if level >= AlertLevel.URGENCE:
            for staff_id in ("soignant_A", "soignant_B", "soignant_C", "chef_garde"):
                add(staff_id, "urgence tous soignants")
        if level >= AlertLevel.DANGER_VITAL:
            add("direction", "danger vital direction")
            add("samu_15", "APPEL SAMU 15 REQUIS — danger vital")
        return targets

    def evaluate(self, state: dict) -> Optional[Alert]:
        """
        Évalue l'état d'un résident et retourne une alerte si nécessaire.
        Les règles sont appliquées dans l'ordre décroissant de gravité.
        """
        rid = state["resident_id"]
        v = state["vitals"]
        m = state["movement"]
        hr = v["heart_rate"]
        spo2 = v["spo2"]
        bp = v["blood_pressure_sys"]
        bp_label = format_bp(v)
        temp = v["temperature"]
        rr = v.get("respiratory_rate", 0)
        last_mv = m.get("last_movement_ago_s", 0)
        is_fall = m.get("is_fall_detected", False)
        ambient_fall = m.get("ambient_fall_confirmed", False)
        sos_pressed = m.get("sos_pressed", False)
        sensor_events = state.get("sensor_events", {})
        ml_risk = state.get("ml_risk", 0.0)
        routine_analysis = state.get("routine_analysis") or {}
        routine_score = float(routine_analysis.get("score") or 0)
        routine_change = (
            routine_analysis.get("alert_level", 0) >= 2
            or state.get("movement_scenario") in {
                "errance_nuit", "sortie_patio", "immobilite_salle_repos", "aller_toilettes_nuit",
                "desorientation_ascenseur", "agitation_couloir", "isolement_chambre", "retour_kine_fatigue",
                "promenade_jardin", "sortie_jardin_non_accompagnee", "chute_jardin",
                "fugue_hors_ehpad", "chute_trajet_repas", "desorientation_avant_repas",
                "malaise_retour_repas",
            }
        )
        current_zone = state.get("current_zone") or state.get("zone")
        pathologies = set(state.get("pathologies") or state.get("profile", {}).get("pathologies") or [])
        mobility = state.get("mobility") or state.get("profile", {}).get("mobility")
        baseline = state.get("baseline") or {}
        baseline_spo2 = float(baseline.get("spo2", 96) or 96)
        cognitive_risk = bool(pathologies.intersection({"alzheimer", "dementia", "demence"}))
        frail_risk = cognitive_risk or mobility == "tres_faible"

        # Mode nuit : seuils adaptés (désaturation nocturne = normale, inactivité = sommeil)
        is_night = state.get("time_of_day") in {"nuit", "coucher", "sieste"}
        is_sleeping = m.get("is_sleeping", False)
        night_sleep = is_night or is_sleeping

        # Seuils SpO2 adaptés (plus tolérants la nuit — désaturation attendue)
        spo2_thr_2 = 91 if night_sleep else 94
        spo2_thr_3 = 88 if night_sleep else 93
        spo2_thr_4 = 84 if night_sleep else 88
        spo2_thr_5 = 82 if night_sleep else 85
        if "bpco" in pathologies:
            spo2_thr_2 = 88 if night_sleep else 90
            spo2_thr_3 = 86 if night_sleep else 88
            spo2_thr_4 = 83 if night_sleep else 85
            spo2_thr_5 = 80 if night_sleep else 82
        if baseline_spo2 < 95:
            spo2_thr_2 = min(spo2_thr_2, baseline_spo2 - 1.5)
            spo2_thr_3 = min(spo2_thr_3, baseline_spo2 - 2.5)
            spo2_thr_4 = min(spo2_thr_4, baseline_spo2 - 4.0)
            spo2_thr_5 = min(spo2_thr_5, baseline_spo2 - 6.0)
        # Inactivité : ignorer niveau 1 si le résident dort (comportement normal)
        immobility_thr_1 = 99999 if night_sleep else 1800
        immobility_thr_3 = 5400 if night_sleep else 3600

        # Calcul NEWS2
        news = compute_news_score(v, m)
        news_score = news["score"]
        if baseline_spo2 < 95 and spo2 >= baseline_spo2 - 2.5:
            news_score = max(0, news_score - news["breakdown"].get("spo2", 0))

        level = None
        reason = ""
        evidence = []
        if current_zone:
            evidence.append(f"zone={location_label(current_zone, state.get('room'))}")
        if sensor_events:
            active_sensors = [k for k, enabled in sensor_events.items() if enabled]
            evidence.append(f"capteurs_actifs={','.join(active_sensors) if active_sensors else 'aucun'}")
        if state.get("sensor_health"):
            weak = [
                s.get("id", s.get("type", "capteur"))
                for s in state.get("sensor_health", [])
                if s.get("status") == "offline" or float(s.get("quality_pct", 100)) < 65
            ]
            evidence.append(f"qualite_capteurs={'ok' if not weak else 'a_verifier:' + ','.join(weak[:3])}")
        evidence.append(f"NEWS={news_score}")
        evidence.append(f"ML={ml_risk:.0%}")
        if state.get("routine_label"):
            evidence.append(f"routine={state.get('routine_label')}")
        if routine_analysis:
            evidence.append(f"routine_score={routine_score:.2f}")
            if routine_analysis.get("flags"):
                evidence.append("routine_flags=" + " | ".join(routine_analysis.get("flags", [])[:2]))

        # --- NIVEAU 5 : Danger vital ---
        if (last_mv > immobility_thr_3 and ((spo2 < spo2_thr_4) or (hr > 140) or (bp < 70))) or (spo2 < spo2_thr_5 and hr > 130) or (hr > 150) or (bp < 60) or (bp > 240) or news_score >= 10:
            level = AlertLevel.DANGER_VITAL
            reason = f"Constantes critiques — SpO2={spo2}%, FC={hr}, PA={bp_label}, T={temp}C [NEWS={news_score}]"

        # --- NIVEAU 4 : Urgence ---
        elif current_zone == "hors_ehpad" or state.get("movement_scenario") == "fugue_hors_ehpad" or sos_pressed or is_fall or ambient_fall or (spo2 < spo2_thr_4) or (hr > 140) or (bp < 70) or (bp > 220) or (temp > 40.0) or (rr and rr > 30) or news_score >= 8:
            level = AlertLevel.URGENCE
            if current_zone == "hors_ehpad" or state.get("movement_scenario") == "fugue_hors_ehpad":
                reason = "Fugue detectee: resident en sortie hors EHPAD"
            elif sos_pressed:
                reason = "Bouton SOS resident active"
            elif ambient_fall:
                reason = f"Chute confirmee par capteurs ambiants — accel={m.get('accel_magnitude', 0):.1f}g"
            elif is_fall:
                reason = f"Chute detectee — accel={m.get('accel_magnitude', 0):.1f}g"
            else:
                reason = f"Constantes dangereuses — SpO2={spo2}%, FC={hr}, PA={bp_label}, T={temp}C [NEWS={news_score}]"

        # --- NIVEAU 3 : Alerte ---
        elif (spo2 < spo2_thr_3) or (hr > 125) or (hr < 45) or (bp > 200) or (bp < 80) or (temp > 39.3) or (rr and rr > 24) or (last_mv > immobility_thr_3) or (routine_score >= 0.70 and (news_score >= 2 or ml_risk > 0.55 or frail_risk)) or (ml_risk > 0.82 and (news_score >= 3 or routine_change or spo2 < spo2_thr_2)) or news_score >= 6:
            level = AlertLevel.ALERT
            if routine_score >= 0.70 and (news_score >= 2 or ml_risk > 0.55 or frail_risk):
                reason = f"Rupture de routine importante: {'; '.join(routine_analysis.get('flags', [])[:2])}"
            elif ml_risk > 0.82 and (news_score >= 3 or routine_change or spo2 < spo2_thr_2):
                reason = f"IA predit risque de malaise eleve ({ml_risk:.0%}) [NEWS={news_score}]"
            elif last_mv > immobility_thr_3:
                reason = f"Absence de mouvement depuis {last_mv//60} min"
            else:
                reason = f"Constantes anormales — SpO2={spo2}%, FC={hr}, PA={bp_label}, T={temp}C [NEWS={news_score}]"

        # --- NIVEAU 2 : Attention ---
        elif (spo2 < spo2_thr_2) or (hr > 110) or (hr < 48) or (bp > 180) or (bp < 90) or (temp > 38.3) or routine_score >= 0.40 or (routine_change and frail_risk) or (ml_risk > 0.65 and (news_score >= 2 or routine_change)) or news_score >= 4:
            level = AlertLevel.ATTENTION
            if ml_risk > 0.65 and (news_score >= 2 or routine_change):
                reason = f"IA detecte un risque modere ({ml_risk:.0%}) [NEWS={news_score}]"
            elif routine_score >= 0.40:
                reason = f"Changement de routine notable: {'; '.join(routine_analysis.get('flags', [])[:2])}"
            elif routine_change:
                reason = f"Changement de routine detecte: {state.get('movement_scenario')}"
            else:
                reason = f"Constante hors norme — SpO2={spo2}%, FC={hr}, PA={bp_label}, T={temp}C [NEWS={news_score}]"

        # --- NIVEAU 1 : Information ---
        elif last_mv > immobility_thr_1:
            level = AlertLevel.INFO
            reason = f"Resident inactif depuis {last_mv//60} min"

        # --- SYNERGIES CLINIQUES (base de connaissance JSON) ---
        medications = set(state.get("medications") or state.get("profile", {}).get("medications") or [])
        _feat = {
            "impact_detected": is_fall or ambient_fall,
            "immobility_after_impact": (is_fall or ambient_fall) and last_mv > 60,
            "anticoagulant": "anticoagulant" in medications,
            "new_confusion": cognitive_risk and (spo2 < 92 or bp < 90 or temp > 38.5),
            "diuretic": "diuretic" in medications or "diuretique" in medications,
            "temperature_abnormal": temp > 38.5 or temp < 35.5,
            "bp_low": bp < 90,
            "exit_door_open": bool(sensor_events.get("door_open")) or current_zone == "hors_ehpad",
            "routine_deviation": routine_change,
            "spo2_drop": spo2 < baseline_spo2 - 3,
            "rr_high": bool(rr and rr > 20),
            "activity_drop_50": last_mv > 3600,
        }
        for rule in self._synergy_rules:
            if all(_feat.get(c, False) for c in rule.get("conditions", [])):
                forced = rule.get("force_alert_level")
                if forced and (level is None or forced > int(level)):
                    level = AlertLevel(forced)
                    reason = f"[KB:{rule['id']}] {rule.get('description', 'Synergie clinique detectee')}"

        if level is None:
            # Résoudre l'alerte existante si les constantes sont revenues à la normale
            if rid in self.active_alerts:
                self._mark_stable_or_resolve(rid)
            self._pending.pop(rid, None)
            return None

        if not self._passes_persistence(rid, level, reason):
            return None

        existing = self.active_alerts.get(rid)

        # Pas de doublon si même niveau ou niveau inférieur
        if existing and not existing.acknowledged:
            self._sync_alert_location(existing, state)
            if level <= existing.level:
                return None

        # Créer une nouvelle alerte
        alert = Alert(
            id=self._new_id(),
            resident_id=rid,
            resident_name=state["resident_name"],
            room=state["room"],
            caregiver=state.get("caregiver", ""),
            current_zone=state.get("current_zone") or state.get("zone") or f"ch{state['room']}",
            location_label=location_label(state.get("current_zone") or state.get("zone"), state.get("room")),
            floor=state.get("position", {}).get("floor", state.get("floor")),
            position=state.get("position") or {},
            sensor_events=sensor_events,
            level=level,
            reason=reason,
            trigger_data={"vitals": v, "movement": m, "ml_risk": ml_risk, "sensor_events": sensor_events, "news": news, "routine_analysis": routine_analysis},
            notified_staff=self._notification_targets(state, level),
        )
        alert.trigger_data["evidence"] = evidence
        alert.trigger_data["location_precision"] = {
            "zone": alert.current_zone,
            "label": alert.location_label,
            "floor": alert.floor,
            "position": alert.position,
        }
        if existing:
            alert.escalated_from = int(existing.level)

        self.active_alerts[rid] = alert
        self.alert_history.append(alert)
        log.warning(f"[ALERT {level.name}] {state['resident_name']} (chambre {state['room']}): {reason}")

        # Sauvegarder dans Redis
        self._save_to_redis(alert, record_history=True)
        return alert

    def _save_to_redis(self, alert: Alert, record_history: bool = False):
        try:
            key = f"alert:{alert.resident_id}:active"
            self.redis.setex(key, 86400, __import__('json').dumps(alert.to_dict()))
            if record_history:
                # Historique evenementiel: creation, escalade, acquittement, resolution.
                # Les simples mises a jour de localisation restent dans la cle active.
                self.redis.lpush("alerts:history", __import__('json').dumps(alert.to_dict()))
                self.redis.ltrim("alerts:history", 0, 999)
        except Exception as e:
            log.error(f"Redis save error: {e}")

    def _delete_active_from_redis(self, resident_id: str):
        try:
            self.redis.delete(f"alert:{resident_id}:active")
        except Exception as e:
            log.error(f"Redis delete active alert error: {e}")

    def _passes_persistence(self, resident_id: str, level: AlertLevel, reason: str) -> bool:
        """Filtre anti-bruit: seules les urgences sont immediates, le reste doit persister."""
        if level >= AlertLevel.URGENCE:
            self._pending.pop(resident_id, None)
            return True

        now = time.time()
        cooldown = 240 if level == AlertLevel.ATTENTION else 180
        if now - self._resolved_recently.get(resident_id, 0) < cooldown:
            return False

        family = reason.split("—", 1)[0].split(":", 1)[0].strip()
        required = 2 if level == AlertLevel.ALERT else 4
        pending = self._pending.get(resident_id)
        if not pending or pending.get("level") != int(level) or pending.get("family") != family:
            self._pending[resident_id] = {
                "level": int(level),
                "family": family,
                "count": 1,
                "first_seen": now,
            }
            return False

        pending["count"] += 1
        if pending["count"] < required and now - pending["first_seen"] < 20:
            return False
        self._pending.pop(resident_id, None)
        return True

    def _mark_stable_or_resolve(self, resident_id: str):
        alert = self.active_alerts.get(resident_id)
        if not alert:
            return
        if alert.level >= AlertLevel.ATTENTION and not alert.acknowledged and not alert.taken_by:
            # Une alerte clinique reste visible tant qu'un soignant ne l'a pas vue
            # ou prise en charge. Sinon elle peut disparaitre sans trace explicite
            # dans le dashboard si les constantes redeviennent stables.
            return
        now = time.time()
        stable_since = getattr(self, "_stable_since", {})
        if not hasattr(self, "_stable_since"):
            self._stable_since = {}
            stable_since = self._stable_since
        if resident_id not in stable_since:
            stable_since[resident_id] = now
            return
        stable_delay = 180 if alert.level <= AlertLevel.ATTENTION else 90
        if now - stable_since[resident_id] >= stable_delay:
            self._resolve_alert(resident_id)
            stable_since.pop(resident_id, None)

    def _resolve_alert(self, resident_id: str):
        alert = self.active_alerts.pop(resident_id, None)
        if alert:
            alert.resolved = True
            self._resolved_recently[resident_id] = time.time()
            self._save_to_redis(alert, record_history=True)
            self._delete_active_from_redis(resident_id)
            log.info(f"Alerte résolue pour {resident_id}")

    def acknowledge(self, resident_id: str, by: str) -> bool:
        alert = self.active_alerts.get(resident_id)
        if alert and not alert.acknowledged:
            alert.acknowledged = True
            alert.acknowledged_at = time.time()
            alert.acknowledged_by = by
            self._save_to_redis(alert, record_history=True)
            log.info(f"Alerte acquittée par {by} pour {resident_id}")
            return True
        return False

    def take_in_charge(self, resident_id: str, by: str, pause_s: int = 600) -> bool:
        alert = self.active_alerts.get(resident_id)
        if alert and not alert.resolved:
            now = time.time()
            alert.taken_at = now
            alert.taken_by = by
            alert.escalation_paused_until = now + pause_s
            self._save_to_redis(alert, record_history=True)
            log.info(f"Alerte prise en charge par {by} pour {resident_id}, escalade suspendue {pause_s}s")
            return True
        return False

    def resolve(self, resident_id: str, by: str) -> bool:
        alert = self.active_alerts.pop(resident_id, None)
        if alert and not alert.resolved:
            now = time.time()
            alert.taken_by = alert.taken_by or by
            alert.taken_at = alert.taken_at or now
            alert.acknowledged = True
            alert.acknowledged_at = now
            alert.acknowledged_by = by
            alert.resolved = True
            self._resolved_recently[resident_id] = now
            self._save_to_redis(alert, record_history=True)
            self._delete_active_from_redis(resident_id)
            log.info(f"Alerte resolue par {by} pour {resident_id}")
            return True
        return False

    def _has_clinical_escalation_signal(self, alert: Alert) -> bool:
        """Vrai si l'alerte porte un signal clinique suffisant pour monter vers urgence."""
        trigger = alert.trigger_data or {}
        vitals = trigger.get("vitals") or {}
        movement = trigger.get("movement") or {}
        news = trigger.get("news") or {}
        routine = trigger.get("routine_analysis") or {}
        ml_risk = float(trigger.get("ml_risk") or 0)
        news_score = int(news.get("score") or 0)
        spo2 = float(vitals.get("spo2") or 100)
        hr = float(vitals.get("heart_rate") or 0)
        bp = float(vitals.get("blood_pressure_sys") or 120)
        temp = float(vitals.get("temperature") or 36.5)
        rr = float(vitals.get("respiratory_rate") or 0)
        routine_score = float(routine.get("score") or 0)

        return bool(
            alert.level >= AlertLevel.URGENCE
            or alert.current_zone == "hors_ehpad"
            or movement.get("is_fall_detected")
            or movement.get("ambient_fall_confirmed")
            or movement.get("sos_pressed")
            or news_score >= 6
            or ml_risk >= 0.82
            or routine_score >= 0.85
            or spo2 < 90
            or hr > 125
            or hr < 45
            or bp < 85
            or bp > 200
            or temp > 39.3
            or rr > 24
        )

    def _escalation_ceiling(self, alert: Alert) -> AlertLevel:
        """Evite qu'une simple alerte de routine devienne danger vital par non-clic."""
        if alert.level >= AlertLevel.URGENCE or self._has_clinical_escalation_signal(alert):
            return AlertLevel.DANGER_VITAL
        return AlertLevel.ALERT

    def check_escalations(self) -> list[dict]:
        """Appelé périodiquement. Escalade les alertes non acquittées et retourne les dicts escaladés."""
        now = time.time()

        # Purge _resolved_recently (entrées > 15 min)
        cutoff = now - 900
        self._resolved_recently = {k: v for k, v in self._resolved_recently.items() if v > cutoff}

        to_escalate = []
        for rid, alert in self.active_alerts.items():
            if alert.acknowledged or alert.resolved:
                continue
            if alert.escalation_paused_until and now < alert.escalation_paused_until:
                continue
            config = LEVEL_CONFIG[alert.level]
            delay = config.get("escalade_delay_s")
            if delay and (now - alert.created_at) > delay:
                next_level = alert.level + 1
                ceiling = self._escalation_ceiling(alert)
                if next_level <= AlertLevel.DANGER_VITAL and next_level <= ceiling:
                    to_escalate.append((rid, alert, AlertLevel(next_level)))

        escalated_dicts = []
        for rid, old_alert, new_level in to_escalate:
            elapsed_min = round((now - old_alert.created_at) / 60)
            old_alert.resolved = True
            escalated_targets = list(old_alert.notified_staff)
            if new_level >= AlertLevel.URGENCE:
                existing_ids = {t.get("id") for t in escalated_targets}
                for staff_id in ("soignant_A", "soignant_B", "soignant_C", "chef_garde"):
                    if staff_id not in existing_ids:
                        escalated_targets.append({"id": staff_id, "name": staff_id, "reason": "escalade urgence"})
            if new_level >= AlertLevel.DANGER_VITAL and "direction" not in {t.get("id") for t in escalated_targets}:
                escalated_targets.append({"id": "direction", "name": "direction", "reason": "danger vital direction"})
            escalated = Alert(
                id=self._new_id(),
                resident_id=old_alert.resident_id,
                resident_name=old_alert.resident_name,
                room=old_alert.room,
                caregiver=old_alert.caregiver,
                current_zone=old_alert.current_zone,
                location_label=old_alert.location_label,
                floor=old_alert.floor,
                position=old_alert.position,
                sensor_events=old_alert.sensor_events,
                level=new_level,
                reason=f"[ESCALADE N{int(old_alert.level)}→N{int(new_level)}] Non acquitté après {elapsed_min} min → {old_alert.reason}",
                trigger_data=old_alert.trigger_data,
                notified_staff=escalated_targets,
                escalated_from=int(old_alert.level),
            )
            self.active_alerts[rid] = escalated
            self.alert_history.append(escalated)
            self._save_to_redis(escalated, record_history=True)
            log.warning(f"[ESCALADE] {old_alert.resident_name}: N{int(old_alert.level)} → N{int(new_level)} après {elapsed_min} min")
            escalated_dicts.append(escalated.to_dict())

        return escalated_dicts

    def get_all_active(self) -> list:
        return [a.to_dict() for a in self.active_alerts.values() if not a.resolved]

    def get_history(self, limit: int = 50) -> list:
        return [a.to_dict() for a in self.alert_history[-limit:]][::-1]
