# Programmation des niveaux d'alerte et escalade

Cette note decrit la logique appliquee par `backend/alert_engine.py`.
Le projet reste un prototype de surveillance et d'aide a la decision: les niveaux
servent a prioriser l'intervention humaine, pas a poser un diagnostic medical.

## Echelle des niveaux

| Niveau | Nom | Objectif | Escalade automatique |
|---:|---|---|---|
| 1 | Info | Signal faible, surveillance simple | Aucune |
| 2 | Attention | Anomalie legere ou routine suspecte | Vers niveau 3 apres 10 min non acquitte |
| 3 | Alerte | Probleme clinique a verifier rapidement | Vers niveau 4 apres 5 min non acquitte |
| 4 | Urgence | Intervention soignant rapide | Vers niveau 5 apres 3 min non acquitte |
| 5 | Danger vital | Situation critique objectivable | Aucune |

Les niveaux 2 et 3 passent par un filtre anti-bruit: le signal doit persister
avant creation de l'alerte. Les niveaux 4 et 5 sont immediats.

## Regles principales

| Evenement | Niveau minimal | Justification |
|---|---:|---|
| Inactivite simple hors sommeil | 1 | Surveillance, pas urgence seule |
| Constante legerement hors norme | 2 | Attention clinique |
| Routine suspecte moderee | 2 | Signal comportemental a suivre |
| Errance nuit fragile | 2 a 3 | Risque accru selon fragilite |
| Lever toilettes nuit fragile | 3 | Risque de chute nocturne |
| Desorientation | 3 | Risque de perte de repere et chute |
| Desorientation Alzheimer en zone sensible | 4 | Risque de securite immediat |
| Sortie jardin non accompagnee | 3 | Surveillance renforcee |
| Sortie jardin non accompagnee avec trouble cognitif | 4 | Risque de fugue ou mise en danger |
| Fatigue clinique apres effort ou soin | 3 si fragilite/NEWS/IA | Risque d'aggravation |
| Hypotension marquee | 3 | Risque de malaise/chute |
| Tachycardie marquee | 3 | Alerte cardio |
| Fievre elevee | 3 | Alerte clinique |
| Malaise repas ou retour repas | 4 | Risque de chute ou immobilite |
| Chute scenario ou capteur | 4 | Intervention rapide |
| Chute confirmee + immobilite + constante aggravee | 5 | Suspicion chute compliquee ou malaise associe |
| SOS resident | 4 | Appel volontaire immediat |
| Fugue hors EHPAD | 4 | Securite immediate |
| Constantes dangereuses | 4 | Urgence clinique |
| Constantes critiques / NEWS tres eleve | 5 | Danger vital objectivable |
| Immobilite longue + constantes critiques | 5 | Suspicion malaise/chute grave |

## Scenarios forces par le moteur

### Niveau 4 direct

- `malaise_salle_manger`
- `malaise_retour_repas`
- `malaise_repas`
- `chute_couloir`
- `chute_chambre`
- `chute_jardin`
- `chute_trajet_repas`
- `chute_salle_bain`
- `fugue_hors_ehpad`
- `sortie_jardin_non_accompagnee` si pathologie cognitive
- `desorientation_ascenseur` / `desorientation_patio` si trouble cognitif ou zone sensible

### Niveau 3 direct

- `aller_toilettes_nuit` si resident fragile
- `desorientation_ascenseur`
- `desorientation_avant_repas`
- `desorientation_patio`
- `sortie_jardin_non_accompagnee` sans trouble cognitif
- `retour_kine_fatigue`, `toilette_matinale_fatigue`,
  `regroupement_patio_fatigue`, `retour_jardin_fatigue` si fragilite,
  NEWS ou risque IA associe

## Escalade

Une alerte non acquittee monte automatiquement si elle reste active:

- Niveau 2 vers 3 apres 10 minutes.
- Niveau 3 vers 4 apres 5 minutes.
- Niveau 4 vers 5 apres 3 minutes.

Une prise en charge par un soignant suspend temporairement l'escalade. Une alerte
clinique non vue reste visible tant qu'elle n'est pas acquittee, prise en charge
ou resolue.

## Position soutenance

Phrase courte:

> Les niveaux combinent gravite actuelle et risque d'evolution. Un malaise est
> classe en urgence niveau 4 car il peut induire une chute ou une immobilite. Le
> niveau 5 reste reserve aux dangers vitaux objectivables par les constantes, le
> NEWS, une chute confirmee avec immobilite et constante aggravee, ou une
> aggravation non prise en charge.
