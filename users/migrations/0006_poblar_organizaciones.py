"""Puebla `Organizacion` y `Establecimiento` desde los CharFields históricos.

Equivalencia 1:1, sin pérdida:
  - cada valor distinto de `User.tenant`      → una `Organizacion` con ese `slug`
  - cada valor de `User.establishment`        → un `Establecimiento` de esa organización
  - luego se rellenan `User.organizacion` y `User.establecimiento`

Idempotente (`get_or_create` + solo escribe FKs vacías) y reversible (el reverse
limpia las FKs y borra únicamente las filas que este forward pudo crear).

Los nombres se hardcodean acá a propósito: una migración de datos es un snapshot
del estado en el momento en que se escribió, y no debe depender de que
`ESTABLISHMENT_CHOICES` siga existiendo en el modelo actual — que es justamente
lo que este refactor viene a eliminar.
"""
from django.db import migrations

# Snapshot de users.User.ESTABLISHMENT_CHOICES al 2026-08-08
NOMBRES_ESTABLECIMIENTO = {
    'TEMUCO': 'Temuco',
    'LAUTARO': 'Lautaro',
    'RENAICO': 'Renaico',
    'SANTIAGO': 'Santiago',
    'IMPERIAL': 'Imperial',
    'ERCILLA': 'Ercilla',
    'ARAUCO': 'Arauco',
    'ANGOL': 'Angol',
    'RED': 'Equipo Red Congregacional',
}

# Organizaciones conocidas. Cualquier tenant no listado toma su propio slug como nombre.
NOMBRES_ORGANIZACION = {
    'sfa': 'Red SFA — Congregación Hermanas Terceras Franciscanas',
}

CODIGO_EQUIPO_CENTRAL = 'RED'


def poblar(apps, schema_editor):
    User = apps.get_model('users', 'User')
    Organizacion = apps.get_model('users', 'Organizacion')
    Establecimiento = apps.get_model('users', 'Establecimiento')

    slugs = User.objects.values_list('tenant', flat=True).distinct()

    for slug in slugs:
        if not slug:
            continue

        organizacion, _ = Organizacion.objects.get_or_create(
            slug=slug,
            defaults={'nombre': NOMBRES_ORGANIZACION.get(slug, slug)},
        )

        codigos = (
            User.objects.filter(tenant=slug)
            .exclude(establishment='')
            .values_list('establishment', flat=True)
            .distinct()
        )

        for codigo in codigos:
            establecimiento, _ = Establecimiento.objects.get_or_create(
                organizacion=organizacion,
                codigo=codigo,
                defaults={
                    'nombre': NOMBRES_ESTABLECIMIENTO.get(codigo, codigo.title()),
                    'es_equipo_central': codigo == CODIGO_EQUIPO_CENTRAL,
                },
            )
            # Solo rellena lo que está vacío: no pisa una asignación manual previa.
            User.objects.filter(
                tenant=slug, establishment=codigo, establecimiento__isnull=True,
            ).update(establecimiento=establecimiento)

        User.objects.filter(tenant=slug, organizacion__isnull=True).update(
            organizacion=organizacion,
        )


def despoblar(apps, schema_editor):
    """Devuelve el estado anterior: los CharFields nunca se tocaron, así que
    basta con soltar las FKs y borrar las filas creadas."""
    User = apps.get_model('users', 'User')
    Organizacion = apps.get_model('users', 'Organizacion')
    Establecimiento = apps.get_model('users', 'Establecimiento')

    User.objects.update(organizacion=None, establecimiento=None)
    Establecimiento.objects.all().delete()
    Organizacion.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0005_establecimiento_organizacion_alter_user_options_and_more'),
    ]

    operations = [
        migrations.RunPython(poblar, despoblar),
    ]
