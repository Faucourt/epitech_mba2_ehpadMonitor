"""Carte de circulation et scenarios de mouvement pour le simulateur EHPAD."""

ZONE_POSITIONS = {
    "entree": (-18, 8, 0),
    "hors_ehpad": (-27, 12, 0),
    "infirmerie_rdc": (-11, 8, 0),
    "pharmacie_admin": (-4.5, 8, 0),
    "couloir_principal": (0, -2.5, 0),
    "salle_commune": (8, 8, 0),
    "patio": (0, 0, 0),
    "jardin": (0, 15, 0),
    "salle_activites": (17, 8, 0),
    "salle_manger": (10, 1, 0),
    "office_cuisine": (18.5, 1, 0),
    "couloir_aile_rdc": (0, -8, 0),
    "escalier": (-21, 0, 0),
    "ascenseur": (-18, 0, 0),
    "poste_infirmier_etage": (-18, 8, 1),
    "kinesitherapie": (-7, 8, 1),
    "salle_repos": (7, 8, 1),
    "couloir_aile_a_etage": (-7, -2.5, 1),
    "couloir_aile_b_etage": (8, -2.5, 1),
    "palier_etage": (-18, 0, 1),
}

DINING_SEATS = [
    {"table": "T1", "seat": 1, "position": (7.4, 0.0, 0)},
    {"table": "T1", "seat": 2, "position": (7.4, 1.1, 0)},
    {"table": "T1", "seat": 3, "position": (8.6, 0.0, 0)},
    {"table": "T1", "seat": 4, "position": (8.6, 1.1, 0)},
    {"table": "T1", "seat": 5, "position": (8.0, 1.8, 0)},
    {"table": "T2", "seat": 1, "position": (10.1, 0.0, 0)},
    {"table": "T2", "seat": 2, "position": (10.1, 1.1, 0)},
    {"table": "T2", "seat": 3, "position": (11.3, 0.0, 0)},
    {"table": "T2", "seat": 4, "position": (11.3, 1.1, 0)},
    {"table": "T2", "seat": 5, "position": (10.7, 1.8, 0)},
    {"table": "T3", "seat": 1, "position": (12.8, 0.0, 0)},
    {"table": "T3", "seat": 2, "position": (12.8, 1.1, 0)},
    {"table": "T3", "seat": 3, "position": (14.0, 0.0, 0)},
    {"table": "T3", "seat": 4, "position": (14.0, 1.1, 0)},
    {"table": "T3", "seat": 5, "position": (13.4, 1.8, 0)},
    {"table": "T4", "seat": 1, "position": (8.2, 2.8, 0)},
    {"table": "T4", "seat": 2, "position": (8.2, 3.8, 0)},
    {"table": "T4", "seat": 3, "position": (9.4, 2.8, 0)},
    {"table": "T4", "seat": 4, "position": (9.4, 3.8, 0)},
    {"table": "T4", "seat": 5, "position": (8.8, 4.4, 0)},
    {"table": "T5", "seat": 1, "position": (11.7, 2.8, 0)},
    {"table": "T5", "seat": 2, "position": (11.7, 3.8, 0)},
    {"table": "T5", "seat": 3, "position": (12.9, 2.8, 0)},
    {"table": "T5", "seat": 4, "position": (12.9, 3.8, 0)},
    {"table": "T5", "seat": 5, "position": (12.3, 4.4, 0)},
]

ROOM_ZONE_POSITIONS = {
    "ch101": (-18, -8, 0), "ch102": (-13.5, -8, 0), "ch103": (-9, -8, 0), "ch104": (-4.5, -8, 0),
    "ch105": (4.5, -8, 0), "ch106": (9, -8, 0), "ch107": (13.5, -8, 0), "ch108": (18, -8, 0),
    "ch201": (-18, -8, 1), "ch202": (-13.5, -8, 1), "ch203": (-9, -8, 1), "ch204": (-4.5, -8, 1),
    "ch208": (4.5, -8, 1), "ch209": (9, -8, 1), "ch210": (13.5, -8, 1), "ch211": (18, -8, 1),
    "ch212": (-13.5, 8, 1), "ch213": (-9, 8, 1), "ch214": (9, 8, 1), "ch215": (13.5, 8, 1),
    "ch216": (18, 8, 1), "ch217": (-18, 8, 1), "ch218": (-4.5, 8, 1), "ch219": (4.5, 8, 1), "ch220": (0, 8, 1),
}

ZONE_POSITIONS.update(ROOM_ZONE_POSITIONS)

ZONE_GRAPH = {
    "entree": ["couloir_principal", "hors_ehpad"],
    "hors_ehpad": ["entree"],
    "infirmerie_rdc": ["couloir_principal"],
    "pharmacie_admin": ["couloir_principal"],
    "salle_commune": ["couloir_principal", "patio", "salle_activites"],
    "patio": ["salle_commune", "entree", "jardin"],
    "jardin": ["patio", "entree"],
    "salle_activites": ["salle_commune"],
    "salle_manger": ["couloir_principal", "office_cuisine"],
    "office_cuisine": ["salle_manger"],
    "couloir_principal": ["entree", "infirmerie_rdc", "pharmacie_admin", "salle_commune", "salle_manger", "couloir_aile_rdc", "ascenseur", "escalier"],
    "couloir_aile_rdc": ["couloir_principal", "ch101", "ch102", "ch103", "ch104", "ch105", "ch106", "ch107", "ch108"],
    "ascenseur": ["couloir_principal", "palier_etage"],
    "escalier": ["couloir_principal", "palier_etage"],
    "palier_etage": ["ascenseur", "escalier", "poste_infirmier_etage", "couloir_aile_a_etage", "couloir_aile_b_etage"],
    "poste_infirmier_etage": ["palier_etage"],
    "kinesitherapie": ["couloir_aile_a_etage"],
    "salle_repos": ["couloir_aile_b_etage"],
    "couloir_aile_a_etage": ["palier_etage", "kinesitherapie", "ch201", "ch202", "ch203", "ch204", "ch208", "ch209", "ch210", "ch211"],
    "couloir_aile_b_etage": ["palier_etage", "salle_repos", "ch212", "ch213", "ch214", "ch215", "ch216", "ch217", "ch218", "ch219", "ch220"],
}

for room_id, (_, _, floor) in ROOM_ZONE_POSITIONS.items():
    corridor = "couloir_aile_rdc" if floor == 0 else ("couloir_aile_b_etage" if room_id in {"ch212", "ch213", "ch214", "ch215", "ch216", "ch217", "ch218", "ch219", "ch220"} else "couloir_aile_a_etage")
    ZONE_GRAPH[room_id] = [corridor]

ROUTINE_TARGETS = {
    "lever_toilette": ["home", "couloir_principal"],
    "petit_dej": ["salle_manger"],
    "soins_matin": ["infirmerie_rdc", "salle_commune", "kinesitherapie"],
    "animation_matin": ["salle_commune", "salle_activites", "kinesitherapie", "patio", "jardin"],
    "trajet_dejeuner": ["salle_manger"],
    "dejeuner": ["salle_manger"],
    "sieste": ["home"],
    "animation_apres_midi": ["salle_commune", "salle_activites", "kinesitherapie", "patio", "jardin", "salle_repos"],
    "gouter": ["salle_manger", "salle_commune"],
    "trajet_diner": ["salle_manger"],
    "diner": ["salle_manger"],
    "soiree": ["salle_commune", "home"],
    "coucher": ["home"],
    "nuit": ["home"],
}

ROUTINE_LABELS = {
    "lever_toilette": "Lever, toilette et habillage",
    "petit_dej": "Petit dejeuner en groupe",
    "soins_matin": "Soins infirmiers / kine",
    "animation_matin": "Animation du matin",
    "trajet_dejeuner": "Trajet vers salle a manger",
    "dejeuner": "Dejeuner en salle a manger",
    "sieste": "Sieste / repos",
    "animation_apres_midi": "Animation apres-midi",
    "gouter": "Gouter",
    "trajet_diner": "Trajet vers diner",
    "diner": "Diner en salle a manger",
    "soiree": "Soiree calme",
    "coucher": "Coucher accompagne",
    "nuit": "Surveillance de nuit",
}

SCENARIO_LIBRARY = [
    {"type": "chute_couloir", "zones": ["couloir_aile_rdc", "couloir_principal", "couloir_aile_a_etage", "couloir_aile_b_etage"], "risk": 1.0},
    {"type": "chute_chambre", "zones": list(ROOM_ZONE_POSITIONS.keys()), "risk": 0.75},
    {"type": "malaise_salle_manger", "zones": ["salle_manger"], "risk": 0.65},
    {"type": "errance_nuit", "zones": ["couloir_principal", "entree", "patio"], "risk": 0.55},
    {"type": "sortie_patio", "zones": ["patio", "entree"], "risk": 0.35},
    {"type": "immobilite_salle_repos", "zones": ["salle_repos", "salle_commune"], "risk": 0.45},
    {"type": "aller_toilettes_nuit", "zones": ["couloir_principal", "couloir_aile_rdc", "couloir_aile_a_etage", "couloir_aile_b_etage"], "risk": 0.3},
    {"type": "desorientation_ascenseur", "zones": ["ascenseur", "palier_etage", "escalier"], "risk": 0.5},
    {"type": "agitation_couloir", "zones": ["couloir_principal", "couloir_aile_rdc", "couloir_aile_a_etage", "couloir_aile_b_etage"], "risk": 0.4},
    {"type": "isolement_chambre", "zones": list(ROOM_ZONE_POSITIONS.keys()), "risk": 0.35},
    {"type": "retour_kine_fatigue", "zones": ["kinesitherapie", "salle_repos"], "risk": 0.45},
    {"type": "promenade_jardin", "zones": ["jardin", "patio"], "risk": 0.25},
    {"type": "sortie_jardin_non_accompagnee", "zones": ["jardin", "entree"], "risk": 0.45},
    {"type": "chute_jardin", "zones": ["jardin"], "risk": 0.5},
    {"type": "fugue_hors_ehpad", "zones": ["entree", "hors_ehpad"], "risk": 0.9},
    {"type": "chute_trajet_repas", "zones": ["couloir_aile_rdc", "couloir_principal", "ascenseur", "palier_etage", "couloir_aile_a_etage", "couloir_aile_b_etage"], "risk": 0.75},
    {"type": "desorientation_avant_repas", "zones": ["couloir_principal", "ascenseur", "palier_etage", "salle_manger"], "risk": 0.55},
    {"type": "malaise_retour_repas", "zones": ["salle_manger", "couloir_principal"], "risk": 0.65},
]


def shortest_path(start, target):
    if start == target:
        return [start]
    seen = {start}
    queue = [(start, [start])]
    while queue:
        node, path = queue.pop(0)
        for nxt in ZONE_GRAPH.get(node, []):
            if nxt in seen:
                continue
            if nxt == target:
                return path + [nxt]
            seen.add(nxt)
            queue.append((nxt, path + [nxt]))
    return [start, target]


def zone_position(zone_id):
    return ZONE_POSITIONS.get(zone_id, (0, 0, 0))
