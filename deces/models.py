from django.db import models
from django.utils import timezone

class Deces(models.Model):
    nom = models.CharField(max_length=100, null=True, blank=True)
    prenoms = models.CharField(max_length=200, null=True, blank=True)
    sexe = models.CharField(max_length=1)
    date_naissance = models.DateField()
    lieu_naissance = models.CharField(max_length=5)
    commune_naissance = models.CharField(max_length=100)
    pays_naissance = models.CharField(max_length=100, blank=True)
    date_deces = models.DateField()
    lieu_deces = models.CharField(max_length=100)
    acte_deces = models.CharField(max_length=10)

    class Meta:
        verbose_name = 'Décès'
        verbose_name_plural = 'Décès'
        indexes = [
            models.Index(fields=['nom']),
            models.Index(fields=['prenoms']),
            models.Index(fields=['date_naissance']),
            models.Index(fields=['date_deces']),
        ]

    def __str__(self):
        return f"{self.nom} {self.prenoms} ({self.date_naissance} - {self.date_deces})"


class ImportHistory(models.Model):
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('processing', 'En cours'),
        ('completed', 'Terminé'),
        ('failed', 'Échec')
    ]

    zip_url = models.URLField(max_length=500)
    zip_filename = models.CharField(max_length=255, default='unknown.zip')
    csv_filename = models.CharField(max_length=255)
    md5_hash = models.CharField(max_length=32, help_text='MD5 hash du fichier CSV')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    records_processed = models.IntegerField(default=0)
    total_records = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Historique d\'import'
        verbose_name_plural = 'Historiques d\'imports'
        ordering = ['-started_at']
        unique_together = ['csv_filename', 'md5_hash']

    def __str__(self):
        return f"{self.zip_filename} - {self.csv_filename} ({self.status}) - {self.started_at.strftime('%Y-%m-%d %H:%M')}"

    def update_status(self, status, error_message=None):
        self.status = status
        if error_message:
            self.error_message = error_message
        if status in ['completed', 'failed']:
            self.completed_at = timezone.now()
        self.save()
