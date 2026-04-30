# Demonstration guidee - rendu pro EHPAD

## Objectif oral

Montrer que le projet n'est pas seulement un dashboard, mais une chaine complete:

```text
simulation EHPAD -> IoT MQTT -> prediction -> alertes -> DPI -> transmission soignante
```

## 1. Demarrage

```powershell
docker compose up --build -d
docker compose ps
```

Validation:

- backend healthy;
- dashboard healthy;
- simulator healthy;
- Redis, MQTT, InfluxDB healthy.

## Identifiants a donner au jury

| Espace | URL | Identifiant | Mot de passe / token |
|---|---|---|---|
| Dashboard central | http://localhost:3002 | aucun | aucun |
| Soignant A | http://localhost:3002/soignant | `soignant_A` | voir `.env` |
| Soignant B | http://localhost:3002/soignant | `soignant_B` | voir `.env` |
| Soignant C | http://localhost:3002/soignant | `soignant_C` | voir `.env` |
| Chef de garde | http://localhost:3002/soignant | `chef_garde` | voir `.env` |
| Direction | http://localhost:3002/soignant | `direction` | voir `.env` |
| Famille Edith Piaf | http://localhost:3002/famille.html | `piaf` | voir `.env` / procedure locale |
| Famille Marie Curie | http://localhost:3002/famille.html | `curie` | voir `.env` / procedure locale |
| Admin familles | http://localhost:3002/admin_famille.html | token admin | voir `.env` |

Patients utiles pour la demo:

| Resident | Chambre | Lien direct |
|---|---:|---|
| `R005` Edith Piaf | 105 | http://localhost:3002/resident/R005 |
| `R019` Dalida | 214 | http://localhost:3002/resident/R019 |
| `R024` Michel Sardou | 219 | http://localhost:3002/resident/R024 |

## 2. Onglet Validation pro

Ouvrir:

```text
http://localhost:3002
```

Aller dans `Validation pro`.

Points a montrer:

- 25 residents, compatible objectif 20-50;
- profils de vie differencies;
- prediction ML/A2A 30-60 min;
- alertes 5 niveaux;
- capteurs vitaux + ambiants;
- capteurs avec statut, batterie et qualite signal;
- debit MQTT et cible de scalabilite;
- mini DPI et transmissions;
- axes encore a renforcer pour un niveau industriel.

Phrase possible:

> Cet onglet sert de matrice de validation. Il separe ce qui est deja implemente de ce qui resterait a industrialiser.

## 3. Vie quotidienne et scenarios

Aller dans `Grille residents`, puis ouvrir plusieurs residents.

Montrer:

- heure simulee;
- phase: nuit, repas, soin, animation, trajet;
- profil de vie;
- surveillance adaptee;
- repas en chambre ou salle a manger;
- scenario assigne.

Phrase possible:

> Les residents ne bougent pas tous pareil. Certains restent en chambre, certains vont au repas, d'autres ont un risque de fugue ou de fatigue respiratoire.

## 4. Plan 2D et 3D

Aller dans `Plan EHPAD` puis `Vue 3D`.

Montrer:

- chambres;
- salle a manger avec tables;
- ascenseur;
- escalier;
- jardin;
- sortie hors EHPAD;
- residents localises;
- capteurs visibles;
- nom au survol en 3D.

Phrase possible:

> L'alerte donne une position fonctionnelle: chambre, couloir, salle a manger, jardin ou sortie, pas seulement un numero de chambre.

## 5. Prediction malaise

Aller dans `Transmissions`, choisir un resident.

Montrer:

- risque 30 min;
- risque 60 min;
- tendance predictive;
- delta 15 min;
- actions soignantes.

Phrase possible:

> La prediction est relancee toutes les 5 minutes. La nouvelle evaluation tient compte de la tendance precedente.

## 6. Alertes

Ouvrir le panneau `Alertes`.

Montrer:

- niveau;
- raison;
- position precise;
- capteurs actifs;
- explication structuree via `/api/alerts/explain/{resident_id}`;
- acquittement.

Phrase possible:

> Les alertes sont graduees de 1 a 5, filtrees pour limiter les fausses alertes et escaladees si elles ne sont pas acquittees.

## 7. Mini DPI et transmission

Dans `Transmissions`, montrer:

- fiche globale soignants;
- mini DPI par resident;
- constantes actuelles;
- historique 30 jours;
- alertes du jour;
- points de vigilance;
- actions a faire.

Phrase possible:

> Le LLM ou la synthese agentique ne decide pas l'alerte. Il transforme les donnees en transmission lisible pour les soignants.

## 8. Scalabilite

Expliquer le calcul:

```text
20 residents x 6 constantes x 1 mesure/seconde = 120 messages/seconde
```

Ce qui est fait:

- MQTT pour le flux;
- JSON par resident dans `data/patients/Rxxx/profile.json` comme source lisible de demo;
- Redis pour l'etat courant et le cache live;
- InfluxDB pour les series capteurs/vitaux;
- JSON `history_daily.json` et `history_detailed.json` pour l'historique patient exportable;
- WebSocket limite;
- ML toutes les 5 minutes;
- LLM hors boucle seconde.
- endpoint `/api/ops/scalability` pour suivre messages/s, WebSocket et cible 120 msg/s.

## 8 bis. Scenarios de validation

Dans `Validation pro`, utiliser les boutons:

- Hypoxie R005;
- Chute couloir;
- Fugue;
- Malaise repas;
- Risque nuit;
- Jardin;
- Chute jardin;
- x30 puis x1.

Point a dire:

> Les scenarios sont declenches par le dashboard via le backend puis MQTT. Cela valide la chaine complete, pas seulement l'affichage.

Ce qui resterait a faire pour industrialiser:

- benchmark 50 residents;
- latence p95;
- monitoring capteurs hors ligne;
- retention long terme;
- calibration sur donnees reelles.

## 9. Espace famille (C3)

Ouvrir:

```text
http://localhost:3002/famille.html
```

Montrer le login avec un compte demo :

| Utilisateur | Mot de passe | Resident |
|-------------|-------------|---------|
| `curie`      | voir `.env` / procedure locale | Marie Curie - Chambre 101 |
| `coubertin`  | voir `.env` / procedure locale | Pierre de Coubertin - Chambre 104 |
| `piaf`       | voir `.env` / procedure locale | Edith Piaf - Chambre 105 |

Points a montrer :

- chaque compte donne acces a **un seul resident**;
- aucune valeur medicale affichee (FC, SpO2, TA absents);
- badge de statut : Situation stable / Sous surveillance / Surveillance renforcee;
- soignant referent et heure de derniere activite;
- token de session 24h, invalide apres deconnexion.

Phrase possible :

> La famille voit l'etat general de leur proche, pas ses constantes. La confidentialite medicale est respectee par conception, pas par une simple suppression d'affichage.

Montrer ensuite l'interface admin :

```text
http://localhost:3002/admin_famille.html
```

Token admin : voir `.env` (`FAMILLE_ADMIN_TOKEN`)

- lister les comptes existants;
- creer un nouveau compte pour un resident;
- supprimer un compte.

## 10. Validation finale

Commandes utiles:

```powershell
Invoke-RestMethod http://localhost:8001/health
Invoke-RestMethod http://localhost:8001/api/project/readiness
Invoke-RestMethod http://localhost:8001/api/a2a/predictions
Invoke-RestMethod http://localhost:8001/api/reports/today
```
