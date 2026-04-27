"""
Profils des 25 résidents de l'EHPAD.
Chaque profil définit des paramètres de base et des facteurs de risque.
"""

ROOM_ASSIGNMENTS = [
    {"room": "101", "floor": 0, "zone": "ch101", "wing": "rdc", "room_sensors": ["wearable", "pir", "matelas"]},
    {"room": "102", "floor": 0, "zone": "ch102", "wing": "rdc", "room_sensors": ["wearable", "radar", "porte"]},
    {"room": "103", "floor": 0, "zone": "ch103", "wing": "rdc", "room_sensors": ["wearable", "pir", "matelas"]},
    {"room": "104", "floor": 0, "zone": "ch104", "wing": "rdc", "room_sensors": ["wearable", "radar", "porte"]},
    {"room": "105", "floor": 0, "zone": "ch105", "wing": "rdc", "room_sensors": ["wearable", "pir", "matelas"]},
    {"room": "106", "floor": 0, "zone": "ch106", "wing": "rdc", "room_sensors": ["wearable", "radar", "porte"]},
    {"room": "107", "floor": 0, "zone": "ch107", "wing": "rdc", "room_sensors": ["wearable", "pir", "matelas"]},
    {"room": "108", "floor": 0, "zone": "ch108", "wing": "rdc", "room_sensors": ["wearable", "radar", "porte"]},
    {"room": "201", "floor": 1, "zone": "ch201", "wing": "aile_a", "room_sensors": ["wearable", "pir"]},
    {"room": "202", "floor": 1, "zone": "ch202", "wing": "aile_a", "room_sensors": ["wearable", "radar"]},
    {"room": "203", "floor": 1, "zone": "ch203", "wing": "aile_a", "room_sensors": ["wearable", "pir"]},
    {"room": "204", "floor": 1, "zone": "ch204", "wing": "aile_a", "room_sensors": ["wearable", "radar"]},
    {"room": "208", "floor": 1, "zone": "ch208", "wing": "aile_a", "room_sensors": ["wearable", "pir"]},
    {"room": "209", "floor": 1, "zone": "ch209", "wing": "aile_a", "room_sensors": ["wearable", "radar"]},
    {"room": "210", "floor": 1, "zone": "ch210", "wing": "aile_a", "room_sensors": ["wearable", "pir"]},
    {"room": "211", "floor": 1, "zone": "ch211", "wing": "aile_a", "room_sensors": ["wearable", "radar"]},
    {"room": "212", "floor": 1, "zone": "ch212", "wing": "aile_b", "room_sensors": ["wearable", "pir"]},
    {"room": "213", "floor": 1, "zone": "ch213", "wing": "aile_b", "room_sensors": ["wearable", "radar"]},
    {"room": "214", "floor": 1, "zone": "ch214", "wing": "aile_b", "room_sensors": ["wearable", "pir"]},
    {"room": "215", "floor": 1, "zone": "ch215", "wing": "aile_b", "room_sensors": ["wearable", "radar"]},
    {"room": "216", "floor": 1, "zone": "ch216", "wing": "aile_b", "room_sensors": ["wearable", "pir"]},
    {"room": "217", "floor": 1, "zone": "ch217", "wing": "aile_b", "room_sensors": ["wearable", "radar"]},
    {"room": "218", "floor": 1, "zone": "ch218", "wing": "aile_b", "room_sensors": ["wearable", "pir"]},
    {"room": "219", "floor": 1, "zone": "ch219", "wing": "aile_b", "room_sensors": ["wearable", "radar"]},
    {"room": "220", "floor": 1, "zone": "ch220", "wing": "aile_b", "room_sensors": ["wearable", "pir", "matelas"]},
]

RESIDENTS = [
    {
        "id": "R001", "name": "Marguerite Dupont", "age": 87, "room": "101",
        "pathologies": ["hypertension", "diabete"], "mobility": "faible",
        "base_hr": 72, "base_spo2": 96, "base_bp_sys": 145, "base_temp": 36.8,
        "risk_factor": 0.3, "caregiver": "soignant_A"
    },
    {
        "id": "R002", "name": "Henri Moreau", "age": 79, "room": "102",
        "pathologies": ["insuffisance_cardiaque"], "mobility": "moyenne",
        "base_hr": 68, "base_spo2": 94, "base_bp_sys": 130, "base_temp": 36.6,
        "risk_factor": 0.5, "caregiver": "soignant_A"
    },
    {
        "id": "R003", "name": "Simone Bernard", "age": 92, "room": "103",
        "pathologies": ["alzheimer", "hypertension"], "mobility": "tres_faible",
        "base_hr": 75, "base_spo2": 95, "base_bp_sys": 150, "base_temp": 36.9,
        "risk_factor": 0.6, "caregiver": "soignant_A"
    },
    {
        "id": "R004", "name": "Pierre Leroy", "age": 75, "room": "104",
        "pathologies": ["diabete"], "mobility": "bonne",
        "base_hr": 65, "base_spo2": 97, "base_bp_sys": 120, "base_temp": 36.5,
        "risk_factor": 0.1, "caregiver": "soignant_B"
    },
    {
        "id": "R005", "name": "Yvette Martin", "age": 84, "room": "105",
        "pathologies": ["parkinson", "hypertension"], "mobility": "faible",
        "base_hr": 70, "base_spo2": 95, "base_bp_sys": 140, "base_temp": 36.7,
        "risk_factor": 0.4, "caregiver": "soignant_B"
    },
    {
        "id": "R006", "name": "André Petit", "age": 81, "room": "106",
        "pathologies": ["bpco"], "mobility": "faible",
        "base_hr": 78, "base_spo2": 92, "base_bp_sys": 135, "base_temp": 36.6,
        "risk_factor": 0.55, "caregiver": "soignant_B"
    },
    {
        "id": "R007", "name": "Louise Durand", "age": 88, "room": "107",
        "pathologies": ["insuffisance_renale", "diabete"], "mobility": "moyenne",
        "base_hr": 74, "base_spo2": 96, "base_bp_sys": 155, "base_temp": 36.8,
        "risk_factor": 0.35, "caregiver": "soignant_C"
    },
    {
        "id": "R008", "name": "Marcel Thomas", "age": 77, "room": "108",
        "pathologies": [], "mobility": "bonne",
        "base_hr": 62, "base_spo2": 98, "base_bp_sys": 118, "base_temp": 36.4,
        "risk_factor": 0.05, "caregiver": "soignant_C"
    },
    {
        "id": "R009", "name": "Jeanne Robert", "age": 90, "room": "201",
        "pathologies": ["alzheimer", "insuffisance_cardiaque"], "mobility": "tres_faible",
        "base_hr": 80, "base_spo2": 93, "base_bp_sys": 160, "base_temp": 37.0,
        "risk_factor": 0.7, "caregiver": "soignant_C"
    },
    {
        "id": "R010", "name": "Gaston Richard", "age": 83, "room": "202",
        "pathologies": ["hypertension"], "mobility": "moyenne",
        "base_hr": 69, "base_spo2": 96, "base_bp_sys": 148, "base_temp": 36.7,
        "risk_factor": 0.25, "caregiver": "soignant_A"
    },
    {
        "id": "R011", "name": "Odette Simon", "age": 86, "room": "203",
        "pathologies": ["parkinson", "diabete"], "mobility": "faible",
        "base_hr": 73, "base_spo2": 95, "base_bp_sys": 138, "base_temp": 36.6,
        "risk_factor": 0.45, "caregiver": "soignant_A"
    },
    {
        "id": "R012", "name": "Fernand Michel", "age": 80, "room": "204",
        "pathologies": ["insuffisance_cardiaque", "bpco"], "mobility": "faible",
        "base_hr": 82, "base_spo2": 91, "base_bp_sys": 142, "base_temp": 36.9,
        "risk_factor": 0.65, "caregiver": "soignant_B"
    },
    {
        "id": "R013", "name": "Hélène Lefebvre", "age": 76, "room": "208",
        "pathologies": ["diabete"], "mobility": "bonne",
        "base_hr": 67, "base_spo2": 97, "base_bp_sys": 125, "base_temp": 36.5,
        "risk_factor": 0.15, "caregiver": "soignant_B"
    },
    {
        "id": "R014", "name": "Roger Leblanc", "age": 91, "room": "209",
        "pathologies": ["alzheimer"], "mobility": "tres_faible",
        "base_hr": 76, "base_spo2": 94, "base_bp_sys": 152, "base_temp": 36.8,
        "risk_factor": 0.5, "caregiver": "soignant_C"
    },
    {
        "id": "R015", "name": "Germaine Fontaine", "age": 85, "room": "210",
        "pathologies": ["hypertension", "insuffisance_renale"], "mobility": "moyenne",
        "base_hr": 71, "base_spo2": 95, "base_bp_sys": 157, "base_temp": 36.7,
        "risk_factor": 0.4, "caregiver": "soignant_C"
    },
    {
        "id": "R016", "name": "Edouard Rousseau", "age": 78, "room": "211",
        "pathologies": ["bpco", "hypertension"], "mobility": "faible",
        "base_hr": 77, "base_spo2": 93, "base_bp_sys": 143, "base_temp": 36.7,
        "risk_factor": 0.5, "caregiver": "soignant_A"
    },
    {
        "id": "R017", "name": "Blanche Morel", "age": 89, "room": "212",
        "pathologies": ["insuffisance_cardiaque"], "mobility": "tres_faible",
        "base_hr": 85, "base_spo2": 92, "base_bp_sys": 165, "base_temp": 37.1,
        "risk_factor": 0.7, "caregiver": "soignant_A"
    },
    {
        "id": "R018", "name": "Lucien Garnier", "age": 74, "room": "213",
        "pathologies": [], "mobility": "bonne",
        "base_hr": 63, "base_spo2": 98, "base_bp_sys": 115, "base_temp": 36.4,
        "risk_factor": 0.05, "caregiver": "soignant_B"
    },
    {
        "id": "R019", "name": "Paulette Chevalier", "age": 93, "room": "214",
        "pathologies": ["alzheimer", "parkinson", "hypertension"], "mobility": "tres_faible",
        "base_hr": 79, "base_spo2": 93, "base_bp_sys": 162, "base_temp": 37.0,
        "risk_factor": 0.75, "caregiver": "soignant_B"
    },
    {
        "id": "R020", "name": "Auguste Mercier", "age": 82, "room": "215",
        "pathologies": ["diabete", "insuffisance_cardiaque"], "mobility": "faible",
        "base_hr": 76, "base_spo2": 94, "base_bp_sys": 148, "base_temp": 36.8,
        "risk_factor": 0.55, "caregiver": "soignant_C"
    },
    {
        "id": "R021", "name": "Thérèse Blanc", "age": 78, "room": "216",
        "pathologies": ["hypertension"], "mobility": "moyenne",
        "base_hr": 68, "base_spo2": 97, "base_bp_sys": 144, "base_temp": 36.6,
        "risk_factor": 0.2, "caregiver": "soignant_C"
    },
    {
        "id": "R022", "name": "Gaétan Caron", "age": 86, "room": "217",
        "pathologies": ["bpco", "insuffisance_renale"], "mobility": "faible",
        "base_hr": 80, "base_spo2": 91, "base_bp_sys": 140, "base_temp": 36.9,
        "risk_factor": 0.6, "caregiver": "soignant_A"
    },
    {
        "id": "R023", "name": "Renée Fournier", "age": 81, "room": "218",
        "pathologies": ["diabete", "hypertension"], "mobility": "moyenne",
        "base_hr": 72, "base_spo2": 96, "base_bp_sys": 150, "base_temp": 36.7,
        "risk_factor": 0.35, "caregiver": "soignant_A"
    },
    {
        "id": "R024", "name": "Léon Girard", "age": 95, "room": "219",
        "pathologies": ["alzheimer", "insuffisance_cardiaque", "hypertension"], "mobility": "tres_faible",
        "base_hr": 83, "base_spo2": 91, "base_bp_sys": 170, "base_temp": 37.2,
        "risk_factor": 0.85, "caregiver": "soignant_B"
    },
    {
        "id": "R025", "name": "Clothilde Perrin", "age": 73, "room": "220",
        "pathologies": [], "mobility": "bonne",
        "base_hr": 60, "base_spo2": 99, "base_bp_sys": 112, "base_temp": 36.3,
        "risk_factor": 0.02, "caregiver": "soignant_B"
    },
]

# Zones de l'EHPAD avec capteurs ambiants (selon le plan Word)
ZONES = [
    {"id": "entree", "name": "Entree / Accueil", "floor": 0, "type": "entree", "sensors": ["rfid", "badge", "ir"]},
    {"id": "hors_ehpad", "name": "Sortie hors EHPAD", "floor": 0, "type": "exterieur_hors_site", "sensors": ["gps_bracelet", "rfid_sortie", "alerte_fugue"]},
    {"id": "infirmerie_rdc", "name": "Infirmerie", "floor": 0, "type": "infirmerie", "sensors": ["dashboard", "alertes_5_niveaux"]},
    {"id": "pharmacie_admin", "name": "Pharmacie / Admin", "floor": 0, "type": "admin", "sensors": ["dashboard_central"]},
    {"id": "couloir_principal", "name": "Couloir principal", "floor": 0, "type": "couloir", "sensors": ["pir", "radar_mmwave", "sol_intelligent"]},
    {"id": "salle_commune", "name": "Salle commune / TV", "floor": 0, "type": "salle_commune", "sensors": ["pir", "co2", "son"]},
    {"id": "patio", "name": "Patio couvert", "floor": 0, "type": "exterieur", "sensors": ["gps_bracelet", "rfid_sortie"]},
    {"id": "jardin", "name": "Jardin therapeutique", "floor": 0, "type": "exterieur", "sensors": ["gps_bracelet", "rfid_sortie", "camera_thermique", "pir"]},
    {"id": "salle_activites", "name": "Salle d'activites", "floor": 0, "type": "therapie", "sensors": ["pir", "ambiant"]},
    {"id": "salle_manger", "name": "Salle a manger", "floor": 0, "type": "restaurant", "sensors": ["presence", "sol_capteur"]},
    {"id": "office_cuisine", "name": "Office / Cuisine", "floor": 0, "type": "cuisine", "sensors": ["fumee", "temperature", "co"]},
    {"id": "couloir_aile_rdc", "name": "Couloir Aile RDC", "floor": 0, "type": "couloir", "sensors": ["ble_beacon", "pir", "sol_intelligent"]},
    {"id": "escalier", "name": "Escalier securise", "floor": 0, "type": "circulation", "sensors": ["pir", "radar_mmwave"]},
    {"id": "ascenseur", "name": "Ascenseur", "floor": 0, "type": "circulation", "sensors": ["badge", "pir"]},
    {"id": "poste_infirmier_etage", "name": "Poste infirmier", "floor": 1, "type": "infirmerie", "sensors": ["surveillance_etage"]},
    {"id": "kinesitherapie", "name": "Kinesitherapie", "floor": 1, "type": "therapie", "sensors": ["pir", "sol", "wearable"]},
    {"id": "salle_repos", "name": "Salle de repos", "floor": 1, "type": "salle_commune", "sensors": ["pir", "co2", "son"]},
    {"id": "couloir_aile_a_etage", "name": "Couloir Aile A", "floor": 1, "type": "couloir", "sensors": ["pir", "ble_beacon", "sol_intelligent"]},
    {"id": "couloir_aile_b_etage", "name": "Couloir Aile B", "floor": 1, "type": "couloir", "sensors": ["pir", "ble_beacon", "radar_mmwave"]},
    {"id": "palier_etage", "name": "Palier escalier / ascenseur", "floor": 1, "type": "circulation", "sensors": ["pir", "badge", "radar_mmwave"]},
]

# Personnel soignant
CAREGIVERS = [
    {"id": "soignant_A", "name": "Infirmière Sophie", "role": "infirmiere", "phone": "+33612345678"},
    {"id": "soignant_B", "name": "Aide-soignant Marc", "role": "aide_soignant", "phone": "+33623456789"},
    {"id": "soignant_C", "name": "Infirmière Julie", "role": "infirmiere", "phone": "+33634567890"},
    {"id": "chef_garde", "name": "Dr. Leclerc", "role": "medecin", "phone": "+33645678901"},
    {"id": "direction", "name": "Directrice Martin", "role": "direction", "phone": "+33656789012"},
]

