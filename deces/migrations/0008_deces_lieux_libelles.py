from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deces', '0007_fix_import_history_relation'),
    ]

    operations = [
        migrations.AddField(
            model_name='deces',
            name='lieu_naissance_libelle',
            field=models.CharField(blank=True, default=None, max_length=300, null=True),
        ),
        migrations.AddField(
            model_name='deces',
            name='lieu_deces_libelle',
            field=models.CharField(blank=True, default=None, max_length=300, null=True),
        ),
        migrations.AddIndex(
            model_name='deces',
            index=models.Index(fields=['lieu_naissance_libelle'], name='deces_deces_lieu_na_lib_idx'),
        ),
        migrations.AddIndex(
            model_name='deces',
            index=models.Index(fields=['lieu_deces_libelle'], name='deces_deces_lieu_de_lib_idx'),
        ),
    ]
