"""Mapping between simulator scenarios and clinical KB scenarios.

The simulator uses operational scenario names. The LLM/RAG layer uses SCNxxx
clinical scenario identifiers from ehpad_watch_kb.json. This mapping bridges
both vocabularies so an active simulator event can pull the right clinical
conduct guidance.
"""

SIMULATOR_TO_KB_SCENARIOS = {
    "hypoxie": ["SCN003_HYPOXEMIA_BPCO_OR_PNEUMONIA", "SCN013_HEART_FAILURE_DECOMPENSATION", "SCN011_ACUTE_CONFUSION_DELIRIUM"],
    "tachycardie": ["SCN004_UTI_SEPSIS_EARLY_DETERIORATION", "SCN015_CHEST_PAIN_CARDIAC_MALAISE", "SCN013_HEART_FAILURE_DECOMPENSATION"],
    "chute": ["SCN001_FALL_NIGHT_ALZHEIMER_ANTICOAGULANT", "SCN002_ORTHOSTATIC_HYPOTENSION_TOILETS", "SCN009_IATROGENIC_FALL_CONFUSION_AFTER_MED_CHANGE"],
    "hypotension": ["SCN002_ORTHOSTATIC_HYPOTENSION_TOILETS", "SCN005_DEHYDRATION_HEATWAVE_DIURETICS", "SCN015_CHEST_PAIN_CARDIAC_MALAISE"],
    "fievre": ["SCN004_UTI_SEPSIS_EARLY_DETERIORATION", "SCN011_ACUTE_CONFUSION_DELIRIUM", "SCN003_HYPOXEMIA_BPCO_OR_PNEUMONIA"],
    "chute_couloir": ["SCN001_FALL_NIGHT_ALZHEIMER_ANTICOAGULANT", "SCN002_ORTHOSTATIC_HYPOTENSION_TOILETS", "SCN009_IATROGENIC_FALL_CONFUSION_AFTER_MED_CHANGE"],
    "chute_chambre": ["SCN001_FALL_NIGHT_ALZHEIMER_ANTICOAGULANT", "SCN002_ORTHOSTATIC_HYPOTENSION_TOILETS", "SCN009_IATROGENIC_FALL_CONFUSION_AFTER_MED_CHANGE"],
    "malaise_salle_manger": ["SCN006_HYPOGLYCEMIA_DIABETES", "SCN002_ORTHOSTATIC_HYPOTENSION_TOILETS", "SCN015_CHEST_PAIN_CARDIAC_MALAISE"],
    "errance_nuit": ["SCN007_WANDERING_ELOPEMENT_ALZHEIMER", "SCN011_ACUTE_CONFUSION_DELIRIUM", "SCN010_PAIN_URINARY_RETENTION_FECALOMA_AGITATION"],
    "sortie_patio": ["SCN007_WANDERING_ELOPEMENT_ALZHEIMER", "SCN008_ROUTINE_BREAKDOWN_APATHY_ISOLATION"],
    "immobilite_salle_repos": ["SCN008_ROUTINE_BREAKDOWN_APATHY_ISOLATION", "SCN014_DENUTRITION_FRAILTY_DECLINE", "SCN011_ACUTE_CONFUSION_DELIRIUM"],
    "aller_toilettes_nuit": ["SCN002_ORTHOSTATIC_HYPOTENSION_TOILETS", "SCN001_FALL_NIGHT_ALZHEIMER_ANTICOAGULANT", "SCN010_PAIN_URINARY_RETENTION_FECALOMA_AGITATION"],
    "desorientation_ascenseur": ["SCN007_WANDERING_ELOPEMENT_ALZHEIMER", "SCN011_ACUTE_CONFUSION_DELIRIUM", "SCN010_PAIN_URINARY_RETENTION_FECALOMA_AGITATION"],
    "agitation_couloir": ["SCN010_PAIN_URINARY_RETENTION_FECALOMA_AGITATION", "SCN011_ACUTE_CONFUSION_DELIRIUM", "SCN009_IATROGENIC_FALL_CONFUSION_AFTER_MED_CHANGE"],
    "isolement_chambre": ["SCN008_ROUTINE_BREAKDOWN_APATHY_ISOLATION", "SCN014_DENUTRITION_FRAILTY_DECLINE", "SCN011_ACUTE_CONFUSION_DELIRIUM"],
    "retour_kine_fatigue": ["SCN003_HYPOXEMIA_BPCO_OR_PNEUMONIA", "SCN013_HEART_FAILURE_DECOMPENSATION", "SCN005_DEHYDRATION_HEATWAVE_DIURETICS"],
    "promenade_jardin": ["SCN005_DEHYDRATION_HEATWAVE_DIURETICS", "SCN014_DENUTRITION_FRAILTY_DECLINE"],
    "sortie_jardin_non_accompagnee": ["SCN007_WANDERING_ELOPEMENT_ALZHEIMER", "SCN001_FALL_NIGHT_ALZHEIMER_ANTICOAGULANT", "SCN005_DEHYDRATION_HEATWAVE_DIURETICS"],
    "chute_jardin": ["SCN001_FALL_NIGHT_ALZHEIMER_ANTICOAGULANT", "SCN005_DEHYDRATION_HEATWAVE_DIURETICS", "SCN002_ORTHOSTATIC_HYPOTENSION_TOILETS"],
    "fugue_hors_ehpad": ["SCN007_WANDERING_ELOPEMENT_ALZHEIMER", "SCN011_ACUTE_CONFUSION_DELIRIUM"],
    "chute_trajet_repas": ["SCN001_FALL_NIGHT_ALZHEIMER_ANTICOAGULANT", "SCN002_ORTHOSTATIC_HYPOTENSION_TOILETS", "SCN006_HYPOGLYCEMIA_DIABETES"],
    "desorientation_avant_repas": ["SCN011_ACUTE_CONFUSION_DELIRIUM", "SCN006_HYPOGLYCEMIA_DIABETES", "SCN007_WANDERING_ELOPEMENT_ALZHEIMER"],
    "malaise_retour_repas": ["SCN002_ORTHOSTATIC_HYPOTENSION_TOILETS", "SCN006_HYPOGLYCEMIA_DIABETES", "SCN013_HEART_FAILURE_DECOMPENSATION"],
    "malaise_repas": ["SCN006_HYPOGLYCEMIA_DIABETES", "SCN002_ORTHOSTATIC_HYPOTENSION_TOILETS", "SCN015_CHEST_PAIN_CARDIAC_MALAISE"],
    "chute_salle_bain": ["SCN002_ORTHOSTATIC_HYPOTENSION_TOILETS", "SCN001_FALL_NIGHT_ALZHEIMER_ANTICOAGULANT", "SCN010_PAIN_URINARY_RETENTION_FECALOMA_AGITATION"],
    "toilette_matinale_fatigue": ["SCN002_ORTHOSTATIC_HYPOTENSION_TOILETS", "SCN005_DEHYDRATION_HEATWAVE_DIURETICS", "SCN013_HEART_FAILURE_DECOMPENSATION"],
    "desorientation_patio": ["SCN007_WANDERING_ELOPEMENT_ALZHEIMER", "SCN011_ACUTE_CONFUSION_DELIRIUM", "SCN005_DEHYDRATION_HEATWAVE_DIURETICS"],
    "regroupement_patio_fatigue": ["SCN003_HYPOXEMIA_BPCO_OR_PNEUMONIA", "SCN013_HEART_FAILURE_DECOMPENSATION", "SCN005_DEHYDRATION_HEATWAVE_DIURETICS"],
    "retour_jardin_fatigue": ["SCN003_HYPOXEMIA_BPCO_OR_PNEUMONIA", "SCN013_HEART_FAILURE_DECOMPENSATION", "SCN005_DEHYDRATION_HEATWAVE_DIURETICS"],
    "risque_nuit": ["SCN002_ORTHOSTATIC_HYPOTENSION_TOILETS", "SCN001_FALL_NIGHT_ALZHEIMER_ANTICOAGULANT", "SCN007_WANDERING_ELOPEMENT_ALZHEIMER"],
    "jardin": ["SCN005_DEHYDRATION_HEATWAVE_DIURETICS", "SCN014_DENUTRITION_FRAILTY_DECLINE"],
}


def kb_ids_for_simulator_scenario(scenario: str | None) -> list[str]:
    if not scenario:
        return []
    return SIMULATOR_TO_KB_SCENARIOS.get(str(scenario), [])


def scenario_kb_links_for_state(state: dict) -> list[dict]:
    links: list[dict] = []
    seen: set[tuple[str, str]] = set()
    weighted_sources = [
        ("scenario_active", state.get("scenario") or state.get("scenario_active"), "active_vital"),
        ("movement_scenario", state.get("movement_scenario"), "active_movement"),
        ("assigned_movement_scenario", state.get("assigned_movement_scenario"), "planned_profile"),
    ]
    for field, scenario, status in weighted_sources:
        for kb_id in kb_ids_for_simulator_scenario(scenario):
            key = (str(scenario), kb_id)
            if key in seen:
                continue
            seen.add(key)
            links.append({"field": field, "scenario": scenario, "kb_id": kb_id, "status": status})
    for scenario in state.get("assigned_scenarios") or []:
        for kb_id in kb_ids_for_simulator_scenario(scenario)[:2]:
            key = (str(scenario), kb_id)
            if key in seen:
                continue
            seen.add(key)
            links.append({"field": "assigned_scenarios", "scenario": scenario, "kb_id": kb_id, "status": "profile_possible"})
    return links
