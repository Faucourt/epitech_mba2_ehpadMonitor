"""
Chargeur de la base de connaissances clinique EHPAD Watch KB v2.
Expose des helpers indexes pour l'alerte engine, le simulateur et l'API.
"""

import json
import os
from functools import lru_cache

KB_PATH = os.path.join(os.path.dirname(__file__), "kb", "ehpad_watch_kb.json")
OFFICIAL_KB_PATH = os.path.join(os.path.dirname(__file__), "kb", "official_elderly_complications_kb.json")
EPIDOR_KB_PATH = os.path.join(os.path.dirname(__file__), "kb", "epidor_kb_mapping_v4.json")
CHARLES_TERRAIN_KB_PATH = os.path.join(os.path.dirname(__file__), "kb", "charles_terrain_kb.json")


@lru_cache(maxsize=1)
def load_kb() -> dict:
    with open(KB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_official_kb() -> dict:
    with open(OFFICIAL_KB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_epidor_mapping() -> dict:
    if not os.path.exists(EPIDOR_KB_PATH):
        return {}
    with open(EPIDOR_KB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_charles_terrain_kb() -> dict:
    if not os.path.exists(CHARLES_TERRAIN_KB_PATH):
        return {}
    with open(CHARLES_TERRAIN_KB_PATH, "r", encoding="utf-8") as f:
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


def get_official_sources() -> list:
    return load_official_kb().get("sources", [])


def get_official_profiles_for_pathologies(pathologies: list[str]) -> list[dict]:
    patho_set = {str(p).lower() for p in pathologies}
    profiles = []
    for item in load_official_kb().get("profiles", []):
        matches = {str(p).lower() for p in item.get("match_pathologies", [])}
        if matches.intersection(patho_set):
            profiles.append(item)
    return profiles


def get_official_cross_complications() -> list:
    return load_official_kb().get("cross_complications", [])


def get_first_aid_actions() -> list:
    return load_official_kb().get("first_aid_actions", [])


def get_charles_terrains() -> list:
    return load_charles_terrain_kb().get("terrains", [])


def get_charles_terrains_for_profile(profile: dict) -> list[dict]:
    pathologies = {str(p).lower() for p in profile.get("pathologies", []) or []}
    meds = {str(m).lower() for m in profile.get("likely_medications", []) or []}
    scenarios = {str(s).lower() for s in profile.get("preferred_scenarios", []) or []}
    age = profile.get("age")
    mobility = str(profile.get("mobility", "")).lower()
    risk_factor = float(profile.get("risk_factor", 0) or 0)
    matched: list[dict] = []
    for terrain in get_charles_terrains():
        rule = terrain.get("match", {}) or {}
        ok = False
        if rule.get("pathologies_any"):
            ok = ok or bool(pathologies.intersection({str(x).lower() for x in rule["pathologies_any"]}))
        if rule.get("medications_any"):
            needles = {str(x).lower() for x in rule["medications_any"]}
            ok = ok or any(any(needle in med for needle in needles) for med in meds)
        if rule.get("scenario_any"):
            ok = ok or bool(scenarios.intersection({str(x).lower() for x in rule["scenario_any"]}))
        if rule.get("age_gte") is not None and age is not None:
            ok = ok or float(age) >= float(rule["age_gte"])
        if rule.get("mobility_in"):
            ok = ok or mobility in {str(x).lower() for x in rule["mobility_in"]}
        if rule.get("risk_factor_gte") is not None:
            ok = ok or risk_factor >= float(rule["risk_factor_gte"])
        if ok:
            matched.append(terrain)
    return matched


def get_epidor_ml_rule_weights() -> dict:
    return load_epidor_mapping().get("ml_rule_weights", {})


def get_epidor_dashboard_config() -> dict:
    return load_epidor_mapping().get("dashboard_mini_dpi", {})


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
