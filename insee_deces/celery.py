import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insee_deces.settings')

app = Celery('insee_deces')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
