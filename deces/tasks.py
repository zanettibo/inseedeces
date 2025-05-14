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
from deces.models import Deces, ImportHistory, DecesImportError
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

class ParseError(Exception):
    """Exception levée lorsqu'une erreur survient lors du parsing d'une ligne."""
    pass

def parse_row(row, no_error=False):
    """Parse une ligne du CSV et retourne un dictionnaire de données valides.
    
    Args:
        row: La ligne de données à parser
        no_error: Si True, ne lève pas d'exception et retourne les données partielles
    
    Returns:
        Un dictionnaire contenant les données parsées
    
    Raises:
        ParseError: Si la ligne est invalide et no_error est False
    """
    # Initialiser le dictionnaire de résultat
    result = {
        'nom': None,
        'prenoms': None,
        'sexe': None,
        'date_naissance': None,
        'lieu_naissance': None,
        'lieu_naissance_nom': None,
        'date_deces': None,
        'lieu_deces': None,
        'acte_deces': None
    }
    
    # Traiter le champ nomprenom spécial (format: <NOM>*<PRENOM 1> [PRENOM 2] [PRENOM 3]/)        
    nom_complet = row.get('nomprenom', '')
    if not nom_complet or '*' not in nom_complet:
        if not no_error:
            raise ParseError(f'Format de nomprenom invalide (doit contenir *) : {nom_complet}')
        return result
    
    # Nettoyer et séparer nom et prénoms
    nom_complet = nom_complet.strip('"/')
    try:
        nom, prenoms = nom_complet.split('*', 1)
        result['nom'] = nom.strip() or None
        result['prenoms'] = prenoms.strip() or None
    except ValueError:
        if not no_error:
            raise ParseError(f'Format nomprenom invalide (pas de *) : {nom_complet}')
        return result
    
    # Vérifier et nettoyer les champs obligatoires
    sexe = row.get('sexe', '')
    result['sexe'] = sexe if sexe in ['1', '2'] else None

    # Parser les dates
    dn = row.get('datenaiss', '')
    dd = row.get('datedeces', '')

    if dn == "00000000":
        result['date_naissance'] = None
    else:
        date_naissance = parse_insee_date(dn)
        result['date_naissance'] = date_naissance
        if not date_naissance and not no_error:
            raise ParseError(f'Date de naissance invalide : {dn}')

    if dd == "00000000":
        result['date_deces'] = None
    else:
        date_deces = parse_insee_date(dd)
        result['date_deces'] = date_deces
        if not date_deces and not no_error:
            raise ParseError(f'Date de décès invalide : {dd}')

    # Vérifier les valeurs obligatoires
    if not all([result['sexe'], result['date_deces']]) and not no_error:
        raise ParseError(f'Champs obligatoires manquants : sexe={result["sexe"]}, date_deces={result["date_deces"]}')

    # Nettoyer les autres champs
    result['lieu_naissance'] = str(row.get('lieunaiss', '')).strip() or None
    result['lieu_naissance_nom'] = str(row.get('commnaiss', '')).strip() or None
    result['lieu_deces'] = str(row.get('lieudeces', '')).strip() or None
    result['acte_deces'] = str(row.get('actedeces', '')).strip() or None

    return result

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
                                parsed_data = parse_row(row)
                                
                                # Créer l'objet Deces
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
                            except (ParseError, Exception) as e:
                                error_count += 1
                                error_type = 'parsing' if isinstance(e, ParseError) else 'inattendue'
                                logger.error(f'Erreur de {error_type} ligne {index+1}: {str(e)}\nDonnées: {row}')
                                
                                # Essayer de récupérer les données partielles
                                try:
                                    parsed_data = parse_row(row, no_error=True)
                                except Exception:
                                    parsed_data = {}
                                
                                # Convertir les données en format JSON-compatible
                                raw_data = {}
                                for k, v in row.to_dict().items():
                                    if pd.isna(v):
                                        raw_data[k] = None
                                    else:
                                        raw_data[k] = str(v)
                                
                                # Sauvegarder l'erreur dans DecesImportError
                                DecesImportError.objects.create(
                                    raw_data=raw_data,
                                    error_message=str(e),
                                    import_history=import_history,
                                    **parsed_data
                                )
                                
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
