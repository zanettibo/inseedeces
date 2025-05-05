import csv
from django.core.management.base import BaseCommand
from deces.models import Region
from django.db import transaction

class Command(BaseCommand):
    help = 'Importe les régions depuis un fichier CSV'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='Chemin vers le fichier CSV à importer')

    def handle(self, *args, **options):
        csv_file = options['csv_file']
        
        try:
            with transaction.atomic():
                # Vider la table avant import
                self.stdout.write('Suppression des données existantes...')
                Region.objects.all().delete()
                
                # Lire et importer le CSV
                self.stdout.write('Import des données...')
                with open(csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    regions_list = []
                    
                    for row in reader:
                        region = Region(
                            reg=row['REG'],
                            cheflieu=row['CHEFLIEU'],
                            tncc=row['TNCC'],
                            ncc=row['NCC'],
                            nccenr=row['NCCENR'],
                            libelle=row['LIBELLE']
                        )
                        regions_list.append(region)
                    
                    # Bulk create pour de meilleures performances
                    Region.objects.bulk_create(regions_list)
                    
                self.stdout.write(self.style.SUCCESS(f'{len(regions_list)} régions importées avec succès'))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Erreur lors de l\'import : {str(e)}'))
            raise
