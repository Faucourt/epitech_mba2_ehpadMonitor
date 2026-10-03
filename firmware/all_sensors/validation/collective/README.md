# Essais collectifs Wokwi — trois résidents et vingt zones

## Mise à jour du 3 octobre 2026

Un essai CLI ultérieur a vérifié les 23 cartes simultanément : 214 capteurs
communicants, dont 203 avec une mesure récente, pendant 60,9 secondes de
couverture complète. Voir [la preuve CLI](cli-recovery-2026-10-03.json).
Les mentions ci-dessous d'un jeton absent et d'un essai CLI restant à faire
décrivent la livraison initiale. Le quota CI a ensuite été épuisé : cette preuve
ne garantit pas une acquisition actuelle. Le mode navigateur couvre seulement
R001–R003 et l'entrée. Voir [le fonctionnement actuel](../../COLLECTIVE.md).

**23 projets ESP32 / 214 capteurs indépendants.** Tous les champs prévus ont été
observés dans les trames UART de ces projets, avec réception des identifiants
vérifiée dans le backend local. Les zones ont été testées successivement.

Une observation séparée a vérifié les **42 capteurs des trois résidents et de
l’entrée simultanément pendant 119 secondes**. Elle ne valide pas 23 cartes
ou 437 capteurs en fonctionnement continu. Les interruptions de Firefox et les
redémarrages observés ne sont pas masqués ; les anciennes mesures expirent.

Les mesures de tension résultent du bouton START. Les essais de badges utilisent
Hold ; les deux lecteurs de l’entrée ont lu respectivement `01020304` et
`11223344`. Les essais prolongés attendent la stabilisation de l’indice COV.
Une valeur obtenue pendant un essai ne signifie pas qu’elle est encore récente.

## Projets et preuves

Chaque ligne possède un compte rendu JSON et sa trace série JSONL. Le compte
rendu distingue les champs observés pendant l’essai de la communication reçue
au contrôle final. Les empreintes relient les preuves au firmware compilé et
aux sources ; les empreintes textuelles normalisent les fins de ligne Windows/Linux.

| Entité | Capteurs | Projet Wokwi | Compte rendu | Trace UART |
|---|---:|---|---|---|
| Marie Curie (`R001`) | 11 | [Ouvrir](https://wokwi.com/projects/476811018920338433) | [JSON](R001.json) | [JSONL](R001.jsonl) |
| Louis Pasteur (`R002`) | 10 | [Ouvrir](https://wokwi.com/projects/476810814842254337) | [JSON](R002.json) | [JSONL](R002.jsonl) |
| Simone Veil (`R003`) | 11 | [Ouvrir](https://wokwi.com/projects/476812231957251073) | [JSON](R003.json) | [JSONL](R003.jsonl) |
| Entree / Accueil (`entree`) | 10 | [Ouvrir](https://wokwi.com/projects/476813411149295617) | [JSON](entree.json) | [JSONL](entree.jsonl) |
| Sortie hors EHPAD (`hors_ehpad`) | 8 | [Ouvrir](https://wokwi.com/projects/476811536858225665) | [JSON](hors_ehpad.json) | [JSONL](hors_ehpad.jsonl) |
| Infirmerie (`infirmerie_rdc`) | 7 | [Ouvrir](https://wokwi.com/projects/476811645982496769) | [JSON](infirmerie_rdc.json) | [JSONL](infirmerie_rdc.jsonl) |
| Pharmacie / Admin (`pharmacie_admin`) | 7 | [Ouvrir](https://wokwi.com/projects/476811754112711681) | [JSON](pharmacie_admin.json) | [JSONL](pharmacie_admin.jsonl) |
| Couloir principal (`couloir_principal`) | 9 | [Ouvrir](https://wokwi.com/projects/476811865720014849) | [JSON](couloir_principal.json) | [JSONL](couloir_principal.jsonl) |
| Salle commune / TV (`salle_commune`) | 8 | [Ouvrir](https://wokwi.com/projects/476811973341673473) | [JSON](salle_commune.json) | [JSONL](salle_commune.jsonl) |
| Patio couvert (`patio`) | 12 | [Ouvrir](https://wokwi.com/projects/476812092031057921) | [JSON](patio.json) | [JSONL](patio.jsonl) |
| Jardin therapeutique (`jardin`) | 10 | [Ouvrir](https://wokwi.com/projects/476812205238482945) | [JSON](jardin.json) | [JSONL](jardin.jsonl) |
| Salle d'activites (`salle_activites`) | 8 | [Ouvrir](https://wokwi.com/projects/476812311646939137) | [JSON](salle_activites.json) | [JSONL](salle_activites.jsonl) |
| Salle a manger (`salle_manger`) | 9 | [Ouvrir](https://wokwi.com/projects/476812418387794945) | [JSON](salle_manger.json) | [JSONL](salle_manger.jsonl) |
| Office / Cuisine (`office_cuisine`) | 8 | [Ouvrir](https://wokwi.com/projects/476812525602607105) | [JSON](office_cuisine.json) | [JSONL](office_cuisine.jsonl) |
| Couloir Aile RDC (`couloir_aile_rdc`) | 9 | [Ouvrir](https://wokwi.com/projects/476812638260579329) | [JSON](couloir_aile_rdc.json) | [JSONL](couloir_aile_rdc.jsonl) |
| Escalier securise (`escalier`) | 9 | [Ouvrir](https://wokwi.com/projects/476812746600517633) | [JSON](escalier.json) | [JSONL](escalier.jsonl) |
| Ascenseur (`ascenseur`) | 9 | [Ouvrir](https://wokwi.com/projects/476812886454362113) | [JSON](ascenseur.json) | [JSONL](ascenseur.jsonl) |
| Poste infirmier (`poste_infirmier_etage`) | 7 | [Ouvrir](https://wokwi.com/projects/476813021704952833) | [JSON](poste_infirmier_etage.json) | [JSONL](poste_infirmier_etage.jsonl) |
| Kinesitherapie (`kinesitherapie`) | 16 | [Ouvrir](https://wokwi.com/projects/476813146364931073) | [JSON](kinesitherapie.json) | [JSONL](kinesitherapie.jsonl) |
| Salle de repos (`salle_repos`) | 8 | [Ouvrir](https://wokwi.com/projects/476813391206425601) | [JSON](salle_repos.json) | [JSONL](salle_repos.jsonl) |
| Couloir Aile A (`couloir_aile_a_etage`) | 9 | [Ouvrir](https://wokwi.com/projects/476813516353990657) | [JSON](couloir_aile_a_etage.json) | [JSONL](couloir_aile_a_etage.jsonl) |
| Couloir Aile B (`couloir_aile_b_etage`) | 9 | [Ouvrir](https://wokwi.com/projects/476813650362019841) | [JSON](couloir_aile_b_etage.json) | [JSONL](couloir_aile_b_etage.jsonl) |
| Palier escalier / ascenseur (`palier_etage`) | 10 | [Ouvrir](https://wokwi.com/projects/476815009189781505) | [JSON](palier_etage.json) | [JSONL](palier_etage.jsonl) |

[Observation simultanée des quatre cartes](simultaneous-observation.json)
et [trames correspondantes](simultaneous-observation.jsonl).

## Reproduire

Ouvrir un lien Wokwi puis lancer la simulation permet de voir le montage et les
trames `SAMPLE` dans le moniteur série. **Ouvrir le lien seul ne raccorde pas ce
nouveau navigateur au dashboard local.** Les essais ci-dessus utilisaient une
passerelle de test Firefox → UART → MQTT ; aucune valeur MQTT de remplacement
n’a été fabriquée. Le lanceur livré fournit la passerelle via Wokwi CLI :

```powershell
python firmware/all_sensors/tools/summarize_collective_validation.py
./firmware/all_sensors/Start-Collective.ps1 -Pilot -Seconds 120
```

La première commande contrôle les preuves archivées sans lancer Wokwi.
La seconde nécessite Docker, les firmwares compilés et le jeton personnel
`WOKWI_CLI_TOKEN`. Voir [COLLECTIVE.md](../../COLLECTIVE.md). Le jeton manquait
lors de cette livraison : l’essai CLI simultané des 23 cartes reste à faire.

## Périmètre restant

Voir les [limites observées pendant les essais prolongés](LIMITES_EXECUTION.md),
notamment les interruptions de Firefox et une anomalie de lecture optique R001.

- 27/45 cartes collectives compilées localement, dont les 23 du pilote.
- Les 22 autres résidents ne sont pas inclus dans ces essais collectifs.
- Le fonctionnement continu des vingt zones ensemble reste à vérifier avec le lanceur.
- Les huit vues du dashboard sont accessibles ; la localisation, le sommeil et
  le risque clinique ne sont pas déduits automatiquement de ces signaux partiels.
- Aucun essai matériel physique, radio BLE ou validation clinique. Aucune nouvelle vidéo.
