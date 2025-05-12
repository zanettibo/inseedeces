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
from deces.models import Deces, ImportHistory
import requests
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

# Configuration pour l'optimisation des imports
BATCH_SIZE = 5000  # Nombre d'enregistrements à insérer en une fois
CHUNK_SIZE = 10000  # Nombre de lignes à lire du CSV en une fois

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
        sexe = row.get('sexe', '')
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
        ln=str(row.get('lieunaiss', ''))
        lieu_naissance = ln if len(ln) == 5 else '0' + ln
        lieu_naissance_nom = row.get('commnaiss', '')
        ld=str(row.get('lieudeces', ''))
        lieu_deces = ld if len(ld) == 5 else '0' + ld
        acte_deces = row.get('actedeces', '')

        # Retourner le dictionnaire avec les données validées
        return {
            'nom': nom,
            'prenoms': prenoms,
            'sexe': sexe,
            'date_naissance': date_naissance,
            'lieu_naissance': lieu_naissance,
            'lieu_naissance_nom': lieu_naissance_nom,
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
    logger.info(f'Démarrage du traitement pour {zip_filename}')
    
    try:
        # Télécharger le fichier ZIP
        logger.info('Téléchargement du fichier ZIP')
        zip_import_history = ImportHistory.objects.create(
            zip_url=zip_url,
            zip_filename=zip_filename,
            csv_filename="unknown.csv",
            md5_hash="unknown",
            status='downloading'
        )
        zip_import_history.save()
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
            zip_import_history.delete()
        # Extraire et traiter chaque fichier CSV
        with zipfile.ZipFile(temp_zip.name, 'r') as zip_ref:
            csv_files = [f for f in zip_ref.namelist() if f.endswith('.csv')]
            
            for csv_file in csv_files:
                logger.info(f'Traitement du fichier {csv_file}')
                records_processed = 0
                # Créer un enregistrement ImportHistory pour ce CSV
                import_history = ImportHistory.objects.create(
                    zip_url=zip_url,
                    zip_filename=zip_filename,
                    csv_filename=csv_file,
                    md5_hash="unknown",
                    status='checking'
                )
                import_history.save()
                # Calculer le MD5 du fichier CSV
                with zip_ref.open(csv_file) as f:
                    md5_hash = hashlib.md5(f.read()).hexdigest()
              
                # Vérifier si le fichier a déjà été traité
                if ImportHistory.objects.filter(csv_filename=csv_file, md5_hash=md5_hash).exists():
                    logger.info(f'Le fichier {csv_file} a déjà été traité')
                    import_history.delete()
                    continue
                
                import_history.md5_hash = md5_hash
                import_history.save()

                # Extraire et traiter le fichier CSV
                with zip_ref.open(csv_file) as f:
                    # Utiliser chunks pour lire le CSV par morceaux
                    df = pd.read_csv(f, sep=';', dtype=str)
                    records = len(df)
                    import_history.total_records = records
                    import_history.status = 'processing'
                    import_history.save()
                    logger.info(f'Nombre total d\'enregistrements à traiter : {records}')
                    f.seek(0)  # Revenir au début du fichier
                    chunks = pd.read_csv(f, sep=';', dtype=str, chunksize=CHUNK_SIZE)
                    error_count = 0
                    deces_batch = []

                    for chunk in chunks:
                        for index, row in chunk.iterrows():
                            try:
                                # Parser la ligne
                                parsed_data, error = parse_row(row)
                                if error:
                                    error_count += 1
                                    logger.warning(f'Ligne {index+1} ignorée : {error}\nDonnées : {row}')
                                    continue

                                # Créer l'objet Deces sans le sauvegarder
                                deces = Deces(
                                    nom=parsed_data['nom'],
                                    prenoms=parsed_data['prenoms'],
                                    sexe=parsed_data['sexe'],
                                    date_naissance=parsed_data['date_naissance'],
                                    lieu_naissance=parsed_data['lieu_naissance'],
                                    lieu_naissance_nom=parsed_data['lieu_naissance_nom'],
                                    date_deces=parsed_data['date_deces'],
                                    lieu_deces=parsed_data['lieu_deces'],
                                    acte_deces=parsed_data['acte_deces']
                                )
                                deces_batch.append(deces)
                                records_processed += 1

                                # Insérer par lot quand on atteint BATCH_SIZE
                                if len(deces_batch) >= BATCH_SIZE:
                                    Deces.objects.bulk_create(deces_batch, update_conflicts=True, update_fields=[
                                        'lieu_naissance', 'lieu_naissance_nom'
                                    ])
                                    deces_batch = []
                            except Exception as row_error:
                                error_count += 1
                                logger.error(f'Erreur ligne {index+1}: {str(row_error)}\nDonnées: {row}')
                                if error_count > 100:
                                    raise Exception(f'Trop d\'erreurs ({error_count}), import arrêté')
                            
                            if index % 1000 == 0:
                                import_history.records_processed = records_processed
                                import_history.save()
                                logger.info(f'Progression : {records_processed}/{records} ({(records_processed/records*100):.1f}%)')
                        
                        # Insérer les derniers enregistrements du chunk
                        if deces_batch:
                            Deces.objects.bulk_create(deces_batch, update_conflicts=True, update_fields=[
                                        'lieu_naissance', 'lieu_naissance_nom'
                                    ])
                            deces_batch = []

                    import_history.total_records = records
                    import_history.records_processed = records_processed
                    import_history.status = 'completed'
                    import_history.save()

                    if records_processed < records * 0.9:  # Si moins de 90% des enregistrements ont été traités
                        raise Exception(f'Import incomplet : seulement {records_processed}/{records} enregistrements traités')
                    logger.info(f'Import terminé : {records_processed} enregistrements traités, {error_count} erreurs')

    except Exception as e:
        logger.error(f'Erreur lors du traitement : {str(e)}')
        # Si une erreur survient pendant le traitement d'un CSV spécifique,
        # on marque uniquement cet import comme échoué
        if 'import_history' in locals():
            import_history.status = 'failed'
            import_history.error_message = str(e)
            import_history.save()
        raise

    finally:
        # Nettoyer les fichiers temporaires
        try:
            if os.path.exists(temp_zip.name):
                try:
                    os.unlink(temp_zip.name)
                except Exception as e:
                    logger.warning(f'Erreur lors du nettoyage du fichier temporaire {temp_zip.name}: {str(e)}')
        except Exception as e:
            logger.error(f'Erreur lors du nettoyage des fichiers temporaires : {str(e)}')

    logger.info('Traitement du ZIP terminé')
