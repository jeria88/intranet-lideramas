import django.contrib.auth.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_user_must_change_password'),
    ]

    operations = [
        # 1. Añadir columna tenant (default='sfa' → todos los usuarios existentes quedan en SFA)
        migrations.AddField(
            model_name='user',
            name='tenant',
            field=models.CharField(default='sfa', max_length=50, verbose_name='Proyecto'),
        ),
        # 2. Quitar unique=True del campo username (la unicidad pasa al unique_together)
        migrations.AlterField(
            model_name='user',
            name='username',
            field=models.CharField(
                error_messages={'unique': 'Ya existe un usuario con ese nombre en este proyecto.'},
                max_length=150,
                validators=[django.contrib.auth.validators.UnicodeUsernameValidator()],
                verbose_name='username',
            ),
        ),
        # 3. Agregar unicidad compuesta (username, tenant)
        migrations.AlterUniqueTogether(
            name='user',
            unique_together={('username', 'tenant')},
        ),
    ]
