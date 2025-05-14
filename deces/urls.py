from django.urls import path
from . import views

app_name = 'deces'

urlpatterns = [
    path('autocomplete/lieu/', views.autocomplete_lieu, name='autocomplete_lieu'),
    path('', views.index, name='index'),
    path('import/', views.import_data, name='import_data'),
    path('import/<int:import_id>/status/', views.import_status, name='import_status'),
    path('import/stats/', views.import_stats, name='import_stats'),
    path('search/', views.search, name='search'),
    
    # URLs pour la gestion des erreurs d'import
    path('import/errors/', views.ImportErrorListView.as_view(), name='import-error-list'),
    path('import/errors/<int:pk>/', views.ImportErrorDetailView.as_view(), name='import-error-detail'),
    path('import/errors/<int:pk>/update/', views.ImportErrorUpdateView.as_view(), name='import-error-update'),
    path('import/errors/<int:pk>/retry/', views.retry_import_error, name='retry-import-error'),
]
