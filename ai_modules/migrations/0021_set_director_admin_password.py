"""NOTA 2026-08-10 — esta migración sembraba una contraseña escrita en el repo.

El literal se retiró: en cualquier base donde esta migración NO haya corrido
todavía, el usuario nace inactivo y sin contraseña usable. Donde SÍ corrió, Django
no la vuelve a ejecutar y el usuario lo cierra `0028_desactivar_director_admin_
sembrado`. La contraseña vieja sigue en el historial de git: si alguna instancia
ajena corrió esta migración, hay que cerrarla ahí.

El guardia que impide que esto vuelva:
`users/tests_marca.py::SinCredencialesEnElCodigoTests`.
"""
from django.db import migrations
from django.contrib.auth.hashers import make_password

def set_director_admin_password(apps, schema_editor):
    User = apps.get_model('users', 'User')
    # El usuario se conserva para no romper referencias históricas, pero nace
    # cerrado: inactivo y con un hash contra el que nada valida.
    u, created = User.objects.get_or_create(
        username='director.admin',
        defaults={
            'role': 'DIRECTOR',
            'establishment': 'RED',
            'is_staff': False,
            'is_active': False,
        }
    )
    u.password = make_password(None)
    # Nos aseguramos de que el rol sea el correcto por si ya existía con otro
    u.role = 'DIRECTOR'
    u.establishment = 'RED'
    u.save()

def reverse_password(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('ai_modules', '0020_ensure_director_admin_permissions'),
    ]

    operations = [
        migrations.RunPython(set_director_admin_password, reverse_password),
    ]
