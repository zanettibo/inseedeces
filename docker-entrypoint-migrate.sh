#!/bin/bash

# Attendre que la base de données soit prête
python manage.py wait_for_db

# Appliquer les migrations
python manage.py migrate --noinput

# Configurer les settings Meilisearch (idempotent, ignoré si Meilisearch indisponible)
python manage.py shell -c "
from deces.search_index import setup_index
try:
    setup_index()
    print('Meilisearch index settings OK')
except Exception as e:
    print(f'Warning: Meilisearch setup skipped: {e}')
" || true

exit 0
