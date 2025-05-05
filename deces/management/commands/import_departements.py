import csv
from django.core.management.base import BaseCommand
from deces.models import Departement, Region
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist

class Command(BaseCommand):
    help = 'Importe les départements depuis un fichier CSV'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='Chemin vers le fichier CSV à importer')

    def handle(self, *args, **options):
        csv_file = options['csv_file']
        
        try:
            with transaction.atomic():
                # Vider la table avant import
                self.stdout.write('Suppression des données existantes...')
                Departement.objects.all().delete()
                
                # Lire et importer le CSV
                self.stdout.write('Import des données...')
                with open(csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    departements_list = []
                    errors = []
                    
                    for row in reader:
                        try:
                            # Vérifier que la région existe
                            region = Region.objects.get(reg=row['REG'])
                            
                            departement = Departement(
                                dep=row['DEP'],
                                reg=region,
                                cheflieu=row['CHEFLIEU'],
                                tncc=row['TNCC'],
                                ncc=row['NCC'],
                                nccenr=row['NCCENR'],
                                libelle=row['LIBELLE']
                            )
                            departements_list.append(departement)
                            
                        except ObjectDoesNotExist:
                            errors.append(f"La région {row['REG']} n'existe pas pour le département {row['DEP']}")
                    
                    if errors:
                        for error in errors:
                            self.stdout.write(self.style.ERROR(error))
                        raise Exception("Des erreurs ont été rencontrées lors de l'import")
                    
                    # Bulk create pour de meilleures performances
                    Departement.objects.bulk_create(departements_list)
                    
                self.stdout.write(self.style.SUCCESS(f'{len(departements_list)} départements importés avec succès'))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Erreur lors de l\'import : {str(e)}'))
            raise
