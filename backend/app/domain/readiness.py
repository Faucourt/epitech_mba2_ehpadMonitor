from app.domain.scenarios import SIMULATION_SCENARIOS

PROJECT_READINESS = [
    {
        "axis": "20-50 residents",
        "status": "done",
        "proof": "25 residents actifs, extensible par NUM_RESIDENTS et profils",
        "improve": "tester une charge 50 residents avec seuils WebSocket/Influx adaptes",
    },
    {
        "axis": "Duree continue mois/annees",
        "status": "done",
        "proof": "historique 365 jours injecte dans InfluxDB au demarrage, retention 90 jours sur donnees brutes, Redis appendonly active, simulation continue Docker",
        "improve": "ajouter snapshots Redis planifies toutes les heures et agregation automatique des donnees au-dela de 90 jours",
    },
    {
        "axis": "IA prediction malaise",
        "status": "done",
        "proof": "ML/A2A relance toutes les 5 min, risque 30 et 60 min, memoire de tendance",
        "improve": "calibrer sur donnees reelles et mesurer recall/specifite par profil",
    },
    {
        "axis": "Alertes 5 niveaux",
        "status": "done",
        "proof": "moteur niveaux 1-5, anti-bruit, localisation, escalade et acquittement",
        "improve": "journaliser le delai d'intervention et les faux positifs par type d'alerte",
    },
    {
        "axis": "Capteurs vitaux + ambiants",
        "status": "done",
        "proof": "wearable, SpO2, FC, PA, temperature, respiration, PIR, radar, porte, sol, matelas, BLE/GPS",
        "improve": "suivre la qualite signal/batterie et les capteurs muets dans le temps",
    },
    {
        "axis": "Vue par resident",
        "status": "done",
        "proof": "detail live, mini DPI, historique 30 jours, prediction, transmission",
        "improve": "ajouter validation soignant et export PDF",
    },
    {
        "axis": "Complexite scale + prediction",
        "status": "done",
        "proof": (
            "MQTT QoS differencie par criticite: QoS2 chutes/SOS, QoS1 vitaux/mouvements, QoS0 ambiant. "
            "WebSocket throttle configurable a 2s par resident, InfluxDB echantillonne a 5s "
            "(25 residents ~= 5 points/s au lieu de 25), ML/A2A toutes les 300s et LLM hors boucle temps reel. "
            "Benchmark 2026-04-29: cible sujet 120 msg/s validee pendant 60s, 0 erreur MQTT, "
            "latence API p95 19.87 ms, CPU backend 55%, RAM backend 175 MiB. "
            "La charge theorique actuelle 25 residents est couverte."
        ),
        "improve": (
            "amelioration future pour l'extension 50 residents: test 300 msg/s partiel, API p95 27.75 ms mais "
            "backend single-worker observe 175 msg/s sur 290 msg/s envoyes; envisager workers ingestion/alerting, "
            "scaling horizontal backend et rate limiting etendu aux routes critiques."
        ),
    },
]

DAY_TEMPLATE = [
    {"time": "06:00-07:30", "period": "lever_toilette", "zones": ["chambre", "couloir"], "risk": "transfert, chute chambre"},
    {"time": "07:30-09:00", "period": "petit_dej", "zones": ["salle_manger", "chambre"], "risk": "trajet repas, hypotension posturale"},
    {"time": "09:00-10:00", "period": "soins_matin", "zones": ["infirmerie", "kinesitherapie", "chambre"], "risk": "fatigue soins"},
    {"time": "10:00-11:45", "period": "animation_matin", "zones": ["salle_commune", "activites", "jardin"], "risk": "effort, desorientation"},
    {"time": "11:45-13:15", "period": "trajet_dejeuner/dejeuner", "zones": ["couloirs", "ascenseur", "salle_manger"], "risk": "chute trajet, malaise repas"},
    {"time": "13:15-15:00", "period": "sieste", "zones": ["chambre", "salle_repos"], "risk": "inactivite normale vs anormale"},
    {"time": "15:00-16:45", "period": "animation_apres_midi/gouter", "zones": ["salle_commune", "jardin", "salle_manger"], "risk": "fatigue, regroupement"},
    {"time": "18:00-19:30", "period": "trajet_diner/diner", "zones": ["couloirs", "salle_manger"], "risk": "chute trajet, malaise retour repas"},
    {"time": "20:30-06:00", "period": "coucher/nuit", "zones": ["chambre", "couloir si errance"], "risk": "sortie de lit, errance, fugue"},
]

SCENARIO_TYPES = SIMULATION_SCENARIOS
