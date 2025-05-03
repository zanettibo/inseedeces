#!/bin/bash

# Attendre que la base de données soit prête
python manage.py wait_for_db

# Attendre que les migrations soient appliquées (vérification toutes les 2 secondes)
while python manage.py showmigrations --plan | grep -q "\[ \]" ; do
    echo "En attente des migrations..."
    sleep 2
done

# Exécuter la commande passée au conteneur
exec "$@"
