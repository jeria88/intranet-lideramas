"""Alta de una organización cliente, sin tocar código.

Reemplaza a `setup_all_establishments`, que creaba los 8 colegios de un cliente
concreto hardcodeados y corría en cada deploy desde el Procfile.

    python manage.py crear_organizacion \
        --slug colegio-andes \
        --nombre "Colegio Los Andes" \
        --establecimientos "Sede Centro,Sede Norte"

Idempotente: se puede correr de nuevo para agregar sedes o reponer asistentes
borrados. Con `--actualizar-prompts` refresca el `system_instruction` de los
asistentes existentes con la plantilla vigente.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from ai_modules.models import AIAssistant
from ai_modules.motores import MOTOR_POR_DEFECTO
from ai_modules.plantillas_roles import ROLE_CONFIGS, _REGLA_URGENCIA
from users.models import Establecimiento, Organizacion

EQUIPO_CENTRAL_CODIGO = 'CENTRAL'


def _prompt_equipo_central(nombre_organizacion, n_establecimientos):
    return (
        f"Eres el/la Coordinador/a del Equipo Central de {nombre_organizacion}.\n"
        f"Área de Acción: Articulación, gobernanza y coordinación estratégica entre "
        f"los {n_establecimientos} establecimientos de la organización.\n"
        "Foco: Metas institucionales, coordinación entre directivos y gestión de la red.\n"
        "Verifica si la consulta corresponde a tu rol; si no, aconseja y deriva al estamento correcto."
    )


class Command(BaseCommand):
    help = 'Da de alta una organización con sus establecimientos y asistentes IA.'

    def add_arguments(self, parser):
        parser.add_argument('--slug', required=True, help='Identificador en URL: /<slug>/login/')
        parser.add_argument('--nombre', required=True, help='Nombre visible de la organización')
        parser.add_argument(
            '--establecimientos', required=True,
            help='Nombres separados por coma. Ej: "Sede Centro,Sede Norte"',
        )
        parser.add_argument(
            '--sin-equipo-central', action='store_true',
            help='No crear el establecimiento de coordinación ni su asistente.',
        )
        parser.add_argument(
            '--actualizar-prompts', action='store_true',
            help='Refresca el system_instruction de los asistentes ya existentes.',
        )

    @transaction.atomic
    def handle(self, *args, **opciones):
        slug = slugify(opciones['slug'])
        if not slug:
            raise CommandError('El slug queda vacío al normalizarlo.')

        nombres = [n.strip() for n in opciones['establecimientos'].split(',') if n.strip()]
        if not nombres:
            raise CommandError('Hay que indicar al menos un establecimiento.')

        organizacion, creada = Organizacion.objects.get_or_create(
            slug=slug, defaults={'nombre': opciones['nombre']},
        )
        self.stdout.write(
            self.style.SUCCESS(f'[+] Organización creada: {organizacion.nombre} ({slug})')
            if creada else f'[=] Organización existente: {organizacion.nombre} ({slug})'
        )

        sedes = []
        for nombre in nombres:
            codigo = slugify(nombre).replace('-', '_').upper()[:20]
            sede, nueva = Establecimiento.objects.get_or_create(
                organizacion=organizacion, codigo=codigo, defaults={'nombre': nombre},
            )
            sedes.append(sede)
            self.stdout.write(f'  {"[+]" if nueva else "[=]"} Establecimiento {codigo} — {nombre}')

        if not opciones['sin_equipo_central']:
            central, nueva = Establecimiento.objects.get_or_create(
                organizacion=organizacion, codigo=EQUIPO_CENTRAL_CODIGO,
                defaults={'nombre': f'Equipo Central {organizacion.nombre}', 'es_equipo_central': True},
            )
            self.stdout.write(f'  {"[+]" if nueva else "[=]"} Equipo central')

        creados = actualizados = existentes = 0

        for sede in sedes:
            for rol, cfg in ROLE_CONFIGS.items():
                asistente_slug = f'{slug}-{rol.lower()}-{sede.codigo.lower()}'
                prompt = _REGLA_URGENCIA + cfg['prompt_fn'](sede.nombre)

                asistente, nuevo = AIAssistant.objects.get_or_create(
                    slug=asistente_slug,
                    defaults={
                        'organizacion': organizacion,
                        'name': f"Asistente {cfg['label']} - {sede.nombre}",
                        'profile_role': rol,
                        'establishment': sede.codigo,
                        'image_name': cfg['image_name'],
                        'is_chat_enabled': True,
                        'description': f"Asistente IA para {cfg['label']} de {sede.nombre}.",
                        'system_instruction': prompt,
                        'motor': MOTOR_POR_DEFECTO,
                    },
                )
                if nuevo:
                    creados += 1
                elif opciones['actualizar_prompts']:
                    asistente.system_instruction = prompt
                    asistente.save(update_fields=['system_instruction'])
                    actualizados += 1
                else:
                    existentes += 1

        if not opciones['sin_equipo_central']:
            slug_central = f'{slug}-central'
            asistente, nuevo = AIAssistant.objects.get_or_create(
                slug=slug_central,
                defaults={
                    'organizacion': organizacion,
                    'name': f'Asistente Equipo Central - {organizacion.nombre}',
                    'profile_role': 'RED',
                    'establishment': EQUIPO_CENTRAL_CODIGO,
                    'image_name': 'red_avatar.png',
                    'motor': MOTOR_POR_DEFECTO,
                    'is_chat_enabled': True,
                    'description': f'Coordinación estratégica de {organizacion.nombre}.',
                    'system_instruction': _prompt_equipo_central(organizacion.nombre, len(sedes)),
                },
            )
            creados += 1 if nuevo else 0

        self.stdout.write(self.style.SUCCESS(
            f'\nAsistentes — creados: {creados} · actualizados: {actualizados} · ya existían: {existentes}'
        ))
        self.stdout.write(f'Acceso: /{slug}/login/')
