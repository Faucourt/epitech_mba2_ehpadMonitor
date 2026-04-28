# Securite et RGPD - projet EHPAD

Ce document decrit le cadre implemente dans la maquette. Il ne remplace pas une homologation SSI/RGPD reelle, mais fixe les controles attendus pour un rendu professionnel.

## Sessions et roles

- Les familles utilisent un token Redis valable 24 h.
- Le personnel utilise un token signe HMAC, stocke cote Redis, valable 8 h.
- Les actions sensibles du personnel exigent `Authorization: Bearer <token>`.
- Les roles privilegies (`chef_garde`, `direction`, `medecin`, `admin`) peuvent consulter l'ensemble des residents.
- Un soignant standard ne peut consulter que les residents dont il est referent, sauf bris de glace.

## Bris de glace

Si un soignant ouvre le DPI d'un resident non assigne, l'API refuse l'acces sauf si :

- une alerte active de niveau 3 ou plus existe pour ce resident ;
- le soignant fournit une justification `X-Break-Glass-Reason` ;
- la justification fait au moins 8 caracteres.

Chaque ouverture est journalisee dans `security:access_log`, et les bris de glace sont aussi copies dans `security:break_glass`.

## Journalisation

Sont traces :

- consultation DPI, historique, routine, prediction IA ;
- actions notification : vu, prise en charge, acquittement, resolution ;
- appels SAMU simules ;
- echecs de connexion personnel ;
- bris de glace.

Les journaux securite sont consultables par chef/direction via :

- `GET /api/security/policy`
- `GET /api/security/access-logs`
- `GET /api/security/break-glass`

## Secrets

Les secrets ne doivent pas rester en dur en production. Copier `.env.example` vers `.env`, puis remplacer :

- `REDIS_PASSWORD`
- `SESSION_SECRET`
- `STAFF_DEMO_PASSWORD`
- `FAMILLE_ADMIN_TOKEN`
- `INFLUX_INIT_PASSWORD`
- `INFLUX_TOKEN`

Le `docker-compose.yml` lit ces variables et protege Redis avec `--requirepass`.

## HTTPS et CORS

- `ALLOWED_ORIGINS` limite les origines autorisees par CORS.
- `HTTPS_REQUIRED=true` impose HTTPS hors localhost.
- En production, placer le dashboard/API derriere un reverse proxy TLS (Nginx, Traefik, Caddy) avec certificat valide.

## Limitation brute force

Les endpoints login famille et personnel sont limites a `5/minute` par IP avec SlowAPI.

## Retention

Parametres applicables :

- `RETENTION_ACCESS_LOG_DAYS` : journaux d'acces DPI et bris de glace.
- `RETENTION_AUDIT_DAYS` : duree cible des audits notification.
- `LLM_DAILY_TTL_DAYS` : conservation des rapports LLM quotidiens.

Pour un deploiement reel, ajouter une tache planifiee qui purge aussi les donnees InfluxDB selon la politique d'etablissement.

## Limites de la maquette

- Pas d'IAM/e-CPS reelle : comptes demo internes.
- Pas de chiffrement applicatif champ par champ.
- Pas de coffre de secrets : utiliser au minimum `.env` hors Git, idealement un secret manager.
- Pas encore de reverse proxy TLS fourni.
- Les donnees sont simulees, mais doivent etre traitees comme des donnees sensibles pendant la demonstration.
