import json
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import numpy as np
from fastapi import HTTPException

from a2a_agents import run_a2a_pipeline


WEEKLY_LIFE_PLAN = [
    {"day": "Lundi", "menu": {"lunch": "Veloute de legumes, poulet roti, puree de carottes, fromage blanc", "dinner": "Potage, omelette aux fines herbes, salade de pommes de terre, compote"}, "activities": {"morning": "Atelier memoire", "afternoon": "Dominos et jeux de societe", "evening": "Lecture calme"}},
    {"day": "Mardi", "menu": {"lunch": "Salade de lentilles, poisson sauce citron, riz, yaourt", "dinner": "Soupe de saison, gratin de courgettes, fruit cuit"}, "activities": {"morning": "Kine douce", "afternoon": "Atelier dessin", "evening": "Musique douce"}},
    {"day": "Mercredi", "menu": {"lunch": "Betteraves, boeuf bourguignon, coquillettes, fromage", "dinner": "Veloute, quiche lorraine, salade, dessert lacte"}, "activities": {"morning": "Revue de presse", "afternoon": "Loto", "evening": "Film ancien"}},
    {"day": "Jeudi", "menu": {"lunch": "Carottes rapees, dinde aux champignons, haricots verts, riz au lait", "dinner": "Soupe, poisson froid mayonnaise legere, pommes vapeur, poire"}, "activities": {"morning": "Gym assise", "afternoon": "Theatre et expression", "evening": "Discussion accompagnee"}},
    {"day": "Vendredi", "menu": {"lunch": "Terrine de legumes, colin, semoule, fromage blanc aux fruits", "dinner": "Potage, croque monsieur adapte, salade, compote"}, "activities": {"morning": "Atelier cuisine", "afternoon": "Chorale", "evening": "Jeux de cartes"}},
    {"day": "Samedi", "menu": {"lunch": "Salade composee, roti de veau, gratin dauphinois, tarte aux pommes", "dinner": "Soupe, jambon blanc, puree, yaourt"}, "activities": {"morning": "Promenade jardin", "afternoon": "Rencontre familles", "evening": "Television accompagnee"}},
    {"day": "Dimanche", "menu": {"lunch": "Menu dominical: entree fraiche, poulet fermier, pommes sautees, patisserie", "dinner": "Potage, assiette froide, fromage, fruit"}, "activities": {"morning": "Temps calme / messe TV", "afternoon": "Gouter musical", "evening": "Retour au calme"}},
]


class DailyReportService:
    def __init__(
        self,
        *,
        redis_client,
        alert_engine,
        residents_map: dict,
        archetypes: dict,
        effective_resident_profile: Callable[[str], dict],
        resident_caregiver: Callable[[str, Optional[dict]], str],
        resident_archetype: Callable[[dict], str],
    ):
        self.redis_client = redis_client
        self.alert_engine = alert_engine
        self.residents_map = residents_map
        self.archetypes = archetypes
        self.effective_resident_profile = effective_resident_profile
        self.resident_caregiver = resident_caregiver
        self.resident_archetype = resident_archetype

    def simulated_history_rows(self, resident_id: str, days: int = 30, step_hours: int = 6):
        profile = self.effective_resident_profile(resident_id)
        if not profile:
            raise HTTPException(404, "Resident non trouve")

        days = max(30, min(days, 730))
        step_hours = max(1, min(step_hours, 24))
        points = int((days * 24) / step_hours) + 1
        risk = float(profile.get("risk_factor", 0.3))
        mobility = profile.get("mobility", "moyenne")
        base_hr = 70 + int(risk * 12)
        base_spo2 = 97 - int(risk * 6)
        base_bp = 125 + int(risk * 45)
        base_temp = 36.6 + risk * 0.4
        now = datetime.now(timezone.utc)
        room_meal = mobility == "tres_faible" and risk >= 0.6
        meal_zone = f"ch{profile.get('room', '')}" if room_meal else "salle_manger"
        zones_by_hour = {
            7: (meal_zone, "petit_dejeuner_en_chambre" if room_meal else "petit_dejeuner"),
            8: (meal_zone, "petit_dejeuner_en_chambre" if room_meal else "petit_dejeuner"),
            10: ("salle_activites", "animation_matin"),
            11: ("couloir_principal", "trajet_repas"),
            12: (meal_zone, "dejeuner_en_chambre" if room_meal else "dejeuner"),
            13: (f"ch{profile.get('room', '')}", "sieste"),
            15: ("salle_commune", "animation_apres_midi"),
            16: (meal_zone, "gouter_en_chambre" if room_meal else "gouter"),
            18: (meal_zone, "diner_en_chambre" if room_meal else "diner"),
            19: ("salle_commune", "soiree"),
        }
        fallback_zones = [f"ch{profile.get('room', '')}", "couloir_principal", "salle_manger", "salle_commune", "salle_repos", "patio", "jardin"]
        rows = []

        for i in range(points):
            ts = now - timedelta(hours=(points - 1 - i) * step_hours)
            seed = sum(ord(c) for c in f"{resident_id}-{ts.date()}-{ts.hour}")
            phase = (seed % 17) - 8
            night = ts.hour < 6 or ts.hour >= 22
            meal = ts.hour in {7, 8, 12, 16, 18}
            scheduled = zones_by_hour.get(ts.hour)
            movement_base = 2400 if night else (300 if meal else 900)
            if mobility in {"faible", "tres_faible"}:
                movement_base += 600
            last_movement = max(30, movement_base + phase * 55)
            event = "routine"
            level = 0

            heart_rate = base_hr + phase
            spo2 = base_spo2 - (2 if night and risk > 0.5 else 0)
            blood_pressure = base_bp + phase * 2
            temperature = base_temp + (phase / 80)
            respiratory_rate = 15 + int(risk * 6) + (1 if spo2 < 93 else 0)
            zone = scheduled[0] if scheduled else fallback_zones[seed % len(fallback_zones)]
            routine = scheduled[1] if scheduled else ("nuit" if night else "routine")

            if ts.hour in {11, 18} and seed % 7 == 0 and risk > 0.35:
                event = "risque_trajet_repas"
                level = 2
                last_movement = 1200
                heart_rate += 10
            elif seed % 41 == 0 and risk > 0.45:
                event = "risque_chute"
                level = 3
                last_movement = 3800
            elif seed % 29 == 0 and risk > 0.35:
                event = "constantes_hors_norme"
                level = 2
                spo2 -= 2
                heart_rate += 18
            elif last_movement > 1800:
                event = "inactivite"
                level = 1

            if seed % 97 == 0 and risk > 0.65:
                event = "chute_detectee"
                level = 4
                last_movement = 4500
                heart_rate += 25
            if seed % 131 == 0 and risk > 0.75:
                event = "danger_vital"
                level = 5
                spo2 = min(spo2, 86)
                heart_rate = max(heart_rate, 142)

            rows.append({
                "time": ts.isoformat().replace("+00:00", "Z"),
                "resident_id": resident_id,
                "room": profile.get("room"),
                "zone": zone,
                "routine": routine,
                "event": event,
                "alert_level": level,
                "heart_rate": round(heart_rate),
                "spo2": round(max(80, min(100, spo2)), 1),
                "blood_pressure_sys": round(blood_pressure),
                "temperature": round(temperature, 1),
                "respiratory_rate": respiratory_rate,
                "last_movement_ago_s": int(last_movement),
                "ml_risk": round(min(0.98, risk + max(0, level - 1) * 0.12), 2),
            })
        return rows

    def local_report_date(self, value: Optional[str] = None) -> str:
        return value or datetime.now().date().isoformat()

    def alert_level_name(self, level: int) -> str:
        names = ["Stable", "Information", "Attention", "Alerte", "Urgence", "Danger vital"]
        if 0 <= int(level) < len(names):
            return names[int(level)]
        return "Inconnu"

    def risk_label(self, score: float) -> str:
        if score >= 0.75:
            return "eleve"
        if score >= 0.5:
            return "modere"
        if score >= 0.25:
            return "faible"
        return "bas"

    def safe_state_for_report(self, resident_id: str) -> dict:
        raw = self.redis_client.get(f"resident:{resident_id}:state")
        profile = self.effective_resident_profile(resident_id)
        if raw:
            state = json.loads(raw)
        else:
            latest = self.simulated_history_rows(resident_id, days=30, step_hours=6)[-1]
            state = {
                "resident_id": resident_id,
                "name": profile.get("name", resident_id),
                "room": profile.get("room"),
                "floor": 0 if str(profile.get("room", "100")).startswith("1") else 1,
                "current_zone": latest.get("zone"),
                "activity": latest.get("routine"),
                "vitals": {
                    "heart_rate": latest.get("heart_rate"),
                    "spo2": latest.get("spo2"),
                    "blood_pressure_sys": latest.get("blood_pressure_sys"),
                    "temperature": latest.get("temperature"),
                    "respiratory_rate": latest.get("respiratory_rate"),
                },
                "movement": {"last_movement_ago_s": latest.get("last_movement_ago_s")},
                "ml_risk": latest.get("ml_risk", profile.get("risk_factor", 0.3)),
                "caregiver": self.resident_caregiver(resident_id, profile),
            }
        state["profile"] = profile
        state["resident_name"] = state.get("name", profile.get("name", resident_id))
        state["avatar"] = state.get("avatar") or profile.get("avatar", "")
        state["caregiver"] = self.resident_caregiver(resident_id, profile)
        archetype = self.resident_archetype(profile)
        state.setdefault("life_profile", {
            "archetype": archetype,
            "archetype_label": self.archetypes[archetype]["label"],
            "daily_focus": self.archetypes[archetype]["daily_focus"],
            "main_risks": self.archetypes[archetype]["main_risks"],
            "supervision": self.archetypes[archetype]["supervision"],
        })
        return state

    def alerts_for_resident_on_date(self, resident_id: str, report_date: str) -> list[dict]:
        alerts = []
        seen = set()
        for alert in self.alert_engine.get_history(500):
            if alert.get("resident_id") != resident_id:
                continue
            created = str(alert.get("created_at") or alert.get("timestamp") or "")
            if created.startswith(report_date):
                seen.add(alert.get("id") or f"{created}:{alert.get('reason')}")
                alerts.append(alert)
        for raw in self.redis_client.lrange("alerts:history", 0, 999):
            try:
                alert = json.loads(raw)
            except Exception:
                continue
            if alert.get("resident_id") != resident_id:
                continue
            created = str(alert.get("created_at") or alert.get("timestamp") or "")
            key = alert.get("id") or f"{created}:{alert.get('reason')}"
            if created.startswith(report_date) and key not in seen:
                seen.add(key)
                alerts.append(alert)
        return alerts

    def active_alert_for_resident(self, resident_id: str) -> Optional[dict]:
        for alert in self.alert_engine.get_all_active():
            if alert.get("resident_id") == resident_id and not alert.get("resolved"):
                return alert
        return None

    def history_summary(self, resident_id: str) -> dict:
        rows = self.simulated_history_rows(resident_id, days=30, step_hours=6)
        if not rows:
            return {}
        alert_rows = [r for r in rows if r.get("alert_level", 0) > 0]
        events: dict[str, int] = {}
        for row in rows:
            events[row["event"]] = events.get(row["event"], 0) + 1
        avg = lambda key: round(float(np.mean([r[key] for r in rows if r.get(key) is not None])), 1)
        trend = rows[-1]["ml_risk"] - rows[max(0, len(rows) - 15)]["ml_risk"]
        return {
            "days": 30,
            "points": len(rows),
            "avg_vitals": {
                "heart_rate": avg("heart_rate"),
                "spo2": avg("spo2"),
                "blood_pressure_sys": avg("blood_pressure_sys"),
                "temperature": avg("temperature"),
                "respiratory_rate": avg("respiratory_rate"),
            },
            "max_ml_risk": round(max(r["ml_risk"] for r in rows), 2),
            "risk_trend": "hausse" if trend > 0.04 else "baisse" if trend < -0.04 else "stable",
            "alerts_count": len(alert_rows),
            "critical_events": [r for r in alert_rows if r.get("alert_level", 0) >= 3][-8:],
            "event_counts": events,
        }

    def prediction_memory_for_resident(self, resident_id: str) -> dict:
        rows = []
        for raw in self.redis_client.lrange(f"a2a:prediction_history:{resident_id}", 0, 11):
            try:
                rows.append(json.loads(raw))
            except Exception:
                pass
        if len(rows) < 2:
            return {"trend": "indisponible", "delta_15min": 0.0, "points": rows}

        latest = rows[0]
        older = rows[min(3, len(rows) - 1)]
        delta = float(latest.get("risk_60min", 0)) - float(older.get("risk_60min", 0))
        if delta >= 0.18:
            trend = "hausse_rapide"
        elif delta >= 0.07:
            trend = "hausse"
        elif delta <= -0.07:
            trend = "baisse"
        else:
            trend = "stable"
        return {"trend": trend, "delta_15min": round(delta, 3), "points": rows}

    def remember_prediction(self, resident_id: str, result: dict):
        pred = result.get("prediction", {})
        row = {
            "generated_at": result.get("generated_at") or datetime.utcnow().isoformat() + "Z",
            "risk_30min": pred.get("risk_30min", 0),
            "risk_60min": pred.get("risk_60min", 0),
            "recommended_level": pred.get("recommended_level", 0),
            "recommended_level_name": pred.get("recommended_level_name", "Stable"),
        }
        key = f"a2a:prediction_history:{resident_id}"
        self.redis_client.lpush(key, json.dumps(row))
        self.redis_client.ltrim(key, 0, 287)
        self.redis_client.expire(key, 48 * 3600)

    def zone_label(self, zone: str) -> str:
        if not zone:
            return "zone non renseignee"
        if str(zone).startswith("ch"):
            return "chambre"
        labels = {
            "salle_manger": "salle a manger",
            "salle_commune": "salle commune",
            "salle_activites": "salle d'activites",
            "salle_repos": "salle de repos",
            "couloir_principal": "couloir",
            "jardin": "jardin therapeutique",
            "patio": "patio",
            "kine": "kinesitherapie",
            "hors_ehpad": "sortie hors etablissement",
        }
        return labels.get(zone, str(zone).replace("_", " "))

    def routine_label_for_family(self, routine: str) -> str:
        labels = {
            "petit_dejeuner": "petit-dejeuner",
            "petit_dejeuner_en_chambre": "petit-dejeuner en chambre",
            "dejeuner": "dejeuner",
            "dejeuner_en_chambre": "dejeuner en chambre",
            "diner": "diner",
            "diner_en_chambre": "diner en chambre",
            "gouter": "gouter",
            "trajet_repas": "trajet vers le repas",
            "nuit": "repos de nuit",
            "routine": "activite habituelle",
            "animation_apres_midi": "animation",
        }
        return labels.get(routine or "", str(routine or "activite habituelle").replace("_", " "))

    def resident_week_life(self, resident_id: str, state: Optional[dict] = None) -> dict:
        now = datetime.now()
        today_index = now.weekday()
        profile = self.effective_resident_profile(resident_id)
        meal_mode = (state or {}).get("meal_mode") or profile.get("meal_mode") or "salle"
        care_level = (state or {}).get("care_level") or profile.get("care_level") or ""
        if meal_mode == "chambre" or care_level == "chambre":
            meal_note = "Repas servis en chambre selon l'autonomie du jour."
        elif meal_mode == "accompagne":
            meal_note = "Repas en salle avec accompagnement soignant."
        else:
            meal_note = "Repas en salle a manger."

        recent = []
        for row in self.simulated_history_rows(resident_id, days=30, step_hours=6)[-6:]:
            recent.append({
                "time": row.get("time"),
                "label": self.routine_label_for_family(row.get("routine")),
                "zone": self.zone_label(row.get("zone")),
                "event": row.get("event"),
            })

        today = WEEKLY_LIFE_PLAN[today_index]
        current_hour = now.hour
        done = []
        if current_hour >= 10:
            done.append(today["activities"]["morning"])
        if current_hour >= 15:
            done.append(today["activities"]["afternoon"])
        if current_hour >= 19:
            done.append(today["activities"]["evening"])
        if not done:
            done.append("Accueil et installation du matin")

        return {
            "today": today["day"],
            "meal_note": meal_note,
            "today_menu": today["menu"],
            "today_activities": today["activities"],
            "activities_done_today": done,
            "recent_activity": recent,
            "week": WEEKLY_LIFE_PLAN,
        }

    def forecast_points(self, state: dict, hist: dict, alerts_today: list[dict]) -> list[str]:
        v = state.get("vitals", {})
        movement = state.get("movement", {})
        risk = float(state.get("ml_risk", 0))
        points = []
        if risk >= 0.7 or hist.get("risk_trend") == "hausse":
            points.append("Risque a venir augmente: surveiller constantes et comportement dans les prochaines 30-60 min.")
        if v.get("spo2", 100) < 94:
            points.append("SpO2 basse ou limite: verifier tolerance a l'effort, dyspnee et saturation.")
        if v.get("heart_rate", 0) > 105 or v.get("blood_pressure_sys", 0) > 165:
            points.append("Constantes cardio en tension: controle rapproche conseille.")
        if movement.get("last_movement_ago_s", 0) > 1800:
            points.append("Inactivite prolongee: verifier position, confort, hydratation et etat de vigilance.")
        if any(a.get("level", 0) >= 3 for a in alerts_today):
            points.append("Alerte significative aujourd'hui: tracer l'observation et confirmer l'acquittement.")
        if not points:
            points.append("Pas de signal fort a venir; maintenir la surveillance habituelle.")
        return points

    def a2a_prediction_for_resident(self, state: dict, hist: dict, active_alert: Optional[dict] = None) -> dict:
        resident_id = state.get("resident_id")
        history_rows = self.simulated_history_rows(resident_id, days=30, step_hours=6) if resident_id else []
        memory = self.prediction_memory_for_resident(resident_id) if resident_id else {}
        return run_a2a_pipeline(state, hist, history_rows, active_alert=active_alert, prediction_memory=memory)

    def build_resident_daily_report(self, resident_id: str, report_date: Optional[str] = None, force: bool = False) -> dict:
        report_date = self.local_report_date(report_date)
        redis_key = f"daily_report:v8:{report_date}:{resident_id}"
        if not force:
            cached = self.redis_client.get(redis_key)
            if cached:
                return json.loads(cached)

        state = self.safe_state_for_report(resident_id)
        profile = state.get("profile", {})
        v = state.get("vitals", {})
        hist = self.history_summary(resident_id)
        alerts_today = self.alerts_for_resident_on_date(resident_id, report_date)
        active_alert = self.active_alert_for_resident(resident_id)
        risk = float(state.get("ml_risk", 0))
        level = max([a.get("level", 0) for a in alerts_today] + ([active_alert.get("level", 0)] if active_alert else [0]))
        location = state.get("location_label") or state.get("current_zone") or state.get("zone") or f"chambre {state.get('room', profile.get('room'))}"
        forecast = self.forecast_points(state, hist, alerts_today)
        a2a_prediction = self.a2a_prediction_for_resident(state, hist, active_alert=active_alert)
        pathologies = profile.get("pathologies", [])

        report = {
            "date": report_date,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "resident_id": resident_id,
            "resident_name": profile.get("name", state.get("resident_name", resident_id)),
            "avatar": profile.get("avatar", state.get("avatar", "")),
            "room": state.get("room", profile.get("room")),
            "floor": state.get("floor"),
            "caregiver": state.get("caregiver", profile.get("caregiver")),
            "profile": {
                "age": profile.get("age"),
                "mobility": profile.get("mobility"),
                "pathologies": pathologies,
                "avatar": profile.get("avatar", state.get("avatar", "")),
                "care_level": state.get("care_level"),
                "life_profile": state.get("life_profile"),
            },
            "current": {
                "location": location,
                "activity": state.get("activity"),
                "routine": state.get("routine_label") or state.get("time_of_day"),
                "time_label": state.get("time_label"),
                "timestamp_simulated": state.get("timestamp_simulated"),
                "simulated_datetime": state.get("simulated_datetime"),
                "simulated_date": state.get("simulated_date"),
                "simulated_time": state.get("simulated_time"),
                "simulated_weekday": state.get("simulated_weekday"),
                "simulated_day_index": state.get("simulated_day_index"),
                "simulated_label": state.get("simulated_label"),
                "vitals": v,
                "movement": state.get("movement", {}),
                "sensor_events": state.get("sensor_events", {}),
            },
            "life_week": self.resident_week_life(resident_id, state),
            "risk": {
                "ml_risk": round(risk, 2),
                "label": self.risk_label(risk),
                "a2a_risk_30min": a2a_prediction["prediction"]["risk_30min"],
                "a2a_risk_60min": a2a_prediction["prediction"]["risk_60min"],
                "a2a_label_30min": a2a_prediction["prediction"]["label_30min"],
                "a2a_label_60min": a2a_prediction["prediction"]["label_60min"],
                "prediction_trend": a2a_prediction["prediction"].get("prediction_trend"),
                "risk_delta_15min": a2a_prediction["prediction"].get("risk_delta_15min"),
                "alert_level": level,
                "alert_level_name": self.alert_level_name(level),
                "trend_30d": hist.get("risk_trend", "stable"),
            },
            "a2a_prediction": a2a_prediction,
            "history_30d": hist,
            "alerts_today": alerts_today[-10:],
            "transmission_summary": (
                f"{profile.get('name', resident_id)} - chambre {state.get('room', profile.get('room'))}: "
                f"risque {self.risk_label(risk)} ({risk:.0%}), niveau {self.alert_level_name(level)}. "
                f"Position actuelle: {location}. "
                f"{len(alerts_today)} alerte(s) ce jour, {hist.get('alerts_count', 0)} evenement(s) sur 30 jours."
            ),
            "watch_points": list(dict.fromkeys(a2a_prediction["prediction"].get("watch_points", []) + forecast)),
            "next_actions": [
                *a2a_prediction["prediction"].get("actions", [])[:2],
                "Controler les constantes selon le niveau de risque.",
                "Verifier la concordance capteurs chambre/sol/porte si anomalie.",
            ],
            "professional_checks": {
                "location_precise": bool(location and location != f"chambre {state.get('room', profile.get('room'))}"),
                "uses_sensor_context": bool(state.get("sensor_events")),
                "uses_prediction_memory": a2a_prediction["prediction"].get("prediction_trend") is not None,
                "care_profile": state.get("life_profile", {}).get("archetype_label"),
            },
        }
        self.redis_client.setex(redis_key, 45 * 86400, json.dumps(report))
        self.redis_client.hset(f"daily_reports:{report_date}", resident_id, json.dumps(report))
        self.redis_client.expire(f"daily_reports:{report_date}", 45 * 86400)
        return report

    def build_global_daily_report(self, report_date: Optional[str] = None, force: bool = False) -> dict:
        report_date = self.local_report_date(report_date)
        redis_key = f"daily_report:v8:{report_date}:global"
        if not force:
            cached = self.redis_client.get(redis_key)
            if cached:
                return json.loads(cached)

        resident_reports = [
            self.build_resident_daily_report(rid, report_date=report_date, force=force)
            for rid in self.residents_map.keys()
        ]
        resident_reports.sort(key=lambda r: (r["risk"]["alert_level"], r["risk"]["ml_risk"]), reverse=True)
        by_caregiver: dict[str, list[dict]] = {}
        for report in resident_reports:
            by_caregiver.setdefault(report.get("caregiver") or "non_assigne", []).append({
                "resident_id": report["resident_id"],
                "resident_name": report["resident_name"],
                "room": report["room"],
                "risk": report["risk"],
                "summary": report["transmission_summary"],
                "watch_points": report["watch_points"][:2],
            })

        global_report = {
            "date": report_date,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "total_residents": len(resident_reports),
            "risk_counts": {
                "stable": sum(1 for r in resident_reports if r["risk"]["alert_level"] == 0 and r["risk"]["ml_risk"] < 0.5),
                "surveillance": sum(1 for r in resident_reports if r["risk"]["alert_level"] in {1, 2} or 0.5 <= r["risk"]["ml_risk"] < 0.7),
                "urgent": sum(1 for r in resident_reports if r["risk"]["alert_level"] >= 3 or r["risk"]["ml_risk"] >= 0.7),
            },
            "priority_residents": resident_reports[:8],
            "by_caregiver": by_caregiver,
            "residents": resident_reports,
            "handover_sheet": [
                {
                    "resident_id": r["resident_id"],
                    "resident_name": r["resident_name"],
                    "room": r["room"],
                    "caregiver": r.get("caregiver"),
                    "level": r["risk"]["alert_level_name"],
                    "risk": r["risk"]["ml_risk"],
                    "risk_30min": r["risk"].get("a2a_risk_30min"),
                    "risk_60min": r["risk"].get("a2a_risk_60min"),
                    "location": r["current"]["location"],
                    "routine": r["current"].get("routine"),
                    "alerts_today": len(r.get("alerts_today", [])),
                    "history_30d_count": r.get("history_30d", {}).get("alerts_count", 0),
                    "summary": r["transmission_summary"],
                    "watch": " ".join(r["watch_points"][:2]),
                    "actions": " ".join(r["next_actions"][:2]),
                }
                for r in resident_reports
            ],
        }
        self.redis_client.setex(redis_key, 45 * 86400, json.dumps(global_report))
        return global_report
