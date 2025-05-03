FROM python:3-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DEBUG=True

WORKDIR /app

# Installation des dépendances système
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    default-libmysqlclient-dev \
    build-essential \
    pkg-config && \
    rm -rf /var/lib/apt/lists/*

# Installation des dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie du code source
COPY . .

# Création des dossiers statiques
RUN mkdir -p static staticfiles

# Collecte des fichiers statiques
RUN python manage.py collectstatic --noinput

# Exposition du port
EXPOSE 8000

# Scripts de démarrage
COPY docker-entrypoint*.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint*.sh

ENV DEBUG=False
# Entrypoint par défaut
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Commande par défaut pour le conteneur web
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "insee_deces.wsgi:application"]
