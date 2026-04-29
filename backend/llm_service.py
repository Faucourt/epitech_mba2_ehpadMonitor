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
    get_medication_risks,
    get_official_cross_complications,
    get_official_profiles_for_pathologies,
    get_scenario,
    get_scenarios,
    scenario_for_archetype,
)

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
    if temp is not None and float(temp) >= 38:
        differential.append("infection respiratoire, urinaire ou sepsis debutant chez sujet age")
        conduct.append("rechercher foyer infectieux: toux, douleur urinaire, plaie, frissons, confusion")
    if sys is not None and float(sys) >= 180:
        differential.append("poussee hypertensive avec risque neuro-cardio")
        escalade.append("deficit FAST, douleur thoracique, dyspnee severe ou trouble conscience")
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
    if movement.get("is_fall_detected") or movement.get("ambient_fall_confirmed") or state.get("fall_detected"):
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
    if movement.get("fall_detected") or state.get("fall_detected"):
        direct_ids.append("SCN001_FALL_NIGHT_ALZHEIMER_ANTICOAGULANT")
    if "insuffisance_cardiaque" in pathologies:
        direct_ids.append("SCN013_HEART_FAILURE_DECOMPENSATION")
    if ml_risk >= 0.7 or alert_level >= 3:
        direct_ids.append("SCN011_ACUTE_CONFUSION_DELIRIUM")

    for sid in direct_ids:
        scenario = get_scenario(sid)
        if scenario:
            selected[scenario["id"]] = scenario

    for sid in scenario_for_archetype(archetype_id)[:3]:
        scenario = get_scenario(sid)
        if scenario and scenario["id"] not in selected:
            selected[scenario["id"]] = scenario

    if len(selected) < 5 and (ml_risk >= 0.5 or alert_level >= 2):
        for scenario in get_scenarios():
            if scenario["id"] in selected:
                continue
            tags = scenario.get("resident_profile_match", {}).get("any", [])
            if any(_patho_matches_tag(pathologies, tag) for tag in tags):
                selected[scenario["id"]] = scenario
            if len(selected) >= 5:
                break

    return list(selected.values())[:5]


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
    if movement.get("is_fall_detected") or movement.get("ambient_fall_confirmed") or state.get("fall_detected"):
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
        if movement.get("is_fall_detected") or movement.get("ambient_fall_confirmed") or (state or {}).get("fall_detected"):
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


def _alert_label(alert: dict) -> str:
    return alert.get("reason") or alert.get("message") or alert.get("title") or "alerte non qualifiee"


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
        evidence.append({"signal": "Pression arterielle critique", "valeur": f"{sys:.0f}/{dia or 0:.0f} mmHg", "interpretation": "surveiller hypotension, poussee hypertensive ou deshydratation", "gravite": "haute"})

    if temp is not None and temp >= 38:
        evidence.append({"signal": "Temperature elevee", "valeur": _fmt(temp, " C"), "interpretation": "signal infectieux possible", "gravite": "moyenne"})
    elif temp is not None and temp < 37.8:
        reassuring.append(f"Temperature non febrile ({temp:.1f} C)")

    if rr is not None and (rr > 24 or rr < 10):
        evidence.append({"signal": "Frequence respiratoire atypique", "valeur": _fmt(rr, "/min"), "interpretation": "surveiller detresse respiratoire ou fatigue", "gravite": "haute"})

    no_move_min = movement.get("no_movement_minutes") or state.get("no_movement_minutes")
    if no_move_min and float(no_move_min) >= 60:
        evidence.append({"signal": "Inactivite prolongee", "valeur": f"{float(no_move_min):.0f} min", "interpretation": "a verifier selon routine et contexte de sommeil", "gravite": "moyenne"})

    if state.get("fall_detected") or movement.get("fall_detected"):
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
            "arguments": ["PA systolique basse", "risque de malaise/chute"],
            "a_verifier": ["PA controlee au repos", "pouls", "apports hydriques", "diuretiques ou traitement recent", "vertiges au lever", "temperature/chaleur"],
            "conduite_soignant": ["mettre au repos", "eviter lever seul", "recontroler PA/FC", "rechercher malaise, chute ou confusion", "alerter si hypotension persistante"],
            "criteres_escalade": ["PAS < 90 persistante", "syncope", "confusion", "chute", "tachycardie associee", "signes de deshydratation severe"],
            "sources_kb": ["SANTE_GOUV_CHALEUR_2026", "HAS_CHUTES_REPETEES_2009", "SCN005_DEHYDRATION_HEATWAVE_DIURETICS"],
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
    if state.get("fall_detected") or movement.get("fall_detected") or movement.get("is_fall_detected"):
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
        action_now = "Controle immediat au lit ou sur zone: conscience, respiration, SpO2 au doigt, FR sur 1 minute, FC, PA, temperature, douleur, dyspnee et chute."
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
PA: {v.get('blood_pressure_sys', 0):.0f}/{v.get('blood_pressure_dia', 0):.0f} mmHg
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
        report = LLMReport(**data)
        fallback = _structured_fallback_report(resident_name, profile, state, alerts_today, clinical_history=clinical_history, source_note="analyse structuree completee automatiquement")
        merged = fallback.model_dump()
        merged.update({k: v for k, v in report.model_dump().items() if v not in (None, [], {})})
        if report.sources_kb and fallback.sources_kb:
            merged["sources_kb"] = list(dict.fromkeys(report.sources_kb + fallback.sources_kb))
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
    context = _compact_prompt_context(profile, state, alerts_today, clinical_history)
    return f"""
Tu es un assistant de transmission EHPAD. Tache courte: reformuler un resume soignant et un message famille non alarmiste.

Contexte compact:
{context}

Reponds uniquement en JSON valide:
{{
  "resume": "2 phrases maximum, utile pour transmission soignante",
  "synthese_clinique": "1 phrase clinique concise",
  "points_vigilance": ["3 points maximum"],
  "actions_soignants": ["3 actions concretes maximum"],
  "message_famille": "1 phrase simple, sans diagnostic certain"
}}

Contraintes:
- ne pose pas de diagnostic certain;
- le resume doit citer le risque ML ou une alerte/constante precise;
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
    kb_slice = kb_context[:5200]
    return f"""
Tu es un copilote clinique pour EHPAD. Tu utilises uniquement les donnees fournies et la KB officielle.
Objectif: hypotheses differentielles, conduite a tenir soignant, surveillance et sources.
Important: relie explicitement chaque conduite a tenir aux antecedents/pathologies du resident quand ils sont fournis.

Contexte patient:
{compact}

KB officielle / scenarios pertinents:
{kb_slice}

Reponds uniquement en JSON valide:
{{
  "niveau_risque": "faible|modere|eleve",
  "preuves": [{{"signal": "...", "valeur": "...", "interpretation": "...", "gravite": "basse|moyenne|haute"}}],
  "hypotheses": [{{"hypothese": "...", "probabilite": "faible|moderee|elevee|a confirmer", "arguments": ["..."], "a_verifier": ["..."], "conduite_soignant": ["..."], "criteres_escalade": ["..."], "sources_kb": ["..."]}}],
  "actions_prioritaires": [{{"delai": "maintenant|15 min|30-60 min|si aggravation", "action": "...", "responsable": "..."}}],
  "plan_surveillance": [{{"parametre": "...", "frequence": "...", "seuil": "..."}}],
  "complications_possibles": [{{"scenario_id": "...", "nom": "...", "explication": "...", "signes_a_rechercher": ["..."]}}],
  "donnees_a_verifier": ["..."],
  "conduite_a_tenir_kb": [{{"scenario_id": "...", "delai": "...", "action": "...", "niveau": "..."}}],
  "incertitudes": ["..."],
  "sources_kb": ["..."]
}}

Contraintes obligatoires:
- maximum 3 preuves, 3 hypotheses, 4 actions, 3 surveillances et 5 sources;
- au moins 3 actions concretes avec delai et responsable;
- si SpO2 <= 90%, prioriser hypoxemie aigue, tolerance respiratoire, controle SpO2/FR et criteres d'appel urgent;
- relier la CAT au terrain: Parkinson/fausse route/chute, hypertension/neuro-cardio, traitements a risque/iatrogenie;
- chaque hypothese doit contenir a_verifier, conduite_soignant et criteres_escalade;
- reprendre les conduites PSC/AFPS pertinentes si elles sont presentes dans la KB;
- citer les ids de sources/scenarios utilises dans sources_kb;
- ne jamais inventer de source absente du contexte.
""".strip()


def _merge_report_from_partial(base: LLMReport, partial: dict[str, Any]) -> LLMReport:
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
        elif not isinstance(merged.get(key), (list, dict)):
            merged[key] = value
    if base.sources_kb and isinstance(partial.get("sources_kb"), list):
        merged["sources_kb"] = list(dict.fromkeys([*partial["sources_kb"], *base.sources_kb]))
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

    fast_model = LLM_FAST_MODEL or ollama_model
    clinical_model = LLM_CLINICAL_MODEL or ollama_model
    medical_model = LLM_MEDICAL_MODEL or ollama_model

    fast_prompt = _build_fast_summary_prompt(resident_name, profile, state, alerts_today, clinical_history)
    try:
        raw_fast, fast_duration = await _call_ollama_limited(
            ollama_host,
            fast_model,
            fast_prompt,
            timeout_s=35.0,
            num_predict=260,
            temperature=0.1,
        )
        duration_ms += int(fast_duration * 1000)
        fast_data = _json_from_llm_text(raw_fast)
        report = _merge_report_from_partial(report, fast_data)
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
        report = _merge_report_from_partial(report, clinical_data)
        used_models.append(f"clinical={clinical_model}")
        trace_steps.append({
            "agent": "Analyse clinique KB",
            "model": clinical_model,
            "role": "Hypotheses differentielles, conduite a tenir, surveillance, sources KB",
            "status": "ok",
            "duration_ms": int(clinical_duration * 1000),
            "fields": sorted([k for k in clinical_data.keys() if k in {"niveau_risque", "preuves", "hypotheses", "actions_prioritaires", "plan_surveillance", "complications_possibles", "donnees_a_verifier", "conduite_a_tenir_kb", "sources_kb"}]),
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
    merged = report.model_dump()
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
