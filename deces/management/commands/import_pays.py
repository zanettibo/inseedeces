import csv
from django.core.management.base import BaseCommand
from deces.models import Pays
from django.db import transaction

class Command(BaseCommand):
    help = 'Importe les pays depuis un fichier CSV'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='Chemin vers le fichier CSV à importer')

    def handle(self, *args, **options):
        csv_file = options['csv_file']
        
        try:
            with transaction.atomic():
                # Vider la table avant import
                self.stdout.write('Suppression des données existantes...')
                Pays.objects.all().delete()
                
                # Lire et importer le CSV
                self.stdout.write('Import des données...')
                with open(csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    pays_list = []
                    
                    for row in reader:
                        pays = Pays(
                            cog=row['COG'],
                            actual=row['ACTUAL'],
                            crpay=row['CRPAY'],
                            ani=row['ANI'],
                            libcog=row['LIBCOG'],
                            libenr=row['LIBENR'],
                            codeiso2=row['CODEISO2'],
                            codeiso3=row['CODEISO3'],
                            codenum3=row['CODENUM3']
                        )
                        pays_list.append(pays)
                    
                    # Bulk create pour de meilleures performances
                    Pays.objects.bulk_create(pays_list)
                    
                self.stdout.write(self.style.SUCCESS(f'{len(pays_list)} pays importés avec succès'))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Erreur lors de l\'import : {str(e)}'))
            raise
