# Generated by Django 5.2 on 2025-05-12 12:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deces', '0003_alter_deces_unique_together_alter_deces_lieu_deces_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='deces',
            name='lieu_naissance_nom',
            field=models.CharField(blank=True, default=None, max_length=200, null=True),
        ),
        migrations.AddIndex(
            model_name='deces',
            index=models.Index(fields=['lieu_naissance_nom'], name='deces_deces_lieu_na_ab4483_idx'),
        ),
    ]
