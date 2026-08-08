"""Carga leads desde un CSV a un target del CRM.

    python manage.py importar_leads --csv colegios_temuco.csv \
        --vertical educacion --ciudad Temuco

Deliberadamente agnóstico de la fuente: sirve para el directorio del MINEDUC, una
exportación de LinkedIn o una lista escrita a mano. Atarlo a un origen concreto lo
volvería inútil apenas cambie ese origen — y para la vertical educación la fuente
todavía no está verificada.

Columnas reconocidas (todas opcionales salvo `nombre`), con alias frecuentes:
    nombre | establecimiento | razon_social
    contacto | director | responsable
    cargo · email | correo · telefono | fono · web | sitio
    direccion | domicilio · rbd

Idempotente: reimportar el mismo archivo no duplica nada, porque el dedupe es por
nombre normalizado. Lo que sí hace es COMPLETAR los campos vacíos de un lead ya
existente, sin pisar lo que ya tenía — un dato escrito a mano vale más que uno de
un padrón.
"""
import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from crm.models import Ciudad, Lead, Target, Vertical, hash_de

ALIAS = {
    'nombre': ('nombre', 'establecimiento', 'razon_social', 'razón_social', 'colegio'),
    'contacto': ('contacto', 'director', 'responsable', 'persona'),
    'cargo': ('cargo', 'puesto'),
    'email': ('email', 'correo', 'e_mail', 'mail'),
    'telefono': ('telefono', 'teléfono', 'fono', 'celular'),
    'web': ('web', 'sitio', 'sitio_web', 'url'),
    'direccion': ('direccion', 'dirección', 'domicilio'),
    'rbd': ('rbd',),
}


def _normalizar_cabecera(campo):
    return slugify(campo or '').replace('-', '_')


def _mapear(fila):
    """Traduce una fila del CSV a los campos del modelo, tolerando alias."""
    plano = {_normalizar_cabecera(k): (v or '').strip() for k, v in fila.items() if k}
    datos = {}
    for campo, alias in ALIAS.items():
        for nombre in alias:
            if plano.get(nombre):
                datos[campo] = plano[nombre]
                break
    return datos


class Command(BaseCommand):
    help = 'Importa leads desde un CSV a un target (vertical × ciudad) del CRM.'

    def add_arguments(self, parser):
        parser.add_argument('--csv', required=True, help='Ruta del archivo')
        parser.add_argument('--vertical', required=True, help='Slug o nombre de la vertical')
        parser.add_argument('--ciudad', required=True)
        parser.add_argument(
            '--origen', default='directorio',
            choices=[c for c, _ in Lead.ORIGEN_CHOICES],
        )
        parser.add_argument(
            '--simular', action='store_true',
            help='Informa qué haría, sin escribir nada.',
        )

    @transaction.atomic
    def handle(self, *args, **opciones):
        ruta = Path(opciones['csv'])
        if not ruta.exists():
            raise CommandError(f'No existe el archivo: {ruta}')

        vertical, _ = Vertical.objects.get_or_create(
            slug=slugify(opciones['vertical']),
            defaults={'nombre': opciones['vertical'].title(), 'activa': True},
        )
        ciudad, _ = Ciudad.objects.get_or_create(nombre=opciones['ciudad'].strip())
        target, creado = Target.objects.get_or_create(vertical=vertical, ciudad=ciudad)
        if creado or not target.etapas.exists():
            target.crear_etapas_por_defecto()

        with ruta.open(encoding='utf-8-sig', newline='') as f:
            filas = list(csv.DictReader(f))

        if not filas:
            raise CommandError('El CSV está vacío o no tiene cabecera.')

        nuevos = completados = repetidos = sin_nombre = 0

        for fila in filas:
            datos = _mapear(fila)
            nombre = datos.pop('nombre', '')
            if not nombre:
                sin_nombre += 1
                continue

            existente = Lead.objects.filter(hash_dedupe=hash_de(nombre)).first()

            if existente:
                # Completar huecos sin pisar: un dato cargado a mano vale más que
                # uno de un padrón.
                faltantes = {k: v for k, v in datos.items() if v and not getattr(existente, k)}
                if faltantes and not opciones['simular']:
                    for campo, valor in faltantes.items():
                        setattr(existente, campo, valor)
                    existente.save()
                if faltantes:
                    completados += 1
                else:
                    repetidos += 1
                continue

            if not opciones['simular']:
                Lead.objects.create(
                    target=target, nombre=nombre, origen=opciones['origen'], **datos,
                )
            nuevos += 1

        if opciones['simular']:
            transaction.set_rollback(True)
            self.stdout.write(self.style.NOTICE('SIMULACIÓN — no se escribió nada'))

        self.stdout.write(self.style.SUCCESS(
            f'\n{target}\n'
            f'  nuevos:      {nuevos}\n'
            f'  completados: {completados}\n'
            f'  sin cambios: {repetidos}\n'
            f'  descartados: {sin_nombre} (sin nombre)'
        ))
