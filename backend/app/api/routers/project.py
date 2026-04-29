from fastapi import APIRouter

from app.domain.readiness import DAY_TEMPLATE, PROJECT_READINESS, SCENARIO_TYPES
from app.domain.residents import RESIDENT_ARCHETYPES, resident_archetype
from resident_profiles import RESIDENTS_MAP

router = APIRouter(tags=["Project"])


@router.get("/api/project/readiness")
def get_project_readiness():
    """Matrice de validation pour le rendu pro du projet EHPAD."""
    residents = []
    for profile in RESIDENTS_MAP.values():
        archetype = resident_archetype(profile)
        residents.append({
            "resident_id": profile["id"],
            "name": profile["name"],
            "room": profile["room"],
            "archetype": archetype,
            **RESIDENT_ARCHETYPES[archetype],
        })
    counts = {}
    for item in residents:
        counts[item["archetype"]] = counts.get(item["archetype"], 0) + 1
    return {
        "project": "EHPAD Monitor",
        "target": "20-50 residents, surveillance continue, prediction malaise, alertes 5 niveaux",
        "readiness": PROJECT_READINESS,
        "resident_profile_counts": counts,
        "resident_profiles": residents,
        "validation_order": [
            "1. profils et scenarios de vie",
            "2. alertes et localisation",
            "3. prediction ML/A2A 30-60 min",
            "4. plan 2D/3D capteurs",
            "5. mini DPI et transmissions",
            "6. scalabilite MQTT/Redis/Influx/WebSocket",
        ],
    }


@router.get("/api/scenarios/life-plan")
def get_life_plan():
    return {
        "day_template": DAY_TEMPLATE,
        "scenario_types": SCENARIO_TYPES,
        "profile_logic": RESIDENT_ARCHETYPES,
    }
