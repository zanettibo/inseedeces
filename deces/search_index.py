import logging
from datetime import datetime, timezone, date as date_type
from functools import reduce

logger = logging.getLogger(__name__)


def _get_client():
    import meilisearch
    from django.conf import settings
    return meilisearch.Client(
        getattr(settings, 'MEILISEARCH_URL', 'http://meilisearch:7700'),
        getattr(settings, 'MEILISEARCH_API_KEY', 'masterKey'),
    )


def setup_index():
    client = _get_client()
    try:
        client.create_index('deces', {'primaryKey': 'id'})
    except Exception:
        pass
    index = client.index('deces')
    index.update_settings({
        'searchableAttributes': ['nom', 'prenoms'],
        'filterableAttributes': [
            'nom', 'prenoms',
            'sexe',
            'date_naissance_ts', 'date_deces_ts',
            'lieu_naissance', 'lieu_deces',
            'dep_naissance', 'reg_naissance',
            'dep_deces', 'reg_deces',
        ],
        'sortableAttributes': ['nom', 'prenoms', 'date_naissance_ts', 'date_deces_ts'],
        'typoTolerance': {
            'enabled': True,
            'minWordSizeForTypos': {'oneTypo': 4, 'twoTypos': 8},
        },
    })
    return index


def _date_to_ts(d):
    if d is None:
        return None
    if isinstance(d, date_type):
        return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())
    return None


def deces_to_doc(deces, commune_info=None, pays_libelle=None):
    """
    commune_info: dict {com_code: {'libelle': str, 'dep': str, 'reg': str}}
    pays_libelle: dict {cog: libcog}
    """
    lieu_n = getattr(deces, 'lieu_naissance', None)
    lieu_d = getattr(deces, 'lieu_deces', None)
    date_d = getattr(deces, 'date_deces', None)
    acte = getattr(deces, 'acte_deces', None)

    dep_n = reg_n = dep_d = reg_d = None
    if commune_info:
        if lieu_n and not str(lieu_n).startswith('99'):
            info = commune_info.get(str(lieu_n), {})
            dep_n = info.get('dep')
            reg_n = info.get('reg')
        if lieu_d and not str(lieu_d).startswith('99'):
            info = commune_info.get(str(lieu_d), {})
            dep_d = info.get('dep')
            reg_d = info.get('reg')

    import re
    date_str = str(date_d).replace('-', '') if date_d else '00000000'
    acte_safe = re.sub(r'[^a-zA-Z0-9\-_]', '_', str(acte)) if acte else ''
    doc_id = f"{date_str}_{lieu_d}_{acte_safe}"

    return {
        'id': doc_id,
        'nom': getattr(deces, 'nom', None),
        'prenoms': getattr(deces, 'prenoms', None),
        'sexe': getattr(deces, 'sexe', None),
        'date_naissance_ts': _date_to_ts(getattr(deces, 'date_naissance', None)),
        'date_deces_ts': _date_to_ts(date_d),
        'lieu_naissance': str(lieu_n) if lieu_n else None,
        'lieu_deces': str(lieu_d) if lieu_d else None,
        'dep_naissance': dep_n,
        'reg_naissance': reg_n,
        'dep_deces': dep_d,
        'reg_deces': reg_d,
        'pk_date_deces': str(date_d),
        'pk_lieu_deces': str(lieu_d),
        'pk_acte_deces': str(acte),
    }


def add_documents_batch(docs):
    try:
        _get_client().index('deces').add_documents(docs)
    except Exception as e:
        logger.warning(f"Meilisearch indexing failed (non-fatal): {e}")


def _date_str_to_ts(date_str):
    if not date_str:
        return None
    try:
        return int(datetime.fromisoformat(str(date_str)).replace(tzinfo=timezone.utc).timestamp())
    except (ValueError, TypeError):
        return None


def search(
    nom=None, prenoms=None,
    nom_flexible=False, prenoms_flexible=False,
    sexe=None,
    date_naissance_debut=None, date_naissance_fin=None,
    date_deces_debut=None, date_deces_fin=None,
    lieu_naissance_id=None, lieu_naissance_type=None,
    lieu_deces_id=None, lieu_deces_type=None,
    order_by=None, order_dir='asc',
    page=1, page_size=20,
):
    """
    Returns (total_count, list_of_pk_tuples).
    pk_tuples = [(pk_date_deces, pk_lieu_deces, pk_acte_deces), ...]
    Flexible fields → Meilisearch query text (typo-tolerance).
    Non-flexible fields → exact filter (no typo-tolerance).
    """
    query_parts = []
    if nom and nom_flexible:
        query_parts.append(nom)
    if prenoms and prenoms_flexible:
        query_parts.append(prenoms)
    query = ' '.join(query_parts)

    filters = []

    if nom and not nom_flexible:
        filters.append(f'nom = "{nom}"')
    if prenoms and not prenoms_flexible:
        filters.append(f'prenoms = "{prenoms}"')

    if sexe:
        filters.append(f'sexe = "{sexe}"')

    ts = _date_str_to_ts(date_naissance_debut)
    if ts is not None:
        filters.append(f'date_naissance_ts >= {ts}')
    ts = _date_str_to_ts(date_naissance_fin)
    if ts is not None:
        filters.append(f'date_naissance_ts <= {ts}')

    ts = _date_str_to_ts(date_deces_debut)
    if ts is not None:
        filters.append(f'date_deces_ts >= {ts}')
    ts = _date_str_to_ts(date_deces_fin)
    if ts is not None:
        filters.append(f'date_deces_ts <= {ts}')

    if lieu_naissance_id and lieu_naissance_type:
        if lieu_naissance_type in ('commune', 'pays'):
            filters.append(f'lieu_naissance = "{lieu_naissance_id}"')
        elif lieu_naissance_type == 'departement':
            filters.append(f'dep_naissance = "{lieu_naissance_id}"')
        elif lieu_naissance_type == 'region':
            filters.append(f'reg_naissance = "{lieu_naissance_id}"')

    if lieu_deces_id and lieu_deces_type:
        if lieu_deces_type in ('commune', 'pays'):
            filters.append(f'lieu_deces = "{lieu_deces_id}"')
        elif lieu_deces_type == 'departement':
            filters.append(f'dep_deces = "{lieu_deces_id}"')
        elif lieu_deces_type == 'region':
            filters.append(f'reg_deces = "{lieu_deces_id}"')

    meili_sort_map = {
        'nom': 'nom',
        'prenoms': 'prenoms',
        'date_naissance': 'date_naissance_ts',
        'date_deces': 'date_deces_ts',
    }

    params = {
        'limit': page_size,
        'offset': (page - 1) * page_size,
        'attributesToRetrieve': ['pk_date_deces', 'pk_lieu_deces', 'pk_acte_deces'],
    }
    if filters:
        params['filter'] = filters
    if order_by and order_by in meili_sort_map:
        direction = 'desc' if order_dir == 'desc' else 'asc'
        params['sort'] = [f"{meili_sort_map[order_by]}:{direction}"]

    result = _get_client().index('deces').search(query, params)

    pks = [
        (h['pk_date_deces'], h['pk_lieu_deces'], h['pk_acte_deces'])
        for h in result.get('hits', [])
    ]
    total = result.get('estimatedTotalHits', 0)
    return total, pks
