"""Cierra el usuario que sembraban las migraciones 0017 y 0021.

`0021_set_director_admin_password` fija la contraseña de `director.admin` con un
literal escrito en el repositorio. Cualquiera que lea el código —o el historial de
git, donde queda para siempre— puede entrar a **cualquier instancia** que haya
corrido esas migraciones. En la instancia de Oracle el usuario estaba activo y sin
haber entrado nunca (detectado el 2026-08-09).

No se editan ni se borran 0017/0021: son historia ya aplicada y reescribirlas no
cambia las bases donde ya corrieron. Esta migración va hacia adelante y deja al
usuario inservible allí donde exista.

Reversible: `is_active` vuelve a True. La contraseña NO vuelve, y eso es a
propósito — recuperarla significaría volver a escribirla acá.
"""
from django.contrib.auth.hashers import make_password
from django.db import migrations


def cerrar_usuario_sembrado(apps, schema_editor):
    User = apps.get_model('users', 'User')
    User.objects.filter(username='director.admin').update(
        is_active=False,
        # `make_password(None)` produce un hash inutilizable: nada valida contra él.
        password=make_password(None),
    )


def reactivar(apps, schema_editor):
    User = apps.get_model('users', 'User')
    User.objects.filter(username='director.admin').update(is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ('ai_modules', '0027_alter_aiassistant_options_alter_aiassistant_managers_and_more'),
        ('users', '0011_organizacion_modulos'),
    ]

    operations = [
        migrations.RunPython(cerrar_usuario_sembrado, reactivar),
    ]
