# Application INSEE-DECES

Cette application Django permet de :
1. Télécharger et traiter les fichiers de données de décès de l'INSEE
2. Rechercher dans la base de données des décès
3. Gérer des référentiels INSEE :
   - Pays et territoires
   - Régions françaises
   - Départements français
   - Communes françaises

## Installation

1. Créer un environnement virtuel :
```bash
python -m venv venv
source venv/bin/activate
```

2. Installer les dépendances :
```bash
pip install -r requirements.txt
```

3. Configurer la base de données :
```bash
python manage.py migrate
```

4. Lancer le serveur de développement :
```bash
python manage.py runserver
```

## Utilisation

### Import des données de décès
Pour importer les données de décès depuis le site de ([l'INSEE](https://www.insee.fr/fr/information/7766585)):
1. Accéder à l'interface d'import via le menu "Importer"
2. Coller l'URL du fichier ZIP de l'INSEE
3. Lancer l'import

### Import du référentiel des pays
Pour mettre à jour le référentiel des pays :
```bash
python manage.py import_pays chemin/vers/fichier.csv
```

Le fichier CSV doit contenir les colonnes suivantes :
- COG : Code du pays ou territoire (5 caractères)
- ACTUAL : Code actualité du pays (1 caractère)
- CRPAY : Code officiel géographique de l'actuel pays de rattachement (5 caractères)
- ANI : Année d'apparition du code au COG (4 caractères)
- LIBCOG : Libellé utilisé dans le COG (70 caractères)
- LIBENR : Nom officiel du pays (200 caractères)
- CODEISO2 : Code ISO 3166 sur 2 caractères
- CODEISO3 : Code ISO 3166 sur 3 caractères
- CODENUM3 : Code ISO 3166 numérique sur 3 chiffres

La commande videra la table des pays avant d'importer les nouvelles données.

### Import du référentiel des régions
Pour mettre à jour le référentiel des régions :
```bash
python manage.py import_regions chemin/vers/fichier.csv
```

Le fichier CSV doit contenir les colonnes suivantes :
- REG : Code région (2 caractères)
- CHEFLIEU : Code de la commune chef-lieu (5 caractères)
- TNCC : Type de nom en clair (1 caractère)
- NCC : Nom en clair en majuscules (200 caractères)
- NCCENR : Nom en clair en typographie riche (200 caractères)
- LIBELLE : Nom en clair avec article (200 caractères)

La commande videra la table des régions avant d'importer les nouvelles données.

### Import du référentiel des départements
Pour mettre à jour le référentiel des départements :
```bash
python manage.py import_departements chemin/vers/fichier.csv
```

Le fichier CSV doit contenir les colonnes suivantes :
- DEP : Code département (3 caractères)
- REG : Code région (2 caractères)
- CHEFLIEU : Code de la commune chef-lieu (5 caractères)
- TNCC : Type de nom en clair (1 caractère)
- NCC : Nom en clair en majuscules (200 caractères)
- NCCENR : Nom en clair en typographie riche (200 caractères)
- LIBELLE : Nom en clair avec article (200 caractères)

**Note** : Les régions référencées dans le fichier doivent exister dans la base de données. Il est recommandé d'importer d'abord les régions avant d'importer les départements.

La commande videra la table des départements avant d'importer les nouvelles données.

### Import du référentiel des communes
Pour mettre à jour le référentiel des communes :
```bash
python manage.py import_communes chemin/vers/fichier.csv
```

Le fichier CSV doit contenir les colonnes suivantes :
- TYPECOM : Type de commune (4 caractères) :
  - COM : Commune
  - ARM : Arrondissement municipal
  - COMA : Commune associée
  - COMD : Commune déléguée
- COM : Code commune (5 caractères)
- REG : Code région (2 caractères)
- DEP : Code département (3 caractères)
- CTCD : Code de la collectivité territoriale (4 caractères)
- ARR : Code arrondissement (4 caractères)
- TNCC : Type de nom en clair (1 caractère)
- NCC : Nom en clair en majuscules (200 caractères)
- NCCENR : Nom en clair en typographie riche (200 caractères)
- LIBELLE : Nom en clair avec article (200 caractères)
- CAN : Code canton (5 caractères)
- COMPARENT : Code de la commune parente (5 caractères)

**Note** : Les régions et départements référencés dans le fichier doivent exister dans la base de données. Il est recommandé d'importer d'abord les régions, puis les départements, avant d'importer les communes.

La commande videra la table des communes avant d'importer les nouvelles données.

## Licence

Ce projet est sous licence GNU GPL v3 - voir le fichier [LICENSE](LICENSE) pour plus de détails.
