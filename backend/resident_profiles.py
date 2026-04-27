"""
Map des profils résidents pour le backend.
Identique aux profils du simulateur.
family_code : code PIN unique remis a la famille de chaque resident.
archetype_id + likely_medications + preferred_scenarios : deduits automatiquement
depuis la KB clinique (ehpad_watch_kb.json) via kb_loader.
"""

RESIDENTS_LIST = [
    {"id": "R001", "name": "Marguerite Dupont",   "age": 87, "room": "101", "pathologies": ["hypertension", "diabete"],                              "mobility": "faible",     "risk_factor": 0.30, "caregiver": "soignant_A", "family_code": "DUPONT101"},
    {"id": "R002", "name": "Henri Moreau",         "age": 79, "room": "102", "pathologies": ["insuffisance_cardiaque"],                               "mobility": "moyenne",    "risk_factor": 0.50, "caregiver": "soignant_A", "family_code": "MOREAU102"},
    {"id": "R003", "name": "Simone Bernard",       "age": 92, "room": "103", "pathologies": ["alzheimer", "hypertension"],                            "mobility": "tres_faible","risk_factor": 0.60, "caregiver": "soignant_A", "family_code": "BERNARD103"},
    {"id": "R004", "name": "Pierre Leroy",         "age": 75, "room": "104", "pathologies": ["diabete"],                                              "mobility": "bonne",      "risk_factor": 0.10, "caregiver": "soignant_B", "family_code": "LEROY104"},
    {"id": "R005", "name": "Yvette Martin",        "age": 84, "room": "105", "pathologies": ["parkinson", "hypertension"],                            "mobility": "faible",     "risk_factor": 0.40, "caregiver": "soignant_B", "family_code": "MARTIN105"},
    {"id": "R006", "name": "Andre Petit",          "age": 81, "room": "106", "pathologies": ["bpco"],                                                 "mobility": "faible",     "risk_factor": 0.55, "caregiver": "soignant_B", "family_code": "PETIT106"},
    {"id": "R007", "name": "Louise Durand",        "age": 88, "room": "107", "pathologies": ["insuffisance_renale", "diabete"],                       "mobility": "moyenne",    "risk_factor": 0.35, "caregiver": "soignant_C", "family_code": "DURAND107"},
    {"id": "R008", "name": "Marcel Thomas",        "age": 77, "room": "108", "pathologies": [],                                                       "mobility": "bonne",      "risk_factor": 0.05, "caregiver": "soignant_C", "family_code": "THOMAS108"},
    {"id": "R009", "name": "Jeanne Robert",        "age": 90, "room": "201", "pathologies": ["alzheimer", "insuffisance_cardiaque"],                  "mobility": "tres_faible","risk_factor": 0.70, "caregiver": "soignant_C", "family_code": "ROBERT201"},
    {"id": "R010", "name": "Gaston Richard",       "age": 83, "room": "202", "pathologies": ["hypertension"],                                         "mobility": "moyenne",    "risk_factor": 0.25, "caregiver": "soignant_A", "family_code": "RICHARD202"},
    {"id": "R011", "name": "Odette Simon",         "age": 86, "room": "203", "pathologies": ["parkinson", "diabete"],                                 "mobility": "faible",     "risk_factor": 0.45, "caregiver": "soignant_A", "family_code": "SIMON203"},
    {"id": "R012", "name": "Fernand Michel",       "age": 80, "room": "204", "pathologies": ["insuffisance_cardiaque", "bpco"],                       "mobility": "faible",     "risk_factor": 0.65, "caregiver": "soignant_B", "family_code": "MICHEL204"},
    {"id": "R013", "name": "Helene Lefebvre",      "age": 76, "room": "208", "pathologies": ["diabete"],                                              "mobility": "bonne",      "risk_factor": 0.15, "caregiver": "soignant_B", "family_code": "LEFEBVRE208"},
    {"id": "R014", "name": "Roger Leblanc",        "age": 91, "room": "209", "pathologies": ["alzheimer"],                                            "mobility": "tres_faible","risk_factor": 0.50, "caregiver": "soignant_C", "family_code": "LEBLANC209"},
    {"id": "R015", "name": "Germaine Fontaine",    "age": 85, "room": "210", "pathologies": ["hypertension", "insuffisance_renale"],                  "mobility": "moyenne",    "risk_factor": 0.40, "caregiver": "soignant_C", "family_code": "FONTAINE210"},
    {"id": "R016", "name": "Edouard Rousseau",     "age": 78, "room": "211", "pathologies": ["bpco", "hypertension"],                                 "mobility": "faible",     "risk_factor": 0.50, "caregiver": "soignant_A", "family_code": "ROUSSEAU211"},
    {"id": "R017", "name": "Blanche Morel",        "age": 89, "room": "212", "pathologies": ["insuffisance_cardiaque"],                               "mobility": "tres_faible","risk_factor": 0.70, "caregiver": "soignant_A", "family_code": "MOREL212"},
    {"id": "R018", "name": "Lucien Garnier",       "age": 74, "room": "213", "pathologies": [],                                                       "mobility": "bonne",      "risk_factor": 0.05, "caregiver": "soignant_B", "family_code": "GARNIER213"},
    {"id": "R019", "name": "Paulette Chevalier",   "age": 93, "room": "214", "pathologies": ["alzheimer", "parkinson", "hypertension"],               "mobility": "tres_faible","risk_factor": 0.75, "caregiver": "soignant_B", "family_code": "CHEVALIER214"},
    {"id": "R020", "name": "Auguste Mercier",      "age": 82, "room": "215", "pathologies": ["diabete", "insuffisance_cardiaque"],                    "mobility": "faible",     "risk_factor": 0.55, "caregiver": "soignant_C", "family_code": "MERCIER215"},
    {"id": "R021", "name": "Therese Blanc",        "age": 78, "room": "216", "pathologies": ["hypertension"],                                         "mobility": "moyenne",    "risk_factor": 0.20, "caregiver": "soignant_C", "family_code": "BLANC216"},
    {"id": "R022", "name": "Gaetan Caron",         "age": 86, "room": "217", "pathologies": ["bpco", "insuffisance_renale"],                          "mobility": "faible",     "risk_factor": 0.60, "caregiver": "soignant_A", "family_code": "CARON217"},
    {"id": "R023", "name": "Renee Fournier",       "age": 81, "room": "218", "pathologies": ["diabete", "hypertension"],                              "mobility": "moyenne",    "risk_factor": 0.35, "caregiver": "soignant_A", "family_code": "FOURNIER218"},
    {"id": "R024", "name": "Leon Girard",          "age": 95, "room": "219", "pathologies": ["alzheimer", "insuffisance_cardiaque", "hypertension"],  "mobility": "tres_faible","risk_factor": 0.85, "caregiver": "soignant_B", "family_code": "GIRARD219"},
    {"id": "R025", "name": "Clothilde Perrin",     "age": 73, "room": "220", "pathologies": [],                                                       "mobility": "bonne",      "risk_factor": 0.02, "caregiver": "soignant_B", "family_code": "PERRIN220"},
]

# Enrichissement KB : archetype, medications, scenarios preferes
def _enrich_with_kb(residents: list) -> list:
    try:
        from kb_loader import infer_archetype, infer_medications, scenario_for_archetype
        for r in residents:
            arch = infer_archetype(r["pathologies"], r["mobility"], r["risk_factor"])
            r["archetype_id"]        = arch
            r["likely_medications"]  = infer_medications(r["pathologies"])
            r["preferred_scenarios"] = scenario_for_archetype(arch)
    except Exception:
        pass  # KB absente ou erreur : profils fonctionnent sans
    return residents

RESIDENTS_LIST = _enrich_with_kb(RESIDENTS_LIST)

RESIDENTS_MAP = {r["id"]: r for r in RESIDENTS_LIST}

# Index inverse code famille → resident_id pour lookup O(1)
FAMILY_CODE_MAP = {r["family_code"].upper(): r["id"] for r in RESIDENTS_LIST}

CAREGIVERS = {
    "soignant_A": {"name": "Infirmiere Sophie", "role": "infirmiere",    "phone": "+33612345678"},
    "soignant_B": {"name": "Aide-soignant Marc","role": "aide_soignant", "phone": "+33623456789"},
    "soignant_C": {"name": "Infirmiere Julie",  "role": "infirmiere",    "phone": "+33634567890"},
    "chef_garde":  {"name": "Dr. Leclerc",       "role": "medecin",       "phone": "+33645678901"},
    "direction":   {"name": "Directrice Martin", "role": "direction",     "phone": "+33656789012"},
}
