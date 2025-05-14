import os
import hashlib
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.views.generic import ListView, UpdateView, DetailView
from django.http import JsonResponse
from django.db.models import Q, Value, CharField, Case, When, OuterRef, Subquery
from django.db.models.functions import Concat
from .models import Deces, Commune, Region, Departement, Pays
from django.views.decorators.cache import cache_page
from django.core.paginator import Paginator
import requests
from .models import Deces, ImportHistory, DecesImportError
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import cache_page
from django.core.cache import cache
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

        print(f"DEBUG - lieu: {lieu}, lieu_type: {lieu_type}")

        if lieu and lieu_type:
            try:
                if lieu_type == 'commune':
                    commune = Commune.objects.select_related('dep', 'reg').get(com=lieu)
                    context['selected_lieu'] = {
                        'id': commune.com,
                        'text': f"{commune.libelle}, {commune.dep.libelle}, {commune.reg.libelle}, France",
                        'type': 'commune'
                    }
                    print(f"DEBUG - Found commune: {context['selected_lieu']}")
                elif lieu_type == 'departement':
                    dept = Departement.objects.select_related('reg').get(dep=lieu)
                    context['selected_lieu'] = {
                        'id': dept.dep,
                        'text': f"{dept.libelle}, {dept.reg.libelle}, France",
                        'type': 'departement'
                    }
                    print(f"DEBUG - Found departement: {context['selected_lieu']}")
                elif lieu_type == 'region':
                    region = Region.objects.get(reg=lieu)
                    context['selected_lieu'] = {
                        'id': region.reg,
                        'text': f"{region.libelle}, France",
                        'type': 'region'
                    }
                    print(f"DEBUG - Found region: {context['selected_lieu']}")
                elif lieu_type == 'pays':
                    pays = Pays.objects.get(cog=lieu)
                    context['selected_lieu'] = {
                        'id': pays.cog,
                        'text': pays.libcog,
                        'type': 'pays'
                    }
                    print(f"DEBUG - Found pays: {context['selected_lieu']}")
            except (Commune.DoesNotExist, Departement.DoesNotExist, Region.DoesNotExist, Pays.DoesNotExist) as e:
                print(f"DEBUG - Error: {e}")
                pass

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
        
        # Trier les résultats
        order_by = self.request.GET.get('order_by', 'nom')
        order_dir = self.request.GET.get('order_dir', 'asc')
        
        if order_dir == 'desc':
            order_by = f'-{order_by}'
        
        return queryset.order_by(order_by)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['order_by'] = self.request.GET.get('order_by', 'nom')
        context['order_dir'] = self.request.GET.get('order_dir', 'asc')
        return context

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

        # Tri des résultats
        valid_fields = {
            'nom': 'nom',
            'prenoms': 'prenoms',
            'date_naissance': 'date_naissance',
            'date_deces': 'date_deces',
            'lieu_deces': 'lieu_deces_nom_resolue',
            'lieu_naissance': 'lieu_naissance_nom_resolue'
        }

        # Ajouter les annotations pour le tri sur les noms de lieux
        results = results.annotate(
            lieu_naissance_nom_resolue=Case(
                When(lieu_naissance__startswith='99',
                     then=Subquery(
                         Pays.objects.filter(cog=OuterRef('lieu_naissance'))
                         .values('libcog')[:1]
                     )),
                default=Concat(
                    Subquery(
                        Commune.objects.filter(com=OuterRef('lieu_naissance'))
                        .values('libelle')[:1]
                    ),
                    Value(', '),
                    Subquery(
                        Commune.objects.filter(com=OuterRef('lieu_naissance'))
                        .values('dep__libelle')[:1]
                    ),
                    output_field=CharField()
                )
            ),
            lieu_deces_nom_resolue=Case(
                When(lieu_deces__startswith='99',
                     then=Subquery(
                         Pays.objects.filter(cog=OuterRef('lieu_deces'))
                         .values('libcog')[:1]
                     )),
                default=Concat(
                    Subquery(
                        Commune.objects.filter(com=OuterRef('lieu_deces'))
                        .values('libelle')[:1]
                    ),
                    Value(', '),
                    Subquery(
                        Commune.objects.filter(com=OuterRef('lieu_deces'))
                        .values('dep__libelle')[:1]
                    ),
                    output_field=CharField()
                )
            )
        )

        if order_by in valid_fields:
            order_field = valid_fields[order_by]
            if order_dir == 'desc':
                order_field = f'-{order_field}'
            results = results.order_by(order_field)

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
        'selected_lieu_deces_text': selected_lieu_deces_text
    }
    response = render(request, 'deces/search.html', context)
    # Désactiver le cache pour cette vue
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response

class ImportErrorListView(ListView):
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

class ImportErrorDetailView(DetailView):
    model = DecesImportError
    template_name = 'deces/import_error_detail.html'
    context_object_name = 'error'

class ImportErrorUpdateView(UpdateView):
    model = DecesImportError
    template_name = 'deces/import_error_form.html'
    fields = ['nom', 'prenoms', 'sexe', 'date_naissance', 'lieu_naissance',
             'lieu_naissance_nom', 'date_deces', 'lieu_deces', 'acte_deces']

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
            messages.error(self.request, f'Erreur lors de la réimportation : {error}')
        return response

def retry_import_error(request, pk):
    error = get_object_or_404(DecesImportError, pk=pk)
    success, error_message = error.retry_import()
    
    if success:
        messages.success(request, 'Les données ont été réimportées avec succès.')
    else:
        messages.error(request, f'Erreur lors de la réimportation : {error_message}')
    
    return redirect('deces:import-error-detail', pk=pk)