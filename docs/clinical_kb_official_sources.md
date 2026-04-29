# KB clinique officielle - personnes agees EHPAD

Ce document explique les ressources ajoutees pour le copilot LLM et le moteur
de triage pedagogique. Le projet reste un demonstrateur: ces seuils et conduites
a tenir ne remplacent pas un protocole medical valide par l'etablissement.

## Fichiers ajoutes

- `backend/kb/official_elderly_complications_kb.json`
  - pathologies suivies;
  - complications transversales;
  - seuils de declenchement adaptes;
  - conduite a tenir soignante;
  - sources officielles.
- `backend/kb/epidor_kb_mapping_v4.json`
  - mapping problemes / residents / capteurs / poids ML / mini-DPI.
- `backend/kb/ml_rule_weights.json`
  - ponderation score 0-100 puis normalisation 0-1.
- `backend/kb/resident_problem_mapping.json`
  - problemes suivis par resident type.
- `backend/kb/sensor_field_mapping.json`
  - correspondance capteurs reels vers champs du projet.
- `backend/kb/dashboard_mini_dpi_config.json`
  - sections attendues pour le Mini DPI.
- `backend/kb/validation_tests_v4.json`
  - cas de validation: hypoglycemie, hypotension, iatrogenie, confusion,
    canicule, denutrition, chute, fugue.

## Sources officielles utilisees

| Domaine | Source | Usage projet |
|---|---|---|
| Chutes personne agee | HAS - Evaluation et prise en charge des personnes agees faisant des chutes repetees | facteurs de risque, signes de gravite, recherche cause precipitant |
| Alzheimer / comportement | HAS - Maladie d'Alzheimer et troubles du comportement perturbateurs | errance, agitation, trouble veille-sommeil, cause somatique/iatrogene |
| Denutrition | HAS - Diagnostic de la denutrition chez la personne de 70 ans et plus | fragilite, perte de poids, risque chute, surveillance nutritionnelle |
| Insuffisance cardiaque | Assurance Maladie | dyspnee, fatigue, oedemes, prise de poids rapide, perte autonomie |
| BPCO | Assurance Maladie | dyspnee, exacerbation, hypoxemie, tolerance effort |
| Diabete / hypoglycemie | Assurance Maladie | sueurs, tremblements, confusion, malaise, conduite de verification |
| AVC | Assurance Maladie | signes visage/bras/parole, appel urgence |
| Canicule / chaleur | Ministere de la Sante | personne agee, hydratation, signes de gravite |
| Sepsis | OMS | infection grave, confusion, respiration rapide, hypotension |
| NEWS2 | Royal College of Physicians | SpO2, frequence respiratoire, PA, pouls, temperature, conscience |
| Premiers secours PSC/AFPS | Ministere de l'Interieur / DGSCGC | malaise, perte de connaissance, arret cardiaque, hemorragie, obstruction, brulure, traumatisme |

## Pathologies couvertes

- BPCO / fragilite respiratoire;
- insuffisance cardiaque;
- diabete / hypoglycemie;
- Alzheimer et troubles cognitifs;
- Parkinson / mobilite fragile;
- insuffisance renale / iatrogenie;
- hypertension / risque neuro-cardio.

## Complications transversales

- chute;
- confusion aigue;
- deshydratation / canicule;
- AVC suspect;
- sepsis / infection grave.

## Conduites a tenir premiers secours

La KB ajoute une couche `first_aid_actions` pour les urgences pratiques:

- malaise;
- perte de connaissance avec respiration;
- arret cardiaque;
- hemorragie externe;
- obstruction grave des voies aeriennes;
- traumatisme apres chute;
- brulure.

Ces fiches sont injectees dans le contexte LLM quand le niveau d'alerte, les
constantes ou les capteurs indiquent un risque immediat. Le LLM doit rester
prudent: il propose une conduite de premiers secours compatible avec PSC/AFPS,
mais l'appel soignant/15/112 suit toujours le protocole de l'etablissement.

## Utilisation par le LLM

Le pipeline LLM injecte maintenant dans le prompt via
`backend/app/services/llm/kb_context.py` et la facade `backend/llm_service.py`:

- les scenarios KB deja pertinents;
- les profils officiels correspondant aux pathologies du resident;
- les seuils adaptes;
- les conduites a tenir;
- les conduites de premiers secours PSC/AFPS si urgence;
- les complications transversales a ne pas manquer.

Le LLM doit:

- expliquer et hierarchiser;
- citer les ids `sources_kb`;
- presenter les seuils comme aide au tri, pas comme diagnostic;
- rappeler les donnees a verifier;
- signaler les red flags.

## Limites a annoncer au jury

- Les seuils sont adaptes au contexte de demo et doivent etre valides par un
  medecin ou un cadre de sante avant usage reel.
- Les donnees residents sont synthetiques.
- Le LLM n'est pas un dispositif medical: il reformule une analyse structuree.
- Le moteur d'alerte doit rester prioritaire sur le LLM pour les urgences.
