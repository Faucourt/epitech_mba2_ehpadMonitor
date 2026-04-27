"""
Chargeur de la base de connaissances clinique EHPAD Watch KB v2.
Expose des helpers indexes pour l'alerte engine, le simulateur et l'API.
"""

import json
import os
from functools import lru_cache

KB_PATH = os.path.join(os.path.dirname(__file__), "kb", "ehpad_watch_kb.json")


@lru_cache(maxsize=1)
def load_kb() -> dict:
    with open(KB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_scenarios() -> list:
    return load_kb().get("scenarios", [])


def get_scenario(scenario_id: str) -> dict | None:
    return next((s for s in get_scenarios() if s["id"] == scenario_id), None)


def get_archetypes() -> list:
    return load_kb().get("simulator_resident_archetypes_v2", [])


def get_archetype(arch_id: str) -> dict | None:
    return next((a for a in get_archetypes() if a["id"] == arch_id), None)


def get_medication_risks() -> dict:
    return load_kb().get("medication_risk_library", {}).get("high_risk_classes_for_elderly", {})


def get_alert_levels() -> dict:
    return load_kb().get("alert_levels", {})


def get_family_policy() -> dict:
    return load_kb().get("family_interface_policy", {})


# --- Helpers metier ---

def scenario_for_archetype(arch_id: str) -> list[str]:
    """Retourne les scenario_ids preferes pour un archetype."""
    arch = get_archetype(arch_id)
    if not arch:
        return []
    return arch.get("preferred_scenarios", [])


def medication_boost(drug_class: str, risk_type: str) -> float:
    """Facteur de risque additionnel selon classe medicamenteuse et type de risque."""
    risks = get_medication_risks()
    entry = risks.get(drug_class, {})
    return entry.get("engine_boosts", {}).get(risk_type, 0.0)


def infer_archetype(pathologies: list, mobility: str, risk_factor: float) -> str:
    """Deduit l'archetype KB depuis le profil resident."""
    p = set(pathologies)
    if "alzheimer" in p:
        return "ARCH_ALZ_FALL"
    if "bpco" in p:
        return "ARCH_BPCO"
    if "insuffisance_cardiaque" in p:
        return "ARCH_CARDIAC"
    if "diabete" in p and risk_factor >= 0.4:
        return "ARCH_DIABETES"
    if "parkinson" in p or len(p) >= 3:
        return "ARCH_POLYMED"
    if mobility == "tres_faible" or risk_factor >= 0.7:
        return "ARCH_NUTRITION"
    if "hypertension" in p:
        return "ARCH_STROKE_RISK"
    return "ARCH_NUTRITION"


def infer_medications(pathologies: list) -> list[str]:
    """Deduit les classes medicamenteuses probables depuis les pathologies."""
    meds = []
    p = set(pathologies)
    if "hypertension" in p:
        meds.append("antihypertensives")
    if "insuffisance_cardiaque" in p:
        meds += ["diuretics", "antihypertensives"]
    if "diabete" in p:
        meds.append("antidiabetics_insulin_sulfonylurea")
    if "parkinson" in p:
        meds += ["anticholinergics", "psychotropes"]
    if "alzheimer" in p:
        meds += ["anticholinergics", "psychotropes"]
    if "insuffisance_renale" in p:
        meds.append("diuretics")
    if len(p) >= 2:
        meds.append("benzodiazepines")
    return list(dict.fromkeys(meds))  # dedup, ordre preserve
