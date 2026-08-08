"""
Comando de management para crear los 5 asistentes v2 de Temuco (uno por rol).

Uso:
    python manage.py setup_v2_temuco
    python manage.py setup_v2_temuco --reset   # elimina y recrea

Los slugs creados son:
    utp-temuco-v2, inspector-temuco-v2, convivencia-temuco-v2,
    director-temuco-v2, representante-temuco-v2

Arquitectura v2:
- system_instruction contiene el prompt mínimo del rol (desde ai_modules/v2/prompts.py).
- Los protocolos específicos se inyectan dinámicamente en runtime (ai_modules/v2/services.py).
- El post-procesamiento filtra artículos Y nombres de documentos no presentes en el RAG.
"""

from django.core.management.base import BaseCommand
from ai_modules.models import AIAssistant
from ai_modules.v2.prompts import ROLE_PROMPTS

EST_CODE = 'TEMUCO'
EST_NAME = 'Temuco'

V2_ROLES = [
    {
        'role_code':  'UTP',
        'label':      'UTP',
        'image_name': 'utp.png',
        'description': f'Asistente IA v2 para la Unidad Técnico-Pedagógica de {EST_NAME}.',
    },
    {
        'role_code':  'INSPECTOR',
        'label':      'Inspector/a General',
        'image_name': 'inspector.png',
        'description': f'Asistente IA v2 para Inspector/a General de {EST_NAME}.',
    },
    {
        'role_code':  'CONVIVENCIA',
        'label':      'Convivencia Escolar',
        'image_name': 'convivencia.png',
        'description': f'Asistente IA v2 para Encargado/a de Convivencia de {EST_NAME}.',
    },
    {
        'role_code':  'DIRECTOR',
        'label':      'Director/a',
        'image_name': 'director.png',
        'description': f'Asistente IA v2 para Director/a de {EST_NAME}.',
    },
    {
        'role_code':  'REPRESENTANTE',
        'label':      'Representante Legal',
        'image_name': 'representante.png',
        'description': f'Asistente IA v2 para Representante Legal de {EST_NAME}.',
    },
]


class Command(BaseCommand):
    help = 'Crea los 5 asistentes IA v2 de Temuco (uno por rol) para pruebas de arquitectura.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Elimina los asistentes v2 existentes y los recrea desde cero.',
        )

    def handle(self, *args, **options):
        reset = options['reset']
        created_count = 0
        updated_count = 0

        for cfg in V2_ROLES:
            role_code = cfg['role_code']
            slug = f"{role_code.lower()}-{EST_CODE.lower()}-v2"
            prompt_fn = ROLE_PROMPTS[role_code]
            system_prompt = prompt_fn(EST_NAME)

            if reset:
                AIAssistant.objects.filter(slug=slug).delete()
                self.stdout.write(self.style.WARNING(f"  [x] Eliminado: {slug}"))

            assistant, created = AIAssistant.objects.get_or_create(
                slug=slug,
                defaults={
                    'name':               f"Asistente {cfg['label']} - {EST_NAME} [v2]",
                    'profile_role':       role_code,
                    'establishment':      EST_CODE,
                    'image_name':         cfg['image_name'],
                    'is_chat_enabled':    True,
                    'description':        cfg['description'],
                    'system_instruction': system_prompt,
                },
            )

            if created:
                self.stdout.write(self.style.SUCCESS(f"  [+] Creado:  {slug}"))
                created_count += 1
            else:
                # Actualizar prompt en caso de que el asistente ya exista
                assistant.system_instruction = system_prompt
                assistant.save(update_fields=['system_instruction'])
                self.stdout.write(self.style.WARNING(f"  [~] Prompt actualizado: {slug}"))
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\nListo — {created_count} creados, {updated_count} actualizados."
            )
        )
        self.stdout.write(
            "\nSlugs disponibles:\n"
            + "\n".join(f"  • {cfg['role_code'].lower()}-{EST_CODE.lower()}-v2" for cfg in V2_ROLES)
        )
        self.stdout.write(
            "\nPara testear con el eval, actualiza la suite apuntando a estos slugs."
        )
