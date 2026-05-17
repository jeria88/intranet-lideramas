from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai_modules', '0021_set_director_admin_password'),
    ]

    operations = [
        migrations.AddField(
            model_name='aiknowledgebase',
            name='nivel',
            field=models.CharField(
                choices=[
                    ('institucional',  'Institucional (solo este colegio)'),
                    ('congregacional', 'Congregacional (toda la red SFA)'),
                    ('nacional',       'Nacional (normativa pública)'),
                ],
                default='institucional',
                max_length=20,
                verbose_name='Nivel de acceso',
            ),
        ),
    ]
