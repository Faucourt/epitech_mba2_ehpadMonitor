import json
from typing import Any

from app.domain.scenario_kb_mapping import scenario_kb_links_for_state
from app.services.llm.kb_context import (
    _clinical_focus_from_profile,
    _fall_detected,
    _kb_guidance,
    _profile_antecedent_kb_links,
)
from app.services.llm.report_builder import _alert_label, _fmt_bp


def build_prompt(
    profile: dict,
    state: dict,
    alerts_today: list[dict],
    kb_context: str,
    clinical_history: dict | None = None,
) -> str:
    v = state.get("vitals", {})
    ml_risk = float(state.get("ml_risk", 0) or 0)
    alert_lines = "\n".join(f"- niveau {a.get('level', '?')}: {_alert_label(a)}" for a in alerts_today[:6]) or "- Aucune alerte aujourd'hui"
    pathologies = ", ".join(profile.get("pathologies", [])) or "Aucune"
    routine = state.get("routine_analysis") or {}
    movement = state.get("movement") or {}
    location = state.get("location_label") or state.get("location") or state.get("current_zone") or "non renseignee"
    clinical_history = clinical_history or {}
    history_block = json.dumps({
        "transmission_summary": clinical_history.get("transmission_summary"),
        "risk": clinical_history.get("risk"),
        "history_30d": clinical_history.get("history_30d"),
        "watch_points": clinical_history.get("watch_points"),
        "next_actions": clinical_history.get("next_actions"),
        "a2a_prediction": clinical_history.get("a2a_prediction", {}).get("prediction") if isinstance(clinical_history.get("a2a_prediction"), dict) else None,
    }, ensure_ascii=False)[:3500] if clinical_history else "{}"

    return f"""Tu es un assistant d'aide a la decision pour un EHPAD francais. Tu n'es pas le decideur medical: tu expliques les signaux, les hypotheses et les actions de surveillance.

{kb_context}

=== RESIDENT ===
Nom: {profile.get('name', '?')}, age: {profile.get('age', '?')} ans, chambre: {profile.get('room', '?')}
Pathologies: {pathologies}
Mobilite: {profile.get('mobility', '?')}
Archetype KB: {profile.get('archetype_id', 'non renseigne')}
Localisation actuelle: {location}

=== SIGNAUX ACTUELS ===
FC: {v.get('heart_rate', 0):.0f} bpm
SpO2: {v.get('spo2', 0):.1f} %
PA: {_fmt_bp(v.get('blood_pressure_sys'), v.get('blood_pressure_dia'))}
Temperature: {v.get('temperature', 0):.1f} C
Frequence respiratoire: {v.get('respiratory_rate', 16):.0f}/min
Risque ML malaise 30-60 min: {ml_risk:.0%}
Routine: {json.dumps(routine, ensure_ascii=False)[:1200]}
Mouvement/capteurs: {json.dumps(movement, ensure_ascii=False)[:1200]}
Historique patient/DPI: {history_block}

Alertes recentes:
{alert_lines}

=== SORTIE ATTENDUE ===
Reponds uniquement avec un JSON valide. Ne donne pas de diagnostic certain. Structure:
{{
  "resume": "2 phrases utiles pour transmission",
  "synthese_clinique": "analyse concise reliant constantes, comportement et localisation",
  "niveau_risque": "faible|modere|eleve",
  "prediction_30_60min": {{"risque_30min": 0.0, "risque_60min": 0.0, "tendance": "stable|hausse|baisse", "localisation": "...", "commentaire": "..."}},
  "preuves": [{{"signal": "...", "valeur": "...", "interpretation": "...", "gravite": "basse|moyenne|haute"}}],
  "hypotheses": [{{"hypothese": "...", "probabilite": "faible|moderee|elevee|a confirmer", "arguments": ["..."], "a_verifier": ["..."], "conduite_soignant": ["..."], "criteres_escalade": ["..."], "sources_kb": ["..."]}}],
  "points_vigilance": ["..."],
  "actions_soignants": ["..."],
  "actions_prioritaires": [{{"delai": "maintenant|15 min|30-60 min|si aggravation", "action": "...", "responsable": "..."}}],
  "plan_surveillance": [{{"parametre": "...", "frequence": "...", "seuil": "..."}}],
  "complications_possibles": [{{"scenario_id": "SCN...", "nom": "...", "explication": "...", "signes_a_rechercher": ["..."]}}],
  "donnees_a_verifier": ["element clinique ou capteur a confirmer"],
  "conduite_a_tenir_kb": [{{"scenario_id": "SCN...", "delai": "maintenant|urgence|surveillance", "action": "...", "niveau": "level_3"}}],
  "signaux_rassurants": ["..."],
  "incertitudes": ["..."],
  "message_famille": "phrase simple non alarmiste",
  "sources_kb": ["SCN..."]
}}

Contraintes obligatoires:
- inclure au moins 3 actions concretes avec delai et responsable;
- si le contexte contient "Conduites a tenir premiers secours PSC/AFPS", reprendre les actions PSC pertinentes dans conduite_a_tenir_kb;
- citer les ids de sources ou fiches utilisees dans sources_kb;
- ne pas rester vague: chaque action doit dire quoi verifier, quand, et quoi escalader;
- pour chaque hypothese differentielle, remplir a_verifier, conduite_soignant et criteres_escalade;
- si urgence possible: mentionner appel soignant/15/112 selon protocole, DAE/PLS/compressions uniquement si les criteres PSC sont presents.
"""

def _compact_prompt_context(profile: dict, state: dict, alerts_today: list[dict], clinical_history: dict | None = None) -> str:
    vitals = state.get("vitals", {})
    movement = state.get("movement") or {}
    routine = state.get("routine_analysis") or {}
    location = (
        state.get("location_label")
        or state.get("location")
        or state.get("current_zone")
        or profile.get("room")
        or "inconnue"
    )
    alerts = [
        {
            "level": item.get("level"),
            "message": _alert_label(item),
        }
        for item in alerts_today[:5]
    ]
    context = {
        "resident": profile.get("name") or profile.get("id"),
        "age": profile.get("age"),
        "pathologies": profile.get("pathologies", [])[:8],
        "archetype_id": profile.get("archetype_id"),
        "likely_medications": profile.get("likely_medications", [])[:8],
        "preferred_scenarios": profile.get("preferred_scenarios", [])[:6],
        "simulator_scenarios": {
            "active_vital": state.get("scenario") or state.get("scenario_active"),
            "active_movement": state.get("movement_scenario"),
            "planned_primary": state.get("assigned_movement_scenario"),
            "possible_profile": (state.get("assigned_scenarios") or [])[:6],
            "kb_links": scenario_kb_links_for_state(state)[:10],
        },
        "antecedents_kb_links": _profile_antecedent_kb_links(profile)[:6],
        "clinical_focus": _clinical_focus_from_profile(
            profile,
            state,
            max((int(a.get("level", 0) or 0) for a in alerts_today), default=0),
        ),
        "localisation": location,
        "vitals": {
            "heart_rate": vitals.get("heart_rate"),
            "spo2": vitals.get("spo2"),
            "blood_pressure_sys": vitals.get("blood_pressure_sys"),
            "blood_pressure_dia": vitals.get("blood_pressure_dia"),
            "blood_pressure": _fmt_bp(vitals.get("blood_pressure_sys"), vitals.get("blood_pressure_dia")),
            "temperature": vitals.get("temperature"),
            "respiratory_rate": vitals.get("respiratory_rate"),
        },
        "ml_risk": round(float(state.get("ml_risk", 0) or 0), 2),
        "movement": {
            "fall_detected": movement.get("fall_detected") or movement.get("is_fall_detected"),
            "no_movement_minutes": movement.get("no_movement_minutes") or state.get("no_movement_minutes"),
            "zone": movement.get("zone") or state.get("current_zone"),
        },
        "routine_score": routine.get("score", routine.get("anomaly_score")),
        "alerts": alerts,
    }
    if isinstance(clinical_history, dict):
        hist = clinical_history.get("history_30d", clinical_history)
        context["history"] = {
            "alerts_count": hist.get("alerts_count"),
            "risk_trend": hist.get("risk_trend"),
            "watch_points": clinical_history.get("watch_points", [])[:4],
            "next_actions": clinical_history.get("next_actions", [])[:4],
        }
    return json.dumps(context, ensure_ascii=False, default=str)

def _build_fast_summary_prompt(
    resident_name: str,
    profile: dict,
    state: dict,
    alerts_today: list[dict],
    clinical_history: dict | None = None,
) -> str:
    vitals = state.get("vitals", {}) or {}
    movement = state.get("movement") or {}
    alert = alerts_today[0] if alerts_today else {}
    alert_level = max((int(a.get("level", 0) or 0) for a in alerts_today), default=0)
    ml_risk = float(state.get("ml_risk", 0) or state.get("prediction_risk", 0) or 0)
    kb = _kb_guidance(profile, state, ml_risk, alert_level)
    clinical_focus = _clinical_focus_from_profile(profile, state, alert_level)
    main_complications = [
        {
            "id": item.get("scenario_id"),
            "nom": item.get("nom"),
            "signes": item.get("signes_a_rechercher", [])[:3],
        }
        for item in kb.get("complications", [])[:3]
    ]
    kb_actions = [
        {
            "delai": item.get("delai"),
            "action": item.get("action"),
            "source": item.get("scenario_id"),
        }
        for item in kb.get("conduite", [])[:5]
    ]
    context = {
        "resident": resident_name or profile.get("name") or profile.get("id"),
        "age": profile.get("age"),
        "chambre": profile.get("room") or profile.get("chambre"),
        "terrain": profile.get("pathologies", [])[:6],
        "constantes": {
            "FC": vitals.get("heart_rate"),
            "SpO2": vitals.get("spo2"),
            "temperature": vitals.get("temperature"),
            "PA": _fmt_bp(vitals.get("blood_pressure_sys"), vitals.get("blood_pressure_dia")),
            "FR": vitals.get("respiratory_rate"),
        },
        "risque_ml": round(ml_risk, 2),
        "alerte": {
            "niveau": alert.get("level"),
            "message": _alert_label(alert) if alert else None,
        },
        "faits_capteurs": {
            "chute_detectee": _fall_detected(state),
            "inactivite_minutes": movement.get("no_movement_minutes") or state.get("no_movement_minutes"),
            "zone": movement.get("zone") or state.get("current_zone"),
        },
        "scenario_actif": state.get("scenario") or state.get("scenario_active") or state.get("movement_scenario"),
        "focus_clinique": clinical_focus.get("focus", [])[:4],
        "complications_kb": main_complications,
        "cat_kb_prioritaire": kb_actions,
        "sources_kb": kb.get("sources_kb", [])[:6],
    }
    return f"""
Tu es un assistant de transmission EHPAD. Tache courte, mais clinique.

Resident: {context["resident"]}, {context.get("age")} ans, chambre {context.get("chambre") or "non precisee"}
Terrain: {", ".join(str(x) for x in context["terrain"]) or "non precise"}
Constantes: FC={context["constantes"]["FC"]} bpm | SpO2={context["constantes"]["SpO2"]}% | Temp={context["constantes"]["temperature"]}C | PA tension arterielle={context["constantes"]["PA"]} mmHg | FR={context["constantes"]["FR"]}/min
Risque ML: {context["risque_ml"]}
Alerte: niveau {context["alerte"]["niveau"]} - {context["alerte"]["message"]}
Faits capteurs: chute_detectee={str(context["faits_capteurs"]["chute_detectee"]).lower()} | inactivite_min={context["faits_capteurs"]["inactivite_minutes"]} | zone={context["faits_capteurs"]["zone"]}
Scenario actif: {context["scenario_actif"] or "aucun"}
Focus clinique KB: {json.dumps(context["focus_clinique"], ensure_ascii=False)}
Complications KB possibles: {json.dumps(context["complications_kb"], ensure_ascii=False)}
Conduites KB prioritaires: {json.dumps(context["cat_kb_prioritaire"], ensure_ascii=False)}
Sources KB: {", ".join(str(x) for x in context["sources_kb"]) or "aucune"}

Reponds en JSON valide avec exactement ces 5 champs:
{{
  "resume": "2 phrases pour transmission soignante, citer 1 constante ou alerte precise",
  "synthese_clinique": "1 phrase clinique concise",
  "points_vigilance": ["point 1", "point 2", "point 3"],
  "actions_soignants": ["action 1", "action 2", "action 3"],
  "message_famille": "1 phrase simple, pas de diagnostic"
}}

Contraintes:
- ne pose pas de diagnostic certain;
- le resume doit suivre les faits capteurs et les constantes; n'invente jamais une chute si chute_detectee=false;
- ne confonds jamais FC et PA: FC est en bpm, PA est la tension arterielle en mmHg;
- les actions doivent reprendre les conduites KB prioritaires adaptees au probleme dominant;
- cite le probleme dominant: respiratoire, tensionnel, infectieux, chute/trauma, confusion, routine, ou stable;
- sois concret: verifier quoi, quand, et qui alerter si aggravation;
- si les donnees sont rassurantes, le dire sans surmedicaliser.
""".strip()

def _build_clinical_router_prompt(
    profile: dict,
    state: dict,
    alerts_today: list[dict],
    kb_context: str,
    clinical_history: dict | None = None,
) -> str:
    compact = _compact_prompt_context(profile, state, alerts_today, clinical_history)
    kb_slice = kb_context[:2500]
    return f"""
Tu es un copilote clinique EHPAD. Utilise uniquement les donnees fournies.
Objectif: hypotheses differentielles et conduite a tenir soignante reliees au terrain du resident.

Contexte patient:
{compact}

KB officielle / scenarios pertinents:
{kb_slice}

Reponds uniquement en JSON valide:
{{
  "niveau_risque": "faible|modere|eleve",
  "hypotheses": [{{"hypothese": "...", "probabilite": "faible|moderee|elevee|a confirmer", "arguments": ["..."], "a_verifier": ["..."], "conduite_soignant": ["..."], "criteres_escalade": ["..."], "sources_kb": ["..."]}}],
  "actions_prioritaires": [{{"delai": "maintenant|15 min|30-60 min|si aggravation", "action": "...", "responsable": "..."}}],
  "donnees_a_verifier": ["..."],
  "conduite_a_tenir_kb": [{{"scenario_id": "...", "delai": "...", "action": "...", "niveau": "..."}}],
  "sources_kb": ["..."]
}}

Contraintes obligatoires:
- maximum 2 hypotheses, 4 actions prioritaires, 5 donnees a verifier, 4 conduites KB et 5 sources;
- si SpO2 <= 90%, prioriser hypoxemie aigue, tolerance respiratoire, controle SpO2/FR et criteres d'appel urgent;
- relier la CAT au terrain: Parkinson/fausse route/chute, hypertension/neuro-cardio, traitements a risque/iatrogenie;
- chaque hypothese doit contenir a_verifier, conduite_soignant et criteres_escalade;
- reprendre les conduites PSC/AFPS pertinentes si elles sont presentes dans la KB;
- sources_kb doit contenir uniquement des IDs presents dans la KB ci-dessus.
""".strip()
