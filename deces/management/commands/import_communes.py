import csv
from django.core.management.base import BaseCommand
from deces.models import Commune, Region, Departement
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist

class Command(BaseCommand):
    help = 'Importe les communes depuis un fichier CSV'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='Chemin vers le fichier CSV à importer')

    def handle(self, *args, **options):
        csv_file = options['csv_file']
        
        try:
            with transaction.atomic():
                # Vider la table avant import
                self.stdout.write('Suppression des données existantes...')
                Commune.objects.all().delete()
                
                # Première passe : importer COM et ARM
                self.stdout.write('Import des communes principales (COM) et arrondissements municipaux (ARM)...')
                communes_principales = []
                communes_associees = []
                errors = []
                
                with open(csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        try:
                            if row['TYPECOM'] not in ['COM', 'ARM']:
                                communes_associees.append(row)
                                continue
                                
                            # Vérifier que la région existe
                            region = Region.objects.get(reg=row['REG'])
                            # Vérifier que le département existe
                            departement = Departement.objects.get(dep=row['DEP'])
                            
                            commune = Commune(
                                typecom=row['TYPECOM'],
                                com=row['COM'],
                                reg=region,
                                dep=departement,
                                ctcd=row['CTCD'],
                                arr=row['ARR'],
                                tncc=row['TNCC'],
                                ncc=row['NCC'],
                                nccenr=row['NCCENR'],
                                libelle=row['LIBELLE'],
                                can=row['CAN'],
                                comparent=row['COMPARENT']
                            )
                            communes_principales.append(commune)
                            
                        except ObjectDoesNotExist as e:
                            errors.append(f"Erreur pour la commune {row['COM']}: {str(e)}")
                
                # Bulk create des communes principales
                if communes_principales:
                    Commune.objects.bulk_create(communes_principales)
                    self.stdout.write(self.style.SUCCESS(f'{len(communes_principales)} communes principales importées'))
                
                # Deuxième passe : importer COMA et COMD
                self.stdout.write('Import des communes associées (COMA) et déléguées (COMD)...')
                communes_secondaires = []
                
                for row in communes_associees:
                    try:
                        if not row['COMPARENT']:
                            errors.append(f"Erreur pour la commune {row['COM']}: Code commune parente manquant")
                            continue
                            
                        # Récupérer la commune parente
                        try:
                            commune_parente = Commune.objects.get(com=row['COMPARENT'])
                        except Commune.DoesNotExist:
                            errors.append(f"Erreur pour la commune {row['COM']}: Commune parente {row['COMPARENT']} non trouvée")
                            continue
                        
                        # Créer la commune associée avec les infos de la commune parente
                        commune = Commune(
                            typecom=row['TYPECOM'],
                            com=row['COM'],
                            reg=commune_parente.reg,
                            dep=commune_parente.dep,
                            ctcd=commune_parente.ctcd,
                            arr=commune_parente.arr,
                            tncc=row['TNCC'],
                            ncc=row['NCC'],
                            nccenr=row['NCCENR'],
                            libelle=row['LIBELLE'],
                            can=row['CAN'],
                            comparent=row['COMPARENT']
                        )
                        communes_secondaires.append(commune)
                        
                    except Exception as e:
                        errors.append(f"Erreur pour la commune {row['COM']}: {str(e)}")
                
                # Bulk create des communes secondaires en ignorant les doublons
                if communes_secondaires:
                    try:
                        Commune.objects.bulk_create(communes_secondaires, ignore_conflicts=True)
                        self.stdout.write(self.style.SUCCESS(f'{len(communes_secondaires)} communes associées traitées'))
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f'Erreur lors de l\'import des communes associées : {str(e)}'))
                
                if errors:
                    for error in errors:
                        self.stdout.write(self.style.WARNING(error))
                
                total = len(communes_principales) + len(communes_secondaires)
                self.stdout.write(self.style.SUCCESS(f'Import terminé. Total : {total} communes'))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Erreur lors de l\'import : {str(e)}'))
            raise
