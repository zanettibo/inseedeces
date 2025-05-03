# Application INSEE-DECES

Cette application Django permet de :
1. Télécharger et traiter les fichiers de données de décès de l'INSEE
2. Rechercher dans la base de données des décès

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

## Licence

Ce projet est sous licence GNU GPL v3 - voir le fichier [LICENSE](LICENSE) pour plus de détails.
