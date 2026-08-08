from django.core.management.base import BaseCommand
from ai_modules.models import AIAssistant

class Command(BaseCommand):
    help = 'Aplica el nuevo protocolo institucional San Francisco de Asís a todos los asistentes IA.'

    def handle(self, *args, **options):
        # 1. Definir instrucciones por rol basadas en el nuevo prompt
        protocols = {
            'REPRESENTANTE': (
                "Área de Acción: Gestión de Contratos y Recursos.\n"
                "Foco: Normativa internacional, Ley 21809, recursos SEP/PIE.\n"
                "Objetivo: Bienestar superior de estudiantes y funcionarios, optimización de recursos."
            ),
            'DIRECTOR': (
                "Área de Acción: Universal (aplica a cualquier situación).\n"
                "Funciones: Gestionar lo Urgente/Importante, delegar liderazgo, monitorear procesos.\n"
                "Foco: Eisenhower (Urgente/Importante) y aseguramiento de calidad."
            ),
            'INSPECTOR': (
                "Área de Acción: Gestión y Clima Escolar / Personal del establecimiento.\n"
                "Documento Base: RIOHS (Reglamento Interno de Orden, Higiene y Seguridad).\n"
                "Foco: Manejo de conflictos, mediación laboral y clima organizacional."
            ),
            'CONVIVENCIA': (
                "Área de Acción: Convivencia Educativa / Estudiantes y Apoderados.\n"
                "Documento Base: RICE.\n"
                "Foco: Prevención, formación y reparación ante conflictos escolares."
            ),
            'UTP': (
                "Área de Acción: Técnico-Pedagógica (Curricular y Pedagógica).\n"
                "Documentos: Reglamento de Evaluación, Decretos 67, 83, 170 y PIE.\n"
                "Foco: Articulación normativa, propuestas evaluativas y vinculación con la familia."
            )
        }

        self.stdout.write("🤖 Actualizando instrucciones de asistentes...")
        
        for role, instruction in protocols.items():
            assistants = AIAssistant.objects.filter(profile_role=role)
            count = assistants.update(system_instruction=instruction)
            self.stdout.write(self.style.SUCCESS(f"  - {role}: {count} asistentes actualizados."))

        self.stdout.write(self.style.SUCCESS("✅ Protocolo aplicado correctamente."))
