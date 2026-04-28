# Comptes famille - acces demonstration

> Ces identifiants sont generes automatiquement au demarrage du backend.
> En production, les mots de passe seraient aleatoires et remis en main propre par l'etablissement.

## Interface famille

URL : http://localhost:3002/famille.html

| Utilisateur | Mot de passe | Resident | Chambre |
|-------------|--------------|----------|---------|
| curie | curie101 | Marie Curie | 101 |
| pasteur | pasteur102 | Louis Pasteur | 102 |
| veil | veil103 | Simone Veil | 103 |
| coubertin | coubertin104 | Pierre de Coubertin | 104 |
| piaf | piaf105 | Edith Piaf | 105 |
| gabin | gabin106 | Jean Gabin | 106 |
| girardot | girardot107 | Annie Girardot | 107 |
| bourvil | bourvil108 | Bourvil | 108 |
| chanel | chanel201 | Coco Chanel | 201 |
| montand | montand202 | Yves Montand | 202 |
| moreau | moreau203 | Jeanne Moreau | 203 |
| aznavour | aznavour204 | Charles Aznavour | 204 |
| bardot | bardot208 | Brigitte Bardot | 208 |
| depardieu | depardieu209 | Gerard Depardieu | 209 |
| mathieu | mathieu210 | Mireille Mathieu | 210 |
| francois | francois211 | Claude Francois | 211 |
| baker | baker212 | Josephine Baker | 212 |
| fernandel | fernandel213 | Fernandel | 213 |
| dalida | dalida214 | Dalida | 214 |
| ventura | ventura215 | Lino Ventura | 215 |
| schneider | schneider216 | Romy Schneider | 216 |
| belmondo | belmondo217 | Jean-Paul Belmondo | 217 |
| marceau | marceau218 | Sophie Marceau | 218 |
| sardou | sardou219 | Michel Sardou | 219 |
| adjani | adjani220 | Isabelle Adjani | 220 |

Chaque compte donne acces uniquement au resident associe.
Le token de session expire apres 24h.

## Interface administration

URL : http://localhost:3002/admin_famille.html

| Role | Token |
|------|-------|
| Admin | ADMIN_EHPAD_2024 |

L'admin peut creer, lister et supprimer des comptes famille.
