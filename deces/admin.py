from django.contrib import admin
from django.utils.html import format_html
from .models import ImportHistory, Deces, DecesImportError

@admin.register(ImportHistory)
class ImportHistoryAdmin(admin.ModelAdmin):
    list_display = ('zip_filename', 'csv_filename', 'status', 'progress_bar', 'pending_errors_display', 'started_at', 'completed_at')
    
    def pending_errors_display(self, obj):
        count = obj.pending_errors
        if count == 0:
            return format_html('<span style="color: green;">0</span>')
        return format_html('<span style="color: red;">{}</span>', count)
    pending_errors_display.short_description = 'Erreurs en attente'
    
    def progress_bar(self, obj):
        if obj.total_records == 0:
            return '0%'
        percentage = (obj.records_processed / obj.total_records) * 100
        return format_html(
            '''<div style="position: relative; width: 100px; height: 20px; background-color: #f0f0f0; border: 1px solid #ccc;">
                <div style="position: absolute; width: {}%; height: 100%; background-color: #90CAF9;"></div>
                <div style="position: absolute; width: 100%; text-align: center; line-height: 20px; color: #000;">{}/{}</div>
            </div>''',
            percentage,
            obj.records_processed,
            obj.total_records
        )
    progress_bar.short_description = 'Progression'
    list_filter = ('status',)
    readonly_fields = ('records_processed', 'total_records', 'error_message', 'started_at', 'completed_at')
    search_fields = ('zip_filename', 'csv_filename', 'md5_hash')
    ordering = ('-started_at',)

@admin.register(DecesImportError)
class DecesImportErrorAdmin(admin.ModelAdmin):
    list_display = ('import_history', 'error_message', 'resolved', 'resolution_date', 'nom', 'prenoms', 'date_naissance', 'date_deces')
    list_filter = ('resolved', 'resolution_date', 'import_history')
    search_fields = ('error_message', 'nom', 'prenoms')
    readonly_fields = ('raw_data', 'error_message', 'import_history')
    ordering = ('-import_history__started_at', '-resolution_date')
    
    fieldsets = (
        ('Informations sur l\'erreur', {
            'fields': ('error_message', 'raw_data', 'import_history', 'resolved', 'resolution_date')
        }),
        ('Données corrigées', {
            'fields': ('nom', 'prenoms', 'sexe', 'date_naissance', 'lieu_naissance', 
                      'lieu_naissance_nom', 'date_deces', 'lieu_deces', 'acte_deces')
        }),
    )

#@admin.register(Deces)
#class DecesAdmin(admin.ModelAdmin):
#    list_display = ('nom', 'prenoms', 'date_naissance', 'date_deces')
#    search_fields = ('nom', 'prenoms')
#    list_filter = ('date_naissance', 'date_deces')
