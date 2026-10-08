# TP M1 - Mesures phyphox

Usage pedagogique uniquement, sans finalite diagnostique. Date : 2026-10-08.
Equipe : yves (choix explicite de l'utilisateur). Pseudonyme : s01.
Aucune table de correspondance personnelle dans le depot.

## Materiel et conditions

- Samsung SM-S721B ; Android 16 ; phyphox 1.2.1 (build 1020105).
- Experience : Acceleration avec g. Accelerometre LSM6DSVTR (STM).
- Export CSV : virgule et point decimal ; secondes et m/s2.
- Position confirmee pour les cinq activites portees : poche droite, vertical,
  haut vers le sol, ecran vers l'exterieur. Trois cycles assis/debout confirmes.
- Chutes : position lache ; consigne donnee : coque, coussin sur lit, environ
  50 cm. Conditions physiques non verifiees a distance.
- CSV copies sans modification depuis les ZIP ; empreintes et provenance dans
  ../../processed/phyphox/qualite.json. Metadonnees originales dans meta/.
- meta/<enregistrement>/time.csv fournit le vrai debut de mesure. L'heure dans
  le nom du ZIP est celle de l'export, pas celle du debut de la mesure.

## Annotations estimees et limites

TOUTES les annotations labels.csv sont estimees a partir des signaux et des
activites declarees, a la demande de l'utilisateur. Ce ne sont pas des temps
notes au chronometre. Les secondes correspondent a la colonne Time (s).
Les bornes sont approximatives, non exhaustives, a confirmer avant apprentissage.
Les fenetres impact incluent les rebonds et la stabilisation. Les trois cycles
assis/debout sont reperes par les changements d'orientation des axes.

Ecarts a la consigne :
- yves remplace eqNN a la demande de l'utilisateur. Faire accepter cette
  derogation ou renommer les fichiers pour une conformite stricte.
- poche-droite precise la position declaree, sans supposer une poche avant.
- Chute r01 : environ 9 s d'immobilite apres les rebonds au lieu des 10 s
  demandees. Remplacee pour le livrable par r03 ; conservee pour la tracabilite.
- Chute r02 : environ 10 s d'immobilite.
- Annotations estimees au lieu d'horaires observes au chronometre.
- Pas de validation de chute humaine ni de validation clinique.
- Plage capteur declaree : 78.4532 m/s2 par axe (environ 8 g). Des valeurs
  atteignent plus de 99 % de cette limite lors des trois chutes : ecretage
  probable. La norme mesuree peut depasser 8 g en combinant plusieurs axes,
  sans que cela exclue une saturation par axe. Les pics ne sont pas une mesure
  fiable de la force d'impact et peuvent sous-estimer les maxima reels.
- Marche : frequence dominante de la norme de 1.5 Hz, compatible avec le TP.
  Estimation FFT sur 1-29 s, interpolation a 50 Hz et fenetre de Hann,
  recherche entre 0.5 et 3 Hz. Ce n'est pas un comptage valide des pas.

## Qualite mesuree

| Fichier | Duree (s) | Frequence (Hz) | Norme max (g) |
|---|---:|---:|---:|
| 20261008_yves_s01_debout_poche-droite_r01.csv | 20.006 | 502.45 | 1.0606 |
| 20261008_yves_s01_marche_poche-droite_r01.csv | 29.998 | 499.4 | 1.7003 |
| 20261008_yves_s01_assis-debout_poche-droite_r01.csv | 30.001 | 499.14 | 1.2132 |
| 20261008_yves_s01_assis_poche-droite_r01.csv | 20.002 | 499.71 | 1.0034 |
| 20261008_yves_s01_allonge_poche-droite_r01.csv | 20.001 | 500.26 | 1.3511 |
| 20261008_yves_s01_chute-objet_lache_r01.csv | 15.002 | 499.93 | 8.3726 |
| 20261008_yves_s01_chute-objet_lache_r02.csv | 15.006 | 498.99 | 11.6803 |
| 20261008_yves_s01_chute-objet_lache_r03.csv | 15.001 | 499.26 | 8.7718 |

## Analyse reproductible

Depuis la racine du depot :

```powershell
python -m pip install pandas matplotlib numpy
python scripts/lire_phyphox.py data/raw/phyphox/20261008_yves_s01_chute-objet_lache_r02.csv
python scripts/verifier_tp_phyphox.py
```

Figures dans docs/figures/phyphox/, jamais dans data/raw/.
Le compteur au-dessus de 2.5 g compte des echantillons, pas des chutes.
Le script rejette les temps non croissants et les valeurs non finies/manquantes.

## Complements facultatifs

Non realises : gyroscope, comparaison poche/poignet, comparaison chute/assise
brusque. time.csv conserve pour une future synchronisation.
Une eventuelle table de correspondance reste chez l'intervenant, hors du depot.

## Nouvel essai de chute r03

Debut reel : 2026-10-08 22:49:50.304 UTC+02:00 (meta/time.csv).
Export : 22:50:09. Duree : 15.001 s ; frequence : 499.26 Hz.
Impact maximal vers 2.070 s ; norme maximale : 8.772 g.
Signal stable autour de 1 g de 3 a 15 s : environ 12 s de repos.
Essais retenus pour le livrable : r02 et r03. r01 conserve comme
essai supplementaire avec repos trop court ; il ne reste plus a refaire.
Huit CSV au total, avec leurs huit figures. Annotations r03 estimees
a partir du signal, comme les autres ; bornes approximatives.

## Bilan des points de controle du TP

- [x] Huit CSV reels conserves, dont les deux chutes retenues r02/r03 et allonge.
- [x] Repos debout et assis : medianes proches de 1 g.
- [x] Marche : oscillation, frequence dominante estimee a 1.5 Hz.
- [x] Chutes : phase proche de 0 g, impact puis immobilite.
- [x] Allonge : axe dominant Y au debut, Z a la fin, pic modere de 1.35 g.
- [x] Frequences, appareil, orientation et provenance documentes.
- [x] Labels au schema demande ; estimations explicitement identifiees.
- [x] Huit figures generees hors de data/raw/, dont les deux chutes retenues.
- [x] Horodatages absolus consultes et preserves dans meta/time.csv par essai.

La verification automatique controle les empreintes des CSV, la progression
des temps, les valeurs finies et les bornes des annotations. Elle ne valide pas
automatiquement la verite des classes ni toutes les conditions experimentales.
Les enregistrements sont interpretes avec les activites confirmees par le sujet.

## Interpretation pour le projet Wokwi et le module 2

Sur cette seule seance, les activites portees restent sous 2.5 g et les chutes
d'objet depassent ce seuil. Cela ne demontre pas qu'un seuil fixe distingue
toutes les chutes : une assise brusque n'a pas ete enregistree et les pics sont
probablement ecretes. L'algorithme devra aussi examiner orientation et repos.
Le telephone est un capteur de reference ; le MPU-6050 du projet n'a pas
necessairement la meme plage, le meme bruit ni la meme frequence.
Une chute d'objet ne valide pas une chute humaine. Les donnees publiques de
chutes humaines du module 2 ont elles-memes des limites de population et de
conditions d'acquisition. Aucune finalite diagnostique n'est revendiquee.

Le volet obligatoire est prepare localement avec deux adaptations explicites :
identifiant yves et annotations estimees. Les complements physiques facultatifs
restent a enregistrer avec le participant ; aucune donnee n'est inventee.
