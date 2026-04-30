# Point 6 - Alertes

Date audit: 2026-04-30

## Valide

- 5 niveaux programmes via `/api/alerts/config`.
- Alertes actives exposees via `/api/alerts`.
- Chaque alerte contient le niveau, la raison, la chambre, la zone precise, l'etage, la position et les soignants notifies.
- Les capteurs actifs sont inclus dans `sensor_events` et dans les preuves `trigger_data.evidence`.
- L'explication structuree est disponible via `/api/alerts/explain/{resident_id}`.
- Le dashboard affiche les capteurs actifs, la position et les soignants notifies.
- Le panneau detail resident permet maintenant d'ouvrir l'explication structuree sans passer par Swagger.
- L'historique dashboard affiche maintenant position et capteurs.
- La fiche mobile soignant affiche maintenant les capteurs impliques dans l'alerte.
- Acquittement possible par WebSocket, avec repli REST si le WebSocket est ferme.
- Escalade automatique visible avec compte a rebours pour les alertes non acquittees.
- Les scenarios a risque ont maintenant un niveau minimal explicite:
  - malaise et chute en niveau 4;
  - chute confirmee + immobilite + constante aggravee en niveau 5;
  - lever toilettes nuit fragile, desorientation simple et sortie jardin non accompagnee en niveau 3;
  - desorientation/sortie non accompagnee avec trouble cognitif en niveau 4.
- La programmation complete est documentee dans `docs/alert_levels_escalation.md`.

## Verification

- `GET /api/alerts/config`: OK.
- `GET /api/alerts`: OK, alertes actives avec position et capteurs.
- `GET /api/alerts/explain/{resident_id}`: OK, resume professionnel + constantes + capteurs + preuves.
- `pytest tests/test_ehpad.py -k "malaise or fall_scenario or night_toilet or disorientation or unaccompanied"`: 6 tests OK.
- `pytest tests/test_ehpad.py -k "alert or scenario or fall or routine or A2A or malaise or disorientation"`: 57 tests OK.
- Suite complete: 148 tests OK.

## Reste a industrialiser

- Tests e2e navigateur sur l'acquittement depuis le dashboard et l'app mobile.
- Journalisation long terme hors Redis pour audit medico-legal.
- Parametrage des delais d'escalade par etablissement/service.
