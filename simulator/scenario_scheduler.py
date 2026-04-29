"""Scenario scheduler for the EHPAD simulator.

Each tick represents roughly one simulated minute. The scheduler keeps events
plausible by combining resident profile, simulated period, cooldowns and daily
limits before it allows a scenario to start.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional


VITAL_SCENARIOS = {"hypoxie", "tachycardie", "chute", "hypotension", "fievre"}


SCENARIO_RULES = {
    "hypoxie": {
        "kind": "vital",
        "base_rate": 0.00006,
        "pathologies": {"bpco": 5.0, "insuffisance_cardiaque": 2.0},
        "mobility": {"faible": 1.2, "tres_faible": 1.4},
        "periods": {"nuit": 1.8, "animation_matin": 1.7, "animation_apres_midi": 1.7, "trajet_dejeuner": 1.4, "trajet_diner": 1.4},
        "cooldown_min": 720,
        "max_per_day": 1,
    },
    "tachycardie": {
        "kind": "vital",
        "base_rate": 0.00005,
        "pathologies": {"insuffisance_cardiaque": 3.0, "hypertension": 1.8},
        "periods": {"animation_matin": 1.6, "animation_apres_midi": 1.5, "trajet_dejeuner": 1.4, "trajet_diner": 1.4},
        "cooldown_min": 540,
        "max_per_day": 1,
    },
    "chute": {
        "kind": "vital",
        "base_rate": 0.000035,
        "mobility": {"faible": 2.2, "tres_faible": 3.5},
        "periods": {"lever_toilette": 2.8, "coucher": 2.4, "nuit": 1.8, "trajet_dejeuner": 1.6, "trajet_diner": 1.6},
        "cooldown_min": 1440,
        "max_per_day": 1,
    },
    "hypotension": {
        "kind": "vital",
        "base_rate": 0.000055,
        "pathologies": {"insuffisance_cardiaque": 1.8, "diabete": 1.4},
        "mobility": {"faible": 1.5, "tres_faible": 1.9},
        "periods": {"lever_toilette": 3.0, "trajet_dejeuner": 1.8, "dejeuner": 1.7, "trajet_diner": 1.8, "diner": 1.7},
        "cooldown_min": 720,
        "max_per_day": 1,
    },
    "fievre": {
        "kind": "vital",
        "base_rate": 0.000025,
        "pathologies": {"diabete": 1.4, "bpco": 1.4},
        "periods": {"nuit": 1.3, "soiree": 1.2},
        "cooldown_min": 1440,
        "max_per_day": 1,
    },
    "chute_couloir": {"kind": "movement", "base_rate": 0.00011, "mobility": {"faible": 2.0, "tres_faible": 2.8}, "periods": {"trajet_dejeuner": 2.2, "trajet_diner": 2.2, "lever_toilette": 1.7}, "cooldown_min": 900, "max_per_day": 1},
    "chute_chambre": {"kind": "movement", "base_rate": 0.00012, "mobility": {"faible": 1.8, "tres_faible": 3.2}, "periods": {"lever_toilette": 3.0, "coucher": 2.5, "nuit": 2.0}, "cooldown_min": 900, "max_per_day": 1},
    "malaise_salle_manger": {"kind": "movement", "base_rate": 0.00012, "pathologies": {"diabete": 2.2, "insuffisance_cardiaque": 1.8}, "periods": {"dejeuner": 3.0, "diner": 3.0, "petit_dej": 1.8}, "cooldown_min": 720, "max_per_day": 1},
    "errance_nuit": {"kind": "movement", "base_rate": 0.00012, "pathologies": {"alzheimer": 4.5, "demence": 4.0}, "periods": {"nuit": 4.0, "coucher": 2.0}, "cooldown_min": 720, "max_per_day": 1},
    "sortie_patio": {"kind": "movement", "base_rate": 0.00008, "mobility": {"bonne": 1.6, "moyenne": 1.2}, "periods": {"animation_matin": 2.0, "animation_apres_midi": 2.4, "soiree": 1.2}, "cooldown_min": 480, "max_per_day": 2},
    "immobilite_salle_repos": {"kind": "movement", "base_rate": 0.00008, "mobility": {"faible": 1.5, "tres_faible": 2.0}, "periods": {"sieste": 2.2, "animation_apres_midi": 1.5}, "cooldown_min": 720, "max_per_day": 1},
    "aller_toilettes_nuit": {"kind": "movement", "base_rate": 0.00010, "mobility": {"faible": 1.5, "tres_faible": 2.0}, "periods": {"nuit": 4.0, "coucher": 1.6}, "cooldown_min": 540, "max_per_day": 1},
    "desorientation_ascenseur": {"kind": "movement", "base_rate": 0.00008, "pathologies": {"alzheimer": 2.6, "demence": 2.4}, "periods": {"trajet_dejeuner": 2.0, "trajet_diner": 2.0, "animation_matin": 1.5}, "cooldown_min": 720, "max_per_day": 1},
    "agitation_couloir": {"kind": "movement", "base_rate": 0.00007, "pathologies": {"alzheimer": 2.0, "demence": 2.0}, "periods": {"soiree": 2.0, "nuit": 1.6}, "cooldown_min": 720, "max_per_day": 1},
    "isolement_chambre": {"kind": "movement", "base_rate": 0.00009, "mobility": {"tres_faible": 2.0, "faible": 1.4}, "periods": {"sieste": 1.8, "animation_matin": 1.4, "animation_apres_midi": 1.4}, "cooldown_min": 720, "max_per_day": 1},
    "retour_kine_fatigue": {"kind": "movement", "base_rate": 0.00009, "pathologies": {"bpco": 2.2, "insuffisance_cardiaque": 2.0}, "periods": {"soins_matin": 2.2, "animation_matin": 1.5, "animation_apres_midi": 1.5}, "cooldown_min": 720, "max_per_day": 1},
    "promenade_jardin": {"kind": "movement", "base_rate": 0.00007, "mobility": {"bonne": 2.2, "moyenne": 1.4}, "periods": {"animation_matin": 2.0, "animation_apres_midi": 2.6}, "cooldown_min": 360, "max_per_day": 2},
    "sortie_jardin_non_accompagnee": {"kind": "movement", "base_rate": 0.00007, "pathologies": {"alzheimer": 2.2, "demence": 2.0}, "periods": {"animation_apres_midi": 2.2, "soiree": 1.4}, "cooldown_min": 720, "max_per_day": 1},
    "chute_jardin": {"kind": "movement", "base_rate": 0.00006, "mobility": {"faible": 1.8, "tres_faible": 2.4}, "periods": {"animation_matin": 1.6, "animation_apres_midi": 2.4}, "cooldown_min": 1440, "max_per_day": 1},
    "fugue_hors_ehpad": {"kind": "movement", "base_rate": 0.000045, "pathologies": {"alzheimer": 6.0, "demence": 5.0}, "periods": {"soiree": 2.5, "nuit": 3.5}, "cooldown_min": 1440, "max_per_day": 1},
    "chute_trajet_repas": {"kind": "movement", "base_rate": 0.00011, "mobility": {"faible": 2.0, "tres_faible": 2.7}, "periods": {"trajet_dejeuner": 3.2, "trajet_diner": 3.2}, "cooldown_min": 900, "max_per_day": 1},
    "desorientation_avant_repas": {"kind": "movement", "base_rate": 0.00008, "pathologies": {"alzheimer": 2.2, "demence": 2.0}, "periods": {"trajet_dejeuner": 2.6, "trajet_diner": 2.6}, "cooldown_min": 720, "max_per_day": 1},
    "malaise_retour_repas": {"kind": "movement", "base_rate": 0.00010, "pathologies": {"diabete": 2.0, "insuffisance_cardiaque": 1.8, "bpco": 1.4}, "periods": {"trajet_dejeuner": 2.8, "trajet_diner": 2.8, "dejeuner": 1.5, "diner": 1.5}, "cooldown_min": 720, "max_per_day": 1},
    "malaise_repas": {"kind": "alias", "target": "malaise_salle_manger"},
    "chute_salle_bain": {"kind": "movement", "base_rate": 0.00010, "mobility": {"faible": 2.0, "tres_faible": 2.8}, "periods": {"lever_toilette": 3.5, "coucher": 1.8}, "cooldown_min": 900, "max_per_day": 1},
    "toilette_matinale_fatigue": {"kind": "movement", "base_rate": 0.00010, "mobility": {"faible": 1.5, "tres_faible": 2.0}, "pathologies": {"bpco": 1.6, "insuffisance_cardiaque": 1.4}, "periods": {"lever_toilette": 4.0}, "cooldown_min": 720, "max_per_day": 1},
    "desorientation_patio": {"kind": "movement", "base_rate": 0.00007, "pathologies": {"alzheimer": 2.4, "demence": 2.2}, "periods": {"animation_matin": 1.8, "animation_apres_midi": 2.5}, "cooldown_min": 720, "max_per_day": 1},
    "regroupement_patio_fatigue": {"kind": "movement", "base_rate": 0.00007, "pathologies": {"bpco": 2.0, "insuffisance_cardiaque": 1.8}, "periods": {"animation_apres_midi": 2.8, "gouter": 1.6}, "cooldown_min": 720, "max_per_day": 1},
    "retour_jardin_fatigue": {"kind": "movement", "base_rate": 0.00007, "pathologies": {"bpco": 2.2, "insuffisance_cardiaque": 1.8}, "periods": {"animation_apres_midi": 2.8}, "cooldown_min": 720, "max_per_day": 1},
    "risque_nuit": {"kind": "alias", "target": "aller_toilettes_nuit"},
    "jardin": {"kind": "alias", "target": "promenade_jardin"},
}


@dataclass
class ScenarioScheduler:
    last_started: dict[str, int] = field(default_factory=dict)
    daily_counts: dict[tuple[int, str], int] = field(default_factory=dict)

    def register_forced(self, scenario: str, tick: int) -> None:
        scenario = resolve_alias(scenario)
        if self.last_started.get(scenario) == tick:
            return
        self.last_started[scenario] = tick
        day = tick // 1440
        self.daily_counts[(day, scenario)] = self.daily_counts.get((day, scenario), 0) + 1

    def choose(self, resident: dict, candidates: list[str], period: str, tick: int, kind: Optional[str] = None) -> Optional[str]:
        weighted: list[tuple[str, float]] = []
        for scenario in candidates:
            scenario = resolve_alias(scenario)
            rule = SCENARIO_RULES.get(scenario)
            if not rule or rule.get("kind") == "alias":
                continue
            if kind and rule.get("kind") != kind:
                continue
            weight = self.weight_for(resident, scenario, period, tick)
            if weight > 0:
                weighted.append((scenario, weight))

        total = sum(weight for _, weight in weighted)
        if total <= 0:
            return None
        if random.random() >= min(total, 0.025):
            return None
        pick = random.uniform(0, total)
        cursor = 0.0
        for scenario, weight in weighted:
            cursor += weight
            if pick <= cursor:
                self.register_forced(scenario, tick)
                return scenario
        return None

    def weight_for(self, resident: dict, scenario: str, period: str, tick: int) -> float:
        rule = SCENARIO_RULES.get(scenario)
        if not rule or rule.get("kind") == "alias":
            return 0.0

        day = tick // 1440
        if self.daily_counts.get((day, scenario), 0) >= int(rule.get("max_per_day", 99)):
            return 0.0
        last = self.last_started.get(scenario)
        if last is not None and tick - last < int(rule.get("cooldown_min", 0)):
            return 0.0

        risk = max(0.02, min(1.0, float(resident.get("risk_factor", 0.3))))
        weight = float(rule.get("base_rate", 0.0)) * (0.35 + risk * 1.65)

        for pathology in resident.get("pathologies", []) or []:
            weight *= float(rule.get("pathologies", {}).get(pathology, 1.0))
        weight *= float(rule.get("mobility", {}).get(resident.get("mobility"), 1.0))
        weight *= float(rule.get("periods", {}).get(period, 0.35))

        if last is not None:
            cooldown = max(1, int(rule.get("cooldown_min", 1)))
            elapsed = tick - last
            weight *= min(1.0, elapsed / (cooldown * 2))
        return weight


def resolve_alias(scenario: str) -> str:
    rule = SCENARIO_RULES.get(scenario)
    if rule and rule.get("kind") == "alias":
        return str(rule["target"])
    return scenario
