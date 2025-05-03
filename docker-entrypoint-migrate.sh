#!/bin/bash

# Attendre que la base de données soit prête
python manage.py wait_for_db

# Appliquer les migrations
python manage.py migrate --noinput

# Le conteneur se termine après avoir appliqué les migrations
exit 0
