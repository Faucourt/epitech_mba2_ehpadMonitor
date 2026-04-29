from typing import Any

from kb_loader import get_charles_terrains_for_profile, get_medication_risks

from app.services.llm.models import LLMReport
from app.services.llm.kb_context import (
    _clinical_focus_from_profile,
    _fall_detected,
    _kb_guidance,
    _profile_antecedent_kb_links,
    build_kb_context,
)


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
