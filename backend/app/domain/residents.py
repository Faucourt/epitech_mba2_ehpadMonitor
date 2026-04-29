RESIDENT_ARCHETYPES = {
    "autonome": {
        "label": "Autonome",
        "daily_focus": "vie sociale, activites, repas en salle",
        "main_risks": ["chute trajet", "malaise effort", "retard alerte si isolement"],
        "supervision": "surveillance standard",
    },
    "accompagne": {
        "label": "Deplacement accompagne",
        "daily_focus": "repas encadre, kine, trajets surveilles",
        "main_risks": ["chute couloir", "fatigue post-kine", "hypotension post-repas"],
        "supervision": "surveillance renforcee aux transferts",
    },
    "chambre": {
        "label": "Reste principalement en chambre",
        "daily_focus": "soins au lit, repas en chambre, prevention escarres",
        "main_risks": ["inactivite", "sortie de lit", "chute chambre"],
        "supervision": "passages soignants programmes",
    },
    "cognitif": {
        "label": "Troubles cognitifs / fugue",
        "daily_focus": "repas et activites securises, controle sorties",
        "main_risks": ["errance", "fugue", "desorientation escalier/ascenseur"],
        "supervision": "surveillance sorties et zones sensibles",
    },
    "respiratoire": {
        "label": "Fragilite respiratoire",
        "daily_focus": "tolerance effort, SpO2 personnalisee, repos",
        "main_risks": ["desaturation", "fatigue retour repas", "dyspnee nocturne"],
        "supervision": "seuils SpO2 adaptes au profil",
    },
    "cardio": {
        "label": "Fragilite cardio-metabolique",
        "daily_focus": "surveillance tension, FC, malaise postural",
        "main_risks": ["tachycardie", "hypotension", "malaise post-repas"],
        "supervision": "controle cardio rapproche si tendance monte",
    },
}


def resident_archetype(profile: dict) -> str:
    pathologies = set(profile.get("pathologies", []))
    mobility = profile.get("mobility", "moyenne")
    risk = float(profile.get("risk_factor", 0.3))
    if pathologies.intersection({"alzheimer", "demence", "dementia"}):
        return "cognitif"
    if "bpco" in pathologies:
        return "respiratoire"
    if pathologies.intersection({"insuffisance_cardiaque", "hypertension"}) and risk >= 0.45:
        return "cardio"
    if mobility == "tres_faible" and risk >= 0.6:
        return "chambre"
    if mobility in {"faible", "tres_faible"}:
        return "accompagne"
    return "autonome"
