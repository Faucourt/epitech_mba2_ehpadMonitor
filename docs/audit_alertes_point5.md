# Point 5 - Alertes, escalade et tracabilite

Date: 2026-04-28

## Ce qui est valide

- Les 5 niveaux d'alerte existent dans `backend/alert_engine.py`.
- Chaque alerte contient: resident, chambre, zone precise, etage, position, capteurs actifs, constantes, score NEWS, risque ML, raison, action attendue.
- Les niveaux 2 et 3 notifient le soignant assigne.
- Le niveau 4 notifie tous les soignants et le chef de garde.
- Le niveau 5 ajoute la direction et l'action SAMU 15 selon protocole.
- Le niveau 5 prepare automatiquement un dossier de pre-appel SAMU simule.
- L'espace soignant `/soignant` recoit les notifications et trace les actions `Vu`, `Je prends`, `Acquitter`.
- Les actions sont historisees dans Redis par personnel et globalement.
- `Je prends` ne cloture pas l'alerte: il trace le soignant responsable et suspend l'escalade pendant 10 minutes.
- Apres `Je prends`, le bouton devient `Resolue`; cette action cloture l'alerte active et reste historisee.

## Corrections faites

- Ajout de `/api/alerts/config` pour exposer les 5 niveaux, leurs delais, leurs actions et leurs regles de routage.
- Nettoyage de l'historique: les simples mises a jour de localisation ne creent plus de lignes historiques en double.
- Resolution: une alerte resolue est historisee puis retiree de la cle active Redis.
- Realisme de l'escalade: une alerte de routine non acquittee est plafonnee au niveau 3 tant qu'il n'y a pas de signal clinique aggravant.
- Les alertes cliniques fortes, fugue, SOS, chute, NEWS eleve ou constantes critiques peuvent toujours escalader jusqu'au niveau 5.
- Workflow soignant renforce: `prise_en_charge` pose `taken_by`, `taken_at`, `escalation_paused_until`; `resolue` ferme l'alerte.
- Workflow SAMU simule: une N5 cree `samu:call:{alert_id}`, puis le personnel peut confirmer `appel_samu_simule_confirme`.

## Verification

- `docker compose up --build -d backend`: OK.
- `docker exec ehpad_backend python -m py_compile /app/main.py`: OK.
- `docker exec ehpad_backend python -m py_compile /app/alert_engine.py`: OK.
- `GET /api/alerts/config`: OK, 5 niveaux retournes.
- `GET /api/alerts`: OK, historique redevenu evenementiel.
- `GET /api/staff`: OK, assignations et notifications par soignant visibles.
- `GET /soignant`: OK.
- Test `taken`: OK, statut `prise_en_charge`, pause d'escalade 10 min.
- Test `resolved`: OK, alerte retiree des alertes actives et audit `resolue`.
- `GET /api/alerts/{resident_id}/samu-call`: garde-fou OK, refuse les alertes hors niveau 5.
- `POST /api/alerts/{resident_id}/samu-call/simulate`: pret pour confirmation humaine tracee des N5.

## Reste a ameliorer plus tard

- Ajouter un bouton dashboard "Regles alertes" qui affiche `/api/alerts/config`.
- Ajouter un export CSV/PDF de la tracabilite des acquittements.
- Ajouter un mode demo qui force une alerte de chaque niveau pour presentation jury.
