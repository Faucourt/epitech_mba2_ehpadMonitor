# Comptes famille - acces demonstration

> Ces identifiants sont generes automatiquement au demarrage du backend.
> En production, les mots de passe seraient aleatoires et remis en main propre par l'etablissement.

## Interface famille

URL : http://localhost:3002/famille.html

| Utilisateur | Mot de passe | Resident | Chambre |
|-------------|--------------|----------|---------|
| curie | voir `.env` / procedure locale | Marie Curie | 101 |
| pasteur | voir `.env` / procedure locale | Louis Pasteur | 102 |
| veil | voir `.env` / procedure locale | Simone Veil | 103 |
| coubertin | voir `.env` / procedure locale | Pierre de Coubertin | 104 |
| piaf | voir `.env` / procedure locale | Edith Piaf | 105 |
| gabin | voir `.env` / procedure locale | Jean Gabin | 106 |
| girardot | voir `.env` / procedure locale | Annie Girardot | 107 |
| bourvil | voir `.env` / procedure locale | Bourvil | 108 |
| chanel | voir `.env` / procedure locale | Coco Chanel | 201 |
| montand | voir `.env` / procedure locale | Yves Montand | 202 |
| moreau | voir `.env` / procedure locale | Jeanne Moreau | 203 |
| aznavour | voir `.env` / procedure locale | Charles Aznavour | 204 |
| bardot | voir `.env` / procedure locale | Brigitte Bardot | 208 |
| depardieu | voir `.env` / procedure locale | Gerard Depardieu | 209 |
| mathieu | voir `.env` / procedure locale | Mireille Mathieu | 210 |
| francois | voir `.env` / procedure locale | Claude Francois | 211 |
| baker | voir `.env` / procedure locale | Josephine Baker | 212 |
| fernandel | voir `.env` / procedure locale | Fernandel | 213 |
| dalida | voir `.env` / procedure locale | Dalida | 214 |
| ventura | voir `.env` / procedure locale | Lino Ventura | 215 |
| schneider | voir `.env` / procedure locale | Romy Schneider | 216 |
| belmondo | voir `.env` / procedure locale | Jean-Paul Belmondo | 217 |
| marceau | voir `.env` / procedure locale | Sophie Marceau | 218 |
| sardou | voir `.env` / procedure locale | Michel Sardou | 219 |
| adjani | voir `.env` / procedure locale | Isabelle Adjani | 220 |

Chaque compte donne acces uniquement au resident associe.
Le token de session expire apres 24h.

## Interface administration

URL : http://localhost:3002/admin_famille.html

| Role | Token |
|------|-------|
| Admin | voir `.env` (`FAMILLE_ADMIN_TOKEN`) |

L'admin peut creer, lister et supprimer des comptes famille.
