import re
import math
import logging
import requests
from functools import reduce
from datetime import date as date_type, datetime

logger = logging.getLogger(__name__)

from django.db.models import Sum, Q, Case, When, F
from django.db.models import CharField
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.contrib import messages
from django.views.generic import ListView, UpdateView, DetailView
from django.core.paginator import Paginator
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import cache_page
from django.core.cache import cache
from django.urls import reverse

from .models import Deces, Commune, Region, Departement, Pays, ImportHistory, DecesImportError
from .tasks import process_insee_file, process_datagouv_file, DATAGOUV_DATASET_ID
from .forms import ImportErrorForm


class MeiliPaginator:
    def __init__(self, total, page_size):
        self.count = total
        self.per_page = page_size
        self.num_pages = max(1, math.ceil(total / page_size))
        self.page_range = range(1, self.num_pages + 1)


class MeiliPage:
    def __init__(self, object_list, number, paginator):
        self.object_list = object_list
        self.number = number
        self.paginator = paginator

    def has_previous(self):
        return self.number > 1

    def has_next(self):
        return self.number < self.paginator.num_pages

    def previous_page_number(self):
        return self.number - 1

    def next_page_number(self):
        return self.number + 1

    def __iter__(self):
        return iter(self.object_list)

def rate_limit(key_prefix, limit=60):
    def decorator(view_func):
        def wrapped_view(request, *args, **kwargs):
            forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            client_ip = forwarded_for.split(',')[0].strip() if forwarded_for else request.META.get('REMOTE_ADDR')
            cache_key = f"{key_prefix}:{client_ip}"
            requests = cache.get(cache_key, 0)
            
            if requests >= limit:
                return JsonResponse({'error': 'Rate limit exceeded'}, status=429)
            
            cache.set(cache_key, requests + 1, 60)  # Reset after 60 seconds
            return view_func(request, *args, **kwargs)
        return wrapped_view
    return decorator

def parse_insee_date(date_str):
    date_str = str(date_str)
    if len(date_str) != 8:
        return None
    
    try:
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

def index(request):
    return render(request, 'deces/index.html')

@login_required
def import_data(request):
    if not request.user.is_staff:
        messages.error(request, 'Vous devez être membre du staff pour importer des données.')
        return redirect('deces:index')
    if request.method == 'POST':
        url = request.POST.get('url', '')
        is_zip = url.endswith('.zip') and url.startswith('https://www.insee.fr/fr/statistiques/fichier/')
        is_txt = url.endswith('.txt') and url.startswith('https://static.data.gouv.fr/')

        if not (is_zip or is_txt):
            return JsonResponse({'error': 'URL invalide'}, status=400)

        try:
            filename = url.split('/')[-1]
            if is_zip:
                process_insee_file.delay(url, filename)
            else:
                process_datagouv_file.delay(url, filename)

            return JsonResponse({'success': True, 'message': 'Import lancé.'})

        except Exception:
            return JsonResponse({'error': 'Erreur interne, veuillez réessayer.'}, status=500)

    imports = ImportHistory.objects.all().order_by('-csv_filename')
    stats = ImportHistory.objects.filter(status__in=['completed', 'processing']).aggregate(
        processed=Sum('records_processed'),
        total=Sum('total_records')
    )
    
    return render(request, 'deces/import.html', {
        'imports': imports,
        'total_records_processed': stats['processed'] or 0,
        'total_records': stats['total'] or 0
    })

@rate_limit('import_status', limit=300)  # 8 imports × 30 updates/minute = 240 + marge
@require_http_methods(['GET'])
@login_required
def import_status(request, import_id):
    try:
        import_history = ImportHistory.objects.get(id=import_id)
        return JsonResponse({
            'status': import_history.status,
            'status_display': import_history.get_status_display(),
            'records_processed': import_history.records_processed,
            'total_records': import_history.total_records,
            'error_message': import_history.error_message,
            'csv_filename': import_history.csv_filename,
            'pending_errors': import_history.pending_errors
        })
    except ImportHistory.DoesNotExist:
        return JsonResponse({'error': 'Import non trouvé'}, status=404)

@login_required
@require_http_methods(['GET'])
def import_status_stream(request, import_id):
    import json, time
    from django.http import StreamingHttpResponse

    TERMINAL = {'completed', 'failed'}
    MAX_SECONDS = 30 * 60

    def event_stream():
        elapsed = 0
        while elapsed < MAX_SECONDS:
            try:
                ih = ImportHistory.objects.get(id=import_id)
                payload = json.dumps({
                    'status': ih.status,
                    'status_display': ih.get_status_display(),
                    'records_processed': ih.records_processed,
                    'total_records': ih.total_records,
                    'error_message': ih.error_message,
                    'pending_errors': ih.pending_errors,
                })
                yield f"data: {payload}\n\n"
                if ih.status in TERMINAL:
                    break
            except ImportHistory.DoesNotExist:
                yield 'data: {"error":"not_found"}\n\n'
                break
            time.sleep(2)
            elapsed += 2
        yield "event: done\ndata: {}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


@rate_limit('import_stats', limit=300)
@require_http_methods(['GET'])
@cache_page(2)  # Cache for 2 seconds
@login_required
def import_stats(request):
    stats = ImportHistory.objects.filter(status__in=['completed', 'processing']).aggregate(
        processed=Sum('records_processed'),
        total=Sum('total_records')
    )
    return JsonResponse({
        'total_records_processed': stats['processed'] or 0,
        'total_records': stats['total'] or 0
    })

def _filename_months(filename):
    """Return frozenset of (year, month) tuples covered by a filename."""
    base = re.sub(r'\.(csv|txt|zip)$', '', filename.lower().replace('_', '-'))
    m = re.match(r'deces-(\d{4})-m(\d{2})$', base)
    if m:
        return frozenset({(int(m.group(1)), int(m.group(2)))})
    m = re.match(r'deces-(\d{4})-t([1-4])$', base)
    if m:
        year, q = int(m.group(1)), int(m.group(2))
        start = (q - 1) * 3 + 1
        return frozenset({(year, start), (year, start + 1), (year, start + 2)})
    m = re.match(r'deces-(\d{4})$', base)
    if m:
        year = int(m.group(1))
        return frozenset({(year, mo) for mo in range(1, 13)})
    return frozenset()


@login_required
@require_http_methods(['GET'])
def datagouv_available_files(request):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Permission refusée'}, status=403)

    cached = cache.get('datagouv_resources_v1')
    if cached is None:
        try:
            resp = requests.get(
                f'https://www.data.gouv.fr/api/1/datasets/{DATAGOUV_DATASET_ID}/',
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()
            cached = data.get('resources', [])
            cache.set('datagouv_resources_v1', cached, 300)
        except Exception as e:
            return JsonResponse({'error': f'API data.gouv.fr indisponible : {e}'}, status=502)

    imported_filenames = ImportHistory.objects.filter(
        status__in=['completed', 'processing', 'checking', 'downloading']
    ).values_list('csv_filename', flat=True)

    # Normalized names for direct match (e.g. Deces_2026_M01.csv → deces-2026-m01)
    imported_normalized = {
        re.sub(r'\.(csv|txt|zip)$', '', f.lower().replace('_', '-'))
        for f in imported_filenames
    }
    # All months covered by imported files
    imported_months = set()
    for f in imported_filenames:
        imported_months |= _filename_months(f)

    available = []
    for r in cached:
        title = r.get('title', '')
        if not title.endswith('.txt'):
            continue
        base = re.sub(r'\.txt$', '', title.lower().replace('_', '-'))
        if base in imported_normalized:
            continue
        months = _filename_months(title)
        if months and months.issubset(imported_months):
            continue
        available.append({
            'title': title,
            'url': r['url'],
            'created_at': r.get('last_modified') or r.get('created_at', ''),
            'filesize': r.get('filesize', 0),
        })

    available.sort(key=lambda x: x['title'], reverse=True)
    return JsonResponse({'files': available})


def autocomplete_lieu(request):
    query = request.GET.get('q', '')
    page = int(request.GET.get('page', 1))
    page_size = 30
    if len(query) < 2:
        return JsonResponse({'results': [], 'pagination': {'more': False}})

    # Calculer l'offset pour la pagination
    offset = (page - 1) * page_size

    # Rechercher dans les communes
    communes = Commune.objects.filter(
        Q(libelle__icontains=query) | 
        Q(ncc__icontains=query)
    ).select_related('dep', 'reg')[offset:offset + page_size]

    # Vérifier s'il y a plus de résultats
    has_more = Commune.objects.filter(
        Q(libelle__icontains=query) | 
        Q(ncc__icontains=query)
    ).count() > offset + page_size

    # Rechercher dans les départements
    departements = Departement.objects.filter(
        Q(libelle__icontains=query) | 
        Q(ncc__icontains=query)
    ).select_related('reg')

    # Rechercher dans les régions
    regions = Region.objects.filter(
        Q(libelle__icontains=query) | 
        Q(ncc__icontains=query)
    )

    # Rechercher dans les pays
    pays = Pays.objects.filter(
        Q(libcog__icontains=query) | 
        Q(libenr__icontains=query)
    )

    results = []
    
    # Ajouter les communes (uniquement pour la France)
    communes_results = [{
        'id': commune.com,
        'text': f"{commune.libelle}, {commune.dep.libelle}, {commune.reg.libelle}, France",
        'type': 'commune'
    } for commune in communes]
    communes_results.sort(key=lambda x: x['text'])
    results.extend(communes_results)

    # Ajouter les départements
    dept_results = [{
        'id': dept.dep,
        'text': f"{dept.libelle}, {dept.reg.libelle}, France",
        'type': 'departement'
    } for dept in departements]
    dept_results.sort(key=lambda x: x['text'])
    results.extend(dept_results)

    # Ajouter les régions
    region_results = [{
        'id': region.reg,
        'text': f"{region.libelle}, France",
        'type': 'region'
    } for region in regions]
    region_results.sort(key=lambda x: x['text'])
    results.extend(region_results)

    # Ajouter les pays (sauf France qui est déjà incluse dans les autres niveaux)
    pays_results = [{
        'id': pays_item.cog,
        'text': pays_item.libcog,
        'type': 'pays'
    } for pays_item in pays if pays_item.cog != '100']
    pays_results.sort(key=lambda x: x['text'])
    results.extend(pays_results)

    return JsonResponse({
        'results': results,
        'pagination': {
            'more': has_more
        }
    })

class SearchView(ListView):
    model = Deces
    template_name = 'deces/search.html'
    paginate_by = 20

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lieu = self.request.GET.get('lieu')
        lieu_type = self.request.GET.get('lieu_type')

        if lieu and lieu_type:
            try:
                if lieu_type == 'commune':
                    commune = Commune.objects.select_related('dep', 'reg').get(com=lieu)
                    context['selected_lieu'] = {
                        'id': commune.com,
                        'text': f"{commune.libelle}, {commune.dep.libelle}, {commune.reg.libelle}, France",
                        'type': 'commune'
                    }
                elif lieu_type == 'departement':
                    dept = Departement.objects.select_related('reg').get(dep=lieu)
                    context['selected_lieu'] = {
                        'id': dept.dep,
                        'text': f"{dept.libelle}, {dept.reg.libelle}, France",
                        'type': 'departement'
                    }
                elif lieu_type == 'region':
                    region = Region.objects.get(reg=lieu)
                    context['selected_lieu'] = {
                        'id': region.reg,
                        'text': f"{region.libelle}, France",
                        'type': 'region'
                    }
                elif lieu_type == 'pays':
                    pays = Pays.objects.get(cog=lieu)
                    context['selected_lieu'] = {
                        'id': pays.cog,
                        'text': pays.libcog,
                        'type': 'pays'
                    }
            except (Commune.DoesNotExist, Departement.DoesNotExist, Region.DoesNotExist, Pays.DoesNotExist) as e:
                logger.debug(f"Selected lieu not found: {e}")

        context['order_by'] = self.request.GET.get('order_by', 'nom')
        context['order_dir'] = self.request.GET.get('order_dir', 'asc')
        return context

    def get_queryset(self):
        queryset = Deces.objects.all()
        
        # Filtrer par nom
        nom = self.request.GET.get('nom')
        if nom:
            queryset = queryset.filter(nom__icontains=nom)
        
        # Filtrer par prénom
        prenom = self.request.GET.get('prenom')
        if prenom:
            queryset = queryset.filter(prenoms__icontains=prenom)
        
        # Filtrer par date de naissance
        date_naissance = self.request.GET.get('date_naissance')
        if date_naissance:
            queryset = queryset.filter(date_naissance=date_naissance)
        
        # Filtrer par date de décès
        date_deces = self.request.GET.get('date_deces')
        if date_deces:
            queryset = queryset.filter(date_deces=date_deces)
        
        # Filtrer par lieu
        lieu = self.request.GET.get('lieu')
        if lieu:
            lieu_type = self.request.GET.get('lieu_type')
            if lieu_type == 'commune':
                queryset = queryset.filter(
                    Q(lieu_naissance=lieu) | 
                    Q(lieu_deces=lieu)
                )
            elif lieu_type == 'departement':
                queryset = queryset.filter(
                    Q(lieu_naissance__in=Commune.objects.filter(dep=lieu).values_list('com', flat=True)) |
                    Q(lieu_deces__in=Commune.objects.filter(dep=lieu).values_list('com', flat=True))
                )
            elif lieu_type == 'region':
                queryset = queryset.filter(
                    Q(lieu_naissance__in=Commune.objects.filter(reg=lieu).values_list('com', flat=True)) |
                    Q(lieu_deces__in=Commune.objects.filter(reg=lieu).values_list('com', flat=True))
                )
            elif lieu_type == 'pays':
                queryset = queryset.filter(
                    Q(lieu_naissance=lieu) | 
                    Q(lieu_deces=lieu)
                )
        
        VALID_ORDER_FIELDS = {'nom', 'prenoms', 'date_naissance', 'date_deces', 'lieu_naissance', 'lieu_deces'}
        order_by = self.request.GET.get('order_by', 'nom')
        order_dir = self.request.GET.get('order_dir', 'asc')
        if order_by not in VALID_ORDER_FIELDS:
            order_by = 'nom'
        direction = '-' if order_dir == 'desc' else ''

        if order_by == 'lieu_naissance':
            queryset = queryset.annotate(
                lieu_naissance_sort=Case(
                    When(lieu_naissance__startswith='99', then=F('lieu_naissance_nom')),
                    default=F('lieu_naissance'),
                    output_field=CharField(),
                )
            ).order_by(f'{direction}lieu_naissance_sort')
        else:
            queryset = queryset.order_by(f'{direction}{order_by}')
        
        return queryset

def search(request):
    # Récupérer les paramètres de recherche
    nom = request.GET.get('nom', '')
    nom_flexible = request.GET.get('nom_flexible')
    prenoms = request.GET.get('prenoms', '')
    prenoms_flexible = request.GET.get('prenoms_flexible')
    sexe = request.GET.get('sexe', '')
    date_naissance_debut = request.GET.get('date_naissance_debut', '')
    date_naissance_fin = request.GET.get('date_naissance_fin', '')
    date_deces_debut = request.GET.get('date_deces_debut', '')
    date_deces_fin = request.GET.get('date_deces_fin', '')

    # Récupérer les paramètres de lieu
    lieu_naissance_id = request.GET.get('lieu_naissance')
    lieu_naissance_type = request.GET.get('lieu_naissance_type')
    lieu_deces_id = request.GET.get('lieu_deces')
    lieu_deces_type = request.GET.get('lieu_deces_type')

    page = request.GET.get('page', 1)
    query = request.GET.get('query', '')
    order_by = request.GET.get('order_by', 'nom')
    order_dir = request.GET.get('order_dir', 'asc')

    # Ne charger les résultats que si au moins un critère de recherche est présent
    has_search_criteria = any([nom, prenoms, sexe, date_naissance_debut, date_naissance_fin, 
                             date_deces_debut, date_deces_fin, lieu_naissance_id, lieu_deces_id])
    
    results = None
    page_obj = None

    if has_search_criteria:
        results = Deces.objects.all()

        # Appliquer les filtres si présents
        if nom:
            if nom_flexible == 'on':
                results = results.filter(nom__contains=nom.upper())
            else:
                results = results.filter(nom=nom.upper())
        if prenoms:
            if prenoms_flexible == 'on':
                results = results.filter(prenoms__contains=prenoms.upper())
            else:
                results = results.filter(prenoms=prenoms.upper())
        if sexe:
            results = results.filter(sexe=sexe)
        
        # Filtres de date de naissance
        if date_naissance_debut:
            results = results.filter(date_naissance__gte=date_naissance_debut)
        if date_naissance_fin:
            results = results.filter(date_naissance__lte=date_naissance_fin)
        
        # Filtres de date de décès
        if date_deces_debut:
            results = results.filter(date_deces__gte=date_deces_debut)
        if date_deces_fin:
            results = results.filter(date_deces__lte=date_deces_fin)

        # Filtres de lieu de naissance
        if lieu_naissance_id and lieu_naissance_type:
            if lieu_naissance_type == 'commune':
                results = results.filter(lieu_naissance=lieu_naissance_id)
            elif lieu_naissance_type == 'departement':
                # Récupérer toutes les communes du département
                commune_list = Commune.objects.filter(dep=lieu_naissance_id).values_list('com', flat=True)
                results = results.filter(lieu_naissance__in=commune_list)
            elif lieu_naissance_type == 'region':
                # Récupérer toutes les communes de la région
                commune_list = Commune.objects.filter(reg=lieu_naissance_id).values_list('com', flat=True)
                results = results.filter(lieu_naissance__in=commune_list)
            elif lieu_naissance_type == 'pays':
                results = results.filter(lieu_naissance=lieu_naissance_id)

        # Filtres de lieu de décès
        if lieu_deces_id and lieu_deces_type:
            if lieu_deces_type == 'commune':
                results = results.filter(lieu_deces=lieu_deces_id)
            elif lieu_deces_type == 'departement':
                # Récupérer toutes les communes du département
                commune_list = Commune.objects.filter(dep=lieu_deces_id).values_list('com', flat=True)
                results = results.filter(lieu_deces__in=commune_list)
            elif lieu_deces_type == 'region':
                # Récupérer toutes les communes de la région
                commune_list = Commune.objects.filter(reg=lieu_deces_id).values_list('com', flat=True)
                results = results.filter(lieu_deces__in=commune_list)
            elif lieu_deces_type == 'pays':
                results = results.filter(lieu_deces=lieu_deces_id)

        valid_fields = {
            'nom': 'nom',
            'prenoms': 'prenoms',
            'date_naissance': 'date_naissance',
            'date_deces': 'date_deces',
            'lieu_deces': 'lieu_deces_libelle',
            'lieu_naissance': 'lieu_naissance_libelle',
        }

        if order_by in valid_fields:
            order_field = valid_fields[order_by]
            if order_dir == 'desc':
                order_field = f'-{order_field}'
            results = results.order_by(order_field)

        # Use Meilisearch for flexible (full-text) name search
        use_meilisearch = (nom_flexible == 'on' or prenoms_flexible == 'on') and (nom or prenoms)
        if use_meilisearch:
            try:
                from .search_index import search as meili_search
                total, pks = meili_search(
                    nom=nom.upper() if nom else None,
                    prenoms=prenoms.upper() if prenoms else None,
                    nom_flexible=(nom_flexible == 'on'),
                    prenoms_flexible=(prenoms_flexible == 'on'),
                    sexe=sexe or None,
                    date_naissance_debut=date_naissance_debut or None,
                    date_naissance_fin=date_naissance_fin or None,
                    date_deces_debut=date_deces_debut or None,
                    date_deces_fin=date_deces_fin or None,
                    lieu_naissance_id=lieu_naissance_id or None,
                    lieu_naissance_type=lieu_naissance_type or None,
                    lieu_deces_id=lieu_deces_id or None,
                    lieu_deces_type=lieu_deces_type or None,
                    order_by=order_by,
                    order_dir=order_dir,
                    page=int(page),
                    page_size=20,
                )
                if pks:
                    conditions = [
                        Q(date_deces=date_type.fromisoformat(pd), lieu_deces=pl, acte_deces=pa)
                        for pd, pl, pa in pks
                    ]
                    combined_q = reduce(lambda a, b: a | b, conditions)
                    records_map = {
                        (str(d.date_deces), d.lieu_deces, d.acte_deces): d
                        for d in Deces.objects.filter(combined_q)
                    }
                    object_list = [records_map.get(pk) for pk in pks]
                    object_list = [r for r in object_list if r is not None]
                else:
                    object_list = []
                paginator = MeiliPaginator(total, 20)
                page_obj = MeiliPage(object_list, int(page), paginator)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Meilisearch unavailable, falling back to DB: {e}")
                use_meilisearch = False

        if not use_meilisearch:
            paginator = Paginator(results, 20)
            page_obj = paginator.get_page(page)

    def get_lieu_text(lieu_id, lieu_type):
        if not lieu_id or not lieu_type:
            return None
        try:
            if lieu_type == 'commune':
                commune = Commune.objects.get(com=lieu_id)
                dept = commune.dep
                region = dept.reg
                return f"{commune.libelle}, {dept.libelle}, {region.libelle}, France"
            elif lieu_type == 'departement':
                dept = Departement.objects.get(dep=lieu_id)
                region = dept.reg
                return f"{dept.libelle}, {region.libelle}, France"
            elif lieu_type == 'region':
                region = Region.objects.get(reg=lieu_id)
                return f"{region.libelle}, France"
            elif lieu_type == 'pays':
                pays = Pays.objects.get(cog=lieu_id)
                return pays.libcog
        except (Commune.DoesNotExist, Departement.DoesNotExist, Region.DoesNotExist, Pays.DoesNotExist):
            return None

    # Récupérer les informations des lieux sélectionnés
    lieu_naissance_id = request.GET.get('lieu_naissance')
    lieu_naissance_type = request.GET.get('lieu_naissance_type')
    selected_lieu_naissance_text = get_lieu_text(lieu_naissance_id, lieu_naissance_type)

    lieu_deces_id = request.GET.get('lieu_deces')
    lieu_deces_type = request.GET.get('lieu_deces_type')
    selected_lieu_deces_text = get_lieu_text(lieu_deces_id, lieu_deces_type)

    context = {
        'nom': nom,
        'prenoms': prenoms,
        'sexe': sexe,
        'date_naissance_debut': date_naissance_debut,
        'date_naissance_fin': date_naissance_fin,
        'date_deces_debut': date_deces_debut,
        'date_deces_fin': date_deces_fin,
        'page_obj': page_obj,
        'has_search_criteria': has_search_criteria,
        'query': query,
        'order_by': order_by,
        'order_dir': order_dir,
        'nom_flexible': nom_flexible,
        'prenoms_flexible': prenoms_flexible,
        'selected_lieu_naissance_text': selected_lieu_naissance_text,
        'selected_lieu_deces_text': selected_lieu_deces_text,
        'lieu_naissance': lieu_naissance_id,
        'lieu_naissance_type': lieu_naissance_type,
        'lieu_deces': lieu_deces_id,
        'lieu_deces_type': lieu_deces_type,
    }
    response = render(request, 'deces/search.html', context)
    # Désactiver le cache pour cette vue
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response

EXPORT_LIMIT = 50_000
EXPORT_SEXE = {'1': 'M', '2': 'F'}


def _build_db_queryset(get_params):
    """Build filtered Deces queryset from GET params (no pagination, no Meilisearch)."""
    nom = get_params.get('nom', '').strip()
    nom_flexible = get_params.get('nom_flexible')
    prenoms = get_params.get('prenoms', '').strip()
    prenoms_flexible = get_params.get('prenoms_flexible')
    sexe = get_params.get('sexe', '')
    date_naissance_debut = get_params.get('date_naissance_debut', '')
    date_naissance_fin = get_params.get('date_naissance_fin', '')
    date_deces_debut = get_params.get('date_deces_debut', '')
    date_deces_fin = get_params.get('date_deces_fin', '')
    lieu_naissance_id = get_params.get('lieu_naissance', '')
    lieu_naissance_type = get_params.get('lieu_naissance_type', '')
    lieu_deces_id = get_params.get('lieu_deces', '')
    lieu_deces_type = get_params.get('lieu_deces_type', '')

    qs = Deces.objects.all()

    if nom:
        qs = qs.filter(nom__contains=nom.upper()) if nom_flexible == 'on' else qs.filter(nom=nom.upper())
    if prenoms:
        qs = qs.filter(prenoms__contains=prenoms.upper()) if prenoms_flexible == 'on' else qs.filter(prenoms=prenoms.upper())
    if sexe:
        qs = qs.filter(sexe=sexe)
    if date_naissance_debut:
        qs = qs.filter(date_naissance__gte=date_naissance_debut)
    if date_naissance_fin:
        qs = qs.filter(date_naissance__lte=date_naissance_fin)
    if date_deces_debut:
        qs = qs.filter(date_deces__gte=date_deces_debut)
    if date_deces_fin:
        qs = qs.filter(date_deces__lte=date_deces_fin)

    if lieu_naissance_id and lieu_naissance_type:
        if lieu_naissance_type == 'commune':
            qs = qs.filter(lieu_naissance=lieu_naissance_id)
        elif lieu_naissance_type == 'departement':
            qs = qs.filter(lieu_naissance__in=Commune.objects.filter(dep=lieu_naissance_id).values_list('com', flat=True))
        elif lieu_naissance_type == 'region':
            qs = qs.filter(lieu_naissance__in=Commune.objects.filter(reg=lieu_naissance_id).values_list('com', flat=True))
        elif lieu_naissance_type == 'pays':
            qs = qs.filter(lieu_naissance=lieu_naissance_id)

    if lieu_deces_id and lieu_deces_type:
        if lieu_deces_type == 'commune':
            qs = qs.filter(lieu_deces=lieu_deces_id)
        elif lieu_deces_type == 'departement':
            qs = qs.filter(lieu_deces__in=Commune.objects.filter(dep=lieu_deces_id).values_list('com', flat=True))
        elif lieu_deces_type == 'region':
            qs = qs.filter(lieu_deces__in=Commune.objects.filter(reg=lieu_deces_id).values_list('com', flat=True))
        elif lieu_deces_type == 'pays':
            qs = qs.filter(lieu_deces=lieu_deces_id)

    return qs


@login_required
@require_http_methods(['POST'])
def nlp_search(request):
    from urllib.parse import urlencode
    query = request.POST.get('query', '').strip()
    if not query:
        return redirect('deces:search')
    try:
        from .nlp_search import build_search_params
        params, _ = build_search_params(query)
        return redirect(f"{reverse('deces:search')}?{urlencode(params)}")
    except Exception as e:
        logger.warning(f"NLP search failed: {e}")
        messages.error(request, f"Analyse impossible : {e}")
        return redirect('deces:search')


def dashboard(request):
    if not request.user.is_staff:
        return redirect('deces:index')
    recent_imports = ImportHistory.objects.filter(
        status='completed'
    ).order_by('-started_at')[:5]
    total_imports = ImportHistory.objects.filter(status='completed').count()
    last_import = ImportHistory.objects.filter(status='completed').order_by('-completed_at').first()
    return render(request, 'deces/dashboard.html', {
        'recent_imports': recent_imports,
        'total_imports': total_imports,
        'last_import': last_import,
    })


@login_required
@require_http_methods(['GET'])
def dashboard_stats(request):
    if not request.user.is_staff:
        return JsonResponse({'error': 'forbidden'}, status=403)
    from django.db import connection

    cache_key = 'dashboard_stats_v1'
    data = cache.get(cache_key)
    if data is None:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT YEAR(date_deces) AS yr, COUNT(*) AS cnt
                FROM deces_deces
                WHERE date_deces >= '1970-01-01'
                GROUP BY YEAR(date_deces)
                ORDER BY yr
            """)
            rows = cursor.fetchall()

        total = sum(r[1] for r in rows)
        data = {
            'total_records': total,
            'years': [r[0] for r in rows if r[0]],
            'counts': [r[1] for r in rows if r[0]],
        }
        cache.set(cache_key, data, 3600)

    return JsonResponse(data)


@login_required
@require_http_methods(['GET'])
def export_search(request):
    from django.http import StreamingHttpResponse
    import csv

    get_params = request.GET
    has_criteria = any(get_params.get(k) for k in [
        'nom', 'prenoms', 'sexe',
        'date_naissance_debut', 'date_naissance_fin',
        'date_deces_debut', 'date_deces_fin',
        'lieu_naissance', 'lieu_deces',
    ])
    if not has_criteria:
        from django.http import HttpResponseBadRequest
        return HttpResponseBadRequest("Au moins un critère de recherche est requis.")

    qs = _build_db_queryset(get_params).order_by('nom', 'prenoms')[:EXPORT_LIMIT]

    def generate_rows():
        header = ['nom', 'prenoms', 'sexe', 'date_naissance', 'lieu_naissance', 'date_deces', 'lieu_deces']
        yield header
        for d in qs.iterator(chunk_size=2000):
            yield [
                d.nom or '',
                d.prenoms or '',
                EXPORT_SEXE.get(d.sexe, d.sexe or ''),
                d.date_naissance.strftime('%d/%m/%Y') if d.date_naissance else '',
                d.lieu_naissance_libelle or d.lieu_naissance or '',
                d.date_deces.strftime('%d/%m/%Y') if d.date_deces else '',
                d.lieu_deces_libelle or d.lieu_deces or '',
            ]

    class CsvWriter:
        def __init__(self):
            import io
            self.buf = io.StringIO()
            self.writer = csv.writer(self.buf, delimiter=';')

        def write_row(self, row):
            self.writer.writerow(row)
            data = self.buf.getvalue()
            self.buf.truncate(0)
            self.buf.seek(0)
            return data

    writer = CsvWriter()
    response = StreamingHttpResponse(
        (writer.write_row(row) for row in generate_rows()),
        content_type='text/csv; charset=utf-8-sig',
    )
    response['Content-Disposition'] = 'attachment; filename="deces_export.csv"'
    return response


@login_required
@require_http_methods(['POST'])
def bulk_error_action(request):
    if not request.user.is_superuser:
        return JsonResponse({'error': 'forbidden'}, status=403)

    action = request.POST.get('action')
    ids = request.POST.getlist('error_ids')
    if not ids:
        messages.warning(request, 'Aucune erreur sélectionnée.')
        return redirect(request.POST.get('next', 'deces:import-error-list'))

    errors = DecesImportError.objects.filter(pk__in=ids, resolved=False)

    if action == 'resolve':
        from django.utils import timezone
        count = errors.update(resolved=True, resolution_date=timezone.now())
        messages.success(request, f'{count} erreur(s) marquée(s) comme résolue(s).')

    elif action == 'retry':
        ok = ko = 0
        for error in errors:
            success, _ = error.retry_import()
            if success:
                ok += 1
            else:
                ko += 1
        if ok:
            messages.success(request, f'{ok} erreur(s) réimportée(s) avec succès.')
        if ko:
            messages.warning(request, f'{ko} erreur(s) non réimportée(s) (données incomplètes).')
    else:
        messages.error(request, 'Action inconnue.')

    from django.utils.http import url_has_allowed_host_and_scheme
    next_url = request.POST.get('next', '')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect('deces:import-error-list')


class ImportErrorListView(LoginRequiredMixin, ListView):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, 'Vous devez être super-utilisateur pour gérer les erreurs d\'import.')
            return redirect('deces:index')
        return super().dispatch(request, *args, **kwargs)
    model = DecesImportError
    template_name = 'deces/import_error_list.html'
    context_object_name = 'errors'
    paginate_by = 50

    def get_queryset(self):
        queryset = super().get_queryset()
        # Filtres
        status = self.request.GET.get('status')
        if status == 'resolved':
            queryset = queryset.filter(resolved=True)
        elif status == 'unresolved':
            queryset = queryset.filter(resolved=False)

        import_id = self.request.GET.get('import_id')
        if import_id:
            queryset = queryset.filter(import_history_id=import_id)

        return queryset.select_related('import_history')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['imports'] = ImportHistory.objects.all()
        context['status'] = self.request.GET.get('status', '')
        context['import_id'] = self.request.GET.get('import_id', '')
        return context

class ImportErrorDetailView(LoginRequiredMixin, DetailView):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, 'Vous devez être super-utilisateur pour voir les détails des erreurs d\'import.')
            return redirect('deces:index')
        return super().dispatch(request, *args, **kwargs)
    model = DecesImportError
    template_name = 'deces/import_error_detail.html'
    context_object_name = 'error'

class ImportErrorUpdateView(LoginRequiredMixin, UpdateView):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, 'Vous devez être super-utilisateur pour corriger les erreurs d\'import.')
            return redirect('deces:index')
        return super().dispatch(request, *args, **kwargs)
    model = DecesImportError
    template_name = 'deces/import_error_form.html'
    form_class = ImportErrorForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['raw_data'] = self.object.raw_data
        return context

    def get_success_url(self):
        return reverse('deces:import-error-detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        success, error = self.object.retry_import()
        if success:
            messages.success(self.request, 'Les données ont été corrigées et importées avec succès.')
        else:
            messages.add_message(self.request, messages.ERROR, f'Erreur lors de la réimportation : {error}', extra_tags='danger')
        return response

@login_required
def retry_import_error(request, pk):
    if not request.user.is_superuser:
        messages.error(request, 'Vous devez être super-utilisateur pour réessayer une erreur d\'import.')
        return redirect('deces:index')
    error = get_object_or_404(DecesImportError, pk=pk)
    success, error_message = error.retry_import()
    
    if success:
        messages.success(request, 'Les données ont été réimportées avec succès.')
    else:
        messages.add_message(request, messages.ERROR, f'Erreur lors de la réimportation : {error_message}', extra_tags='danger')
    
    return redirect('deces:import-error-detail', pk=pk)