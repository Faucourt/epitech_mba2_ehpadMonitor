import json
from typing import Any

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
