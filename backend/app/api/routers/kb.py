from fastapi import APIRouter, HTTPException

from app.core.runtime import runtime as rt

router = APIRouter(tags=["Knowledge Base"])


@router.get("/api/kb/scenarios")
def kb_scenarios():
    """Liste tous les scenarios cliniques de la KB."""
    import kb_loader

    scenarios = kb_loader.get_scenarios()
    return {
        "count": len(scenarios),
        "scenarios": [
            {
                "id": s["id"],
                "name": s["name"],
                "category": s["category"],
                "clinical_rationale": s.get("clinical_rationale", ""),
                "family_visibility": s.get("family_visibility", ""),
            }
            for s in scenarios
        ],
    }


@router.get("/api/kb/scenarios/{scenario_id}")
def kb_scenario_detail(scenario_id: str):
    """Detail complet d'un scenario KB."""
    import kb_loader

    scenario = kb_loader.get_scenario(scenario_id)
    if not scenario:
        raise HTTPException(404, "Scenario inconnu")
    return scenario


@router.get("/api/kb/archetypes")
def kb_archetypes():
    """Liste les archetypes residents de la KB avec baseline et scenarios associes."""
    import kb_loader

    archetypes = kb_loader.get_archetypes()
    return {"count": len(archetypes), "archetypes": archetypes}


@router.get("/api/kb/residents")
def kb_residents_enriched():
    """Residents enrichis : archetype KB, medicaments probables, scenarios preferes."""
    result = [
        {
            "id": resident["id"],
            "name": resident["name"],
            "room": resident["room"],
            "pathologies": resident["pathologies"],
            "archetype_id": resident.get("archetype_id", ""),
            "likely_medications": resident.get("likely_medications", []),
            "preferred_scenarios": resident.get("preferred_scenarios", []),
            "risk_factor": resident["risk_factor"],
        }
        for resident in rt.residents_list
    ]
    return {"count": len(result), "residents": result}


@router.get("/api/kb/official")
def kb_official_references():
    """References officielles par pathologie et complications transversales."""
    import kb_loader

    kb = kb_loader.load_official_kb()
    return {
        "metadata": kb.get("metadata", {}),
        "sources": kb.get("sources", []),
        "profiles": kb.get("profiles", []),
        "cross_complications": kb.get("cross_complications", []),
        "first_aid_actions": kb.get("first_aid_actions", []),
        "llm_rules": kb.get("llm_rules", []),
    }


@router.get("/api/kb/epidor")
def kb_epidor_mapping():
    """Mapping EPIDOR V4: residents, capteurs, poids rules/ML et config Mini DPI."""
    import kb_loader

    mapping = kb_loader.load_epidor_mapping()
    return {
        "metadata": mapping.get("metadata", {}),
        "resident_problem_count": len(mapping.get("resident_problem_mapping", [])),
        "sensor_field_count": len(mapping.get("sensor_field_mapping", [])),
        "ml_rule_weights": mapping.get("ml_rule_weights", {}),
        "dashboard_mini_dpi": mapping.get("dashboard_mini_dpi", {}),
        "validation_tests_count": len(mapping.get("validation_tests", [])),
    }
