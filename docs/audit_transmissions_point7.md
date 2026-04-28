# Point 7 - Mini DPI et transmission

Date audit: 2026-04-28

## Valide

- Onglet `Transmissions` present dans le dashboard.
- Fiche globale soignants disponible via `/api/reports/today` et `/api/reports/daily/{date}`.
- Regeneration manuelle possible via `/api/reports/daily/generate`.
- Rapport quotidien automatise au demarrage de chaque jour via `daily_report_loop`.
- Mini DPI par resident disponible via `/api/residents/{resident_id}/dpi`.
- Acces mini DPI securise par session soignant, avec bris de glace si resident non assigne.
- La fiche globale affiche maintenant position, routine, niveau, risque actuel, risque 30/60 min, alertes du jour, historique 30 jours, points de vigilance et actions.
- Le mini DPI dashboard affiche constantes, profil, risque actuel, prediction A2A 30/60 min, tendance, alertes du jour, evenements 30 jours, points de vigilance, actions et rapport LLM.
- La page patient dediee affiche maintenant correctement `watch_points` et `next_actions` dans la transmission.
- Les rapports LLM quotidiens restent separes : ils synthetisent, mais ne decident pas les alertes.

## Verification

- `GET /api/reports/today`: OK, champs `risk_30min`, `risk_60min`, `alerts_today`, `history_30d_count`, `actions`.
- `GET /api/residents/R005/dpi?date=2026-04-28` avec `chef_garde`: OK, `watch_points` et `next_actions` presents.
- Dashboard `/`: OK, colonnes 30/60 min et actions presentes.
- Page patient `/resident/R005`: OK, section actions soignantes presente.

## Reste a industrialiser

- Signature electronique des transmissions.
- Export PDF horodate par equipe.
- Archivage long terme hors Redis pour valeur probante.
- Workflow IDE/AS distinct si l'etablissement impose des circuits differencies.
