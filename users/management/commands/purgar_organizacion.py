"""Baja definitiva de una organización cliente y todos sus datos.

Es destructivo y no tiene vuelta atrás: exige `--confirmar` con el slug exacto.
Sin esa bandera solo informa qué borraría, que es la forma normal de usarlo.

    python manage.py purgar_organizacion --slug sfa            # informe
    python manage.py purgar_organizacion --slug sfa --confirmar sfa

Los superusuarios NO se borran: son soporte del producto, no del cliente. Se les
suelta la organización para que sobrevivan a la baja y sigan pudiendo entrar.
"""
from django.apps import apps as django_apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from users.models import Establecimiento, Organizacion, User
from users.scoping import ModeloDeOrganizacion


class Command(BaseCommand):
    help = 'Elimina una organización y todos sus datos. Sin --confirmar, solo informa.'

    def add_arguments(self, parser):
        parser.add_argument('--slug', required=True)
        parser.add_argument(
            '--confirmar', default=None,
            help='Repetir el slug exacto para ejecutar el borrado.',
        )

    def handle(self, *args, **opciones):
        slug = opciones['slug']
        try:
            organizacion = Organizacion.objects.get(slug=slug)
        except Organizacion.DoesNotExist:
            raise CommandError(f'No existe la organización "{slug}".')

        inventario = []
        for Modelo in django_apps.get_models():
            if not issubclass(Modelo, ModeloDeOrganizacion):
                continue
            n = Modelo.objects.filter(organizacion=organizacion).count()
            if n:
                inventario.append((f'{Modelo._meta.app_label}.{Modelo.__name__}', n))

        usuarios = User.objects.filter(organizacion=organizacion)
        a_borrar = usuarios.filter(is_superuser=False)
        a_conservar = usuarios.filter(is_superuser=True)
        sedes = Establecimiento.objects.filter(organizacion=organizacion)

        self.stdout.write(self.style.WARNING(f'\nOrganización: {organizacion.nombre} ({slug})'))
        self.stdout.write('\nSe eliminaría:')
        for etiqueta, n in sorted(inventario, key=lambda x: -x[1]):
            self.stdout.write(f'  {n:>6}  {etiqueta}')
        self.stdout.write(f'  {sedes.count():>6}  users.Establecimiento')
        self.stdout.write(f'  {a_borrar.count():>6}  users.User')
        self.stdout.write(
            f'\nSe conservan {a_conservar.count()} superusuario(s), sin organización: '
            f'{", ".join(a_conservar.values_list("username", flat=True)) or "ninguno"}'
        )

        if opciones['confirmar'] != slug:
            self.stdout.write(self.style.NOTICE(
                f'\nNada se borró. Para ejecutar: --confirmar {slug}'
            ))
            return

        with transaction.atomic():
            # Los superusuarios primero: `User.organizacion` es PROTECT y bloquearía
            # el borrado de la organización.
            a_conservar.update(organizacion=None, establecimiento=None)
            borrados_usuarios = a_borrar.delete()[0]
            organizacion.delete()  # CASCADE se lleva sedes y datos de negocio

        self.stdout.write(self.style.SUCCESS(
            f'\nOrganización "{slug}" eliminada. Usuarios borrados: {borrados_usuarios}.'
        ))
