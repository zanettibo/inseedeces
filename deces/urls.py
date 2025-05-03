from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('import/', views.import_data, name='import_data'),
    path('import/<int:import_id>/status/', views.import_status, name='import_status'),
    path('import/stats/', views.import_stats, name='import_stats'),
    path('search/', views.search, name='search'),
]
