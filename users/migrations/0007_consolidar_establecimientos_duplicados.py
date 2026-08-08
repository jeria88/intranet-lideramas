"""Consolida establecimientos que solo difieren en mayúsculas.

`User.establishment` era un CharField libre y acumuló variantes: en la base real
convivían `TEMUCO` (6 usuarios) y `temuco` (1). Al poblar la tabla, la migración
0006 las reprodujo fielmente como dos sedes distintas — que es lo correcto para
una migración de datos: copiar, no adivinar. Acá se corrige.

Genérico a propósito: no arregla el caso `temuco`, arregla la clase entera de
duplicados por mayúsculas, en cualquier organización. La reincidencia queda
cerrada en `Establecimiento.save()`, que normaliza el código.
"""
from django.db import migrations


def consolidar(apps, schema_editor):
    User = apps.get_model('users', 'User')
    Establecimiento = apps.get_model('users', 'Establecimiento')

    # 1. Normalizar el CharField histórico para que no vuelva a divergir de la FK.
    for valor in set(User.objects.values_list('establishment', flat=True)):
        if valor and valor != valor.strip().upper():
            User.objects.filter(establishment=valor).update(establishment=valor.strip().upper())

    # 2. Consolidar sedes duplicadas dentro de cada organización.
    for org_id in Establecimiento.objects.values_list('organizacion_id', flat=True).distinct():
        por_codigo = {}
        for est in Establecimiento.objects.filter(organizacion_id=org_id).order_by('id'):
            por_codigo.setdefault(est.codigo.strip().upper(), []).append(est)

        for codigo, sedes in por_codigo.items():
            # El canónico es el que ya está en mayúsculas; si ninguno lo está, el más antiguo.
            canonico = next((e for e in sedes if e.codigo == codigo), sedes[0])

            for duplicado in sedes:
                if duplicado.pk == canonico.pk:
                    continue
                User.objects.filter(establecimiento=duplicado).update(establecimiento=canonico)
                # Conservar datos que solo tenía el duplicado antes de descartarlo.
                if not canonico.rbd and duplicado.rbd:
                    canonico.rbd = duplicado.rbd
                if duplicado.es_equipo_central:
                    canonico.es_equipo_central = True
                duplicado.delete()

            if canonico.codigo != codigo:
                canonico.codigo = codigo
            canonico.save()


def sin_reverso(apps, schema_editor):
    """No se puede deshacer: la variante en minúsculas era el bug, no un dato.

    El reverso es un no-op explícito para que la migración siga siendo
    reversible hacia atrás en la cadena sin romper `migrate <app> <número>`.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0006_poblar_organizaciones'),
    ]

    operations = [
        migrations.RunPython(consolidar, sin_reverso),
    ]
