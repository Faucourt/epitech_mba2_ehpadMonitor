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
    created_at: float = field(default_factory=time.time)
    acknowledged: bool = False
    acknowledged_at: Optional[float] = None
    acknowledged_by: Optional[str] = None
    escalated_from: Optional[int] = None
    resolved: bool = False

    def to_dict(self):
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
            "level_name": LEVEL_CONFIG[self.level]["name"],
            "color": LEVEL_CONFIG[self.level]["color"],
            "action": LEVEL_CONFIG[self.level]["action"],
            "reason": self.reason,
            "trigger_data": self.trigger_data,
            "created_at": datetime.fromtimestamp(self.created_at, timezone.utc).isoformat().replace("+00:00", "Z"),
            "acknowledged": self.acknowledged,
            "acknowledged_by": self.acknowledged_by,
            "escalated_from": self.escalated_from,
            "resolved": self.resolved,
            "time_since_s": round(time.time() - self.created_at),
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
        temp = v["temperature"]
        rr = v.get("respiratory_rate", 0)
        last_mv = m.get("last_movement_ago_s", 0)
        is_fall = m.get("is_fall_detected", False)
        ambient_fall = m.get("ambient_fall_confirmed", False)
        sos_pressed = m.get("sos_pressed", False)
        sensor_events = state.get("sensor_events", {})
        ml_risk = state.get("ml_risk", 0.0)
        routine_change = state.get("movement_scenario") in {
            "errance_nuit", "sortie_patio", "immobilite_salle_repos", "aller_toilettes_nuit",
            "desorientation_ascenseur", "agitation_couloir", "isolement_chambre", "retour_kine_fatigue",
            "promenade_jardin", "sortie_jardin_non_accompagnee", "chute_jardin",
            "fugue_hors_ehpad", "chute_trajet_repas", "desorientation_avant_repas",
            "malaise_retour_repas",
        }
        current_zone = state.get("current_zone") or state.get("zone")

        # Mode nuit : seuils adaptés (désaturation nocturne = normale, inactivité = sommeil)
        is_night = state.get("time_of_day") in {"nuit", "coucher", "sieste"}
        is_sleeping = m.get("is_sleeping", False)
        night_sleep = is_night or is_sleeping

        # Seuils SpO2 adaptés (plus tolérants la nuit — désaturation attendue)
        spo2_thr_2 = 92 if night_sleep else 95
        spo2_thr_3 = 89 if night_sleep else 93
        spo2_thr_4 = 84 if night_sleep else 88
        spo2_thr_5 = 82 if night_sleep else 85
        # Inactivité : ignorer niveau 1 si le résident dort (comportement normal)
        immobility_thr_1 = 99999 if night_sleep else 1800
        immobility_thr_3 = 5400 if night_sleep else 3600

        # Calcul NEWS2
        news = compute_news_score(v, m)
        news_score = news["score"]

        level = None
        reason = ""

        # --- NIVEAU 5 : Danger vital ---
        if (last_mv > immobility_thr_3 and ((spo2 < spo2_thr_4) or (hr > 140) or (bp < 70))) or (spo2 < spo2_thr_5 and hr > 130) or (hr > 150) or (bp < 60) or (bp > 220) or news_score >= 9:
            level = AlertLevel.DANGER_VITAL
            reason = f"Constantes critiques — SpO2={spo2}%, FC={hr}, PA={bp} [NEWS={news_score}]"

        # --- NIVEAU 4 : Urgence ---
        elif current_zone == "hors_ehpad" or state.get("movement_scenario") == "fugue_hors_ehpad" or sos_pressed or is_fall or ambient_fall or (spo2 < spo2_thr_4) or (hr > 140) or (bp < 70) or (bp > 200) or (temp > 40.0) or (rr and rr > 30) or news_score >= 7:
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
                reason = f"Constantes dangereuses — SpO2={spo2}%, FC={hr}, PA={bp}, T={temp}C [NEWS={news_score}]"

        # --- NIVEAU 3 : Alerte ---
        elif (spo2 < spo2_thr_3) or (hr > 120) or (hr < 45) or (bp > 180) or (bp < 80) or (temp > 39.5) or (rr and rr > 24) or (last_mv > immobility_thr_3) or (ml_risk > 0.75) or news_score >= 5:
            level = AlertLevel.ALERT
            if ml_risk > 0.75:
                reason = f"IA predit risque de malaise eleve ({ml_risk:.0%}) [NEWS={news_score}]"
            elif last_mv > immobility_thr_3:
                reason = f"Absence de mouvement depuis {last_mv//60} min"
            else:
                reason = f"Constantes anormales — SpO2={spo2}%, FC={hr}, PA={bp}, T={temp}C [NEWS={news_score}]"

        # --- NIVEAU 2 : Attention ---
        elif (spo2 < spo2_thr_2) or (hr > 100) or (hr < 50) or (bp > 160) or (bp < 90) or (temp > 38.5) or routine_change or (ml_risk > 0.5) or news_score >= 3:
            level = AlertLevel.ATTENTION
            if ml_risk > 0.5:
                reason = f"IA detecte un risque modere ({ml_risk:.0%}) [NEWS={news_score}]"
            elif routine_change:
                reason = f"Changement de routine detecte: {state.get('movement_scenario')}"
            else:
                reason = f"Constante hors norme — SpO2={spo2}%, FC={hr}, PA={bp} [NEWS={news_score}]"

        # --- NIVEAU 1 : Information ---
        elif last_mv > immobility_thr_1:
            level = AlertLevel.INFO
            reason = f"Resident inactif depuis {last_mv//60} min"

        if level is None:
            # Résoudre l'alerte existante si les constantes sont revenues à la normale
            if rid in self.active_alerts:
                self._resolve_alert(rid)
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
            trigger_data={"vitals": v, "movement": m, "ml_risk": ml_risk, "sensor_events": sensor_events, "news": news},
        )
        if existing:
            alert.escalated_from = int(existing.level)

        self.active_alerts[rid] = alert
        self.alert_history.append(alert)
        log.warning(f"[ALERT {level.name}] {state['resident_name']} (chambre {state['room']}): {reason}")

        # Sauvegarder dans Redis
        self._save_to_redis(alert)
        return alert

    def _save_to_redis(self, alert: Alert):
        try:
            key = f"alert:{alert.resident_id}:active"
            self.redis.setex(key, 86400, __import__('json').dumps(alert.to_dict()))
            # Liste historique
            self.redis.lpush("alerts:history", __import__('json').dumps(alert.to_dict()))
            self.redis.ltrim("alerts:history", 0, 999)
        except Exception as e:
            log.error(f"Redis save error: {e}")

    def _resolve_alert(self, resident_id: str):
        alert = self.active_alerts.pop(resident_id, None)
        if alert:
            alert.resolved = True
            log.info(f"Alerte résolue pour {resident_id}")

    def acknowledge(self, resident_id: str, by: str) -> bool:
        alert = self.active_alerts.get(resident_id)
        if alert and not alert.acknowledged:
            alert.acknowledged = True
            alert.acknowledged_at = time.time()
            alert.acknowledged_by = by
            self._save_to_redis(alert)
            log.info(f"Alerte acquittée par {by} pour {resident_id}")
            return True
        return False

    def check_escalations(self):
        """Appelé périodiquement pour escalader les alertes non acquittées."""
        now = time.time()
        to_escalate = []

        for rid, alert in self.active_alerts.items():
            if alert.acknowledged or alert.resolved:
                continue
            config = LEVEL_CONFIG[alert.level]
            delay = config.get("escalade_delay_s")
            if delay and (now - alert.created_at) > delay:
                next_level = alert.level + 1
                if next_level <= AlertLevel.DANGER_VITAL:
                    to_escalate.append((rid, alert, AlertLevel(next_level)))

        for rid, old_alert, new_level in to_escalate:
            old_alert.resolved = True
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
                reason=f"[ESCALADE] Non acquitté en temps → {old_alert.reason}",
                trigger_data=old_alert.trigger_data,
                escalated_from=int(old_alert.level),
            )
            self.active_alerts[rid] = escalated
            self.alert_history.append(escalated)
            self._save_to_redis(escalated)
            log.warning(f"[ESCALADE] {old_alert.resident_name}: {old_alert.level.name} → {new_level.name}")

    def get_all_active(self) -> list:
        return [a.to_dict() for a in self.active_alerts.values() if not a.resolved]

    def get_history(self, limit: int = 50) -> list:
        return [a.to_dict() for a in self.alert_history[-limit:]][::-1]

