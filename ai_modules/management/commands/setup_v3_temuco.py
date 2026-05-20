"""
Comando de management para crear los 5 asistentes v3 de Temuco (uno por rol).

Uso:
    python manage.py setup_v3_temuco
    python manage.py setup_v3_temuco --reset

Slugs: utp-temuco-v3, inspector-temuco-v3, convivencia-temuco-v3,
       director-temuco-v3, representante-temuco-v3

Arquitectura v3:
- Pipeline de 2 etapas: decisión de competencia (temp=0) + respuesta con
  whitelist explícita de citas (temp=0.3).
- Sin post-procesador de regex: la whitelist se construye antes de la
  generación, eliminando citas inventadas en origen.
"""

from django.core.management.base import BaseCommand
from ai_modules.models import AIAssistant
from ai_modules.v3.prompts import prompt_etapa2

EST_CODE = 'TEMUCO'
EST_NAME = 'Temuco'

V3_ROLES = [
    {'role_code': 'UTP',           'label': 'UTP',               'image_name': 'utp.png'},
    {'role_code': 'INSPECTOR',     'label': 'Inspector/a General','image_name': 'inspector.png'},
    {'role_code': 'CONVIVENCIA',   'label': 'Convivencia Escolar','image_name': 'convivencia.png'},
    {'role_code': 'DIRECTOR',      'label': 'Director/a',         'image_name': 'director.png'},
    {'role_code': 'REPRESENTANTE', 'label': 'Representante Legal','image_name': 'representante.png'},
]


class Command(BaseCommand):
    help = 'Crea los 5 asistentes IA v3 de Temuco (pipeline 2 etapas + whitelist de citas).'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Elimina y recrea los asistentes v3.')

    def handle(self, *args, **options):
        reset = options['reset']
        created = updated = 0

        for cfg in V3_ROLES:
            role_code = cfg['role_code']
            slug = f"{role_code.lower()}-{EST_CODE.lower()}-v3"
            # system_instruction guarda el prompt de etapa 2 (para referencia en admin)
            system_prompt = prompt_etapa2(role_code, EST_NAME)

            if reset:
                AIAssistant.objects.filter(slug=slug).delete()
                self.stdout.write(self.style.WARNING(f"  [x] Eliminado: {slug}"))

            assistant, was_created = AIAssistant.objects.get_or_create(
                slug=slug,
                defaults={
                    'name':               f"Asistente {cfg['label']} - {EST_NAME} [v3]",
                    'profile_role':       role_code,
                    'establishment':      EST_CODE,
                    'image_name':         cfg['image_name'],
                    'is_chat_enabled':    True,
                    'description':        f"Asistente IA v3 — {cfg['label']} de {EST_NAME}. Pipeline 2 etapas.",
                    'system_instruction': system_prompt,
                },
            )

            if was_created:
                self.stdout.write(self.style.SUCCESS(f"  [+] Creado:  {slug}"))
                created += 1
            else:
                assistant.system_instruction = system_prompt
                assistant.save(update_fields=['system_instruction'])
                self.stdout.write(self.style.WARNING(f"  [~] Actualizado: {slug}"))
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nListo — {created} creados, {updated} actualizados."
        ))
        self.stdout.write(
            "\nSlugs:\n" +
            "\n".join(f"  • {c['role_code'].lower()}-{EST_CODE.lower()}-v3" for c in V3_ROLES)
        )
