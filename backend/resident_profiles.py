"""
Map des profils résidents pour le backend.
Identique aux profils du simulateur.
"""

RESIDENTS_LIST = [
    {"id": "R001", "name": "Marguerite Dupont", "age": 87, "room": "101", "pathologies": ["hypertension", "diabete"], "mobility": "faible", "risk_factor": 0.3, "caregiver": "soignant_A"},
    {"id": "R002", "name": "Henri Moreau", "age": 79, "room": "102", "pathologies": ["insuffisance_cardiaque"], "mobility": "moyenne", "risk_factor": 0.5, "caregiver": "soignant_A"},
    {"id": "R003", "name": "Simone Bernard", "age": 92, "room": "103", "pathologies": ["alzheimer", "hypertension"], "mobility": "tres_faible", "risk_factor": 0.6, "caregiver": "soignant_A"},
    {"id": "R004", "name": "Pierre Leroy", "age": 75, "room": "104", "pathologies": ["diabete"], "mobility": "bonne", "risk_factor": 0.1, "caregiver": "soignant_B"},
    {"id": "R005", "name": "Yvette Martin", "age": 84, "room": "105", "pathologies": ["parkinson", "hypertension"], "mobility": "faible", "risk_factor": 0.4, "caregiver": "soignant_B"},
    {"id": "R006", "name": "André Petit", "age": 81, "room": "106", "pathologies": ["bpco"], "mobility": "faible", "risk_factor": 0.55, "caregiver": "soignant_B"},
    {"id": "R007", "name": "Louise Durand", "age": 88, "room": "107", "pathologies": ["insuffisance_renale", "diabete"], "mobility": "moyenne", "risk_factor": 0.35, "caregiver": "soignant_C"},
    {"id": "R008", "name": "Marcel Thomas", "age": 77, "room": "108", "pathologies": [], "mobility": "bonne", "risk_factor": 0.05, "caregiver": "soignant_C"},
    {"id": "R009", "name": "Jeanne Robert", "age": 90, "room": "201", "pathologies": ["alzheimer", "insuffisance_cardiaque"], "mobility": "tres_faible", "risk_factor": 0.7, "caregiver": "soignant_C"},
    {"id": "R010", "name": "Gaston Richard", "age": 83, "room": "202", "pathologies": ["hypertension"], "mobility": "moyenne", "risk_factor": 0.25, "caregiver": "soignant_A"},
    {"id": "R011", "name": "Odette Simon", "age": 86, "room": "203", "pathologies": ["parkinson", "diabete"], "mobility": "faible", "risk_factor": 0.45, "caregiver": "soignant_A"},
    {"id": "R012", "name": "Fernand Michel", "age": 80, "room": "204", "pathologies": ["insuffisance_cardiaque", "bpco"], "mobility": "faible", "risk_factor": 0.65, "caregiver": "soignant_B"},
    {"id": "R013", "name": "Hélène Lefebvre", "age": 76, "room": "208", "pathologies": ["diabete"], "mobility": "bonne", "risk_factor": 0.15, "caregiver": "soignant_B"},
    {"id": "R014", "name": "Roger Leblanc", "age": 91, "room": "209", "pathologies": ["alzheimer"], "mobility": "tres_faible", "risk_factor": 0.5, "caregiver": "soignant_C"},
    {"id": "R015", "name": "Germaine Fontaine", "age": 85, "room": "210", "pathologies": ["hypertension", "insuffisance_renale"], "mobility": "moyenne", "risk_factor": 0.4, "caregiver": "soignant_C"},
    {"id": "R016", "name": "Edouard Rousseau", "age": 78, "room": "211", "pathologies": ["bpco", "hypertension"], "mobility": "faible", "risk_factor": 0.5, "caregiver": "soignant_A"},
    {"id": "R017", "name": "Blanche Morel", "age": 89, "room": "212", "pathologies": ["insuffisance_cardiaque"], "mobility": "tres_faible", "risk_factor": 0.7, "caregiver": "soignant_A"},
    {"id": "R018", "name": "Lucien Garnier", "age": 74, "room": "213", "pathologies": [], "mobility": "bonne", "risk_factor": 0.05, "caregiver": "soignant_B"},
    {"id": "R019", "name": "Paulette Chevalier", "age": 93, "room": "214", "pathologies": ["alzheimer", "parkinson", "hypertension"], "mobility": "tres_faible", "risk_factor": 0.75, "caregiver": "soignant_B"},
    {"id": "R020", "name": "Auguste Mercier", "age": 82, "room": "215", "pathologies": ["diabete", "insuffisance_cardiaque"], "mobility": "faible", "risk_factor": 0.55, "caregiver": "soignant_C"},
    {"id": "R021", "name": "Therese Blanc", "age": 78, "room": "216", "pathologies": ["hypertension"], "mobility": "moyenne", "risk_factor": 0.2, "caregiver": "soignant_C"},
    {"id": "R022", "name": "Gaetan Caron", "age": 86, "room": "217", "pathologies": ["bpco", "insuffisance_renale"], "mobility": "faible", "risk_factor": 0.6, "caregiver": "soignant_A"},
    {"id": "R023", "name": "Renee Fournier", "age": 81, "room": "218", "pathologies": ["diabete", "hypertension"], "mobility": "moyenne", "risk_factor": 0.35, "caregiver": "soignant_A"},
    {"id": "R024", "name": "Leon Girard", "age": 95, "room": "219", "pathologies": ["alzheimer", "insuffisance_cardiaque", "hypertension"], "mobility": "tres_faible", "risk_factor": 0.85, "caregiver": "soignant_B"},
    {"id": "R025", "name": "Clothilde Perrin", "age": 73, "room": "220", "pathologies": [], "mobility": "bonne", "risk_factor": 0.02, "caregiver": "soignant_B"},
]

RESIDENTS_MAP = {r["id"]: r for r in RESIDENTS_LIST}

CAREGIVERS = {
    "soignant_A": {"name": "Infirmière Sophie", "role": "infirmiere", "phone": "+33612345678"},
    "soignant_B": {"name": "Aide-soignant Marc", "role": "aide_soignant", "phone": "+33623456789"},
    "soignant_C": {"name": "Infirmière Julie", "role": "infirmiere", "phone": "+33634567890"},
    "chef_garde": {"name": "Dr. Leclerc", "role": "medecin", "phone": "+33645678901"},
    "direction": {"name": "Directrice Martin", "role": "direction", "phone": "+33656789012"},
}
