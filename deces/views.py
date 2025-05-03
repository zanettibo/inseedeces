import os
import hashlib
from django.shortcuts import render
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q, Sum
import requests
from .models import Deces, ImportHistory
from .tasks import process_insee_file

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

    imports = ImportHistory.objects.all().order_by('-started_at')
    stats = ImportHistory.objects.filter(status__in=['completed', 'processing']).aggregate(
        processed=Sum('records_processed'),
        total=Sum('total_records')
    )
    
    return render(request, 'deces/import.html', {
        'imports': imports,
        'total_records_processed': stats['processed'] or 0,
        'total_records': stats['total'] or 0
    })

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
    prenoms = request.GET.get('prenoms', '')
    sexe = request.GET.get('sexe', '')
    date_naissance_debut = request.GET.get('date_naissance_debut', '')
    date_naissance_fin = request.GET.get('date_naissance_fin', '')
    date_deces_debut = request.GET.get('date_deces_debut', '')
    date_deces_fin = request.GET.get('date_deces_fin', '')
    page = request.GET.get('page', 1)
    query = request.GET.get('query', '')

    # Ne charger les résultats que si au moins un critère de recherche est présent
    has_search_criteria = any([nom, prenoms, sexe, date_naissance_debut, date_naissance_fin, 
                             date_deces_debut, date_deces_fin])
    
    results = None
    page_obj = None

    if has_search_criteria:
        results = Deces.objects.all()

        # Appliquer les filtres si présents
        if nom:
            results = results.filter(nom__icontains=nom)
        if prenoms:
            results = results.filter(prenoms__icontains=prenoms)
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
        results = results.order_by('nom', 'prenoms')

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
        'query': query
    }
    return render(request, 'deces/search.html', context)