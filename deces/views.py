import os
import hashlib
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render
from django.core.cache import cache
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import cache_page
from django.core.paginator import Paginator
from django.db.models import Q
import requests
from .models import Deces, ImportHistory
from .tasks import process_insee_file

def rate_limit(key_prefix, limit=60):
    def decorator(view_func):
        def wrapped_view(request, *args, **kwargs):
            client_ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR'))
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

def import_data(request):
    if request.method == 'POST':
        url = request.POST.get('url')
        if not url or not url.endswith('.zip'):
            return JsonResponse({'error': 'URL invalide'}, status=400)
        if not url.startswith('https://www.insee.fr/fr/statistiques/fichier/'):
            return JsonResponse({'error': 'URL invalide'}, status=400)

        try:
            # Lancer la tâche asynchrone avec l'URL et le nom du fichier
            filename = url.split('/')[-1]
            process_insee_file.delay(url, filename)

            return JsonResponse({
                'success': True,
                'message': 'Import lancé. Les fichiers CSV non déjà importés seront traités.'
            })

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

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
def import_status(request, import_id):
    try:
        import_history = ImportHistory.objects.get(id=import_id)
        return JsonResponse({
            'status': import_history.status,
            'status_display': import_history.get_status_display(),
            'records_processed': import_history.records_processed,
            'total_records': import_history.total_records,
            'error_message': import_history.error_message,
            'csv_filename': import_history.csv_filename
        })
    except ImportHistory.DoesNotExist:
        return JsonResponse({'error': 'Import non trouvé'}, status=404)

@rate_limit('import_stats', limit=300)
@require_http_methods(['GET'])
@cache_page(2)  # Cache for 2 seconds
def import_stats(request):
    stats = ImportHistory.objects.filter(status__in=['completed', 'processing']).aggregate(
        processed=Sum('records_processed'),
        total=Sum('total_records')
    )
    return JsonResponse({
        'total_records_processed': stats['processed'] or 0,
        'total_records': stats['total'] or 0
    })

def search(request):
    nom = request.GET.get('nom', '')
    nom_flexible = request.GET.get('nom_flexible', '') == 'on'
    prenoms = request.GET.get('prenoms', '')
    prenoms_flexible = request.GET.get('prenoms_flexible', '') == 'on'
    sexe = request.GET.get('sexe', '')
    date_naissance_debut = request.GET.get('date_naissance_debut', '')
    date_naissance_fin = request.GET.get('date_naissance_fin', '')
    date_deces_debut = request.GET.get('date_deces_debut', '')
    date_deces_fin = request.GET.get('date_deces_fin', '')
    page = request.GET.get('page', 1)
    query = request.GET.get('query', '')
    order_by = request.GET.get('order_by', 'nom')
    order_dir = request.GET.get('order_dir', 'asc')

    # Ne charger les résultats que si au moins un critère de recherche est présent
    has_search_criteria = any([nom, prenoms, sexe, date_naissance_debut, date_naissance_fin, 
                             date_deces_debut, date_deces_fin])
    
    results = None
    page_obj = None

    if has_search_criteria:
        results = Deces.objects.all()

        # Appliquer les filtres si présents
        if nom:
            if nom_flexible:
                results = results.filter(nom__contains=nom.upper())
            else:
                results = results.filter(nom=nom.upper())
        if prenoms:
            if prenoms_flexible:
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

        # Tri des résultats
        valid_fields = {
            'nom': 'nom',
            'prenoms': 'prenoms',
            'date_naissance': 'date_naissance',
            'date_deces': 'date_deces',
            'lieu_deces': 'lieu_deces'
        }

        if order_by in valid_fields:
            order_field = valid_fields[order_by]
            if order_dir == 'desc':
                order_field = f'-{order_field}'
            results = results.order_by(order_field)

        paginator = Paginator(results, 20)
        page_obj = paginator.get_page(page)

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
        'prenoms_flexible': prenoms_flexible
    }
    return render(request, 'deces/search.html', context)