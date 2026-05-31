from django.core.management.base import BaseCommand
from deces.models import Deces, Commune, Pays
from deces.search_index import setup_index, add_documents_batch, deces_to_doc


class Command(BaseCommand):
    help = 'Build Meilisearch index from database (safe to re-run: overwrites existing docs)'

    def add_arguments(self, parser):
        parser.add_argument('--batch-size', type=int, default=10000)
        parser.add_argument('--from-offset', type=int, default=0, help='Resume from this offset')

    def handle(self, *args, **options):
        self.stdout.write("Loading reference data...")
        commune_info = {
            c.com: {'libelle': f"{c.libelle}, {c.dep.libelle}", 'dep': c.dep_id, 'reg': c.reg_id}
            for c in Commune.objects.select_related('dep').all()
        }
        pays_libelle = {p.cog: p.libcog for p in Pays.objects.all()}

        self.stdout.write("Configuring Meilisearch index...")
        setup_index()

        batch_size = options['batch_size']
        offset = options['from_offset']
        total = Deces.objects.count()
        self.stdout.write(f"Total records: {total:,}, starting from offset {offset:,}")

        qs = Deces.objects.order_by('date_deces', 'lieu_deces', 'acte_deces')

        while offset < total:
            batch = list(qs[offset:offset + batch_size])
            if not batch:
                break
            docs = [deces_to_doc(d, commune_info=commune_info, pays_libelle=pays_libelle) for d in batch]
            add_documents_batch(docs)
            offset += len(batch)
            pct = offset / total * 100
            self.stdout.write(f"Indexed {offset:,}/{total:,} ({pct:.1f}%)")

        self.stdout.write(self.style.SUCCESS(f"Index built: {offset:,} records sent to Meilisearch"))
        self.stdout.write("Note: Meilisearch processes documents asynchronously. Check http://localhost:7700 for progress.")
