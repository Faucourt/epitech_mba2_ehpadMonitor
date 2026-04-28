"""
Map des profils résidents pour le backend.
Identique aux profils du simulateur.
family_code : code PIN unique remis a la famille de chaque resident.
archetype_id + likely_medications + preferred_scenarios : deduits automatiquement
depuis la KB clinique (ehpad_watch_kb.json) via kb_loader.
"""

RESIDENTS_LIST = [
    {"id": "R001", "name": "Marie Curie",          "age": 87, "room": "101", "pathologies": ["hypertension", "diabete"],                              "mobility": "faible",     "risk_factor": 0.30, "caregiver": "soignant_A", "family_code": "CURIE101",      "avatar": "/avatars/resident_101_marie_curie.png"},
    {"id": "R002", "name": "Louis Pasteur",        "age": 79, "room": "102", "pathologies": ["insuffisance_cardiaque"],                               "mobility": "moyenne",    "risk_factor": 0.50, "caregiver": "soignant_A", "family_code": "PASTEUR102",    "avatar": "/avatars/resident_102_louis_pasteur.png"},
    {"id": "R003", "name": "Simone Veil",          "age": 92, "room": "103", "pathologies": ["alzheimer", "hypertension"],                            "mobility": "tres_faible","risk_factor": 0.60, "caregiver": "soignant_A", "family_code": "VEIL103",       "avatar": "/avatars/resident_103_simone_veil.png"},
    {"id": "R004", "name": "Pierre de Coubertin",  "age": 75, "room": "104", "pathologies": ["diabete"],                                              "mobility": "bonne",      "risk_factor": 0.10, "caregiver": "soignant_B", "family_code": "COUBERTIN104",  "avatar": "/avatars/resident_104_pierre_de_coubertin.png"},
    {"id": "R005", "name": "Edith Piaf",           "age": 84, "room": "105", "pathologies": ["parkinson", "hypertension"],                            "mobility": "faible",     "risk_factor": 0.40, "caregiver": "soignant_B", "family_code": "PIAF105",       "avatar": "/avatars/resident_105_edith_piaf.png"},
    {"id": "R006", "name": "Jean Gabin",           "age": 81, "room": "106", "pathologies": ["bpco"],                                                 "mobility": "faible",     "risk_factor": 0.55, "caregiver": "soignant_B", "family_code": "GABIN106",      "avatar": "/avatars/resident_106_jean_gabin.png"},
    {"id": "R007", "name": "Annie Girardot",       "age": 88, "room": "107", "pathologies": ["insuffisance_renale", "diabete"],                       "mobility": "moyenne",    "risk_factor": 0.35, "caregiver": "soignant_C", "family_code": "GIRARDOT107",   "avatar": "/avatars/resident_107_annie_girardot.png"},
    {"id": "R008", "name": "Bourvil",              "age": 77, "room": "108", "pathologies": [],                                                       "mobility": "bonne",      "risk_factor": 0.05, "caregiver": "soignant_C", "family_code": "BOURVIL108",    "avatar": "/avatars/resident_108_bourvil.png"},
    {"id": "R009", "name": "Coco Chanel",          "age": 90, "room": "201", "pathologies": ["alzheimer", "insuffisance_cardiaque"],                  "mobility": "tres_faible","risk_factor": 0.70, "caregiver": "soignant_C", "family_code": "CHANEL201",     "avatar": "/avatars/resident_201_coco_chanel.png"},
    {"id": "R010", "name": "Yves Montand",         "age": 83, "room": "202", "pathologies": ["hypertension"],                                         "mobility": "moyenne",    "risk_factor": 0.25, "caregiver": "soignant_A", "family_code": "MONTAND202",    "avatar": "/avatars/resident_202_yves_montand.png"},
    {"id": "R011", "name": "Jeanne Moreau",        "age": 86, "room": "203", "pathologies": ["parkinson", "diabete"],                                 "mobility": "faible",     "risk_factor": 0.45, "caregiver": "soignant_A", "family_code": "MOREAU203",     "avatar": "/avatars/resident_203_jeanne_moreau.png"},
    {"id": "R012", "name": "Charles Aznavour",     "age": 80, "room": "204", "pathologies": ["insuffisance_cardiaque", "bpco"],                       "mobility": "faible",     "risk_factor": 0.65, "caregiver": "soignant_B", "family_code": "AZNAVOUR204",   "avatar": "/avatars/resident_204_charles_aznavour.png"},
    {"id": "R013", "name": "Brigitte Bardot",      "age": 76, "room": "208", "pathologies": ["diabete"],                                              "mobility": "bonne",      "risk_factor": 0.15, "caregiver": "soignant_B", "family_code": "BARDOT208",     "avatar": "/avatars/resident_208_brigitte_bardot.png"},
    {"id": "R014", "name": "Gerard Depardieu",     "age": 91, "room": "209", "pathologies": ["alzheimer"],                                            "mobility": "tres_faible","risk_factor": 0.50, "caregiver": "soignant_C", "family_code": "DEPARDIEU209",  "avatar": "/avatars/resident_209_gerard_depardieu.png"},
    {"id": "R015", "name": "Mireille Mathieu",     "age": 85, "room": "210", "pathologies": ["hypertension", "insuffisance_renale"],                  "mobility": "moyenne",    "risk_factor": 0.40, "caregiver": "soignant_C", "family_code": "MATHIEU210",    "avatar": "/avatars/resident_210_mireille_mathieu.png"},
    {"id": "R016", "name": "Claude Francois",      "age": 78, "room": "211", "pathologies": ["bpco", "hypertension"],                                 "mobility": "faible",     "risk_factor": 0.50, "caregiver": "soignant_A", "family_code": "FRANCOIS211",   "avatar": "/avatars/resident_211_claude_francois.png"},
    {"id": "R017", "name": "Josephine Baker",      "age": 89, "room": "212", "pathologies": ["insuffisance_cardiaque"],                               "mobility": "tres_faible","risk_factor": 0.70, "caregiver": "soignant_A", "family_code": "BAKER212",      "avatar": "/avatars/resident_212_josephine_baker.png"},
    {"id": "R018", "name": "Fernandel",            "age": 74, "room": "213", "pathologies": [],                                                       "mobility": "bonne",      "risk_factor": 0.05, "caregiver": "soignant_B", "family_code": "FERNANDEL213",  "avatar": "/avatars/resident_213_fernandel.png"},
    {"id": "R019", "name": "Dalida",               "age": 93, "room": "214", "pathologies": ["alzheimer", "parkinson", "hypertension"],               "mobility": "tres_faible","risk_factor": 0.75, "caregiver": "soignant_B", "family_code": "DALIDA214",     "avatar": "/avatars/resident_214_dalida.png"},
    {"id": "R020", "name": "Lino Ventura",         "age": 82, "room": "215", "pathologies": ["diabete", "insuffisance_cardiaque"],                    "mobility": "faible",     "risk_factor": 0.55, "caregiver": "soignant_C", "family_code": "VENTURA215",    "avatar": "/avatars/resident_215_lino_ventura.png"},
    {"id": "R021", "name": "Romy Schneider",       "age": 78, "room": "216", "pathologies": ["hypertension"],                                         "mobility": "moyenne",    "risk_factor": 0.20, "caregiver": "soignant_C", "family_code": "SCHNEIDER216",  "avatar": "/avatars/resident_216_romy_schneider.png"},
    {"id": "R022", "name": "Jean-Paul Belmondo",   "age": 86, "room": "217", "pathologies": ["bpco", "insuffisance_renale"],                          "mobility": "faible",     "risk_factor": 0.60, "caregiver": "soignant_A", "family_code": "BELMONDO217",   "avatar": "/avatars/resident_217_jean_paul_belmondo.png"},
    {"id": "R023", "name": "Sophie Marceau",       "age": 81, "room": "218", "pathologies": ["diabete", "hypertension"],                              "mobility": "moyenne",    "risk_factor": 0.35, "caregiver": "soignant_A", "family_code": "MARCEAU218",    "avatar": "/avatars/resident_218_sophie_marceau.png"},
    {"id": "R024", "name": "Michel Sardou",        "age": 95, "room": "219", "pathologies": ["alzheimer", "insuffisance_cardiaque", "hypertension"],  "mobility": "tres_faible","risk_factor": 0.85, "caregiver": "soignant_B", "family_code": "SARDOU219",     "avatar": "/avatars/resident_219_michel_sardou.png"},
    {"id": "R025", "name": "Isabelle Adjani",      "age": 73, "room": "220", "pathologies": [],                                                       "mobility": "bonne",      "risk_factor": 0.02, "caregiver": "soignant_B", "family_code": "ADJANI220",     "avatar": "/avatars/resident_220_isabelle_adjani.png"},
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
