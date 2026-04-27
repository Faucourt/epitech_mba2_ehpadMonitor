# Comptes famille — acces demonstration

> Ces identifiants sont generes automatiquement au demarrage du backend.
> En production, les mots de passe seraient aleatoires et remis en main propre par l'etablissement.

## Interface famille

URL : http://localhost:3002/famille.html

| Utilisateur  | Mot de passe   | Resident              | Chambre |
|--------------|----------------|-----------------------|---------|
| dupont       | dupont101      | Marguerite Dupont     | 101     |
| moreau       | moreau102      | Henri Moreau          | 102     |
| bernard      | bernard103     | Simone Bernard        | 103     |
| leroy        | leroy104       | Pierre Leroy          | 104     |
| martin       | martin105      | Yvette Martin         | 105     |
| petit        | petit106       | Andre Petit           | 106     |
| durand       | durand107      | Louise Durand         | 107     |
| thomas       | thomas108      | Marcel Thomas         | 108     |
| robert       | robert201      | Jeanne Robert         | 201     |
| richard      | richard202     | Gaston Richard        | 202     |
| simon        | simon203       | Odette Simon          | 203     |
| michel       | michel204      | Fernand Michel        | 204     |
| lefebvre     | lefebvre208    | Helene Lefebvre       | 208     |
| leblanc      | leblanc209     | Roger Leblanc         | 209     |
| fontaine     | fontaine210    | Germaine Fontaine     | 210     |
| rousseau     | rousseau211    | Edouard Rousseau      | 211     |
| morel        | morel212       | Blanche Morel         | 212     |
| garnier      | garnier213     | Lucien Garnier        | 213     |
| chevalier    | chevalier214   | Paulette Chevalier    | 214     |
| mercier      | mercier215     | Auguste Mercier       | 215     |
| blanc        | blanc216       | Therese Blanc         | 216     |
| caron        | caron217       | Gaetan Caron          | 217     |
| fournier     | fournier218    | Renee Fournier        | 218     |
| girard       | girard219      | Leon Girard           | 219     |
| perrin       | perrin220      | Clothilde Perrin      | 220     |

Chaque compte donne acces uniquement au resident associe.
Le token de session expire apres 24h.

## Interface administration

URL : http://localhost:3002/admin_famille.html

| Role  | Token            |
|-------|------------------|
| Admin | ADMIN_EHPAD_2024 |

L'admin peut creer, lister et supprimer des comptes famille.
