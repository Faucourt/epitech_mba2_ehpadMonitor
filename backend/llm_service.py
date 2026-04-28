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
import secrets
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from kb_loader import (
    get_archetype,
    get_medication_risks,
    get_scenario,
    get_scenarios,
    scenario_for_archetype,
)

log = logging.getLogger(__name__)

_JOB_TTL = 3600


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
    complications: list[dict[str, Any]] = []
    conduct: list[dict[str, Any]] = []
    checks: list[str] = []
    sources: list[str] = []

    for scenario in scenarios:
        sid = scenario.get("id")
        sources.append(sid)
        signals = _scenario_signal_names(scenario)[:4]
        complications.append({
            "scenario_id": sid,
            "nom": scenario.get("name", sid),
            "explication": scenario.get("clinical_rationale", ""),
            "signes_a_rechercher": signals,
        })
        conduct.extend(_scenario_actions_as_guidance(scenario))
        for signal in signals:
            checks.append(f"Rechercher/valider: {signal}")

    checks.extend([
        "Verifier qualite et fraicheur des capteurs avant conclusion.",
        "Comparer aux constantes habituelles et au comportement de base du resident.",
        "Tracer l'observation soignante et l'acquittement si alerte.",
    ])
    return {
        "sources_kb": list(dict.fromkeys([s for s in sources if s])),
        "complications": complications[:5],
        "conduite": conduct[:10],
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
                signals = ", ".join(e.get("signal", "?") for e in early)
                lines.append(f"    Signaux precoces: {signals}")
            actions = scenario.get("actions", {})
            if isinstance(actions, dict) and actions:
                action_bits: list[str] = []
                for level, items in list(actions.items())[:3]:
                    if isinstance(items, list):
                        action_bits.append(f"{level}: {', '.join(_human_action(str(i)) for i in items[:3])}")
                if action_bits:
                    lines.append(f"    Conduite a tenir: {' | '.join(action_bits)}")

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
        hypotheses.append({"hypothese": "episode respiratoire ou hypoxemie", "probabilite": "moderee a elevee", "arguments": ["SpO2 basse", "profil BPCO" if "bpco" in pathologies else "constante anormale"]})
    if sys is not None and sys < 95:
        hypotheses.append({"hypothese": "hypotension ou deshydratation", "probabilite": "moderee", "arguments": ["PA systolique basse", "risque de malaise/chute"]})
    if temp is not None and temp >= 38:
        hypotheses.append({"hypothese": "syndrome infectieux debutant", "probabilite": "moderee", "arguments": ["temperature elevee", "surveillance constantes rapprochee"]})
    if routine_score >= 0.4 or "alzheimer" in pathologies:
        hypotheses.append({"hypothese": "trouble comportemental ou confusion debutante", "probabilite": "a confirmer", "arguments": ["rupture de routine", "profil cognitif" if "alzheimer" in pathologies else "activite inhabituelle"]})
    if not hypotheses:
        hypotheses.append({"hypothese": "etat stable avec surveillance adaptee au profil", "probabilite": "probable", "arguments": ["pas de signal critique majeur", "continuer le suivi de tendance"]})

    action_now = "Passer voir le resident, confirmer la localisation et refaire les constantes."
    if niveau == "eleve":
        action_now = "Controle immediat au lit ou sur zone, constantes completes, recherche douleur/dyspnee/chute."
    actions = [
        {"delai": "maintenant", "action": action_now, "responsable": "soignant assigne"},
        {"delai": "15 min", "action": "Recontrole FC, SpO2, PA, temperature et verification coherence capteurs.", "responsable": "soignant assigne"},
        {"delai": "30-60 min", "action": "Comparer au comportement habituel et reevaluer le score predictif.", "responsable": "IDE / referent"},
    ]
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

    vigilance = [e["interpretation"] for e in evidence[:4]] or ["Surveillance de routine adaptee au profil."]
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
        donnees_a_verifier=kb["donnees_a_verifier"],
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
  "hypotheses": [{{"hypothese": "...", "probabilite": "faible|moderee|elevee|a confirmer", "arguments": ["..."]}}],
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


async def _call_ollama(ollama_host: str, model: str, prompt: str) -> tuple[str, float]:
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            f"{ollama_host}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
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
