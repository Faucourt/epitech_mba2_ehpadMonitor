# Point 9 - Espace famille

Date audit: 2026-04-28

## Valide

- Interface famille disponible sur `/famille.html`.
- Login individuel par compte famille, token Redis 24h.
- Chaque compte donne acces uniquement au resident associe.
- Acces a un autre resident refuse en 403.
- La vue famille ne renvoie pas de constantes medicales (`FC`, `SpO2`, `PA`, temperature, scores cliniques, alertes brutes).
- L'API renvoie maintenant un champ `privacy_scope` pour expliciter ce qui est visible et masque.
- La vue famille reste disponible meme si l'etat live Redis du resident n'est pas encore present, grace au fallback `_safe_state_for_report`.
- Interface sous forme de carnet/livre avec onglets : resume, aujourd'hui, semaine, photos.
- Menu du jour, activites prevues, activites realisees et programme semaine affiches.
- Album photos d'activites accessible via `/album_activites.html`.
- Admin comptes famille disponible sur `/admin_famille.html` avec token admin.
- Creation, liste et suppression de comptes famille disponibles cote API.

## Verification

- `POST /api/famille/login` avec un compte famille de demonstration: OK.
- `GET /api/famille/R005` avec token Piaf: OK.
- Champs medicaux absents: `vitals`, `heart_rate`, `spo2` absents.
- `GET /api/famille/R002` avec token Curie: 403 attendu.
- `GET /api/admin/famille/accounts`: OK avec token admin.
- `/famille.html`: OK, livre + encart confidentialite.
- `/album_activites.html`: OK.

## Attention tests

- Le login famille est volontairement rate limite a `5/minute` par IP.
- Les tests automatises qui martelent `/api/famille/login` peuvent recevoir `429`.
- Pour une CI propre, isoler le rate limiter ou utiliser un client/IP de test separe.

## Reste a industrialiser

- Authentification IAM/e-CPS ou compte famille provisionne par annuaire.
- Double facteur pour les familles.
- Consentement resident/famille et journal d'acces consultable.
- Moderation/validation des photos avant publication famille.
