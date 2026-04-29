"""
Service LLM pour EHPAD Monitor.

Le LLM n'est pas utilise comme "oracle". Il reformule et hierarchise une
analyse clinique deja structuree par les constantes, les alertes, le modele ML,
les routines et la base de connaissances. En cas de sortie faible ou invalide,
un rapport deterministe reste disponible.
"""

import asyncio
import json
import logging
import os
import secrets
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from kb_loader import (
    get_first_aid_actions,
    get_archetype,
    get_charles_terrains_for_profile,
    get_medication_risks,
    get_official_cross_complications,
    get_official_profiles_for_pathologies,
    get_scenario,
    get_scenarios,
    scenario_for_archetype,
)
from app.domain.scenario_kb_mapping import scenario_kb_links_for_state

log = logging.getLogger(__name__)

_JOB_TTL = 3600

LLM_ROUTING_ENABLED = os.getenv("LLM_ROUTING_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
LLM_FAST_MODEL = os.getenv("LLM_FAST_MODEL", "llama3.2:3b")
LLM_CLINICAL_MODEL = os.getenv("LLM_CLINICAL_MODEL", "qwen2.5:7b")
LLM_MEDICAL_MODEL = os.getenv("LLM_MEDICAL_MODEL", "meditron:7b")


class LLMReport(BaseModel):
    resume: str
    points_vigilance: list[str]
    actions_soignants: list[str]
    niveau_risque: Literal["faible", "modere", "eleve"]
    sources_kb: list[str] = Field(default_factory=list)

    synthese_clinique: str | None = None
    prediction_30_60min: dict[str, Any] = Field(default_factory=dict)
    preuves: list[dict[str, Any]] = Field(default_factory=list)
    hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    actions_prioritaires: list[dict[str, Any]] = Field(default_factory=list)
    plan_surveillance: list[dict[str, Any]] = Field(default_factory=list)
    complications_possibles: list[dict[str, Any]] = Field(default_factory=list)
    donnees_a_verifier: list[str] = Field(default_factory=list)
    conduite_a_tenir_kb: list[dict[str, Any]] = Field(default_factory=list)
    signaux_rassurants: list[str] = Field(default_factory=list)
    incertitudes: list[str] = Field(default_factory=list)
    message_famille: str | None = None
    rapport_medical: dict[str, Any] = Field(default_factory=dict)
    llm_trace: dict[str, Any] = Field(default_factory=dict)


_PATHO_TAGS: dict[str, list[str]] = {
    "alzheimer_or_related_disorder": ["alzheimer"],
    "cognitive_decline": ["alzheimer", "parkinson"],
    "copd": ["bpco"],
    "diabetes": ["diabete"],
    "heart_failure": ["insuffisance_cardiaque"],
    "hypertension": ["hypertension"],
    "renal_failure": ["insuffisance_renale"],
    "anticoagulant_treatment": [],
    "balance_disorder": ["parkinson"],
    "fall_history": [],
}


def _patho_matches_tag(pathologies: list[str], tag: str) -> bool:
    keywords = _PATHO_TAGS.get(tag, [tag])
    return any(k in pathologies for k in keywords)


def _med_risk_description(entry: dict) -> str:
    risks = entry.get("risks", [])
    return ", ".join(risks[:5]) if risks else ""


def _fall_detected(state: dict) -> bool:
    movement = state.get("movement") or {}
    return bool(
        state.get("fall_detected")
        or movement.get("fall_detected")
        or movement.get("is_fall_detected")
        or movement.get("ambient_fall_confirmed")
    )


def _profile_antecedent_kb_links(profile: dict) -> list[dict[str, Any]]:
    pathologies = profile.get("pathologies", []) or []
    likely_meds = profile.get("likely_medications", []) or []
    links: list[dict[str, Any]] = []
    for item in get_official_profiles_for_pathologies(pathologies):
        links.append({
            "type": "pathologie",
            "id": item.get("id"),
            "label": item.get("label"),
            "patient_context": item.get("id"),
            "watch": item.get("watch", [])[:6],
            "thresholds": item.get("trigger_adaptation", {}),
            "conduct": item.get("conduct", [])[:5],
            "sources": item.get("source_ids", []),
        })

    for terrain in get_charles_terrains_for_profile(profile)[:6]:
        impact = terrain.get("impact_rapport", {}) or {}
        links.append({
            "type": "terrain_charles",
            "id": terrain.get("id"),
            "label": terrain.get("label"),
            "patient_context": "terrain extrait KB Charles compatible resident",
            "watch": terrain.get("points_a_verifier", [])[:6],
            "thresholds": terrain.get("threshold_hints", {}),
            "conduct": [
                impact.get("interventions"),
                impact.get("surveillance"),
                impact.get("appel_medecin"),
            ],
            "sources": terrain.get("source_refs", []),
        })

    medication_risks = get_medication_risks()
    for med in likely_meds:
        entry = medication_risks.get(med, {})
        if not entry:
            continue
        links.append({
            "type": "traitement_probable",
            "id": med,
            "label": entry.get("label", med),
            "patient_context": med,
            "watch": entry.get("risks", [])[:6],
            "thresholds": entry.get("engine_boosts", {}),
            "conduct": [
                "rechercher changement recent de traitement",
                "surveiller chute, confusion, hypotension ou somnolence selon classe",
                "transmettre a l'IDE/medecin si symptome nouveau ou degradation",
            ],
            "sources": entry.get("source_ids", []),
        })

    preferred = profile.get("preferred_scenarios", []) or []
    for sid in preferred[:4]:
        scenario = get_scenario(sid)
        if not scenario:
            continue
        links.append({
            "type": "scenario_patient",
            "id": sid,
            "label": scenario.get("name", sid),
            "patient_context": "scenario prefere du profil resident",
            "watch": _scenario_signal_names(scenario)[:6],
            "thresholds": {},
            "conduct": [item.get("action") or _human_action(str(item)) if isinstance(item, dict) else _human_action(str(item)) for item in _scenario_actions_as_guidance(scenario)[:5]],
            "sources": [sid],
        })
    return links


def _clinical_focus_from_profile(profile: dict, state: dict, alert_level: int) -> dict[str, Any]:
    vitals = state.get("vitals", {}) or {}
    movement = state.get("movement", {}) or {}
    pathologies = {str(p).lower() for p in profile.get("pathologies", []) or []}
    meds = {str(m).lower() for m in profile.get("likely_medications", []) or []}
    focus: list[str] = []
    escalade: list[str] = []
    differential: list[str] = []
    conduct: list[str] = []

    spo2 = vitals.get("spo2")
    rr = vitals.get("respiratory_rate")
    hr = vitals.get("heart_rate")
    sys = vitals.get("blood_pressure_sys")
    dia = vitals.get("blood_pressure_dia")
    temp = vitals.get("temperature")
    hr = vitals.get("heart_rate")
    sys = vitals.get("blood_pressure_sys")
    dia = vitals.get("blood_pressure_dia")
    temp = vitals.get("temperature")

    if spo2 is not None and float(spo2) < 93:
        severe_spo2 = float(spo2) <= 90
        focus.append(
            "Hypoxemie aigue probable: SpO2 <= 90%, confirmer mesure et tolerance clinique."
            if severe_spo2
            else "Desaturation respiratoire a surveiller: SpO2 < 93%, comparer a la baseline et verifier la tolerance."
        )
        differential.extend([
            "exacerbation respiratoire ou pneumopathie",
            "fausse route/aspiration si contexte repas ou trouble neurologique",
            "decompensation cardio-respiratoire si dyspnee, oedemes ou douleur thoracique",
            "artefact capteur a exclure mais ne pas retarder l'evaluation si signes cliniques",
        ])
        conduct.extend([
            "se rendre au lit ou sur zone, ne pas laisser le resident seul pendant l'evaluation",
            "installer au repos, position demi-assise si dyspnee et selon tolerance",
            "recontroler SpO2 au doigt sur autre doigt si besoin, FR sur 1 minute, FC, PA, temperature et conscience",
            "evaluer dyspnee, cyanose, tirage, parole, douleur thoracique, toux/fievre, encombrement et fausse route recente",
            "alerter IDE immediatement, puis medecin/15 selon protocole si SpO2 persiste <= 90% ou signe de mauvaise tolerance"
            if severe_spo2
            else "informer l'IDE et recontroler rapidement; escalader si SpO2 descend <= 90% ou signe de mauvaise tolerance",
        ])
        escalade.extend([
            "SpO2 <= 88% persistante ou baisse rapide sous baseline",
            "dyspnee au repos, cyanose, tirage, impossibilite de parler",
            "confusion nouvelle, somnolence, malaise ou chute associee",
            "douleur thoracique, signes neurologiques ou aggravation rapide",
        ])
    if rr is not None and float(rr) >= 22:
        focus.append("Tachypnee: signe precoce de deterioration respiratoire/infectieuse a rapprocher de la SpO2.")
        escalade.append("FR >= 25/min ou epuisement respiratoire")
    if hr is not None and (float(hr) >= 120 or float(hr) <= 50):
        focus.append("Frequence cardiaque atypique: rapprocher du malaise, douleur, infection, trouble du rythme ou effet medicamenteux.")
        conduct.extend([
            "recontroler FC manuellement si possible et verifier pouls regulier/irregulier",
            "rechercher douleur thoracique, malaise, sueurs, dyspnee, fievre, deshydratation ou hypoglycemie si diabete",
            "alerter IDE rapidement si FC >= 120, FC <= 50 symptomatique, douleur thoracique, malaise ou dyspnee",
        ])
        escalade.extend([
            "FC >= 130 persistante ou FC <= 40",
            "douleur thoracique, malaise, syncope, dyspnee ou trouble conscience",
        ])
    if temp is not None and float(temp) >= 38:
        differential.append("infection respiratoire, urinaire ou sepsis debutant chez sujet age")
        conduct.extend([
            "recontroler temperature et constantes completes, dont FR, FC, PA et SpO2",
            "rechercher foyer infectieux: toux, douleur urinaire, plaie, frissons, confusion",
            "alerter IDE/medecin selon protocole si confusion, hypotension, tachypnee, SpO2 basse ou degradation rapide",
        ])
        escalade.extend([
            "confusion aigue, hypotension, respiration rapide, SpO2 basse ou marbrures",
            "temperature tres elevee ou hypothermie chez personne agee",
        ])
    if sys is not None and float(sys) >= 180:
        differential.append("poussee hypertensive avec risque neuro-cardio")
        conduct.extend([
            "reprendre PA apres 5 minutes de repos avec systolique et diastolique, verifier brassard et bras adapte",
            "rechercher signes FAST/VITE, cephalee brutale, douleur thoracique, dyspnee, malaise ou trouble conscience",
            "alerter IDE rapidement si PA tres elevee persistante ou symptomes neuro-cardio",
        ])
        escalade.append("deficit FAST, douleur thoracique, dyspnee severe ou trouble conscience")
    if sys is not None and float(sys) < 95:
        differential.append("hypotension, deshydratation, malaise postural ou effet antihypertenseur/diuretique")
        conduct.extend([
            "installer au repos assis ou couche, securiser le resident et eviter lever seul",
            "reprendre PA avec systolique/diastolique apres repos; si possible comparer assis/debout selon protocole",
            "rechercher vertiges, malaise, chute, apports diminues, diarrhee/vomissements, chaleur ou changement de traitement",
            "alerter IDE si PA basse persistante, malaise, chute, confusion ou tachycardie associee",
        ])
        escalade.extend([
            "PAS < 90 persistante, syncope, chute, confusion ou signes de choc",
            "hypotension avec fievre, SpO2 basse ou degradation rapide",
        ])
    if "parkinson" in pathologies:
        focus.append("Parkinson: risque majore de chute, fausse route, freezing et hypotension orthostatique.")
        conduct.extend([
            "assister les transferts/deplacements, ne pas laisser marcher seul pendant l'episode",
            "verifier heure de prise des traitements et rechercher freezing, dysphagie ou fausse route",
        ])
    if "hypertension" in pathologies:
        focus.append("Hypertension: ne pas banaliser dyspnee, douleur thoracique, malaise ou signe neurologique.")
        conduct.append("reprendre PA apres repos et rechercher signes FAST/douleur thoracique/dyspnee")
    if {"benzodiazepines", "psychotropes", "anticholinergics", "antihypertensives"}.intersection(meds):
        focus.append("Traitements a risque possibles: iatrogenie pouvant favoriser chute, confusion, somnolence ou hypotension.")
        differential.append("iatrogenie medicamenteuse ou effet sedatif/hypotenseur")
        conduct.append("rechercher introduction/changement recent de psychotrope, benzodiazepine, anticholinergique ou antihypertenseur")
    if _fall_detected(state):
        focus.append("Chute detectee: traumatisme et duree au sol a evaluer avant mobilisation.")
        escalade.append("traumatisme cranien, douleur intense, deformation, anticoagulant, trouble conscience")

    if alert_level >= 4:
        conduct.append("tracer heure, constantes, signes cliniques, actions realisees et personne alertee")

    return {
        "focus": list(dict.fromkeys(focus))[:8],
        "differential": list(dict.fromkeys(differential))[:8],
        "conduct": list(dict.fromkeys(conduct))[:10],
        "escalade": list(dict.fromkeys(escalade))[:10],
    }


_ACTION_LABELS = {
    "envoyer_soignant_assigné": "Envoyer le soignant assigne",
    "ouvrir_fiche_résident": "Ouvrir le mini-DPI resident",
    "vérifier_localisation": "Verifier la localisation precise",
    "alerter_IDE": "Alerter l'IDE",
    "contrôle_SpO2_au_doigt": "Controler la SpO2 au doigt",
    "contrôle_FR": "Controler la frequence respiratoire",
    "évaluer_dyspnée": "Evaluer dyspnee, cyanose, tirage, tolerance",
    "alerte_urgence_soignants": "Alerter l'equipe soignante en urgence",
    "protocole_respiratoire": "Appliquer le protocole respiratoire de l'etablissement",
    "prévenir_médecin_selon_protocole": "Prevenir le medecin selon protocole",
    "contrôle_tension_couché_debout": "Controler la tension couche/debout si possible",
    "aide_au_retour_assis_ou_couché": "Installer assis ou couche, securiser le resident",
    "contrôle_conscience": "Controler vigilance et conscience",
    "contrôle_traumatisme": "Rechercher traumatisme ou douleur apres malaise/chute",
    "protocole_urgence_établissement": "Activer le protocole urgence etablissement",
    "appel_15_si_critères_confirmés": "Appeler le 15 si criteres de gravite confirmes",
    "prévenir_direction": "Prevenir la direction selon procedure",
}


def _human_action(value: str) -> str:
    return _ACTION_LABELS.get(value, value.replace("_", " ").replace("Ã©", "e").replace("Ã¨", "e"))


def _scenario_actions_as_guidance(scenario: dict) -> list[dict[str, Any]]:
    guidance: list[dict[str, Any]] = []
    actions = scenario.get("actions", {})
    if not isinstance(actions, dict):
        return guidance
    delay_by_level = {
        "level_1": "information",
        "level_2": "surveillance",
        "level_3": "maintenant",
        "level_4": "urgence",
        "level_5": "danger vital",
    }
    for level, items in actions.items():
        if not isinstance(items, list):
            continue
        for item in items[:4]:
            guidance.append({
                "scenario_id": scenario.get("id"),
                "scenario": scenario.get("name"),
                "niveau": level,
                "delai": delay_by_level.get(level, level),
                "action": _human_action(str(item)),
            })
    return guidance


def _scenario_signal_names(scenario: dict) -> list[str]:
    signals: list[str] = []
    for key in ("early_signals_30_60min", "early_signals_days_weeks"):
        for item in scenario.get(key, []) or []:
            if isinstance(item, dict) and item.get("signal"):
                signals.append(str(item["signal"]))
    return signals


_SIGNAL_LABELS = {
    "spo2_drop": "baisse de SpO2 par rapport a la baseline",
    "spo2_drop_3_points_vs_baseline": "SpO2 baisse d'au moins 3 points sous la valeur habituelle",
    "dyspnea_or_spo2_drop": "dyspnee ou baisse de SpO2",
    "respiratory_rate_21_24": "frequence respiratoire entre 21 et 24/min",
    "heart_rate_91_110_or_more": "frequence cardiaque > 90/min ou tachycardie",
    "activity_drop": "baisse d'activite inhabituelle",
    "activité_moins_50_percent_vs_baseline": "activite inferieure de 50% a l'habitude",
    "absence_repas_if_available": "repas non pris ou apports diminues",
    "new_confusion": "confusion nouvelle ou fluctuation inhabituelle",
    "sleep_wake_disruption": "trouble veille-sommeil nouveau",
    "agitation_or_apathy": "agitation ou apathie inhabituelle",
    "agitation or apathy": "agitation ou apathie inhabituelle",
    "temperature_abnormal": "temperature anormale",
    "temperature abnormal": "temperature anormale",
}


def _human_signal(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    return _SIGNAL_LABELS.get(cleaned, cleaned.replace("_", " "))


def _conduct_item(
    scenario_id: str,
    delai: str,
    action: str,
    niveau: str = "clinical_guidance",
    responsable: str = "soignant / IDE selon protocole",
) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "delai": delai,
        "action": action,
        "niveau": niveau,
        "responsable": responsable,
    }


def _select_kb_scenarios(profile: dict, state: dict, ml_risk: float, alert_level: int) -> list[dict]:
    pathologies = [str(p).lower() for p in profile.get("pathologies", [])]
    archetype_id = profile.get("archetype_id", "ARCH_NUTRITION")
    vitals = state.get("vitals", {})
    routine = state.get("routine_analysis") or {}
    movement = state.get("movement") or {}
    selected: dict[str, dict] = {}

    direct_ids: list[str] = []
    if vitals.get("spo2", 100) < 93 or vitals.get("respiratory_rate", 16) >= 21:
        direct_ids.append("SCN003_HYPOXEMIA_BPCO_OR_PNEUMONIA")
    if vitals.get("blood_pressure_sys", 120) < 95:
        direct_ids.extend(["SCN002_ORTHOSTATIC_HYPOTENSION_TOILETS", "SCN005_DEHYDRATION_HEATWAVE_DIURETICS"])
    if vitals.get("temperature", 36.8) >= 38 or vitals.get("heart_rate", 70) >= 110:
        direct_ids.append("SCN004_UTI_SEPSIS_EARLY_DETERIORATION")
    if "diabete" in pathologies:
        direct_ids.append("SCN006_HYPOGLYCEMIA_DIABETES")
    if "alzheimer" in pathologies and (state.get("current_zone") == "hors_ehpad" or state.get("movement_scenario") == "fugue_hors_ehpad"):
        direct_ids.append("SCN007_WANDERING_ELOPEMENT_ALZHEIMER")
    if routine.get("score", routine.get("anomaly_score", 0)) and float(routine.get("score", routine.get("anomaly_score", 0)) or 0) >= 0.4:
        direct_ids.append("SCN008_ROUTINE_BREAKDOWN_APATHY_ISOLATION")
    if _fall_detected(state):
        direct_ids.append("SCN001_FALL_NIGHT_ALZHEIMER_ANTICOAGULANT")
    if "insuffisance_cardiaque" in pathologies:
        direct_ids.append("SCN013_HEART_FAILURE_DECOMPENSATION")
    if ml_risk >= 0.7 or alert_level >= 3:
        direct_ids.append("SCN011_ACUTE_CONFUSION_DELIRIUM")

    scenario_links = scenario_kb_links_for_state(state)
    active_statuses = {"active_vital", "active_movement"}
    direct_ids = [
        link["kb_id"]
        for link in scenario_links
        if link.get("status") in active_statuses
    ] + direct_ids + [
        link["kb_id"]
        for link in scenario_links
        if link.get("status") not in active_statuses
    ]

    for sid in direct_ids:
        scenario = get_scenario(sid)
        if scenario:
            selected[scenario["id"]] = scenario

    for sid in scenario_for_archetype(archetype_id)[:3]:
        scenario = get_scenario(sid)
        if scenario and scenario["id"] not in selected:
            selected[scenario["id"]] = scenario

    if len(selected) < 3 and (ml_risk >= 0.5 or alert_level >= 2):
        for scenario in get_scenarios():
            if scenario["id"] in selected:
                continue
            tags = scenario.get("resident_profile_match", {}).get("any", [])
            if any(_patho_matches_tag(pathologies, tag) for tag in tags):
                selected[scenario["id"]] = scenario
            if len(selected) >= 3:
                break

    return list(selected.values())[:3]


def _kb_guidance(profile: dict, state: dict, ml_risk: float, alert_level: int) -> dict[str, Any]:
    scenarios = _select_kb_scenarios(profile, state, ml_risk, alert_level)
    scenario_complications: list[dict[str, Any]] = []
    official_complications: list[dict[str, Any]] = []
    first_aid_complications: list[dict[str, Any]] = []
    scenario_conduct: list[dict[str, Any]] = []
    official_conduct: list[dict[str, Any]] = []
    first_aid_conduct: list[dict[str, Any]] = []
    checks: list[str] = []
    sources: list[str] = []

    for scenario in scenarios:
        sid = scenario.get("id")
        sources.append(sid)
        raw_signals = _scenario_signal_names(scenario)[:4]
        signals = [_human_signal(signal) for signal in raw_signals if _human_signal(signal)]
        scenario_complications.append({
            "scenario_id": sid,
            "nom": scenario.get("name", sid),
            "explication": scenario.get("clinical_rationale", ""),
            "signes_a_rechercher": signals,
        })
        scenario_conduct.extend(_scenario_actions_as_guidance(scenario))
        for signal in signals:
            checks.append(f"Verifier cliniquement: {signal}")

    pathologies = profile.get("pathologies", [])
    vitals = state.get("vitals", {})
    spo2 = vitals.get("spo2")
    rr = vitals.get("respiratory_rate")
    hr = vitals.get("heart_rate")
    sys = vitals.get("blood_pressure_sys")
    dia = vitals.get("blood_pressure_dia")
    temp = vitals.get("temperature")
    if spo2 is not None and float(spo2) < 93:
        severe_spo2 = float(spo2) <= 90
        first = [
            _conduct_item("hypoxemia_emergency", "maintenant", "Se rendre immediatement aupres du resident et verifier s'il est conscient, s'il parle et s'il respire sans effort majeur.", "kb_resp_alert"),
            _conduct_item("hypoxemia_emergency", "maintenant", "Installer au repos, en position assise ou demi-assise si dyspnee; ne pas faire marcher le resident.", "kb_resp_alert"),
            _conduct_item("hypoxemia_emergency", "maintenant", "Reprendre SpO2 au doigt, frequence respiratoire sur 1 minute, FC, PA, temperature et etat de conscience; changer de doigt/capteur si signal douteux.", "kb_resp_alert"),
            _conduct_item("hypoxemia_emergency", "maintenant", "Rechercher signes de mauvaise tolerance: dyspnee au repos, cyanose, tirage, parole impossible, douleur thoracique, confusion, somnolence, chute ou fausse route.", "kb_resp_alert"),
            _conduct_item(
                "hypoxemia_emergency",
                "urgence" if severe_spo2 else "15 min",
                "Alerter l'IDE sans delai; si SpO2 reste <= 90%, SpO2 <= 88%, detresse respiratoire, douleur thoracique, trouble neurologique ou conscience alteree: declencher medecin/15/112 selon protocole."
                if severe_spo2
                else "Informer l'IDE et reevaluer rapidement; escalader si baisse progressive, dyspnee, confusion, douleur thoracique ou SpO2 <= 90%.",
                "kb_resp_alert",
            ),
        ]
        first_aid_conduct.extend(first)
        checks.extend([
            "SpO2 actuelle comparee a la baseline du resident",
            "Frequence respiratoire comptee sur 1 minute",
            "Tolerance respiratoire: dyspnee, cyanose, tirage, parole, douleur thoracique",
            "Contexte de fausse route: repas recent, toux, voix mouillee, encombrement",
            "Etat neurologique: confusion brutale, somnolence, deficit FAST",
        ])
    if rr is not None and float(rr) >= 21:
        checks.append("Tachypnee: verifier FR, SpO2, temperature, douleur, anxiete et foyer infectieux")
    if sys is not None and float(sys) < 95:
        first_aid_conduct.extend([
            _conduct_item("hypotension_malaise", "maintenant", f"Installer au repos assis ou couche, securiser le resident et ne pas le faire lever seul; PA actuelle {_fmt_bp(sys, dia)}.", "kb_bp_alert"),
            _conduct_item("hypotension_malaise", "maintenant", "Reprendre PA systolique/diastolique apres repos, controler FC, SpO2, temperature et etat de conscience.", "kb_bp_alert"),
            _conduct_item("hypotension_malaise", "maintenant", "Rechercher vertiges, malaise, chute, apports diminues, diarrhee/vomissements, chaleur ou changement de traitement.", "kb_bp_alert"),
            _conduct_item("hypotension_malaise", "urgence", "Alerter IDE si PA basse persistante, PAS < 90, syncope, confusion, chute, tachycardie ou signes de choc.", "kb_bp_alert"),
        ])
        checks.extend([
            "PA systolique et diastolique controlee apres repos",
            "Symptomes hypotension: vertiges, malaise, syncope, chute, confusion",
            "Facteurs favorisants: deshydratation, chaleur, diarrhee/vomissements, diuretique ou antihypertenseur recent",
        ])
    if sys is not None and float(sys) >= 180:
        first_aid_conduct.extend([
            _conduct_item("hypertension_neuro_cardio", "maintenant", f"Installer au repos et reprendre PA systolique/diastolique apres 5 minutes; PA actuelle {_fmt_bp(sys, dia)}.", "kb_bp_alert"),
            _conduct_item("hypertension_neuro_cardio", "maintenant", "Rechercher signes FAST/VITE, cephalee brutale, douleur thoracique, dyspnee, malaise ou trouble conscience.", "kb_bp_alert"),
            _conduct_item("hypertension_neuro_cardio", "urgence", "Alerter IDE/medecin selon protocole si PA tres elevee persistante ou symptome neurologique/cardio-respiratoire.", "kb_bp_alert"),
        ])
        checks.extend([
            "PA systolique et diastolique apres repos avec brassard adapte",
            "Signes FAST/VITE: visage, bras, parole, temps",
            "Douleur thoracique, dyspnee severe, cephalee brutale ou trouble conscience",
        ])
    if hr is not None and (float(hr) >= 120 or float(hr) <= 50):
        first_aid_conduct.extend([
            _conduct_item("heart_rate_abnormal", "maintenant", "Recontroler FC et pouls, verifier regularite, douleur, malaise, sueurs, dyspnee et temperature.", "kb_vitals_alert"),
            _conduct_item("heart_rate_abnormal", "15 min", "Comparer FC a la baseline et rechercher cause: douleur, infection, deshydratation, hypoglycemie si diabete ou medicament recent.", "kb_vitals_alert"),
            _conduct_item("heart_rate_abnormal", "urgence", "Alerter IDE si FC >= 120 persistante, FC <= 50 symptomatique, douleur thoracique, syncope, dyspnee ou trouble conscience.", "kb_vitals_alert"),
        ])
        checks.extend([
            "Pouls regulier ou irregulier",
            "Douleur thoracique, malaise, dyspnee, sueurs, fievre ou hypoglycemie si diabete",
        ])
    if temp is not None and float(temp) >= 38:
        first_aid_conduct.extend([
            _conduct_item("infection_sepsis_watch", "maintenant", "Recontroler temperature et constantes completes: FR, FC, PA systolique/diastolique, SpO2 et conscience.", "kb_infection_alert"),
            _conduct_item("infection_sepsis_watch", "maintenant", "Rechercher foyer infectieux: toux/encombrement, douleur urinaire, plaie, frissons, douleurs, confusion ou baisse d'etat general.", "kb_infection_alert"),
            _conduct_item("infection_sepsis_watch", "urgence", "Alerter IDE/medecin rapidement si confusion, hypotension, tachypnee, SpO2 basse, marbrures ou degradation rapide.", "kb_infection_alert"),
        ])
        checks.extend([
            "Foyer infectieux: respiratoire, urinaire, cutane ou douleur inexpliquee",
            "Signes sepsis: confusion, hypotension, respiration rapide, SpO2 basse, marbrures, degradation rapide",
        ])
    for item in get_official_profiles_for_pathologies(pathologies)[:4]:
        sources.extend(item.get("source_ids", []))
        sources.append(item.get("id"))
        official_complications.append({
            "scenario_id": item.get("id"),
            "nom": item.get("label"),
            "explication": "Reference officielle pathologie: surveiller les signes d'aggravation et comparer a la baseline du resident.",
            "signes_a_rechercher": item.get("watch", [])[:6],
        })
        for action in item.get("conduct", [])[:4]:
            official_conduct.append({
                "scenario_id": item.get("id"),
                "delai": "maintenant" if alert_level >= 3 else "surveillance",
                "action": action,
                "niveau": "official_guidance",
            })
        triggers = item.get("trigger_adaptation", {})
        for key, value in list(triggers.items())[:3]:
            checks.append(f"Seuil adapte {item.get('id')} / {key}: {value}")

    first_aid_actions = get_first_aid_actions()
    selected_first_aid: list[str] = []
    vitals = state.get("vitals", {})
    movement = state.get("movement") or {}
    consciousness = str(state.get("consciousness") or movement.get("consciousness") or "").lower()
    breathing_status = str(state.get("breathing_status") or movement.get("breathing_status") or "").lower()
    if alert_level >= 2 or ml_risk >= 0.5:
        selected_first_aid.append("psc_malaise")
    if _fall_detected(state):
        selected_first_aid.append("psc_traumatisme_chute")
    unconscious = consciousness in {"inconscient", "unconscious", "unresponsive", "ne_repond_pas"}
    abnormal_breathing = breathing_status in {"absente", "anormale", "gasp", "ne_respire_pas", "not_breathing", "abnormal"}
    if unconscious and not abnormal_breathing:
        selected_first_aid.append("psc_perte_connaissance_respire")
    if unconscious and abnormal_breathing:
        selected_first_aid.append("psc_arret_cardiaque")
    for item in first_aid_actions:
        if item.get("id") not in set(selected_first_aid):
            continue
        sources.extend(item.get("source_ids", []))
        first_aid_complications.append({
            "scenario_id": item.get("id"),
            "nom": item.get("label"),
            "explication": "Conduite a tenir premiers secours PSC/AFPS a adapter au protocole de l'etablissement.",
            "signes_a_rechercher": item.get("when", [])[:6],
        })
        for action in item.get("conduct", [])[:5]:
            first_aid_conduct.append({
                "scenario_id": item.get("id"),
                "delai": "urgence" if alert_level >= 4 else "maintenant",
                "action": action,
                "niveau": "psc_first_aid",
            })
        for avoid in item.get("do_not", [])[:3]:
            checks.append(f"PSC/AFPS - eviter: {avoid}")

    checks.extend([
        "Verifier qualite et fraicheur des capteurs avant conclusion.",
        "Comparer aux constantes habituelles et au comportement de base du resident.",
        "Tracer l'observation soignante et l'acquittement si alerte.",
    ])
    return {
        "sources_kb": list(dict.fromkeys([s for s in sources if s])),
        "complications": (first_aid_complications + official_complications + scenario_complications)[:8],
        "conduite": (first_aid_conduct + official_conduct + scenario_conduct)[:14],
        "donnees_a_verifier": list(dict.fromkeys(checks))[:10],
    }


def _allowed_source_ids(profile: dict, state: dict, alerts_today: list[dict]) -> set[str]:
    alert_level = max((int(a.get("level", 0) or 0) for a in alerts_today), default=0)
    ml_risk = float(state.get("ml_risk", 0) or state.get("prediction_risk", 0) or 0)
    ids: set[str] = set()
    for item in _kb_guidance(profile, state, ml_risk, alert_level).get("sources_kb", []):
        if item:
            ids.add(str(item))
    for scenario in _select_kb_scenarios(profile, state, ml_risk, alert_level):
        sid = scenario.get("id")
        if sid:
            ids.add(str(sid))
    for link in scenario_kb_links_for_state(state):
        for key in ("kb_id", "scenario_id", "id"):
            value = link.get(key)
            if value:
                ids.add(str(value))
    for link in _profile_antecedent_kb_links(profile):
        if link.get("id"):
            ids.add(str(link["id"]))
        for source in link.get("sources", []) or []:
            if source:
                ids.add(str(source))
    return ids


def _filter_source_list(values: Any, allowed_sources: set[str]) -> list[str]:
    if not isinstance(values, list):
        return []
    filtered: list[str] = []
    for value in values:
        sid = str(value or "").strip()
        if sid and sid in allowed_sources and sid not in filtered:
            filtered.append(sid)
    return filtered


def _filter_partial_sources(partial: dict[str, Any], allowed_sources: set[str] | None) -> dict[str, Any]:
    if not allowed_sources:
        return partial
    partial = dict(partial)
    if "sources_kb" in partial:
        partial["sources_kb"] = _filter_source_list(partial.get("sources_kb"), allowed_sources)
    for field in ("hypotheses", "complications_possibles", "conduite_a_tenir_kb"):
        if not isinstance(partial.get(field), list):
            continue
        cleaned_items: list[Any] = []
        for item in partial[field]:
            if not isinstance(item, dict):
                cleaned_items.append(item)
                continue
            item = dict(item)
            if "sources_kb" in item:
                item["sources_kb"] = _filter_source_list(item.get("sources_kb"), allowed_sources)
            sid = item.get("scenario_id")
            if sid and str(sid).startswith("SCN") and str(sid) not in allowed_sources:
                item.pop("scenario_id", None)
            cleaned_items.append(item)
        partial[field] = cleaned_items
    return partial


def build_kb_context(
    pathologies: list[str],
    archetype_id: str,
    ml_risk: float,
    alert_level: int,
    state: dict | None = None,
    profile: dict | None = None,
) -> str:
    lines: list[str] = ["=== CONTEXTE BASE DE CONNAISSANCES CLINIQUE ==="]
    profile = profile or {}
    antecedent_links = _profile_antecedent_kb_links(profile)
    if antecedent_links:
        lines.append("\nAntecedents patient relies a la KB et a la conduite a tenir:")
        for link in antecedent_links[:8]:
            lines.append(f"  [{link.get('id')}] {link.get('type')} - {link.get('label')}")
            watch = link.get("watch", [])[:5]
            conduct = link.get("conduct", [])[:4]
            thresholds = link.get("thresholds", {})
            if watch:
                lines.append(f"    A surveiller chez ce resident: {', '.join(str(x) for x in watch)}")
            if thresholds:
                bits = [f"{k}: {v}" for k, v in list(thresholds.items())[:3]]
                lines.append(f"    Seuils/declencheurs adaptes: {' | '.join(bits)}")
            if conduct:
                lines.append(f"    Conduite liee au profil: {', '.join(str(x) for x in conduct)}")

    arch = get_archetype(archetype_id)
    if arch:
        lines.append(f"\nArchetype clinique: {arch.get('name', archetype_id)}")
        risk_factors = arch.get("risk_factors", [])
        if risk_factors:
            lines.append(f"Facteurs de risque: {', '.join(risk_factors[:5])}")
        baseline = arch.get("baseline", {})
        if baseline:
            b = ", ".join(f"{k}={v}" for k, v in list(baseline.items())[:4])
            lines.append(f"References archetype: {b}")

    scenario_objects = _select_kb_scenarios(
        profile or {"pathologies": pathologies, "archetype_id": archetype_id},
        state or {},
        ml_risk,
        alert_level,
    )

    if scenario_objects:
        sim_links = scenario_kb_links_for_state(state or {})
        if sim_links:
            lines.append("\nMapping scenarios simulateur -> KB clinique:")
            for link in sim_links[:10]:
                lines.append(f"  {link.get('scenario')} ({link.get('status')}) -> {link.get('kb_id')}")
        lines.append("\nScenarios cliniques pertinents:")
        for scenario in scenario_objects:
            rationale = scenario.get("clinical_rationale", "")[:180]
            lines.append(f"  [{scenario['id']}] {scenario.get('name', scenario['id'])}")
            if rationale:
                lines.append(f"    Raisonnement: {rationale}")
            early = scenario.get("early_signals_30_60min", [])[:4]
            if early:
                signals = ", ".join(_human_signal(e.get("signal", "?")) for e in early)
                lines.append(f"    Signaux precoces: {signals}")
            actions = scenario.get("actions", {})
            if isinstance(actions, dict) and actions:
                action_bits: list[str] = []
                for level, items in list(actions.items())[:3]:
                    if isinstance(items, list):
                        action_bits.append(f"{level}: {', '.join(_human_action(str(i)) for i in items[:3])}")
                if action_bits:
                    lines.append(f"    Conduite a tenir: {' | '.join(action_bits)}")

    official_profiles = get_official_profiles_for_pathologies(pathologies)
    if official_profiles:
        lines.append("\nReferences officielles par pathologie:")
        for item in official_profiles[:4]:
            lines.append(f"  [{item.get('id')}] {item.get('label')}")
            watch = item.get("watch", [])[:6]
            if watch:
                lines.append(f"    A surveiller: {', '.join(watch)}")
            triggers = item.get("trigger_adaptation", {})
            if triggers:
                trigger_bits = [f"{k}: {v}" for k, v in list(triggers.items())[:3]]
                lines.append(f"    Seuils adaptes: {' | '.join(trigger_bits)}")
            conduct = item.get("conduct", [])[:4]
            if conduct:
                lines.append(f"    Conduite: {', '.join(conduct)}")

    cross_complications = get_official_cross_complications()
    if cross_complications:
        lines.append("\nComplications transversales a ne pas manquer:")
        relevant = []
        patho_set = set(pathologies)
        if "diabete" in patho_set:
            relevant.append("confusion_aigue")
        if {"bpco", "insuffisance_cardiaque"}.intersection(patho_set):
            relevant.extend(["sepsis_infection", "confusion_aigue"])
        if {"alzheimer", "parkinson"}.intersection(patho_set):
            relevant.extend(["chute", "confusion_aigue"])
        if "hypertension" in patho_set:
            relevant.append("avc_suspect")
        if len(patho_set) >= 2:
            relevant.append("deshydratation_canicule")
        selected = [
            item for item in cross_complications
            if item.get("id") in set(relevant)
        ][:4]
        for item in selected:
            lines.append(f"  [{item.get('id')}] Signaux: {', '.join(item.get('watch', [])[:5])}")
            red_flags = item.get("red_flags", [])[:4]
            if red_flags:
                lines.append(f"    Red flags: {', '.join(red_flags)}")

    first_aid_actions = get_first_aid_actions()
    if first_aid_actions:
        vitals = (state or {}).get("vitals", {})
        movement = (state or {}).get("movement", {})
        consciousness = str((state or {}).get("consciousness") or movement.get("consciousness") or "").lower()
        breathing_status = str((state or {}).get("breathing_status") or movement.get("breathing_status") or "").lower()
        current_zone = (state or {}).get("current_zone") or (state or {}).get("zone")
        selected_first_aid: list[str] = []
        if alert_level >= 2 or ml_risk >= 0.5:
            selected_first_aid.append("psc_malaise")
        if _fall_detected(state or {}):
            selected_first_aid.append("psc_traumatisme_chute")
        unconscious = consciousness in {"inconscient", "unconscious", "unresponsive", "ne_repond_pas"}
        abnormal_breathing = breathing_status in {"absente", "anormale", "gasp", "ne_respire_pas", "not_breathing", "abnormal"}
        if unconscious and not abnormal_breathing:
            selected_first_aid.append("psc_perte_connaissance_respire")
        if unconscious and abnormal_breathing:
            selected_first_aid.append("psc_arret_cardiaque")
        if (state or {}).get("sensor_events", {}).get("fall_confirmed_by_room_sensor"):
            selected_first_aid.append("psc_traumatisme_chute")
        if current_zone == "hors_ehpad":
            selected_first_aid.append("psc_malaise")
        selected = [
            item for item in first_aid_actions
            if item.get("id") in set(selected_first_aid)
        ][:4]
        if selected:
            lines.append("\nConduites a tenir premiers secours PSC/AFPS:")
            for item in selected:
                lines.append(f"  [{item.get('id')}] {item.get('label')}")
                conduct = item.get("conduct", [])[:5]
                if conduct:
                    lines.append(f"    Faire: {', '.join(conduct)}")
                do_not = item.get("do_not", [])[:3]
                if do_not:
                    lines.append(f"    Eviter: {', '.join(do_not)}")

    med_risks = get_medication_risks()
    patho_set = set(pathologies)
    med_lines: list[str] = []
    if "alzheimer" in patho_set or "parkinson" in patho_set:
        desc = _med_risk_description(med_risks.get("anticholinergics", {}))
        if desc:
            med_lines.append(f"  Anticholinergiques: {desc}")
    if "hypertension" in patho_set or "insuffisance_cardiaque" in patho_set:
        desc = _med_risk_description(med_risks.get("antihypertensives", {}))
        if desc:
            med_lines.append(f"  Antihypertenseurs: {desc}")
    if "diabete" in patho_set:
        desc = _med_risk_description(med_risks.get("antidiabetics_insulin_sulfonylurea", {}))
        if desc:
            med_lines.append(f"  Antidiabetiques/insuline: {desc}")
    if "bpco" in patho_set:
        desc = _med_risk_description(med_risks.get("benzodiazepines", {}))
        if desc:
            med_lines.append(f"  Benzodiazepines/BPCO: {desc}")
    if len(patho_set) >= 2:
        desc = _med_risk_description(med_risks.get("diuretics", {}))
        if desc:
            med_lines.append(f"  Diuretiques: {desc}")

    if med_lines:
        lines.append("\nRisques medicamenteux:")
        lines.extend(med_lines)

    lines.append("\n=== FIN CONTEXTE KB ===")
    return "\n".join(lines)


def _risk_level(ml_risk: float, alert_level: int, evidence_count: int = 0) -> str:
    if ml_risk >= 0.7 or alert_level >= 4 or evidence_count >= 3:
        return "eleve"
    if ml_risk >= 0.4 or alert_level >= 2 or evidence_count >= 1:
        return "modere"
    return "faible"


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "non renseigne"
    if isinstance(value, float):
        return f"{value:.1f}{suffix}"
    return f"{value}{suffix}"


def _fmt_bp(sys: Any, dia: Any = None) -> str:
    if sys is None:
        return "PA non renseignee"
    try:
        sys_txt = f"{float(sys):.0f}"
    except (TypeError, ValueError):
        sys_txt = str(sys)
    if dia is None:
        return f"{sys_txt} mmHg"
    try:
        dia_txt = f"{float(dia):.0f}"
    except (TypeError, ValueError):
        dia_txt = str(dia)
    return f"{sys_txt}/{dia_txt} mmHg"


def _alert_label(alert: dict) -> str:
    return alert.get("reason") or alert.get("message") or alert.get("title") or "alerte non qualifiee"


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _problem_text(hypotheses: list[dict[str, Any]], kb: dict[str, Any] | None = None, profile: dict | None = None) -> str:
    chunks: list[str] = []
    for hypothesis in hypotheses or []:
        chunks.append(str(hypothesis.get("hypothese", "")))
        chunks.extend(str(x) for x in hypothesis.get("sources_kb", []) or [])
        chunks.extend(str(x) for x in hypothesis.get("arguments", []) or [])
    if kb:
        for item in kb.get("conduite", []) or []:
            chunks.append(str(item.get("scenario_id") or item.get("niveau") or ""))
            chunks.append(str(item.get("action") or ""))
        for item in kb.get("complications", []) or []:
            chunks.append(str(item.get("scenario_id") or ""))
            chunks.append(str(item.get("nom") or ""))
        chunks.extend(str(x) for x in kb.get("sources_kb", []) or [])
    if profile:
        chunks.extend(str(x) for x in profile.get("pathologies", []) or [])
        chunks.extend(str(x) for x in profile.get("likely_medications", []) or [])
    return " ".join(chunks).lower()


def _dominant_problem(
    vitals: dict,
    state: dict,
    hypotheses: list[dict[str, Any]],
    routine_score: float,
    profile: dict | None = None,
    kb: dict[str, Any] | None = None,
) -> str:
    spo2 = vitals.get("spo2")
    sys = vitals.get("blood_pressure_sys")
    temp = vitals.get("temperature")
    hr = vitals.get("heart_rate")
    spo2_f = _safe_float(spo2)
    sys_f = _safe_float(sys)
    temp_f = _safe_float(temp)
    hr_f = _safe_float(hr)
    text = _problem_text(hypotheses, kb=kb, profile=profile)
    if _fall_detected(state):
        return "chute_traumatisme"
    if spo2_f is not None and spo2_f < 93:
        return "respiratoire_hypoxemie"
    if temp_f is not None and temp_f >= 38 or "scn004" in text or "sepsis" in text:
        return "infectieux"
    if "scn012" in text:
        return "avc_suspect"
    if "scn015" in text or "cardiac_malaise" in text:
        return "cardiaque_malaise"
    if "scn006" in text or ("diabete" in text and any(word in text for word in ("hypogly", "malaise", "confusion"))):
        return "diabete_hypoglycemie"
    if sys_f is not None and (sys_f < 95 or sys_f > 180):
        return "tensionnel"
    if "scn013" in text or "insuffisance cardiaque" in text:
        return "insuffisance_cardiaque"
    if "scn005" in text or "deshydratation" in text or ("insuffisance_renale" in text and any(word in text for word in ("hypotension", "confusion", "canicule"))):
        return "deshydratation_renal"
    if "scn010" in text or "retention" in text or "fecalome" in text:
        return "douleur_retention_fecalome"
    if "scn007" in text or "errance" in text or "fugue" in text:
        return "errance_fugue"
    if "scn014" in text or "denutrition" in text or "fragilite" in text:
        return "denutrition_fragilite"
    if "scn009" in text or "iatrogen" in text or "medicament" in text:
        return "iatrogenie_medicamenteuse"
    if "scn011" in text or routine_score >= 0.4 or any("confusion" in str(h.get("hypothese", "")).lower() for h in hypotheses):
        return "confusion_delirium"
    if hr_f is not None and (hr_f >= 120 or hr_f <= 50):
        return "cardiaque_rythme"
    return "surveillance"


def _build_medical_structured_note(
    resident_name: str,
    profile: dict,
    state: dict,
    alerts_today: list[dict],
    clinical_history: dict,
    evidence: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    surveillance: list[dict[str, Any]],
    kb: dict[str, Any],
    niveau: str,
) -> dict[str, Any]:
    vitals = state.get("vitals", {}) or {}
    movement = state.get("movement") or {}
    routine = state.get("routine_analysis") or {}
    routine_score = float(routine.get("score", routine.get("anomaly_score", 0)) or 0)
    pathologies = profile.get("pathologies", []) or []
    likely_meds = profile.get("likely_medications", []) or []
    medication_risks = get_medication_risks()
    charles_terrains = get_charles_terrains_for_profile(profile)
    traitements = []
    for med in likely_meds:
        entry = medication_risks.get(med, {})
        traitements.append({
            "id": med,
            "nom": entry.get("label", med),
            "points_vigilance": entry.get("risks", [])[:4],
            "statut": "probable_deduit_du_profil_kb",
        })
    terrain_context = [
        {
            "id": terrain.get("id"),
            "label": terrain.get("label"),
            "apports": terrain.get("apporte_au_projet", [])[:4],
            "points_a_verifier": terrain.get("points_a_verifier", [])[:6],
            "impact_rapport": terrain.get("impact_rapport", {}),
            "sources": terrain.get("source_refs", []),
        }
        for terrain in charles_terrains
    ]

    active_alert = alerts_today[0] if alerts_today else {}
    location = state.get("location_label") or state.get("location") or state.get("current_zone") or profile.get("room")
    problem = _dominant_problem(vitals, state, hypotheses, routine_score, profile=profile, kb=kb)
    spo2 = vitals.get("spo2")
    rr = vitals.get("respiratory_rate")
    hr = vitals.get("heart_rate")
    sys = vitals.get("blood_pressure_sys")
    dia = vitals.get("blood_pressure_dia")
    temp = vitals.get("temperature")

    appel_medecin = [
        "prevenir medecin coordonnateur/traitant selon protocole si anomalie confirmee ou aggravation",
        "transmettre constantes completes, evolution, contexte, antecedents, traitements probables et actions deja realisees",
    ]
    appel_urgence = [
        "appeler 15/112 selon protocole si detresse vitale, trouble conscience, douleur thoracique, signe neurologique, dyspnee severe ou aggravation rapide"
    ]
    if problem == "respiratoire_hypoxemie":
        appel_medecin.insert(0, "contacter IDE puis medecin si SpO2 reste basse apres controle capteur ou si dyspnee/toux/fievre/fausse route")
        appel_urgence.insert(0, "appeler 15/112 si SpO2 <= 88-90% persistante, cyanose, tirage, parole impossible, confusion ou douleur thoracique")
    elif problem == "tensionnel":
        appel_medecin.insert(0, "contacter IDE/medecin si PA reste tres basse ou tres elevee apres repos et controle brassard")
        appel_urgence.insert(0, "appeler 15/112 si syncope, deficit FAST/VITE, douleur thoracique, dyspnee severe ou trouble conscience")
    elif problem == "infectieux":
        appel_medecin.insert(0, "contacter IDE/medecin si fievre confirmee avec alteration etat general ou foyer infectieux suspect")
        appel_urgence.insert(0, "appeler 15/112 si signes de sepsis: confusion, hypotension, tachypnee, marbrures, SpO2 basse ou degradation rapide")
    elif problem == "chute_traumatisme":
        appel_medecin.insert(0, "contacter IDE/medecin avant mobilisation si douleur, traumatisme, anticoagulant ou doute")
        appel_urgence.insert(0, "appeler 15/112 si perte de connaissance, traumatisme cranien, deformation, douleur intense ou deficit neurologique")
    elif problem == "diabete_hypoglycemie":
        appel_medecin.insert(0, "contacter IDE/medecin si malaise, sueurs, tremblements, confusion ou glycemie anormale chez resident diabetique")
        appel_urgence.insert(0, "appeler 15/112 si perte de connaissance, convulsions, impossibilite de resucrage oral ou trouble de vigilance persistant")
    elif problem == "confusion_delirium":
        appel_medecin.insert(0, "contacter IDE/medecin si confusion brutale, douleur, fievre, retention, hypoxie, hypoglycemie ou changement comportemental net")
        appel_urgence.insert(0, "appeler 15/112 si deficit neurologique, trouble de conscience, SpO2 basse, hypotension, sepsis suspect ou agitation dangereuse")
    elif problem == "avc_suspect":
        appel_medecin.insert(0, "prevenir IDE/medecin apres appel urgent et tracer l'heure de debut ou de derniere fois vu normal")
        appel_urgence.insert(0, "appeler 15/112 immediatement si visage asymetrique, faiblesse d'un bras, trouble parole, trouble visuel ou deficit brutal")
    elif problem in {"cardiaque_malaise", "cardiaque_rythme"}:
        appel_medecin.insert(0, "contacter IDE/medecin si douleur thoracique, malaise, palpitations, dyspnee, sueurs ou FC tres anormale")
        appel_urgence.insert(0, "appeler 15/112 si douleur thoracique persistante, syncope, dyspnee severe, trouble conscience ou signes de choc")
    elif problem == "insuffisance_cardiaque":
        appel_medecin.insert(0, "contacter IDE/medecin si dyspnee, oedemes, prise de poids rapide, toux nocturne ou baisse SpO2 sur terrain cardiaque")
        appel_urgence.insert(0, "appeler 15/112 si detresse respiratoire, douleur thoracique, cyanose, hypotension ou aggravation rapide")
    elif problem == "deshydratation_renal":
        appel_medecin.insert(0, "contacter IDE/medecin si apports bas, diuretique, insuffisance renale, hypotension, confusion ou signes de deshydratation")
        appel_urgence.insert(0, "appeler 15/112 si syncope, hypotension severe, trouble conscience, signes de choc ou deshydratation majeure")
    elif problem == "douleur_retention_fecalome":
        appel_medecin.insert(0, "contacter IDE/medecin si douleur inexpliquee, agitation, globe urinaire suspect, absence de selles ou abdomen douloureux")
        appel_urgence.insert(0, "appeler 15/112 si abdomen aigu, douleur intense, vomissements, malaise, sepsis suspect ou alteration rapide")
    elif problem == "errance_fugue":
        appel_medecin.insert(0, "prevenir IDE/responsable de secteur si resident introuvable, sortie non autorisee, confusion ou risque de fugue")
        appel_urgence.insert(0, "appeler 15/112 si resident retrouve avec traumatisme, hypothermie/deshydratation, confusion severe ou danger immediat")
    elif problem == "denutrition_fragilite":
        appel_medecin.insert(0, "contacter IDE/medecin si perte d'appetit durable, perte de poids, apports insuffisants, fatigue majeure ou chute fonctionnelle")
        appel_urgence.insert(0, "appeler 15/112 seulement si malaise, trouble conscience, detresse vitale ou deshydratation severe associee")
    elif problem == "iatrogenie_medicamenteuse":
        appel_medecin.insert(0, "contacter IDE/medecin si changement recent de traitement avec chute, somnolence, confusion, hypotension ou bradycardie")
        appel_urgence.insert(0, "appeler 15/112 si trouble conscience important, depression respiratoire, traumatisme grave ou malaise severe")

    traitements_a_realiser = [
        "aucun traitement medicamenteux autonome par le systeme; appliquer uniquement prescriptions/protocoles de l'etablissement via IDE/medecin",
        "preparer le dossier de transmission: constantes, heure, evolution, antecedents, traitements probables, allergies si connues",
    ]
    if problem == "respiratoire_hypoxemie":
        traitements_a_realiser.insert(0, "installer au repos, position demi-assise si dyspnee, verifier SpO2/FR et tolerance avant toute mobilisation")
        traitements_a_realiser.append("oxygene/traitement inhalé uniquement si prescription ou protocole local active par IDE/medecin")
    if problem == "tensionnel":
        traitements_a_realiser.insert(0, "reprendre PA systolique/diastolique apres repos, bras adapte, brassard adapte, comparer a la baseline")
    if problem == "infectieux":
        traitements_a_realiser.insert(0, "recontroler temperature et rechercher foyer infectieux; hydratation uniquement selon etat clinique/protocole")
    if problem == "chute_traumatisme":
        traitements_a_realiser.insert(0, "ne pas relever si douleur, traumatisme suspect, trouble conscience ou doute; proteger, couvrir, rassurer")
    if problem == "diabete_hypoglycemie":
        traitements_a_realiser.insert(0, "verifier glycemie capillaire si disponible; mettre au repos; ne pas faire marcher; resucrage uniquement selon protocole si conscient")
    if problem == "confusion_delirium":
        traitements_a_realiser.insert(0, "mettre en securite, environnement calme, lunettes/appareillage si besoin, rechercher douleur, retention, fievre, hypoxie ou hypoglycemie")
    if problem == "avc_suspect":
        traitements_a_realiser.insert(0, "noter heure debut/derniere fois vu normal; ne pas donner a boire ou manger si trouble deglutition; surveiller conscience")
    if problem in {"cardiaque_malaise", "cardiaque_rythme", "insuffisance_cardiaque"}:
        traitements_a_realiser.insert(0, "repos strict, constantes completes, eviter effort, rechercher douleur thoracique/dyspnee/sueurs/syncope")
    if problem == "deshydratation_renal":
        traitements_a_realiser.insert(0, "mettre au repos, verifier apports/diurese, bouche seche, pli cutane, poids recent; hydratation selon tolerance/protocole")
    if problem == "douleur_retention_fecalome":
        traitements_a_realiser.insert(0, "evaluer douleur, abdomen, dernieres selles, mictions; ne pas banaliser agitation nouvelle chez sujet age")
    if problem == "errance_fugue":
        traitements_a_realiser.insert(0, "securiser la zone, rechercher le resident selon protocole, verifier sortie, chute, exposition au froid/chaud et constantes au retour")
    if problem == "denutrition_fragilite":
        traitements_a_realiser.insert(0, "evaluer apports, poids, fatigue, hydratation, troubles deglutition; transmettre pour plan nutritionnel")
    if problem == "iatrogenie_medicamenteuse":
        traitements_a_realiser.insert(0, "verifier changement recent de traitement, horaire de prise, double prise possible, somnolence, hypotension et chute")

    problem_source_ids = {
        "respiratoire_hypoxemie": {"hypoxemia_emergency", "bpco", "psc_malaise", "SCN003_HYPOXEMIA_BPCO_OR_PNEUMONIA"},
        "tensionnel": {"hypotension_malaise", "hypertension_neuro_cardio", "psc_malaise", "SCN002_HYPOTENSION_ORTHOSTATIC_MALAISE"},
        "infectieux": {"infection_sepsis_watch", "psc_malaise", "SCN004_UTI_SEPSIS_EARLY_DETERIORATION"},
        "chute_traumatisme": {"psc_traumatisme_chute", "SCN001_FALL_NIGHT_ALZHEIMER_ANTICOAGULANT"},
        "diabete_hypoglycemie": {"diabete", "SCN006_HYPOGLYCEMIA_DIABETES", "psc_malaise"},
        "confusion_delirium": {"SCN011_ACUTE_CONFUSION_DELIRIUM", "confusion_aigue", "alzheimer", "psc_malaise"},
        "avc_suspect": {"SCN012_STROKE_FAST_SUSPECTED", "avc_suspect", "hypertension_neuro_cardio"},
        "cardiaque_malaise": {"SCN015_CHEST_PAIN_CARDIAC_MALAISE", "heart_rate_abnormal", "psc_malaise"},
        "cardiaque_rythme": {"heart_rate_abnormal", "psc_malaise"},
        "insuffisance_cardiaque": {"SCN013_HEART_FAILURE_DECOMPENSATION", "insuffisance_cardiaque", "hypoxemia_emergency"},
        "deshydratation_renal": {"SCN005_DEHYDRATION_HEATWAVE_DIURETICS", "deshydratation_canicule", "insuffisance_renale", "hypotension_malaise"},
        "douleur_retention_fecalome": {"SCN010_PAIN_URINARY_RETENTION_FECALOMA_AGITATION"},
        "errance_fugue": {"SCN007_WANDERING_ELOPEMENT_ALZHEIMER", "alzheimer"},
        "denutrition_fragilite": {"SCN014_DENUTRITION_FRAILTY_DECLINE", "sujet_age_fragile"},
        "iatrogenie_medicamenteuse": {"SCN009_IATROGENIC_FALL_CONFUSION_AFTER_MED_CHANGE"},
        "surveillance": set(),
    }
    kb_solutions = []
    for item in kb.get("conduite", []):
        action = item.get("action")
        if not action:
            continue
        source = str(item.get("scenario_id") or item.get("niveau") or "")
        is_problem_source = source in problem_source_ids.get(problem, set()) or problem in {"cardiaque_rythme", "surveillance"}
        if is_problem_source:
            kb_solutions.append({
                "delai": item.get("delai", "maintenant"),
                "action": action,
                "source_kb": source,
                "niveau": item.get("niveau"),
            })

    if problem == "respiratoire_hypoxemie":
        solutions_adaptees = {
            "probleme_cible": "Hypoxemie / desaturation sur terrain BPCO",
            "objectif": "confirmer la mesure, evaluer la tolerance respiratoire, eviter l'effort, escalader vite si mauvaise tolerance",
            "a_faire_immediatement": [
                "Aller voir le resident sans attendre et verifier conscience, parole et respiration.",
                "Mettre au repos, position assise ou demi-assise si dyspnee; ne pas faire marcher le resident.",
                "Reprendre SpO2 au doigt, verifier qualite du signal/capteur et comparer a la baseline BPCO.",
                "Compter la frequence respiratoire sur 1 minute et reprendre FC, PA, temperature, etat de conscience.",
            ],
            "a_rechercher_cliniquement": [
                "dyspnee au repos ou a l'effort",
                "cyanose, tirage, impossibilite de parler",
                "douleur thoracique, malaise, sueurs",
                "toux, fievre, encombrement bronchique",
                "fausse route recente: repas, toux pendant/apres repas, voix mouillee",
                "confusion, somnolence ou changement brutal de comportement",
            ],
            "surveillance_rapprochee": [
                "Recontrole SpO2/FR/FC/PA/temperature a 15 min si anomalie confirmee.",
                "Tracer tendance SpO2 et FR; verifier si SpO2 baisse ou reste sous baseline.",
                "Surveiller douleur thoracique, dyspnee, cyanose, confusion et tolerance au repos.",
            ],
            "appel_ide_medecin": [
                "IDE sans delai si SpO2 reste basse apres controle capteur ou si dyspnee/toux/fievre/fausse route.",
                "Medecin selon protocole si anomalie persistante, aggravation, suspicion pneumonie/exacerbation BPCO ou besoin de prescription.",
            ],
            "appel_15_112": [
                "SpO2 <= 88-90% persistante ou baisse rapide sous baseline.",
                "dyspnee au repos, cyanose, tirage, parole impossible.",
                "douleur thoracique, trouble neurologique, confusion/somnolence, detresse respiratoire.",
            ],
            "traitements_protocoles": [
                "Oxygene, aerosol/bronchodilatateur ou autre traitement uniquement si prescription ou protocole local active par IDE/medecin.",
                "Ne pas donner a boire/manger si suspicion de fausse route ou trouble de conscience.",
            ],
            "actions_kb_sources": kb_solutions[:8],
        }
    elif problem == "tensionnel":
        solutions_adaptees = {
            "probleme_cible": "Anomalie tensionnelle / malaise possible",
            "objectif": "confirmer PA systolique/diastolique, securiser le resident et rechercher signes neuro-cardio",
            "a_faire_immediatement": [
                "Installer au repos assis ou couche selon tolerance.",
                "Reprendre PA apres 5 minutes avec brassard adapte, noter systolique et diastolique.",
                "Controler FC, SpO2, temperature, conscience et symptomes.",
            ],
            "a_rechercher_cliniquement": ["vertiges", "syncope/malaise", "douleur thoracique", "dyspnee", "signes FAST/VITE", "deshydratation ou traitement recent"],
            "surveillance_rapprochee": ["Recontrole PA/FC a 15 min si anomalie confirmee.", "Eviter lever seul tant que malaise ou hypotension possible."],
            "appel_ide_medecin": appel_medecin[:4],
            "appel_15_112": appel_urgence[:4],
            "traitements_protocoles": ["Traitement antihypertenseur/hydratation uniquement selon prescription ou protocole IDE/medecin."],
            "actions_kb_sources": kb_solutions[:8],
        }
    elif problem == "infectieux":
        solutions_adaptees = {
            "probleme_cible": "Syndrome infectieux / sepsis a exclure",
            "objectif": "confirmer constantes, rechercher foyer et reperer signes de gravite chez sujet age",
            "a_faire_immediatement": ["Recontroler temperature, FR, FC, PA, SpO2 et conscience.", "Rechercher toux/encombrement, douleur urinaire, plaie, frissons, douleurs, baisse etat general."],
            "a_rechercher_cliniquement": ["confusion aigue", "hypotension", "tachypnee", "SpO2 basse", "marbrures", "degradation rapide"],
            "surveillance_rapprochee": ["Recontrole constantes a 15-30 min selon gravite.", "Tracer foyer suspect et evolution."],
            "appel_ide_medecin": appel_medecin[:4],
            "appel_15_112": appel_urgence[:4],
            "traitements_protocoles": ["Antipyretique, antibiotique, hydratation medicalisee uniquement selon prescription/protocole."],
            "actions_kb_sources": kb_solutions[:8],
        }
    elif problem == "chute_traumatisme":
        solutions_adaptees = {
            "probleme_cible": "Chute / traumatisme possible",
            "objectif": "ne pas aggraver une lesion, evaluer conscience/respiration/douleur et alerter selon gravite",
            "a_faire_immediatement": ["Ne pas relever si douleur importante, traumatisme suspect ou trouble conscience.", "Controler conscience, respiration, douleur, plaie/saignement, deformation.", "Couvrir, rassurer, surveiller constantes."],
            "a_rechercher_cliniquement": ["traumatisme cranien", "douleur intense", "deformation", "deficit neurologique", "anticoagulant", "duree au sol"],
            "surveillance_rapprochee": ["Recontrole douleur, conscience et constantes.", "Tracer circonstances et heure probable de chute."],
            "appel_ide_medecin": appel_medecin[:4],
            "appel_15_112": appel_urgence[:4],
            "traitements_protocoles": ["Antalgie ou mobilisation uniquement selon evaluation IDE/medecin/protocole."],
            "actions_kb_sources": kb_solutions[:8],
        }
    elif problem == "diabete_hypoglycemie":
        solutions_adaptees = {
            "probleme_cible": "Malaise diabetique / hypoglycemie a exclure",
            "objectif": "securiser le resident, verifier la glycemie et traiter uniquement selon protocole si trouble compatible",
            "a_faire_immediatement": [
                "Mettre au repos, ne pas faire marcher le resident et rester avec lui.",
                "Verifier conscience, parole, sueurs, tremblements, faim, paleur, agitation ou confusion.",
                "Controler glycemie capillaire si materiel/protocole disponible, puis reprendre FC, PA, SpO2 et temperature.",
                "Verifier repas saute, effort, insuline/antidiabetique recent ou erreur de prise.",
            ],
            "a_rechercher_cliniquement": [
                "sueurs, tremblements, paleur, faim brutale",
                "confusion, agitation, somnolence ou trouble parole",
                "perte de connaissance ou convulsions",
                "repas non pris, vomissements, infection ou changement traitement",
            ],
            "surveillance_rapprochee": [
                "Recontrole clinique et glycemie selon protocole apres correction ou si symptomes persistent.",
                "Tracer valeur glycemique, heure, repas, traitement recent et evolution neurologique.",
            ],
            "appel_ide_medecin": appel_medecin[:4],
            "appel_15_112": appel_urgence[:4],
            "traitements_protocoles": [
                "Resucrage oral uniquement si resident conscient, capable d'avaler et protocole local valide.",
                "Ne rien donner par la bouche si trouble de conscience ou trouble de deglutition.",
                "Glucagon/traitement injectable uniquement par professionnel habilite selon prescription/protocole.",
            ],
            "actions_kb_sources": kb_solutions[:8],
        }
    elif problem == "confusion_delirium":
        solutions_adaptees = {
            "probleme_cible": "Syndrome confusionnel aigu / delirium",
            "objectif": "identifier une cause reversible et reperer vite les signes de gravite chez la personne agee",
            "a_faire_immediatement": [
                "Mettre le resident en securite, parler calmement, limiter stimulation et risque de chute.",
                "Verifier constantes completes: FC, PA, SpO2, FR, temperature, douleur, glycemie si possible.",
                "Comparer au comportement habituel: debut brutal, fluctuation, sommeil, alimentation, hydratation.",
                "Rechercher douleur, retention urinaire, fecalome, infection, hypoxie, hypoglycemie ou medicament recent.",
            ],
            "a_rechercher_cliniquement": [
                "debut brutal ou fluctuant",
                "somnolence, agitation ou hallucinations",
                "douleur, globe urinaire, constipation",
                "fievre, toux, signes urinaires, deshydratation",
                "deficit neurologique FAST/VITE",
            ],
            "surveillance_rapprochee": [
                "Surveillance rapprochee comportement + constantes toutes 15-30 min si trouble actif.",
                "Tracer ecart a la baseline, facteurs declenchants possibles et reponse aux mesures de securisation.",
            ],
            "appel_ide_medecin": appel_medecin[:4],
            "appel_15_112": appel_urgence[:4],
            "traitements_protocoles": [
                "Contention ou sedatif uniquement selon decision medicale/protocole et en dernier recours.",
                "Corriger cause simple uniquement selon protocole: douleur, hypoglycemie, hypoxie, hydratation, retention.",
            ],
            "actions_kb_sources": kb_solutions[:8],
        }
    elif problem == "avc_suspect":
        solutions_adaptees = {
            "probleme_cible": "Suspicion AVC / deficit neurologique brutal",
            "objectif": "declencher l'urgence, dater le debut et eviter toute perte de chance",
            "a_faire_immediatement": [
                "Faire test FAST/VITE: visage, bras, parole, heure de debut.",
                "Appeler 15/112 sans attendre si signe neurologique brutal.",
                "Noter heure de debut ou derniere fois vu normal.",
                "Surveiller conscience, respiration, SpO2, PA et glycemie si possible.",
            ],
            "a_rechercher_cliniquement": [
                "asymetrie visage",
                "faiblesse ou engourdissement d'un bras/jambe",
                "trouble parole ou comprehension",
                "trouble visuel, vertige brutal, cephalee inhabituelle",
                "chute ou trouble deglutition associe",
            ],
            "surveillance_rapprochee": [
                "Ne pas laisser seul; reevaluer conscience et respiration en attendant secours.",
                "Preparer antecedents, traitements anticoagulants/antiagregants et heure de debut.",
            ],
            "appel_ide_medecin": appel_medecin[:4],
            "appel_15_112": appel_urgence[:4],
            "traitements_protocoles": [
                "Ne pas donner a boire, manger ou medicament si trouble deglutition/conscience.",
                "Ne pas retarder l'appel pour refaire plusieurs mesures.",
            ],
            "actions_kb_sources": kb_solutions[:8],
        }
    elif problem in {"cardiaque_malaise", "cardiaque_rythme"}:
        solutions_adaptees = {
            "probleme_cible": "Malaise cardiaque / trouble du rythme possible",
            "objectif": "mettre au repos, reperer signes coronariens ou choc et escalader rapidement",
            "a_faire_immediatement": [
                "Installer au repos, eviter tout effort et rester a proximite.",
                "Controler FC, regularite du pouls si possible, PA, SpO2, FR, temperature et conscience.",
                "Rechercher douleur thoracique, oppression, dyspnee, sueurs, nausees, malaise ou syncope.",
                "Verifier terrain cardio, anticoagulant/antiagregant et medicament recent.",
            ],
            "a_rechercher_cliniquement": [
                "douleur thoracique ou oppression",
                "dyspnee, sueurs, paleur, nausees",
                "syncope, malaise, palpitations",
                "FC tres rapide, tres lente ou irreguliere",
            ],
            "surveillance_rapprochee": [
                "Surveiller conscience, douleur, dyspnee, SpO2, FC et PA jusqu'a avis.",
                "Tracer heure debut, duree, facteurs declenchants et evolution.",
            ],
            "appel_ide_medecin": appel_medecin[:4],
            "appel_15_112": appel_urgence[:4],
            "traitements_protocoles": [
                "Aucun traitement cardiaque autonome; appliquer prescription/protocole uniquement via IDE/medecin.",
                "Ne pas faire marcher le resident tant que malaise ou douleur non evalue.",
            ],
            "actions_kb_sources": kb_solutions[:8],
        }
    elif problem == "insuffisance_cardiaque":
        solutions_adaptees = {
            "probleme_cible": "Decompensation cardiaque / dyspnee sur terrain fragile",
            "objectif": "evaluer tolerance respiratoire et signes de surcharge, transmettre rapidement",
            "a_faire_immediatement": [
                "Mettre au repos, position demi-assise si dyspnee.",
                "Controler SpO2, FR, FC, PA, temperature et tolerance a la parole.",
                "Rechercher oedemes, prise de poids recente, toux nocturne, orthopnee, fatigue inhabituelle.",
                "Comparer SpO2 et dyspnee a la baseline du resident.",
            ],
            "a_rechercher_cliniquement": [
                "dyspnee au repos ou allonge",
                "oedemes membres inferieurs",
                "prise de poids rapide",
                "toux nocturne, crepitants si evaluation IDE",
                "douleur thoracique ou malaise",
            ],
            "surveillance_rapprochee": [
                "Recontrole SpO2/FR/FC/PA a 15-30 min si dyspnee ou SpO2 basse.",
                "Tracer poids recent, oedemes, tolerance et traitements cardio/diuretiques probables.",
            ],
            "appel_ide_medecin": appel_medecin[:4],
            "appel_15_112": appel_urgence[:4],
            "traitements_protocoles": [
                "Diuretique, oxygene ou adaptation traitement uniquement selon prescription/protocole.",
                "Eviter effort et position allongee si dyspnee.",
            ],
            "actions_kb_sources": kb_solutions[:8],
        }
    elif problem == "deshydratation_renal":
        solutions_adaptees = {
            "probleme_cible": "Deshydratation / risque renal / hypotension",
            "objectif": "evaluer apports, diurese et tolerance hemodynamique, prevenir aggravation renale",
            "a_faire_immediatement": [
                "Installer au repos, securiser lever et marche.",
                "Controler PA couche/assis si possible, FC, temperature, SpO2, conscience.",
                "Verifier apports hydriques, diurese, diarrhee/vomissements, canicule, diuretique ou insuffisance renale.",
                "Rechercher bouche seche, pli cutane, vertiges, confusion, fatigue inhabituelle.",
            ],
            "a_rechercher_cliniquement": [
                "hypotension orthostatique ou malaise au lever",
                "baisse diurese ou urines foncees",
                "confusion, somnolence, faiblesse",
                "vomissements, diarrhee, fievre, chaleur",
            ],
            "surveillance_rapprochee": [
                "Recontrole PA/FC/conscience apres repos et selon protocole.",
                "Tracer apports, diurese, poids si disponible et medicaments a risque.",
            ],
            "appel_ide_medecin": appel_medecin[:4],
            "appel_15_112": appel_urgence[:4],
            "traitements_protocoles": [
                "Hydratation orale seulement si resident conscient, sans fausse route, et selon protocole.",
                "Adaptation diuretique/traitement renal uniquement sur avis medical.",
            ],
            "actions_kb_sources": kb_solutions[:8],
        }
    elif problem == "douleur_retention_fecalome":
        solutions_adaptees = {
            "probleme_cible": "Douleur, retention urinaire ou fecalome possible",
            "objectif": "chercher une cause somatique d'agitation/douleur et eviter retard de prise en charge",
            "a_faire_immediatement": [
                "Evaluer douleur avec echelle adaptee et observer agitation, grimace, position antalgique.",
                "Verifier abdomen, derniere miction, dernieres selles, nausees/vomissements et temperature.",
                "Reprendre constantes completes et rechercher confusion associee.",
                "Prevenir IDE si globe urinaire, abdomen douloureux ou douleur inhabituelle.",
            ],
            "a_rechercher_cliniquement": [
                "absence de miction ou globe suspect",
                "constipation prolongee ou fecalome suspect",
                "douleur abdominale, vomissements",
                "agitation/confusion comme signe de douleur",
                "fievre ou alteration generale",
            ],
            "surveillance_rapprochee": [
                "Tracer douleur, selles/mictions, abdomen et evolution comportementale.",
                "Recontrole constantes si douleur persistante ou agitation.",
            ],
            "appel_ide_medecin": appel_medecin[:4],
            "appel_15_112": appel_urgence[:4],
            "traitements_protocoles": [
                "Antalgie, sondage, laxatif/lavement uniquement selon prescription/protocole.",
                "Ne pas attribuer une agitation nouvelle uniquement au comportement sans recherche somatique.",
            ],
            "actions_kb_sources": kb_solutions[:8],
        }
    elif problem == "errance_fugue":
        solutions_adaptees = {
            "probleme_cible": "Errance / sortie non autorisee / risque de fugue",
            "objectif": "localiser et securiser le resident, puis chercher cause clinique ou environnementale",
            "a_faire_immediatement": [
                "Verifier localisation capteurs, chambre, zones communes et sorties selon protocole.",
                "Prevenir equipe/responsable de secteur et declencher recherche interne si resident introuvable.",
                "Au retour, controler constantes, douleur, chute, exposition froid/chaud, hydratation et confusion.",
                "Rechercher declencheur: douleur, besoin toilette, anxiete, bruit, changement routine.",
            ],
            "a_rechercher_cliniquement": [
                "chute ou traumatisme pendant errance",
                "desorientation brutale ou delirium",
                "douleur, retention, faim/soif, besoin d'elimination",
                "hypothermie, coup de chaleur, fatigue",
            ],
            "surveillance_rapprochee": [
                "Surveillance localisation renforcee et transmissions equipe/famille selon protocole.",
                "Analyser horaire/lieu de recurrence pour adapter plan de soins.",
            ],
            "appel_ide_medecin": appel_medecin[:4],
            "appel_15_112": appel_urgence[:4],
            "traitements_protocoles": [
                "Mesures de securisation environnementale selon protocole, pas de contention sans decision medicale.",
                "Rechercher et traiter cause somatique avant de conclure a un trouble comportemental isole.",
            ],
            "actions_kb_sources": kb_solutions[:8],
        }
    elif problem == "denutrition_fragilite":
        solutions_adaptees = {
            "probleme_cible": "Denutrition / fragilite / declin fonctionnel",
            "objectif": "objectiver baisse des apports et retentissement fonctionnel pour declencher plan nutritionnel",
            "a_faire_immediatement": [
                "Verifier repas pris, hydratation, poids recent, fatigue et capacite a se mobiliser.",
                "Rechercher douleur buccale/dentaire, trouble deglutition, nausees, constipation, humeur depressive.",
                "Controler constantes si faiblesse, malaise, chute ou confusion.",
                "Transmettre au referent/IDE pour suivi nutritionnel et pesee programmee.",
            ],
            "a_rechercher_cliniquement": [
                "perte de poids ou vetements devenus amples",
                "repas non termines, refus alimentaire",
                "fatigue, sarcopenie, baisse marche",
                "trouble deglutition, fausse route, douleur buccale",
                "isolement ou tristesse",
            ],
            "surveillance_rapprochee": [
                "Suivre apports repas/hydratation et poids selon protocole.",
                "Tracer evolution autonomie, chutes, fatigue et refus alimentaire.",
            ],
            "appel_ide_medecin": appel_medecin[:4],
            "appel_15_112": appel_urgence[:4],
            "traitements_protocoles": [
                "Complement nutritionnel, texture adaptee ou bilan dietetique uniquement selon prescription/protocole.",
                "Ne pas forcer alimentation si trouble deglutition suspect: demander evaluation.",
            ],
            "actions_kb_sources": kb_solutions[:8],
        }
    elif problem == "iatrogenie_medicamenteuse":
        solutions_adaptees = {
            "probleme_cible": "Iatrogenie medicamenteuse / effet indesirable possible",
            "objectif": "relier les signes au changement therapeutique possible et prevenir chute, confusion ou depression respiratoire",
            "a_faire_immediatement": [
                "Verifier changement recent de traitement, nouvelle dose, double prise, oubli ou automedication.",
                "Controler conscience, PA, FC, SpO2, FR, douleur et risque de chute.",
                "Rechercher somnolence, confusion, vertiges, hypotension, bradycardie, dyspnee ou chute.",
                "Transmettre rapidement medicaments probables et horaire de prise a l'IDE/medecin.",
            ],
            "a_rechercher_cliniquement": [
                "somnolence ou trouble de vigilance",
                "chute, vertige, hypotension",
                "confusion nouvelle",
                "bradycardie, malaise, dyspnee",
                "prise benzodiazepine, diuretique, antidiabetique, anticoagulant ou antihypertenseur",
            ],
            "surveillance_rapprochee": [
                "Surveiller conscience, respiration, PA/FC et risque de chute jusqu'a avis.",
                "Tracer medicament, dose, heure, symptomes et evolution.",
            ],
            "appel_ide_medecin": appel_medecin[:4],
            "appel_15_112": appel_urgence[:4],
            "traitements_protocoles": [
                "Ne jamais modifier un traitement sans avis medical.",
                "Mesures de securite anti-chute et surveillance rapprochee en attendant avis.",
            ],
            "actions_kb_sources": kb_solutions[:8],
        }
    else:
        solutions_adaptees = {
            "probleme_cible": problem,
            "objectif": "surveillance adaptee au profil et verification clinique des signaux capteurs",
            "a_faire_immediatement": [a.get("action") for a in actions[:4] if a.get("action")],
            "a_rechercher_cliniquement": kb.get("donnees_a_verifier", [])[:8],
            "surveillance_rapprochee": [s.get("seuil") for s in surveillance if s.get("seuil")],
            "appel_ide_medecin": appel_medecin[:4],
            "appel_15_112": appel_urgence[:4],
            "traitements_protocoles": traitements_a_realiser[:4],
            "actions_kb_sources": kb_solutions[:8],
        }

    note = {
        "titre": "Note clinique structuree Mini-DPI",
        "statut": "aide_a_la_decision_non_diagnostic",
        "identite": {
            "nom": resident_name,
            "age": profile.get("age"),
            "chambre": profile.get("room"),
            "mobilite": profile.get("mobility"),
            "soignant_referent": profile.get("caregiver"),
        },
        "contexte_appel": {
            "localisation": location,
            "probleme_dominant": problem,
            "niveau_risque": niveau,
            "alerte_active": _alert_label(active_alert) if active_alert else None,
            "historique_30j": {
                "alertes": (clinical_history.get("history_30d", {}) if isinstance(clinical_history, dict) else {}).get("alerts_count"),
                "tendance": (clinical_history.get("history_30d", {}) if isinstance(clinical_history, dict) else {}).get("risk_trend"),
            },
        },
        "antecedents": pathologies,
        "terrains_kb": terrain_context,
        "traitements_probables_ou_a_verifier": traitements,
        "observation_initiale": {
            "constantes": {
                "fc_bpm": hr,
                "spo2_pct": spo2,
                "fr_min": rr,
                "pa_mmhg": _fmt_bp(sys, dia),
                "temperature_c": temp,
            },
            "etat_capteurs": {
                "chute_detectee": _fall_detected(state),
                "activite": state.get("activity"),
                "inactivite_min": movement.get("no_movement_minutes") or state.get("no_movement_minutes"),
                "routine_score": routine_score,
            },
            "preuves": evidence[:6],
        },
        "hypotheses_differentielles": hypotheses[:4],
        "solutions_kb_adaptees": solutions_adaptees,
        "conduite_immediate_soignant": actions[:8],
        "surveillance": surveillance,
        "traitements_gestes_a_realiser": traitements_a_realiser,
        "criteres_appel_medecin_ide": list(dict.fromkeys(appel_medecin))[:6],
        "criteres_appel_15_112": list(dict.fromkeys(appel_urgence))[:5],
        "transmissions_a_tracer": [
            "heure de debut et heure de controle",
            "constantes completes avec PA systolique/diastolique et FR comptee",
            "signes cliniques observes et tolerance",
            "actions realisees, personne alertee, reponse obtenue",
            "evolution a 15 min puis 30-60 min",
        ],
        "limites": [
            "rapport d'aide a la decision, ne remplace pas l'examen clinique",
            "traitements medicamenteux uniquement selon prescription/protocole local",
        ],
        "sources_kb": kb.get("sources_kb", []),
    }
    note["compte_rendu_medical"] = _build_medical_narrative(note)
    return note


def _build_medical_narrative(note: dict[str, Any]) -> dict[str, Any]:
    identite = note.get("identite", {})
    contexte = note.get("contexte_appel", {})
    observation = note.get("observation_initiale", {})
    constantes = observation.get("constantes", {})
    solutions = note.get("solutions_kb_adaptees", {})
    hypotheses = note.get("hypotheses_differentielles", [])
    main_hyp = hypotheses[0] if hypotheses else {}
    antecedents = note.get("antecedents", [])
    terrains = note.get("terrains_kb", [])
    traitements = note.get("traitements_probables_ou_a_verifier", [])

    atcd_txt = ", ".join(str(x) for x in antecedents) if antecedents else "aucun antecedent renseigne"
    terrain_txt = ", ".join(str(t.get("label") or t.get("id")) for t in terrains if isinstance(t, dict)) or "aucun terrain KB complementaire"
    traitements_txt = ", ".join(
        str(t.get("nom") or t.get("id")) for t in traitements if isinstance(t, dict)
    ) or "traitements habituels non renseignes dans le projet, a verifier dans le DPI reel"
    constants_txt = (
        f"FC {constantes.get('fc_bpm')} bpm, SpO2 {constantes.get('spo2_pct')}%, "
        f"FR {constantes.get('fr_min')}/min, PA {constantes.get('pa_mmhg')}, "
        f"T {constantes.get('temperature_c')} C"
    )
    diagnosis = main_hyp.get("hypothese") or contexte.get("probleme_dominant") or "situation a evaluer"
    arguments = main_hyp.get("arguments", []) if isinstance(main_hyp, dict) else []
    checks = main_hyp.get("a_verifier", []) if isinstance(main_hyp, dict) else []
    escalation = main_hyp.get("criteres_escalade", []) if isinstance(main_hyp, dict) else []
    immediate = solutions.get("a_faire_immediatement", [])
    search = solutions.get("a_rechercher_cliniquement", [])
    follow = solutions.get("surveillance_rapprochee", [])
    protocols = solutions.get("traitements_protocoles", [])

    return {
        "titre": "Compte rendu medical IA - Mini-DPI",
        "avertissement": "Document d'aide a la decision pour transmission soignante; ne remplace pas l'examen clinique ni la decision medicale.",
        "identification_resident": (
            f"{identite.get('nom')} ({identite.get('age')} ans), chambre {identite.get('chambre')}, "
            f"mobilite {identite.get('mobilite')}, soignant referent {identite.get('soignant_referent')}."
        ),
        "diagnostic_initial": {
            "texte": (
                f"Le resident presente un probleme dominant {contexte.get('probleme_dominant')} avec un niveau de risque "
                f"{contexte.get('niveau_risque')}. Les antecedents connus sont: {atcd_txt}. "
                f"Terrains KB retenus: {terrain_txt}. "
                f"L'observation initiale retrouve {constants_txt}. L'hypothese prioritaire est: {diagnosis}."
            ),
            "arguments_cliniques": arguments,
            "elements_a_verifier": checks,
            "examens_ou_controles_utiles": [
                "controle manuel/fiabilise des constantes",
                "examen clinique par soignant/IDE selon protocole",
                "avis medical si anomalie persistante ou signe de gravite",
            ],
        },
        "traitements_et_interventions": {
            "texte": (
                "La prise en charge immediate vise a securiser le resident, confirmer les donnees capteurs "
                "et appliquer les conduites issues de la KB et du protocole d'etablissement. "
                f"Traitements habituels/probables a verifier: {traitements_txt}."
            ),
            "interventions_immediates": immediate,
            "signes_a_rechercher": search,
            "traitements_protocoles": protocols,
            "justification": solutions.get("objectif"),
        },
        "suivi_et_evolution": {
            "texte": (
                "Le suivi doit documenter l'evolution des symptomes, la tolerance clinique, la reponse aux gestes "
                "realises et l'apparition de tout critere d'aggravation."
            ),
            "surveillance": follow,
            "criteres_aggravation": escalation,
            "transmissions": note.get("transmissions_a_tracer", []),
        },
        "conclusion_et_recommandations": {
            "texte": (
                "La situation necessite une surveillance rapprochee et une transmission structuree a l'equipe. "
                "L'appel IDE/medecin ou 15/112 depend de la persistance des anomalies et de la tolerance clinique."
            ),
            "appel_ide_medecin": note.get("criteres_appel_medecin_ide", []),
            "appel_15_112": note.get("criteres_appel_15_112", []),
            "limites": note.get("limites", []),
        },
    }


def _structured_fallback_report(
    resident_name: str,
    profile: dict,
    state: dict,
    alerts_today: list[dict],
    clinical_history: dict | None = None,
    source_note: str = "",
) -> LLMReport:
    vitals = state.get("vitals", {})
    ml_risk = float(state.get("ml_risk", 0) or 0)
    ml_prediction = state.get("ml_prediction") or state.get("a2a_prediction") or {}
    routine = state.get("routine_analysis") or {}
    movement = state.get("movement") or {}
    location = (
        state.get("location_label")
        or state.get("location")
        or state.get("current_zone")
        or profile.get("room")
        or "localisation inconnue"
    )
    alert_level = max((int(a.get("level", 0) or 0) for a in alerts_today), default=0)
    kb = _kb_guidance(profile, state, ml_risk, alert_level)
    clinical_focus = _clinical_focus_from_profile(profile, state, alert_level)
    clinical_history = clinical_history or {}
    hist = clinical_history.get("history_30d", clinical_history) if isinstance(clinical_history, dict) else {}
    history_risk = clinical_history.get("risk", {}) if isinstance(clinical_history, dict) else {}
    history_actions = clinical_history.get("next_actions", []) if isinstance(clinical_history, dict) else []
    history_watch = clinical_history.get("watch_points", []) if isinstance(clinical_history, dict) else []

    evidence: list[dict[str, Any]] = []
    reassuring: list[str] = []

    spo2 = vitals.get("spo2")
    hr = vitals.get("heart_rate")
    sys = vitals.get("blood_pressure_sys")
    dia = vitals.get("blood_pressure_dia")
    temp = vitals.get("temperature")
    rr = vitals.get("respiratory_rate")

    if spo2 is not None and spo2 < 93:
        evidence.append({"signal": "SpO2 basse", "valeur": _fmt(spo2, "%"), "interpretation": "risque hypoxemie ou episode respiratoire", "gravite": "haute"})
    elif spo2 is not None and spo2 >= 95:
        reassuring.append(f"SpO2 conservee ({spo2:.1f}%)")

    if hr is not None and (hr > 110 or hr < 50):
        evidence.append({"signal": "Frequence cardiaque atypique", "valeur": _fmt(hr, " bpm"), "interpretation": "peut preceder malaise, douleur, infection ou trouble du rythme", "gravite": "moyenne"})
    elif hr is not None and 55 <= hr <= 100:
        reassuring.append(f"FC dans une zone habituelle ({hr:.0f} bpm)")

    if sys is not None and (sys < 95 or sys > 180):
        evidence.append({"signal": "Pression arterielle critique", "valeur": _fmt_bp(sys, dia), "interpretation": "surveiller hypotension, poussee hypertensive ou deshydratation", "gravite": "haute"})

    if temp is not None and temp >= 38:
        evidence.append({"signal": "Temperature elevee", "valeur": _fmt(temp, " C"), "interpretation": "signal infectieux possible", "gravite": "moyenne"})
    elif temp is not None and temp < 37.8:
        reassuring.append(f"Temperature non febrile ({temp:.1f} C)")

    if rr is not None and (rr > 24 or rr < 10):
        evidence.append({"signal": "Frequence respiratoire atypique", "valeur": _fmt(rr, "/min"), "interpretation": "surveiller detresse respiratoire ou fatigue", "gravite": "haute"})

    no_move_min = movement.get("no_movement_minutes") or state.get("no_movement_minutes")
    if no_move_min and float(no_move_min) >= 60:
        evidence.append({"signal": "Inactivite prolongee", "valeur": f"{float(no_move_min):.0f} min", "interpretation": "a verifier selon routine et contexte de sommeil", "gravite": "moyenne"})

    if _fall_detected(state):
        evidence.append({"signal": "Chute detectee", "valeur": "capteur positif", "interpretation": "verification immediate necessaire", "gravite": "haute"})

    routine_score = float(routine.get("score", routine.get("anomaly_score", 0)) or 0)
    if routine_score >= 0.4:
        evidence.append({"signal": "Rupture de routine", "valeur": f"{routine_score:.0%}", "interpretation": "changement comportemental potentiellement precoce", "gravite": "moyenne"})

    if ml_risk >= 0.4:
        evidence.append({"signal": "Prediction ML 30-60 min", "valeur": f"{ml_risk:.0%}", "interpretation": "risque prospectif a surveiller avant evenement", "gravite": "haute" if ml_risk >= 0.7 else "moyenne"})

    if hist.get("risk_trend") == "hausse":
        evidence.append({"signal": "Historique 30 jours", "valeur": "tendance risque en hausse", "interpretation": "le risque actuel s'inscrit dans une degradation de tendance", "gravite": "moyenne"})
    if hist.get("alerts_count", 0) >= 3:
        evidence.append({"signal": "Recurrence alertes", "valeur": f"{hist.get('alerts_count')} alertes / 30j", "interpretation": "recurrence a integrer dans la surveillance et les transmissions", "gravite": "moyenne"})

    for alert in alerts_today[:3]:
        evidence.append({"signal": "Alerte active", "valeur": _alert_label(alert), "interpretation": f"niveau {alert.get('level', '?')}", "gravite": "haute" if int(alert.get("level", 0) or 0) >= 4 else "moyenne"})

    niveau = _risk_level(ml_risk, alert_level, len(evidence))
    pathologies = set(profile.get("pathologies", []))
    hypotheses: list[dict[str, Any]] = []
    if spo2 is not None and spo2 < 93:
        escalation = ["SpO2 < 88% ou chute rapide vs baseline", "dyspnee importante", "confusion ou cyanose", "NEWS2 eleve", "detresse respiratoire"]
        if spo2 <= 90:
            escalation = list(dict.fromkeys([
                "SpO2 <= 88-90% persistante malgre controle capteur",
                "dyspnee au repos, cyanose, tirage ou parole impossible",
                "confusion nouvelle, somnolence, malaise ou chute associee",
                "douleur thoracique, signe neurologique ou aggravation rapide",
            ] + escalation))
        hypotheses.append({
            "hypothese": "hypoxemie aigue / episode respiratoire a evaluer sans delai" if spo2 <= 90 else "episode respiratoire ou hypoxemie",
            "probabilite": "elevee" if spo2 <= 90 else "moderee a elevee",
            "arguments": ["SpO2 basse", f"SpO2 mesuree a {spo2:.1f}%", "profil BPCO" if "bpco" in pathologies else "terrain fragile / personne agee"],
            "a_verifier": ["SpO2 au doigt et qualite du signal", "frequence respiratoire", "dyspnee au repos/effort", "cyanose/tirage/parole", "toux, fievre, encombrement ou fausse route", "etat de conscience"],
            "conduite_soignant": ["installer au repos en position confortable/demi-assise si dyspnee", "controler SpO2/FR/FC/PA/temperature", "evaluer tolerance respiratoire et douleur thoracique", "alerter IDE/medecin si SpO2 basse persistante ou signe de mauvaise tolerance"],
            "criteres_escalade": escalation,
            "sources_kb": ["AMELI_BPCO_2026", "RCP_NEWS2", "SCN003_HYPOXEMIA_BPCO_OR_PNEUMONIA"],
        })
    if spo2 is not None and spo2 <= 90 and ("parkinson" in pathologies or "alzheimer" in pathologies):
        hypotheses.append({
            "hypothese": "fausse route ou aspiration a exclure",
            "probabilite": "a confirmer",
            "arguments": ["SpO2 tres basse chez resident neurologique", "terrain favorisant dysphagie/fausse route" if "parkinson" in pathologies else "terrain cognitif fragile"],
            "a_verifier": ["episode repas recent", "toux pendant/apres repas", "voix mouillee", "encombrement", "dyspnee brutale", "temperature"],
            "conduite_soignant": ["installer et surveiller respiration", "ne pas donner a boire/manger si trouble deglutition ou conscience", "alerter IDE si suspicion fausse route", "tracer contexte repas et signes observes"],
            "criteres_escalade": ["dyspnee persistante", "SpO2 <= 90%", "cyanose", "trouble conscience", "toux inefficace ou encombrement important"],
            "sources_kb": ["SCN003_HYPOXEMIA_BPCO_OR_PNEUMONIA", "DGSCGC_PSC_RECOMMANDATIONS"],
        })
    if sys is not None and sys < 95:
        hypotheses.append({
            "hypothese": "hypotension ou deshydratation",
            "probabilite": "moderee",
            "arguments": [f"PA basse ({_fmt_bp(sys, dia)})", "risque de malaise/chute"],
            "a_verifier": ["PA systolique et diastolique controlee au repos", "pouls", "apports hydriques", "diuretiques ou traitement recent", "vertiges au lever", "temperature/chaleur"],
            "conduite_soignant": ["mettre au repos assis/couche", "eviter lever seul", "recontroler PA systolique/diastolique et FC", "rechercher malaise, chute ou confusion", "alerter si hypotension persistante"],
            "criteres_escalade": ["PAS < 90 persistante", "syncope", "confusion", "chute", "tachycardie associee", "signes de deshydratation severe"],
            "sources_kb": ["SANTE_GOUV_CHALEUR_2026", "HAS_CHUTES_REPETEES_2009", "SCN005_DEHYDRATION_HEATWAVE_DIURETICS"],
        })
    if sys is not None and sys > 180:
        hypotheses.append({
            "hypothese": "poussee hypertensive / risque neuro-cardio a evaluer",
            "probabilite": "moderee",
            "arguments": [f"PA elevee ({_fmt_bp(sys, dia)})", "terrain hypertension ou sujet age fragile"],
            "a_verifier": ["PA systolique et diastolique apres repos", "brassard adapte", "douleur thoracique", "dyspnee", "cephalee brutale", "signes FAST/VITE"],
            "conduite_soignant": ["installer au repos", "reprendre PA systolique/diastolique apres 5 min", "rechercher FAST: visage, bras, parole, temps", "alerter IDE si PA persistante ou symptomes"],
            "criteres_escalade": ["deficit FAST/VITE", "douleur thoracique", "dyspnee severe", "trouble conscience", "PA tres elevee persistante"],
            "sources_kb": ["AMELI_AVC_2024", "HAS_AVC_SIGNES_ALERTE_2025", "hypertension"],
        })
    if temp is not None and temp >= 38:
        hypotheses.append({
            "hypothese": "syndrome infectieux debutant ou sepsis precoce",
            "probabilite": "moderee",
            "arguments": ["temperature elevee", "surveillance constantes rapprochee"],
            "a_verifier": ["temperature controlee", "FR", "FC", "PA", "SpO2", "confusion nouvelle", "douleur urinaire/toux/plaie"],
            "conduite_soignant": ["controler constantes completes", "rechercher foyer infectieux", "surveiller conscience", "transmettre rapidement si degradation"],
            "criteres_escalade": ["hypotension", "tachypnee", "confusion aigue", "SpO2 basse", "degradation rapide"],
            "sources_kb": ["WHO_SEPSIS_2024", "SCN004_UTI_SEPSIS_EARLY_DETERIORATION"],
        })
    if routine_score >= 0.4 or "alzheimer" in pathologies:
        hypotheses.append({
            "hypothese": "trouble comportemental ou confusion debutante",
            "probabilite": "a confirmer",
            "arguments": ["rupture de routine", "profil cognitif" if "alzheimer" in pathologies else "activite inhabituelle"],
            "a_verifier": ["douleur", "fievre", "retention urinaire", "constipation", "hypoxie", "hypoglycemie si diabete", "medicament recent", "environnement inhabituel"],
            "conduite_soignant": ["approche calme", "securiser la zone", "rechercher cause somatique simple", "eviter contention non justifiee", "alerter equipe si fugue/chute/agitation dangereuse"],
            "criteres_escalade": ["confusion brutale", "danger pour resident/autrui", "chute", "sortie hors EHPAD", "constantes anormales"],
            "sources_kb": ["HAS_ALZHEIMER_TCP_2012", "SCN011_ACUTE_CONFUSION_DELIRIUM"],
        })
    if _fall_detected(state):
        hypotheses.append({
            "hypothese": "chute ou traumatisme",
            "probabilite": "elevee",
            "arguments": ["capteur chute positif", "personne agee fragile"],
            "a_verifier": ["douleur", "traumatisme cranien", "plaie/saignement", "deformation", "conscience", "anticoagulant", "duree au sol"],
            "conduite_soignant": ["ne pas relever si douleur ou traumatisme suspect", "controler conscience/respiration/constantes", "couvrir et rassurer", "alerter selon gravite"],
            "criteres_escalade": ["perte connaissance", "douleur intense", "deformation", "deficit neurologique", "chute tete sous anticoagulant", "constantes critiques"],
            "sources_kb": ["HAS_CHUTES_REPETEES_2009", "DGSCGC_PSC_RECOMMANDATIONS", "psc_traumatisme_chute"],
        })
    if not hypotheses:
        hypotheses.append({
            "hypothese": "etat stable avec surveillance adaptee au profil",
            "probabilite": "probable",
            "arguments": ["pas de signal critique majeur", "continuer le suivi de tendance"],
            "a_verifier": ["coherence capteurs", "routine habituelle", "absence plainte", "constantes dans la baseline"],
            "conduite_soignant": ["maintenir surveillance habituelle", "tracer si changement", "reevaluer si alerte capteur ou plainte"],
            "criteres_escalade": ["nouvelle douleur", "dyspnee", "chute", "confusion", "constantes hors seuil"],
            "sources_kb": [],
        })

    action_now = "Passer voir le resident, confirmer la localisation et refaire les constantes."
    if niveau == "eleve":
        if _fall_detected(state):
            action_now = "Controle immediat au lit ou sur zone: conscience, respiration, SpO2 au doigt, FR sur 1 minute, FC, PA, temperature, douleur, dyspnee et signes de traumatisme/chute."
        else:
            action_now = "Controle immediat au lit ou sur zone: conscience, respiration, SpO2 au doigt, FR sur 1 minute, FC, PA, temperature, douleur, dyspnee et malaise."
    actions = [
        {"delai": "maintenant", "action": action_now, "responsable": "soignant assigne"},
        {"delai": "15 min", "action": "Recontrole SpO2/FR/FC/PA/temperature, noter l'evolution et verifier si les signes respiratoires ou neurologiques persistent.", "responsable": "soignant assigne / IDE"},
        {"delai": "30-60 min", "action": "Comparer au comportement habituel et reevaluer le score predictif.", "responsable": "IDE / referent"},
    ]
    for action in reversed(clinical_focus["conduct"][:5]):
        if action and all(action != existing["action"] for existing in actions):
            actions.insert(1, {
                "delai": "maintenant" if niveau == "eleve" else "surveillance",
                "action": action,
                "responsable": "soignant / IDE selon gravite",
                "source_kb": "antecedents_patient",
            })
    for kb_action in kb["conduite"][:4]:
        action_text = kb_action.get("action")
        if action_text and all(action_text != existing["action"] for existing in actions):
            actions.append({
                "delai": kb_action.get("delai", "selon protocole"),
                "action": action_text,
                "responsable": "equipe de soins",
                "source_kb": kb_action.get("scenario_id"),
            })
    for action in history_actions[:2]:
        if action and all(action != existing["action"] for existing in actions):
            actions.append({"delai": "transmission", "action": str(action), "responsable": "equipe de soins"})
    if niveau == "eleve":
        actions.append({"delai": "si aggravation", "action": "Escalade selon protocole interne et appel medical si signes critiques.", "responsable": "IDE / medecin / direction selon niveau"})

    surveillance = [
        {"parametre": "Constantes", "frequence": "15 min si risque eleve, sinon 30-60 min", "seuil": "SpO2 < 93, FC > 110 ou < 50, PAS < 95"},
        {"parametre": "Mobilite/localisation", "frequence": "continu via capteurs", "seuil": "absence mouvement inhabituelle, sortie non prevue, chute"},
        {"parametre": "Routine", "frequence": "reevaluation 5 min", "seuil": "ecart durable aux habitudes repas/nuit/deplacement"},
    ]

    risk_60 = ml_prediction.get("risk_60min") or ml_prediction.get("risk") or ml_risk
    trend = ml_prediction.get("prediction_trend") or state.get("prediction_trend") or ("hausse" if ml_risk >= 0.6 else "stable")
    resume = (
        f"{resident_name} est localise(e) en {location}. Risque malaise 30-60 min "
        f"{ml_risk:.0%}, niveau {niveau}. "
        f"{'Signaux principaux: ' + ', '.join(e['signal'] for e in evidence[:3]) if evidence else 'Pas de signal critique majeur.'}"
    )
    if hist:
        resume += f" Historique: {hist.get('alerts_count', 0)} alerte(s)/30j, tendance {hist.get('risk_trend', history_risk.get('trend_30d', 'stable'))}."
    if source_note:
        resume += f" ({source_note})"

    vigilance = list(dict.fromkeys(clinical_focus["focus"] + [e["interpretation"] for e in evidence[:4]])) or ["Surveillance de routine adaptee au profil."]
    if history_watch:
        vigilance = list(dict.fromkeys(vigilance + [str(p) for p in history_watch[:3]]))

    rapport_medical = _build_medical_structured_note(
        resident_name=resident_name,
        profile=profile,
        state=state,
        alerts_today=alerts_today,
        clinical_history=clinical_history,
        evidence=evidence,
        hypotheses=hypotheses,
        actions=actions,
        surveillance=surveillance,
        kb=kb,
        niveau=niveau,
    )

    return LLMReport(
        resume=resume,
        synthese_clinique=resume,
        points_vigilance=vigilance,
        actions_soignants=[a["action"] for a in actions[:3]],
        niveau_risque=niveau,
        prediction_30_60min={
            "risque_30min": round(ml_risk, 2),
            "risque_60min": round(float(risk_60 or ml_risk), 2),
            "tendance": trend,
            "localisation": location,
            "commentaire": "Prediction prospective, a confirmer par evaluation clinique.",
        },
        preuves=evidence,
        hypotheses=hypotheses[:4],
        actions_prioritaires=actions,
        plan_surveillance=surveillance,
        complications_possibles=kb["complications"],
        donnees_a_verifier=list(dict.fromkeys(kb["donnees_a_verifier"] + clinical_focus["differential"] + clinical_focus["escalade"]))[:16],
        conduite_a_tenir_kb=kb["conduite"],
        signaux_rassurants=reassuring[:4],
        incertitudes=[
            "Les capteurs ne remplacent pas l'examen clinique.",
            "Les causes proposees sont des hypotheses a confirmer.",
        ],
        message_famille="Surveillance renforcee en cours par l'equipe, avec verification des constantes et du comportement.",
        rapport_medical=rapport_medical,
        sources_kb=kb["sources_kb"],
    )


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


def _extract_json_block(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        return text[start:end]
    return text


def parse_llm_output(
    raw: str,
    resident_name: str,
    profile: dict,
    state: dict,
    alerts_today: list[dict],
    clinical_history: dict | None = None,
    source_note: str = "",
) -> LLMReport:
    try:
        data = json.loads(_extract_json_block(raw))
        data = _filter_partial_sources(data, _allowed_source_ids(profile, state, alerts_today))
        report = LLMReport(**data)
        fallback = _structured_fallback_report(resident_name, profile, state, alerts_today, clinical_history=clinical_history, source_note="analyse structuree completee automatiquement")
        merged = fallback.model_dump()
        merged.update({k: v for k, v in report.model_dump().items() if v not in (None, [], {})})
        allowed_sources = _allowed_source_ids(profile, state, alerts_today)
        if report.sources_kb and fallback.sources_kb:
            merged["sources_kb"] = _filter_source_list(list(dict.fromkeys(report.sources_kb + fallback.sources_kb)), allowed_sources)
        merged = _filter_partial_sources(merged, allowed_sources)
        return LLMReport(**merged)
    except (json.JSONDecodeError, ValidationError, Exception):
        return _structured_fallback_report(resident_name, profile, state, alerts_today, clinical_history=clinical_history, source_note=source_note or "sortie LLM invalide, repli clinique structure")


def _json_from_llm_text(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(_extract_json_block(raw))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _normalize_risk_label(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    cleaned = (
        value.strip().lower()
        .replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("ë", "e")
        .replace("à", "a")
        .replace("ù", "u")
    )
    aliases = {
        "bas": "faible",
        "basse": "faible",
        "low": "faible",
        "moyen": "modere",
        "moyenne": "modere",
        "moderee": "modere",
        "modere": "modere",
        "moderate": "modere",
        "haut": "eleve",
        "haute": "eleve",
        "elevee": "eleve",
        "eleve": "eleve",
        "high": "eleve",
    }
    return aliases.get(cleaned, cleaned)


def _normalize_check_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    prefixes = ("Rechercher/valider:", "Verifier cliniquement:", "A verifier:")
    for prefix in prefixes:
        if text.startswith(prefix):
            raw = text[len(prefix):].strip()
            return f"Verifier cliniquement: {_human_signal(raw)}"
    if "_" in text and len(text.split()) <= 4:
        return f"Verifier cliniquement: {_human_signal(text)}"
    return text


def _normalize_action_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return _human_action(text)


def _max_risk_label(left: Any, right: Any) -> str:
    order = {"faible": 0, "modere": 1, "eleve": 2}
    left_norm = _normalize_risk_label(left)
    right_norm = _normalize_risk_label(right)
    if order.get(str(right_norm), -1) > order.get(str(left_norm), -1):
        return str(right_norm)
    return str(left_norm if left_norm in order else right_norm if right_norm in order else "faible")


def _normalize_report_partial(partial: dict[str, Any]) -> dict[str, Any]:
    if "niveau_risque" in partial:
        partial["niveau_risque"] = _normalize_risk_label(partial.get("niveau_risque"))
    if isinstance(partial.get("donnees_a_verifier"), list):
        partial["donnees_a_verifier"] = [
            item for item in (_normalize_check_text(v) for v in partial["donnees_a_verifier"]) if item
        ]
    for field in ("actions_prioritaires", "conduite_a_tenir_kb"):
        if isinstance(partial.get(field), list):
            normalized = []
            for item in partial[field]:
                if isinstance(item, dict):
                    item = dict(item)
                    if "action" in item:
                        item["action"] = _normalize_action_text(item.get("action"))
                    normalized.append(item)
                else:
                    normalized.append(_normalize_action_text(item))
            partial[field] = normalized
    if isinstance(partial.get("hypotheses"), list):
        normalized_hypotheses = []
        for item in partial["hypotheses"]:
            if isinstance(item, dict):
                item = dict(item)
                if isinstance(item.get("a_verifier"), list):
                    item["a_verifier"] = [
                        check for check in (_normalize_check_text(v) for v in item["a_verifier"]) if check
                    ]
                if isinstance(item.get("conduite_soignant"), list):
                    item["conduite_soignant"] = [
                        action for action in (_normalize_action_text(v) for v in item["conduite_soignant"]) if action
                    ]
            normalized_hypotheses.append(item)
        partial["hypotheses"] = normalized_hypotheses
    return partial


def _sanitize_fast_summary(partial: dict[str, Any], state: dict) -> dict[str, Any]:
    if not isinstance(partial, dict):
        return {}
    partial = dict(partial)
    if _fall_detected(state):
        return partial

    fall_tokens = ("chute", "fall", "traumatisme")
    for field in ("resume", "synthese_clinique", "message_famille"):
        value = partial.get(field)
        if isinstance(value, str) and any(token in value.lower() for token in fall_tokens):
            partial.pop(field, None)
            continue
        if isinstance(value, str):
            lowered = value.lower()
            if ("fréquence cardiaque" in lowered or "frequence cardiaque" in lowered or "fc" in lowered) and "mmhg" in lowered:
                partial.pop(field, None)
    for field in ("points_vigilance", "actions_soignants"):
        values = partial.get(field)
        if isinstance(values, list):
            partial[field] = [
                item for item in values
                if not any(token in str(item).lower() for token in fall_tokens)
            ]
    return partial


def _summary_is_specific(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    return any(token in lowered for token in ("spo2", "fc", "pa", "risque", "alerte", "chute", "temp", "%", "news"))


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


def _merge_report_from_partial(base: LLMReport, partial: dict[str, Any], allowed_sources: set[str] | None = None) -> LLMReport:
    partial = _filter_partial_sources(partial, allowed_sources)
    partial = _normalize_report_partial(dict(partial))
    merged = base.model_dump()
    allowed = set(merged.keys())
    merge_list_fields = {
        "preuves",
        "hypotheses",
        "actions_prioritaires",
        "plan_surveillance",
        "complications_possibles",
        "donnees_a_verifier",
        "conduite_a_tenir_kb",
        "points_vigilance",
        "actions_soignants",
        "incertitudes",
    }
    for key, value in partial.items():
        if key not in allowed or value in (None, "", [], {}):
            continue
        if key in {"resume", "synthese_clinique"} and not _summary_is_specific(value):
            continue
        if key in merge_list_fields and isinstance(merged.get(key), list) and isinstance(value, list):
            combined: list[Any] = []
            seen: set[str] = set()
            deterministic_first = {
                "hypotheses",
                "actions_prioritaires",
                "plan_surveillance",
                "donnees_a_verifier",
                "conduite_a_tenir_kb",
            }
            ordered_items = (
                [*merged.get(key, []), *value]
                if key in deterministic_first
                else [*value, *merged.get(key, [])]
            )
            for item in ordered_items:
                marker = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, (dict, list)) else str(item)
                if marker in seen:
                    continue
                seen.add(marker)
                combined.append(item)
            limits = {
                "preuves": 8,
                "hypotheses": 6,
                "actions_prioritaires": 12,
                "plan_surveillance": 8,
                "complications_possibles": 8,
                "donnees_a_verifier": 16,
                "conduite_a_tenir_kb": 16,
                "points_vigilance": 10,
                "actions_soignants": 8,
                "incertitudes": 6,
            }
            merged[key] = combined[:limits.get(key, 10)]
        elif isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = value
        elif key == "niveau_risque":
            merged[key] = _max_risk_label(merged.get(key), value)
        elif not isinstance(merged.get(key), (list, dict)):
            merged[key] = value
    if base.sources_kb and isinstance(partial.get("sources_kb"), list):
        merged["sources_kb"] = list(dict.fromkeys([*partial["sources_kb"], *base.sources_kb]))
    if allowed_sources:
        merged["sources_kb"] = _filter_source_list(merged.get("sources_kb"), allowed_sources)
    return LLMReport(**merged)


async def _call_ollama(ollama_host: str, model: str, prompt: str, timeout_s: float = 90.0) -> tuple[str, float]:
    return await _call_ollama_limited(ollama_host, model, prompt, timeout_s=timeout_s)


async def _call_ollama_limited(
    ollama_host: str,
    model: str,
    prompt: str,
    timeout_s: float = 90.0,
    num_predict: int = 900,
    temperature: float = 0.1,
) -> tuple[str, float]:
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(
            f"{ollama_host}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": temperature,
                    "num_predict": num_predict,
                },
            },
        )
        resp.raise_for_status()
        text = resp.json().get("response", "").strip()
    return text, time.monotonic() - t0


def _build_result(
    job_id: str | None,
    resident_id: str,
    resident_name: str,
    report: LLMReport,
    source: str,
    duration_ms: int,
    state: dict,
    alerts_today: list[dict],
    clinical_history: dict | None,
    kb_ctx: str,
) -> dict:
    result = {
        "resident_id": resident_id,
        "resident_name": resident_name,
        "report": report.model_dump(),
        "model": source,
        "duration_ms": duration_ms,
        "ml_risk": round(float(state.get("ml_risk", 0) or 0), 2),
        "alerts_count_today": len(alerts_today),
        "kb_context_injected": bool(kb_ctx),
        "scenario_kb_links": scenario_kb_links_for_state(state)[:12],
        "rag_enabled": True,
        "clinical_decision_support": True,
        "uses_patient_history": bool(clinical_history),
    }
    if job_id:
        result["status"] = "done"
        result["job_id"] = job_id
    return result


async def _generate_report_core(
    resident_id: str,
    resident_name: str,
    profile: dict,
    state: dict,
    alerts_today: list[dict],
    ollama_host: str,
    ollama_model: str,
    clinical_history: dict | None = None,
) -> tuple[LLMReport, str, int, str]:
    pathologies = profile.get("pathologies", [])
    archetype_id = profile.get("archetype_id", "ARCH_NUTRITION")
    ml_risk = float(state.get("ml_risk", 0) or 0)
    alert_level = max((int(a.get("level", 0) or 0) for a in alerts_today), default=0)
    kb_ctx = build_kb_context(pathologies, archetype_id, ml_risk, alert_level, state=state, profile=profile)

    if LLM_ROUTING_ENABLED:
        return await _generate_report_core_routed(
            resident_id=resident_id,
            resident_name=resident_name,
            profile=profile,
            state=state,
            alerts_today=alerts_today,
            ollama_host=ollama_host,
            ollama_model=ollama_model,
            clinical_history=clinical_history,
            kb_ctx=kb_ctx,
        )

    prompt = build_prompt(profile, state, alerts_today, kb_ctx, clinical_history=clinical_history)

    source = ollama_model
    duration_ms = 0
    raw_text = ""
    source_note = ""
    try:
        raw_text, duration_s = await _call_ollama(ollama_host, ollama_model, prompt)
        duration_ms = int(duration_s * 1000)
        log.info("LLM report %s - %s ms - prompt %s chars", resident_id, duration_ms, len(prompt))
    except Exception as exc:
        log.warning("LLM Ollama indisponible pour %s: %s", resident_id, exc)
        source = "fallback structure (Ollama indisponible)"
        source_note = "Ollama indisponible"

    report = parse_llm_output(raw_text, resident_name, profile, state, alerts_today, clinical_history=clinical_history, source_note=source_note)
    return report, source, duration_ms, kb_ctx


async def _generate_report_core_routed(
    resident_id: str,
    resident_name: str,
    profile: dict,
    state: dict,
    alerts_today: list[dict],
    ollama_host: str,
    ollama_model: str,
    clinical_history: dict | None,
    kb_ctx: str,
) -> tuple[LLMReport, str, int, str]:
    base = _structured_fallback_report(
        resident_name,
        profile,
        state,
        alerts_today,
        clinical_history=clinical_history,
        source_note="base deterministe completee par routage LLM",
    )
    report = base
    duration_ms = 0
    used_models: list[str] = []
    failed_models: list[str] = []
    trace_steps: list[dict[str, Any]] = []
    allowed_sources = _allowed_source_ids(profile, state, alerts_today)

    fast_model = LLM_FAST_MODEL or ollama_model
    clinical_model = LLM_CLINICAL_MODEL or ollama_model
    medical_model = LLM_MEDICAL_MODEL or ollama_model

    fast_prompt = _build_fast_summary_prompt(resident_name, profile, state, alerts_today, clinical_history)
    try:
        raw_fast, fast_duration = await _call_ollama_limited(
            ollama_host,
            fast_model,
            fast_prompt,
            timeout_s=50.0,
            num_predict=420,
            temperature=0.1,
        )
        duration_ms += int(fast_duration * 1000)
        fast_data = _json_from_llm_text(raw_fast)
        fast_data = _sanitize_fast_summary(fast_data, state)
        report = _merge_report_from_partial(report, fast_data, allowed_sources=allowed_sources)
        used_models.append(f"fast={fast_model}")
        trace_steps.append({
            "agent": "Synthese rapide",
            "model": fast_model,
            "role": "Resume soignant, points de vigilance courts, message famille",
            "status": "ok",
            "duration_ms": int(fast_duration * 1000),
            "fields": sorted([k for k in fast_data.keys() if k in {"resume", "synthese_clinique", "points_vigilance", "actions_soignants", "message_famille"}]),
        })
        log.info("LLM fast summary %s - %s ms - prompt %s chars", resident_id, int(fast_duration * 1000), len(fast_prompt))
    except Exception as exc:
        failed_models.append(f"fast={fast_model}")
        trace_steps.append({
            "agent": "Synthese rapide",
            "model": fast_model,
            "role": "Resume soignant, points de vigilance courts, message famille",
            "status": "failed",
            "error": str(exc)[:180],
        })
        log.warning("LLM fast indisponible pour %s (%s): %s", resident_id, fast_model, exc)

    clinical_prompt = _build_clinical_router_prompt(profile, state, alerts_today, kb_ctx, clinical_history)
    try:
        raw_clinical, clinical_duration = await _call_ollama_limited(
            ollama_host,
            clinical_model,
            clinical_prompt,
            timeout_s=95.0,
            num_predict=950,
            temperature=0.05,
        )
        duration_ms += int(clinical_duration * 1000)
        clinical_data = _json_from_llm_text(raw_clinical)
        report = _merge_report_from_partial(report, clinical_data, allowed_sources=allowed_sources)
        used_models.append(f"clinical={clinical_model}")
        trace_steps.append({
            "agent": "Analyse clinique KB",
            "model": clinical_model,
            "role": "Hypotheses differentielles, conduite a tenir, surveillance, sources KB",
            "status": "ok",
            "duration_ms": int(clinical_duration * 1000),
            "fields": sorted([k for k in clinical_data.keys() if k in {"niveau_risque", "hypotheses", "actions_prioritaires", "donnees_a_verifier", "conduite_a_tenir_kb", "sources_kb"}]),
        })
        log.info("LLM clinical %s - %s ms - prompt %s chars", resident_id, int(clinical_duration * 1000), len(clinical_prompt))
    except Exception as exc:
        failed_models.append(f"clinical={clinical_model}")
        trace_steps.append({
            "agent": "Analyse clinique KB",
            "model": clinical_model,
            "role": "Hypotheses differentielles, conduite a tenir, surveillance, sources KB",
            "status": "failed",
            "error": str(exc)[:180],
        })
        log.warning("LLM clinique indisponible pour %s (%s): %s", resident_id, clinical_model, exc)

    if not used_models and medical_model not in {fast_model, clinical_model}:
        prompt = build_prompt(profile, state, alerts_today, kb_ctx, clinical_history=clinical_history)
        try:
            raw_medical, medical_duration = await _call_ollama_limited(
                ollama_host,
                medical_model,
                prompt,
                timeout_s=95.0,
                num_predict=1300,
                temperature=0.05,
            )
            duration_ms += int(medical_duration * 1000)
            report = parse_llm_output(
                raw_medical,
                resident_name,
                profile,
                state,
                alerts_today,
                clinical_history=clinical_history,
                source_note="",
            )
            used_models.append(f"medical={medical_model}")
            trace_steps.append({
                "agent": "Rapport medical complet",
                "model": medical_model,
                "role": "Fallback complet quand les agents specialises ne suffisent pas",
                "status": "ok",
                "duration_ms": int(medical_duration * 1000),
                "fields": ["rapport complet LLMReport"],
            })
            log.info("LLM medical fallback %s - %s ms - prompt %s chars", resident_id, int(medical_duration * 1000), len(prompt))
        except Exception as exc:
            failed_models.append(f"medical={medical_model}")
            trace_steps.append({
                "agent": "Rapport medical complet",
                "model": medical_model,
                "role": "Fallback complet quand les agents specialises ne suffisent pas",
                "status": "failed",
                "error": str(exc)[:180],
            })
            log.warning("LLM medical indisponible pour %s (%s): %s", resident_id, medical_model, exc)

    if used_models:
        source = "router(" + ", ".join(used_models) + ")"
        if failed_models:
            source += " + fallback partiel"
    else:
        source = "fallback structure (routage LLM indisponible: " + ", ".join(failed_models or ["aucun modele"]) + ")"
    trace_steps.insert(0, {
        "agent": "Base deterministe",
        "model": "rules+KB+ML",
        "role": "Garantit un rapport minimal avec constantes, alertes, historique et KB meme sans LLM",
        "status": "ok",
        "fields": ["preuves", "hypotheses", "actions_prioritaires", "conduite_a_tenir_kb"],
    })
    merged = _filter_partial_sources(report.model_dump(), allowed_sources)
    merged["sources_kb"] = _filter_source_list(merged.get("sources_kb"), allowed_sources)
    merged["llm_trace"] = {
        "routing_enabled": True,
        "source": source,
        "steps": trace_steps,
        "failed_models": failed_models,
    }
    report = LLMReport(**merged)
    return report, source, duration_ms, kb_ctx


async def _generate_and_store(
    job_id: str,
    resident_id: str,
    resident_name: str,
    profile: dict,
    state: dict,
    alerts_today: list[dict],
    clinical_history: dict | None,
    ollama_host: str,
    ollama_model: str,
    redis_client,
) -> None:
    report, source, duration_ms, kb_ctx = await _generate_report_core(
        resident_id, resident_name, profile, state, alerts_today, ollama_host, ollama_model, clinical_history=clinical_history
    )
    result = _build_result(job_id, resident_id, resident_name, report, source, duration_ms, state, alerts_today, clinical_history, kb_ctx)
    redis_client.setex(f"llm:job:{job_id}", _JOB_TTL, json.dumps(result, ensure_ascii=False))
    _audit(redis_client, resident_id, source, duration_ms, report)


def _audit(redis_client, resident_id: str, source: str, duration_ms: int, report: LLMReport, job_id: str | None = None) -> None:
    audit = {
        "job_id": job_id,
        "resident_id": resident_id,
        "model": source,
        "duration_ms": duration_ms,
        "niveau_risque": report.niveau_risque,
        "preuves": len(report.preuves),
        "ts": time.time(),
    }
    redis_client.lpush("llm:audit", json.dumps(audit, ensure_ascii=False))
    redis_client.ltrim("llm:audit", 0, 199)


def start_report_job(
    redis_client,
    resident_id: str,
    resident_name: str,
    profile: dict,
    state: dict,
    alerts_today: list[dict],
    ollama_host: str,
    ollama_model: str,
    clinical_history: dict | None = None,
) -> str:
    job_id = secrets.token_hex(10)
    redis_client.setex(
        f"llm:job:{job_id}",
        _JOB_TTL,
        json.dumps({"status": "pending", "job_id": job_id, "resident_id": resident_id}),
    )
    asyncio.create_task(
        _generate_and_store(
            job_id, resident_id, resident_name, profile, state, alerts_today,
            clinical_history, ollama_host, ollama_model, redis_client,
        )
    )
    return job_id


def get_report_result(redis_client, job_id: str) -> dict:
    raw = redis_client.get(f"llm:job:{job_id}")
    if not raw:
        return {"status": "not_found", "job_id": job_id}
    return json.loads(raw)


async def run_report_sync(
    resident_id: str,
    resident_name: str,
    profile: dict,
    state: dict,
    alerts_today: list[dict],
    ollama_host: str,
    ollama_model: str,
    redis_client=None,
    clinical_history: dict | None = None,
) -> dict:
    report, source, duration_ms, kb_ctx = await _generate_report_core(
        resident_id, resident_name, profile, state, alerts_today, ollama_host, ollama_model, clinical_history=clinical_history
    )
    result = _build_result(None, resident_id, resident_name, report, source, duration_ms, state, alerts_today, clinical_history, kb_ctx)
    if redis_client:
        _audit(redis_client, resident_id, source, duration_ms, report)
    return result
