import tempfile
import os
import requests
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.conf import settings


STEPS = [
    ('regions',      'import_regions'),
    ('departements', 'import_departements'),
    ('communes',     'import_communes'),
    ('pays',         'import_pays'),
]


class Command(BaseCommand):
    help = 'Download and import all geographic referentials (COG) from INSEE'

    def add_arguments(self, parser):
        parser.add_argument('--regions-url',      default=None)
        parser.add_argument('--departements-url',  default=None)
        parser.add_argument('--communes-url',      default=None)
        parser.add_argument('--pays-url',          default=None)
        parser.add_argument(
            '--only', nargs='+',
            choices=['regions', 'departements', 'communes', 'pays'],
            help='Import only specified referentials',
        )

    def handle(self, *args, **options):
        cog_urls = dict(settings.COG_URLS)

        for key in ('regions', 'departements', 'communes', 'pays'):
            override = options.get(f'{key}_url')
            if override:
                cog_urls[key] = override

        only = options.get('only') or [s[0] for s in STEPS]
        steps = [(key, cmd) for key, cmd in STEPS if key in only]

        with tempfile.TemporaryDirectory() as tmpdir:
            for key, cmd_name in steps:
                url = cog_urls[key]
                self.stdout.write(f'\n[{key}] Downloading from {url}...')

                try:
                    response = requests.get(url, timeout=60, stream=True)
                    response.raise_for_status()
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f'[{key}] Download failed: {e}'))
                    self.stderr.write(self.style.ERROR(
                        f'  → Update COG_URL_{key.upper()} or pass --{key}-url'
                    ))
                    continue

                csv_path = os.path.join(tmpdir, f'{key}.csv')
                with open(csv_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                size_kb = os.path.getsize(csv_path) // 1024
                self.stdout.write(f'[{key}] Downloaded {size_kb} KB → importing...')

                try:
                    call_command(cmd_name, csv_path, verbosity=0)
                    self.stdout.write(self.style.SUCCESS(f'[{key}] Done.'))
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f'[{key}] Import failed: {e}'))

        self.stdout.write(self.style.SUCCESS('\nAll referentials updated.'))
        self.stdout.write('Run backfill_libelles to refresh denormalized labels in deces table.')
