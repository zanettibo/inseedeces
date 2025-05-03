import os
import csv
import uuid
import hashlib
import shutil
import tempfile
import zipfile
import pandas as pd
from datetime import datetime
from celery import shared_task
from django.db import transaction
from celery.utils.log import get_task_logger
import requests
from .models import Deces, ImportHistory

logger = get_task_logger(__name__)

def parse_insee_date(date_str):
    """Convertit une date INSEE (AAAAMMJJ) en objet date."""
    if not date_str or not date_str.strip('"'):
        return None
    
    try:
        # Nettoyer la date des guillemets
        date_str = date_str.strip('"')
        
        year = int(date_str[:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])
        
        # Si le jour est 00, on le met à 1
        if day == 0:
            day = 1
        # Si le mois est 00, on le met à 1
        if month == 0:
            month = 1
            
        return datetime(year, month, day).date()
    except (ValueError, TypeError):
        return None

def parse_row(row):
    """Parse une ligne du CSV et retourne un dictionnaire de données valides ou (None, raison) si la ligne est invalide."""
    try:
        # Traiter le champ nomprenom spécial (format: <NOM>*<PRENOM 1> [PRENOM 2] [PRENOM 3]/)        
        nom_complet = row.get('nomprenom', '')
        if not nom_complet or '*' not in nom_complet:
            return None, f'Format de nomprenom invalide (doit contenir *) : {nom_complet}'
        
        # Nettoyer et séparer nom et prénoms
        nom_complet = nom_complet.strip('"/')
        try:
            nom, prenoms = nom_complet.split('*', 1)
        except ValueError:
            return None, f'Format nomprenom invalide (pas de *) : {nom_complet}'
            
        # Nettoyer et autoriser les valeurs vides
        nom = nom.strip() or None
        prenoms = prenoms.strip() or None
        
        # Vérifier et nettoyer les champs obligatoires
        sexe = row.get('sexe', '').strip('"')
        date_naissance = parse_insee_date(row.get('datenaiss'))
        date_deces = parse_insee_date(row.get('datedeces'))
        
        # Vérifier les champs obligatoires
        if not sexe in ['1', '2']:
            return None, f'Sexe invalide : {sexe} (doit être 1 ou 2)'
        
        if not date_naissance:
            return None, f'Date de naissance invalide : {row.get("datenaiss")}'
            
        if not date_deces:
            return None, f'Date de décès invalide : {row.get("datedeces")}'
            
        # Nettoyer les autres champs
        lieu_naissance = row.get('lieunaiss', '').strip('"')[:5]
        commune_naissance = row.get('commnaiss', '').strip('"')
        pays_naissance = row.get('paysnaiss', '').strip('"')
        lieu_deces = row.get('lieudeces', '').strip('"')[:5]
        acte_deces = row.get('actedeces', '').strip('"')[:10]

        # Retourner le dictionnaire avec les données validées
        return {
            'nom': nom,
            'prenoms': prenoms,
            'sexe': sexe,
            'date_naissance': date_naissance,
            'lieu_naissance': lieu_naissance,
            'commune_naissance': commune_naissance,
            'pays_naissance': pays_naissance,
            'date_deces': date_deces,
            'lieu_deces': lieu_deces,
            'acte_deces': acte_deces
        }, None
    except Exception as e:
        return None, f'Erreur inattendue : {str(e)}'

def clean_previous_import(csv_filename, md5_hash):
    """Nettoie les données d'un import précédent."""
    try:
        # Supprimer l'historique d'import
        ImportHistory.objects.filter(csv_filename=csv_filename, md5_hash=md5_hash).delete()
        logger.info(f'Historique d\'import supprimé pour {csv_filename} (MD5: {md5_hash})')
        return True
    except Exception as e:
        logger.error(f'Erreur lors du nettoyage des données : {str(e)}')
        return False

@shared_task(bind=True)
def process_insee_file(self, zip_url, zip_filename):
    logger.info(f'Démarrage de l\'import pour {zip_filename}')
    
    # Créer un enregistrement ImportHistory
    import_history = ImportHistory.objects.create(
        zip_url=zip_url,
        zip_filename=zip_filename,
        status='downloading'
    )

    try:
        # Télécharger le fichier ZIP
        logger.info('Téléchargement du fichier ZIP')
        response = requests.get(zip_url, stream=True)
        response.raise_for_status()

        # Sauvegarder le fichier ZIP temporairement
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_zip:
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    downloaded_size += len(chunk)
                    temp_zip.write(chunk)
                    if total_size:
                        progress = (downloaded_size / total_size) * 100
                        logger.debug(f'Téléchargement : {progress:.1f}%')
            temp_zip.flush()
            logger.info('Fichier ZIP téléchargé avec succès')

        # Extraire et traiter chaque fichier CSV du ZIP
        with zipfile.ZipFile(temp_zip.name, 'r') as zip_ref:
            csv_files = [f for f in zip_ref.namelist() if f.endswith('.csv')]
            logger.info(f'Fichiers CSV trouvés : {csv_files}')
            
            for csv_file in csv_files:
                logger.info(f'Traitement du fichier {csv_file}')
                
                # Calculer le MD5 du fichier CSV
                with zip_ref.open(csv_file) as f:
                    md5_hash = hashlib.md5(f.read()).hexdigest()
                    logger.info(f'MD5 du fichier : {md5_hash}')
                
                # Vérifier si ce fichier a déjà été importé
                try:
                    existing_import = ImportHistory.objects.filter(
                        csv_filename=csv_file,
                        md5_hash=md5_hash
                    ).first()
                    
                    if existing_import:
                        # Si l'import existe déjà, on l'ignore pour éviter les doublons
                        status = 'terminé' if existing_import.status == 'completed' else 'en cours/incomplet'
                        logger.warning(
                            f'Le fichier {csv_file} (MD5: {md5_hash}) a déjà un import {status}. '
                            f'Il sera ignoré pour éviter les doublons. Pour réessayer, supprimez d\'abord '
                            f'l\'entrée ImportHistory et les données associées.'
                        )
                        continue
                    else:
                        # Créer une nouvelle entrée
                        import_history.csv_filename = csv_file
                        import_history.md5_hash = md5_hash
                        import_history.save()
                        
                except Exception as e:
                    logger.error(f'Erreur lors de la vérification des doublons : {str(e)}')
                    # On continue avec le fichier suivant
                    continue

                import_history.status = 'processing'
                import_history.save()

                # Extraire et traiter le fichier CSV
                with tempfile.NamedTemporaryFile(delete=False, suffix='.csv') as temp_csv:
                    with zip_ref.open(csv_file) as source, open(temp_csv.name, 'wb') as target:
                        shutil.copyfileobj(source, target)

                    # Compter le nombre total de lignes
                    total_records = sum(1 for line in open(temp_csv.name, encoding='utf-8'))
                    total_records -= 1  # Exclure l'en-tête
                    import_history.total_records = total_records
                    import_history.save()
                    logger.info(f'Nombre total d\'enregistrements à traiter : {total_records}')

                    # Lire et traiter le CSV
                    records_processed = 0
                    error_count = 0
                    with open(temp_csv.name, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f, delimiter=';')
                        
                        for i, row in enumerate(reader, 1):
                            try:
                                with transaction.atomic():
                                    # Parser la ligne
                                    parsed_data, error = parse_row(row)
                                    if parsed_data is None:
                                        error_count += 1
                                        logger.warning(f'Ligne {i} ignorée : {error}\nDonnées : {row}')
                                        continue

                                    # Créer l'enregistrement
                                    Deces.objects.create(**parsed_data
                                    )
                                    records_processed += 1
                            except Exception as row_error:
                                error_count += 1
                                logger.error(f'Erreur ligne {i}: {str(row_error)}\nDonnées: {row}')
                                if error_count > 100:
                                    raise Exception(f'Trop d\'erreurs ({error_count}), import arrêté')

                            if i % 1000 == 0:
                                import_history.records_processed = records_processed
                                import_history.save()
                                logger.info(f'Progression : {records_processed}/{total_records} ({(records_processed/total_records*100):.1f}%)')
                                # Force le commit de la transaction en cours
                                transaction.commit()

                    # Nettoyer
                    os.unlink(temp_csv.name)
                    logger.info(f'Import terminé : {records_processed} enregistrements traités, {error_count} erreurs')

        # Nettoyer
        os.unlink(temp_zip.name)
        
        if records_processed < total_records * 0.9:  # Si moins de 90% des enregistrements ont été traités
            raise Exception(f'Import incomplet : seulement {records_processed}/{total_records} enregistrements traités')

        import_history.status = 'completed'
        import_history.save()
        logger.info('Import terminé avec succès')

    except Exception as e:
        logger.error(f'Erreur lors de l\'import : {str(e)}', exc_info=True)
        import_history.status = 'failed'
        import_history.error_message = str(e)
        import_history.save()
        raise
