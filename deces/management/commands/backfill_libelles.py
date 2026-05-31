import time
from django.core.management.base import BaseCommand
from django.db import connection
from deces.models import Commune, Pays


YEAR_CHUNKS = [
    ('1800-01-01', '1950-12-31'),
    ('1951-01-01', '1960-12-31'),
    ('1961-01-01', '1970-12-31'),
    ('1971-01-01', '1980-12-31'),
    ('1981-01-01', '1990-12-31'),
    ('1991-01-01', '2000-12-31'),
    ('2001-01-01', '2010-12-31'),
    ('2011-01-01', '2020-12-31'),
    ('2021-01-01', '2099-12-31'),
]


class Command(BaseCommand):
    help = 'Backfill lieu_naissance_libelle and lieu_deces_libelle via chunked JOIN UPDATEs'

    def add_arguments(self, parser):
        parser.add_argument(
            '--skip-naissance', action='store_true',
            help='Skip lieu_naissance_libelle (already done)'
        )
        parser.add_argument(
            '--skip-deces', action='store_true',
            help='Skip lieu_deces_libelle'
        )

    def _build_tmp_table(self, cursor, commune_map, pays_map):
        cursor.execute("DROP TEMPORARY TABLE IF EXISTS tmp_lieu_libelle")
        cursor.execute("""
            CREATE TEMPORARY TABLE tmp_lieu_libelle (
                code VARCHAR(5) NOT NULL,
                libelle VARCHAR(300),
                PRIMARY KEY (code)
            )
        """)
        combined = {**commune_map, **pays_map}
        items = list(combined.items())
        for i in range(0, len(items), 500):
            batch = items[i:i + 500]
            placeholders = ','.join(['(%s, %s)'] * len(batch))
            values = [v for pair in batch for v in pair]
            cursor.execute(
                f"INSERT INTO tmp_lieu_libelle (code, libelle) VALUES {placeholders}",
                values
            )
        return len(combined)

    def _run_chunked_update(self, column_lieu, column_libelle, cursor, label):
        t0 = time.time()
        total_rows = 0
        for i, (date_start, date_end) in enumerate(YEAR_CHUNKS):
            t_chunk = time.time()
            cursor.execute(f"""
                UPDATE deces_deces d
                JOIN tmp_lieu_libelle t ON d.{column_lieu} = t.code
                SET d.{column_libelle} = t.libelle
                WHERE d.date_deces BETWEEN %s AND %s
            """, [date_start, date_end])
            rows = cursor.rowcount
            total_rows += rows
            elapsed = time.time() - t0
            chunk_time = time.time() - t_chunk
            self.stdout.write(
                f"  [{label}] chunk {i+1}/{len(YEAR_CHUNKS)} "
                f"{date_start}→{date_end}: {rows:,} rows in {chunk_time:.0f}s "
                f"| total {total_rows:,} | {elapsed:.0f}s elapsed"
            )
        return total_rows

    def handle(self, *args, **options):
        t0 = time.time()

        self.stdout.write("Loading reference data...")
        commune_map = {
            c.com: f"{c.libelle}, {c.dep.libelle}"
            for c in Commune.objects.select_related('dep').all()
        }
        pays_map = {p.cog: p.libcog for p in Pays.objects.all()}
        self.stdout.write(f"Loaded {len(commune_map)} communes + {len(pays_map)} pays")

        with connection.cursor() as cursor:
            self.stdout.write("Building temporary lookup table...")
            n = self._build_tmp_table(cursor, commune_map, pays_map)
            self.stdout.write(f"  {n} codes inserted")

            if not options['skip_naissance']:
                self.stdout.write("Updating lieu_naissance_libelle (chunked by year)...")
                rows = self._run_chunked_update('lieu_naissance', 'lieu_naissance_libelle', cursor, 'naissance')
                self.stdout.write(f"  lieu_naissance done: {rows:,} rows")
            else:
                self.stdout.write("Skipping lieu_naissance_libelle (--skip-naissance)")

            if not options['skip_deces']:
                self.stdout.write("Updating lieu_deces_libelle (chunked by year)...")
                rows = self._run_chunked_update('lieu_deces', 'lieu_deces_libelle', cursor, 'deces')
                self.stdout.write(f"  lieu_deces done: {rows:,} rows")
            else:
                self.stdout.write("Skipping lieu_deces_libelle (--skip-deces)")

            cursor.execute("DROP TEMPORARY TABLE IF EXISTS tmp_lieu_libelle")

        self.stdout.write(
            self.style.SUCCESS(f"Backfill done in {time.time() - t0:.0f}s")
        )
