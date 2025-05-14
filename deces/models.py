from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.urls import reverse

class Deces(models.Model):
    # Define composite primary key from these three fields
    id = None
    pk = models.CompositePrimaryKey("date_deces", "lieu_deces", "acte_deces")

    # Personal information
    nom = models.CharField(max_length=100, null=True, blank=True)
    prenoms = models.CharField(max_length=200, null=True, blank=True)
    sexe = models.CharField(max_length=1)
    
    # Birth information
    date_naissance = models.DateField(null=True)
    lieu_naissance = models.CharField(max_length=5)
    lieu_naissance_nom = models.CharField(max_length=200, null=True, blank=True, default=None)
    
    # Death information - these fields are part of the primary key
    date_deces = models.DateField()
    lieu_deces = models.CharField(max_length=5)
    acte_deces = models.CharField(max_length=10)
    
    @property
    def lieu_naissance_detail(self):
        if not self.lieu_naissance:
            return None

        # Si le code commence par 99, c'est un pays
        if self.lieu_naissance.startswith('99'):
            try:
                return Pays.objects.get(cog=self.lieu_naissance)
            except Pays.DoesNotExist:
                return self.lieu_naissance

        # Sinon c'est une commune
        try:
            return Commune.objects.get(com=self.lieu_naissance)
        except Commune.DoesNotExist:
            return self.lieu_naissance

    @property
    def lieu_deces_detail(self):
        if not self.lieu_deces:
            return None

        # Si le code commence par 99, c'est un pays
        if self.lieu_deces.startswith('99'):
            try:
                return Pays.objects.get(cog=self.lieu_deces)
            except Pays.DoesNotExist:
                return self.lieu_deces

        # Sinon c'est une commune
        try:
            return Commune.objects.get(com=self.lieu_deces)
        except Commune.DoesNotExist:
            return self.lieu_deces

    class Meta:
        verbose_name = 'Décès'
        verbose_name_plural = 'Décès'
        unique_together = ['nom', 'prenoms', 'date_naissance', 'sexe', 'date_deces', 'lieu_deces', 'acte_deces']
        indexes = [
            models.Index(fields=['nom']),
            models.Index(fields=['prenoms']),
            models.Index(fields=['sexe']),
            models.Index(fields=['date_naissance']),
            models.Index(fields=['lieu_naissance']),
            models.Index(fields=['lieu_naissance_nom']),
            models.Index(fields=['date_deces']),
            models.Index(fields=['lieu_deces'])
        ]

    def __str__(self):
        return f"{self.nom} {self.prenoms} ({self.date_naissance} - {self.date_deces})"

class Pays(models.Model):
    # Clé primaire
    cog = models.CharField(max_length=5, primary_key=True, help_text='Code du pays ou territoire')
    
    # Champs de base
    actual = models.CharField(max_length=1, help_text='Code actualité du pays ou territoire étranger')
    crpay = models.CharField(max_length=5, blank=True, help_text='Code officiel géographique de l\'actuel pays de rattachement')
    ani = models.CharField(max_length=4, blank=True, help_text='Année d\'apparition du code au COG')
    
    # Libellés
    libcog = models.CharField(max_length=70, help_text='Libellé utilisé dans le COG')
    libenr = models.CharField(max_length=200, help_text='Nom officiel du pays, ou composition détaillée du territoire')
    
    # Codes ISO
    codeiso2 = models.CharField(max_length=2, blank=True, help_text='Code du pays sur 2 caractères conforme à la norme internationale ISO 3166')
    codeiso3 = models.CharField(max_length=3, blank=True, help_text='Code du pays sur 3 caractères conforme à la norme internationale ISO 3166')
    codenum3 = models.CharField(max_length=3, blank=True, help_text='Code du pays à 3 chiffres conforme à la norme internationale ISO 3166')
    
    class Meta:
        verbose_name = 'Pays'
        verbose_name_plural = 'Pays'
        ordering = ['libcog']
        indexes = [
            models.Index(fields=['libcog']),
            models.Index(fields=['libenr']),
            models.Index(fields=['codeiso2']),
            models.Index(fields=['codeiso3']),
        ]

    def __str__(self):
        return f'{self.libcog} ({self.cog})'


class Region(models.Model):
    # Clé primaire
    reg = models.CharField(max_length=2, primary_key=True, help_text='Code région')
    
    # Informations de base
    cheflieu = models.CharField(max_length=5, help_text='Code de la commune chef-lieu')
    tncc = models.CharField(max_length=1, help_text='Type de nom en clair')
    
    # Noms et libellés
    ncc = models.CharField(max_length=200, help_text='Nom en clair (majuscules)')
    nccenr = models.CharField(max_length=200, help_text='Nom en clair (typographie riche)')
    libelle = models.CharField(max_length=200, help_text='Nom en clair (typographie riche) avec article')
    
    class Meta:
        verbose_name = 'Région'
        verbose_name_plural = 'Régions'
        ordering = ['ncc']
        indexes = [
            models.Index(fields=['ncc']),
            models.Index(fields=['nccenr']),
            models.Index(fields=['libelle']),
        ]

    def __str__(self):
        return self.libelle


class Departement(models.Model):
    # Clé primaire
    dep = models.CharField(max_length=3, primary_key=True, help_text='Code département')
    
    # Relations
    reg = models.ForeignKey(Region, on_delete=models.CASCADE, help_text='Code région')
    
    # Informations de base
    cheflieu = models.CharField(max_length=5, help_text='Code de la commune chef-lieu')
    tncc = models.CharField(max_length=1, help_text='Type de nom en clair')
    
    # Noms et libellés
    ncc = models.CharField(max_length=200, help_text='Nom en clair (majuscules)')
    nccenr = models.CharField(max_length=200, help_text='Nom en clair (typographie riche)')
    libelle = models.CharField(max_length=200, help_text='Nom en clair (typographie riche) avec article')
    
    class Meta:
        verbose_name = 'Département'
        verbose_name_plural = 'Départements'
        ordering = ['ncc']
        indexes = [
            models.Index(fields=['ncc']),
            models.Index(fields=['nccenr']),
            models.Index(fields=['libelle']),
        ]
    
    def __str__(self):
        return self.libelle

class Commune(models.Model):
    # Type de commune
    TYPECOM_CHOICES = [
        ('COM', 'Commune'),
        ('ARM', 'Arrondissement municipal'),
        ('COMA', 'Commune associée'),
        ('COMD', 'Commune déléguée')
    ]
    typecom = models.CharField(max_length=4, choices=TYPECOM_CHOICES, help_text='Type de commune')
    
    # Clé primaire
    com = models.CharField(max_length=5, primary_key=True, help_text='Code commune')
    
    # Relations
    reg = models.ForeignKey(Region, on_delete=models.CASCADE, help_text='Code région')
    dep = models.ForeignKey(Departement, on_delete=models.CASCADE, help_text='Code département')
    
    # Informations administratives
    ctcd = models.CharField(max_length=4, help_text='Code de la collectivité territoriale ayant les compétences départementales')
    arr = models.CharField(max_length=4, help_text='Code arrondissement')
    tncc = models.CharField(max_length=1, help_text='Type de nom en clair')
    
    # Noms et libellés
    ncc = models.CharField(max_length=200, help_text='Nom en clair (majuscules)')
    nccenr = models.CharField(max_length=200, help_text='Nom en clair (typographie riche)')
    libelle = models.CharField(max_length=200, help_text='Nom en clair (typographie riche) avec article')
    
    # Informations complémentaires
    can = models.CharField(max_length=5, help_text='Code canton')
    comparent = models.CharField(max_length=5, blank=True, help_text='Code de la commune parente')
    
    class Meta:
        verbose_name = 'Commune'
        verbose_name_plural = 'Communes'
        ordering = ['dep', 'ncc']
        indexes = [
            models.Index(fields=['ncc']),
            models.Index(fields=['nccenr']),
            models.Index(fields=['libelle']),
        ]

    def __str__(self):
        return f'{self.libelle} ({self.dep_id})'


class ImportHistory(models.Model):
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('downloading', 'Téléchargement'),
        ('checking', 'Vérification'),
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

    @property
    def pending_errors(self):
        """Retourne le nombre d'erreurs non résolues pour cet import"""
        return self.decesimporterror_set.filter(resolved=False).count()

    def update_status(self, status, error_message=None):
        self.status = status
        if error_message:
            self.error_message = error_message
        if status in ['completed', 'failed']:
            self.completed_at = timezone.now()
        self.save()

class DecesImportError(models.Model):
    # Données brutes de la ligne en erreur
    import_history = models.ForeignKey(ImportHistory, on_delete=models.CASCADE)
    raw_data = models.JSONField(help_text='Données brutes de la ligne en erreur')
    error_message = models.TextField(help_text='Message d\'erreur lors de l\'import')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved = models.BooleanField(default=False)
    resolution_date = models.DateTimeField(null=True, blank=True)

    # Champs modifiables pour correction
    nom = models.CharField(max_length=100, null=True, blank=True)
    prenoms = models.CharField(max_length=200, null=True, blank=True)
    sexe = models.CharField(max_length=1, null=True, blank=True)
    date_naissance = models.DateField(null=True, blank=True)
    lieu_naissance = models.CharField(max_length=5, null=True, blank=True)
    lieu_naissance_nom = models.CharField(max_length=200, null=True, blank=True)
    date_deces = models.DateField(null=True, blank=True)
    lieu_deces = models.CharField(max_length=5, null=True, blank=True)
    acte_deces = models.CharField(max_length=10, null=True, blank=True)

    class Meta:
        verbose_name = 'Erreur d\'import'
        verbose_name_plural = 'Erreurs d\'import'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['resolved']),
            models.Index(fields=['import_history']),
        ]

    def __str__(self):
        return f"Erreur d'import {self.id} - {self.error_message[:50]}"

    def get_absolute_url(self):
        return reverse('deces:import-error-detail', kwargs={'pk': self.pk})

    def mark_as_resolved(self):
        self.resolved = True
        self.resolution_date = timezone.now()
        self.save()

    def retry_import(self):
        """Tente de réimporter la ligne dans la table Deces avec les données corrigées"""
        try:
            # Préparer les données
            data = {
                'nom': self.nom,
                'prenoms': self.prenoms,
                'sexe': self.sexe,
                'date_naissance': self.date_naissance,
                'lieu_naissance': self.lieu_naissance,
                'lieu_naissance_nom': self.lieu_naissance_nom,
                'date_deces': self.date_deces,
                'lieu_deces': self.lieu_deces,
                'acte_deces': self.acte_deces
            }
            
            # Chercher un doublon existant
            existing = Deces.objects.filter(
                date_deces=self.date_deces,
                lieu_deces=self.lieu_deces,
                acte_deces=self.acte_deces
            ).first()
            
            if existing:
                # Mettre à jour l'existant
                for key, value in data.items():
                    setattr(existing, key, value)
                existing.full_clean()
                existing.save()
            else:
                # Créer un nouveau
                deces = Deces(**data)
                deces.full_clean()
                deces.save()
            
            self.mark_as_resolved()
            return True, None
        except ValidationError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Erreur inattendue: {str(e)}"
