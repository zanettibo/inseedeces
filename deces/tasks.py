import os
import hashlib
import tempfile
import zipfile
import pandas as pd
from datetime import datetime
from celery import shared_task
from deces.models import Deces, ImportHistory, DecesImportError, Commune, Pays
from deces.search_index import deces_to_doc, add_documents_batch
import requests
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

BATCH_SIZE = 5000
CHUNK_SIZE = 10000
DATAGOUV_DATASET_ID = '5de8f397634f4164071119c5'


def parse_txt_line(line):
    return {
        'nomprenom': line[0:80].strip(),
        'sexe': line[80:81],
        'datenaiss': line[81:89],
        'lieunaiss': line[89:94].strip(),
        'commnaiss': line[94:124].strip(),
        'paysnaiss': line[124:154].strip(),
        'datedeces': line[154:162],
        'lieudeces': line[162:167].strip(),
        'actedeces': line[167:176].strip(),
    }


def parse_insee_date(date_str):
    if not date_str or not date_str.strip('"'):
        return None

    try:
        date_str = date_str.strip('"')
        year = int(date_str[:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])
        if day == 0:
            day = 1
        if month == 0:
            month = 1
        return datetime(year, month, day).date()
    except (ValueError, TypeError):
        return None


class ParseError(Exception):
    pass


def _load_reference_maps():
    """Load commune and pays lookup dicts into memory. Called once per import task."""
    commune_info = {
        c.com: {
            'libelle': f"{c.libelle}, {c.dep.libelle}",
            'dep': c.dep_id,
            'reg': c.reg_id,
        }
        for c in Commune.objects.select_related('dep').all()
    }
    pays_map = {p.cog: p.libcog for p in Pays.objects.all()}
    return commune_info, pays_map


def _resolve_libelle(code, commune_info, pays_map):
    if not code:
        return None
    if str(code).startswith('99'):
        return pays_map.get(str(code))
    return commune_info.get(str(code), {}).get('libelle')


def parse_row(row, no_error=False, commune_info=None, pays_map=None):
    result = {
        'nom': None,
        'prenoms': None,
        'sexe': None,
        'date_naissance': None,
        'lieu_naissance': None,
        'lieu_naissance_nom': None,
        'lieu_naissance_libelle': None,
        'date_deces': None,
        'lieu_deces': None,
        'lieu_deces_libelle': None,
        'acte_deces': None,
    }

    nom_complet = row.get('nomprenom', '')
    if not nom_complet or '*' not in nom_complet:
        if not no_error:
            raise ParseError(f'Format de nomprenom invalide (doit contenir *) : {nom_complet}')
        return result

    nom_complet = nom_complet.strip('"/')
    try:
        nom, prenoms = nom_complet.split('*', 1)
        result['nom'] = nom.strip() or None
        result['prenoms'] = prenoms.strip() or None
    except ValueError:
        if not no_error:
            raise ParseError(f'Format nomprenom invalide (pas de *) : {nom_complet}')
        return result

    sexe = row.get('sexe', '')
    result['sexe'] = sexe if sexe in ['1', '2'] else None

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

    if not all([result['sexe'], result['date_deces']]) and not no_error:
        raise ParseError(f'Champs obligatoires manquants : sexe={result["sexe"]}, date_deces={result["date_deces"]}')

    result['lieu_naissance'] = str(row.get('lieunaiss', '')).strip() or None
    result['lieu_naissance_nom'] = str(row.get('commnaiss', '')).strip() or None
    result['lieu_deces'] = str(row.get('lieudeces', '')).strip() or None
    result['acte_deces'] = str(row.get('actedeces', '')).strip() or None

    if commune_info is not None and pays_map is not None:
        result['lieu_naissance_libelle'] = _resolve_libelle(result['lieu_naissance'], commune_info, pays_map)
        result['lieu_deces_libelle'] = _resolve_libelle(result['lieu_deces'], commune_info, pays_map)

    return result


def _flush_batch(deces_batch, commune_info, pays_map):
    Deces.objects.bulk_create(deces_batch, update_conflicts=True, update_fields=[
        'lieu_naissance', 'lieu_naissance_nom',
        'lieu_naissance_libelle', 'lieu_deces_libelle',
    ])
    meili_docs = [deces_to_doc(d, commune_info=commune_info, pays_libelle=pays_map) for d in deces_batch]
    add_documents_batch(meili_docs)


def _process_rows(rows_iter, import_history, commune_info, pays_map, total_records):
    records_processed = 0
    error_count = 0
    deces_batch = []

    for index, row in enumerate(rows_iter):
        try:
            parsed_data = parse_row(row, commune_info=commune_info, pays_map=pays_map)
            deces_batch.append(Deces(
                nom=parsed_data['nom'],
                prenoms=parsed_data['prenoms'],
                sexe=parsed_data['sexe'],
                date_naissance=parsed_data['date_naissance'],
                lieu_naissance=parsed_data['lieu_naissance'],
                lieu_naissance_nom=parsed_data['lieu_naissance_nom'],
                lieu_naissance_libelle=parsed_data['lieu_naissance_libelle'],
                date_deces=parsed_data['date_deces'],
                lieu_deces=parsed_data['lieu_deces'],
                lieu_deces_libelle=parsed_data['lieu_deces_libelle'],
                acte_deces=parsed_data['acte_deces'],
            ))
            records_processed += 1

            if len(deces_batch) >= BATCH_SIZE:
                _flush_batch(deces_batch, commune_info, pays_map)
                deces_batch = []

        except (ParseError, Exception) as e:
            error_count += 1
            error_type = 'parsing' if isinstance(e, ParseError) else 'inattendue'
            logger.error(f'Erreur de {error_type} ligne {index+1}: {str(e)}\nDonnées: {row}')

            try:
                parsed_data = parse_row(row, no_error=True)
            except Exception:
                parsed_data = {}

            DecesImportError.objects.create(
                raw_data={k: str(v) if v is not None else None for k, v in row.items()},
                error_message=str(e),
                import_history=import_history,
                **{k: v for k, v in parsed_data.items() if k not in ('lieu_naissance_libelle', 'lieu_deces_libelle')}
            )

            if error_count > 100:
                raise Exception(f'Trop d\'erreurs ({error_count}), import arrêté')

        if index % 1000 == 0:
            import_history.records_processed = records_processed
            import_history.save()
            if total_records:
                logger.info(f'Progression : {records_processed}/{total_records} ({(records_processed/total_records*100):.1f}%)')

    if deces_batch:
        _flush_batch(deces_batch, commune_info, pays_map)

    return records_processed


@shared_task(bind=True)
def process_insee_file(self, zip_url, zip_filename):
    logger.info(f'Démarrage du traitement pour {zip_filename}')
    temp_zip = None

    try:
        logger.info('Chargement des référentiels géographiques...')
        commune_info, pays_map = _load_reference_maps()
        logger.info(f'Référentiels chargés: {len(commune_info)} communes, {len(pays_map)} pays')

        logger.info('Téléchargement du fichier ZIP')
        zip_import_history = ImportHistory.objects.create(
            zip_url=zip_url,
            zip_filename=zip_filename,
            csv_filename="unknown.csv",
            md5_hash="unknown",
            status='downloading'
        )
        try:
            response = requests.get(zip_url, stream=True, timeout=60)
            response.raise_for_status()
        except Exception as e:
            zip_import_history.update_status('failed', str(e))
            raise

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

        with zipfile.ZipFile(temp_zip.name, 'r') as zip_ref:
            csv_files = [f for f in zip_ref.namelist() if f.endswith('.csv')]

            for csv_file in csv_files:
                logger.info(f'Traitement du fichier {csv_file}')
                records_processed = 0
                import_history = ImportHistory.objects.create(
                    zip_url=zip_url,
                    zip_filename=zip_filename,
                    csv_filename=csv_file,
                    md5_hash="unknown",
                    status='checking'
                )
                import_history.save()

                with zip_ref.open(csv_file) as f:
                    md5_hash = hashlib.md5(f.read()).hexdigest()

                if ImportHistory.objects.filter(csv_filename=csv_file, md5_hash=md5_hash).exists():
                    logger.info(f'Le fichier {csv_file} a déjà été traité')
                    import_history.delete()
                    continue

                import_history.md5_hash = md5_hash
                import_history.save()

                with zip_ref.open(csv_file) as f:
                    records = sum(1 for _ in f) - 1  # subtract header
                import_history.total_records = records
                import_history.status = 'processing'
                import_history.save()
                logger.info(f'Nombre total d\'enregistrements à traiter : {records}')

                with zip_ref.open(csv_file) as f:
                    chunks = pd.read_csv(f, sep=';', dtype=str, chunksize=CHUNK_SIZE)

                    def pandas_iter():
                        for chunk in chunks:
                            for _, row in chunk.iterrows():
                                yield {k: (None if pd.isna(v) else str(v)) for k, v in row.items()}

                    records_processed = _process_rows(pandas_iter(), import_history, commune_info, pays_map, records)

                    import_history.total_records = records
                    import_history.records_processed = records_processed
                    import_history.update_status('completed')

                    from django.core.cache import cache
                    cache.delete('dashboard_stats_v1')

                    if records_processed < records * 0.9:
                        raise Exception(f'Import incomplet : seulement {records_processed}/{records} enregistrements traités')
                    logger.info(f'Import terminé : {records_processed} enregistrements traités')

    except Exception as e:
        logger.error(f'Erreur lors du traitement : {str(e)}')
        if 'import_history' in locals():
            import_history.status = 'failed'
            import_history.error_message = str(e)
            import_history.save()
        raise

    finally:
        try:
            if temp_zip is not None and os.path.exists(temp_zip.name):
                os.unlink(temp_zip.name)
        except Exception as e:
            logger.warning(f'Erreur nettoyage fichier temporaire : {str(e)}')

    logger.info('Traitement du ZIP terminé')


@shared_task(bind=True)
def process_datagouv_file(self, txt_url, txt_filename):
    logger.info(f'Démarrage du traitement data.gouv.fr pour {txt_filename}')
    temp_txt = None

    try:
        logger.info('Chargement des référentiels géographiques...')
        commune_info, pays_map = _load_reference_maps()

        import_history = ImportHistory.objects.create(
            zip_url=txt_url,
            zip_filename=txt_filename,
            csv_filename=txt_filename,
            md5_hash='unknown',
            status='downloading'
        )

        try:
            response = requests.get(txt_url, stream=True, timeout=60)
            response.raise_for_status()
        except Exception as e:
            import_history.update_status('failed', str(e))
            raise

        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt', mode='wb') as temp_txt:
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    downloaded_size += len(chunk)
                    temp_txt.write(chunk)
                    if total_size:
                        logger.debug(f'Téléchargement : {(downloaded_size/total_size*100):.1f}%')
            temp_txt.flush()
        logger.info('Fichier TXT téléchargé avec succès')

        with open(temp_txt.name, 'rb') as f:
            md5_hash = hashlib.md5(f.read()).hexdigest()

        if ImportHistory.objects.filter(csv_filename=txt_filename, md5_hash=md5_hash).exclude(id=import_history.id).exists():
            logger.info(f'Le fichier {txt_filename} a déjà été traité')
            import_history.delete()
            return

        import_history.md5_hash = md5_hash
        import_history.status = 'checking'
        import_history.save()

        with open(temp_txt.name, 'r', encoding='utf-8', errors='replace') as f:
            lines = [line.rstrip('\n\r') for line in f if len(line.rstrip('\n\r')) >= 176]

        records = len(lines)
        import_history.total_records = records
        import_history.status = 'processing'
        import_history.save()
        logger.info(f'Nombre total d\'enregistrements à traiter : {records}')

        records_processed = _process_rows(
            (parse_txt_line(line) for line in lines),
            import_history, commune_info, pays_map, records
        )

        import_history.total_records = records
        import_history.records_processed = records_processed
        import_history.update_status('completed')

        from django.core.cache import cache
        cache.delete('dashboard_stats_v1')

        if records_processed < records * 0.9:
            raise Exception(f'Import incomplet : seulement {records_processed}/{records} enregistrements traités')
        logger.info(f'Import terminé : {records_processed} enregistrements traités')

    except Exception as e:
        logger.error(f'Erreur lors du traitement : {str(e)}')
        if 'import_history' in locals():
            import_history.status = 'failed'
            import_history.error_message = str(e)
            import_history.save()
        raise

    finally:
        try:
            if temp_txt is not None and os.path.exists(temp_txt.name):
                os.unlink(temp_txt.name)
        except Exception as e:
            logger.warning(f'Erreur nettoyage fichier temporaire : {str(e)}')

    logger.info('Traitement data.gouv.fr terminé')
