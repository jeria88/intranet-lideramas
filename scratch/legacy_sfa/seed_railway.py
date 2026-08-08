import os
import django
import random
from django.utils import timezone
from datetime import timedelta
from django.conf import settings
import json

# Configurar entorno de Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from meetings.models import MeetingRoom, MeetingBooking
from ai_modules.models import AIAssistant
from library.models import Category

User = get_user_model()

print("🌱 Iniciando SEED (Exclusivo Temuco)...")

# ── 1. Usuarios Demo ──────────────────────────────────────────────────────────
DEMO_USERS = [
    {'username': 'director.demo',     'role': 'DIRECTOR',     'establishment': 'TEMUCO'},
    {'username': 'utp.demo',          'role': 'UTP',          'establishment': 'TEMUCO'},
    {'username': 'inspector.demo',    'role': 'INSPECTOR',    'establishment': 'TEMUCO'},
    {'username': 'convivencia.demo', 'role': 'CONVIVENCIA', 'establishment': 'TEMUCO'},
    {'username': 'red.demo',          'role': 'RED',          'establishment': 'RED'},
]

for ud in DEMO_USERS:
    user, created = User.objects.get_or_create(
        username=ud['username'],
        defaults={
            'first_name': ud['username'].split('.')[0].capitalize(),
            'last_name': 'Demo',
            'role': ud['role'],
            'establishment': ud['establishment'],
            'email': f"{ud['username']}@demo.cl"
        }
    )
    if created:
        user.set_password('Admin1234!')
        user.save()

# ── 2. Asistentes IA Oficiales (Temuco) ───────────────────────────────────────
print("\n🤖 Sincronizando Asistentes IA Temuco...")
ASSISTANTS = [
    {
        'name': 'Asistente Estratégico (Director) - Temuco', 
        'slug': 'director-temuco', 
        'profile_role': 'DIRECTOR', 
        'establishment': 'TEMUCO',
        'is_chat_enabled': True,
        'description': 'Gestión institucional y liderazgo - Temuco.',
        'system_instruction': (
            "Área de Acción: Universal (aplica a cualquier situación).\n"
            "Funciones: Gestionar lo Urgente/Importante, delegar liderazgo, monitorear procesos.\n"
            "Foco: Eisenhower (Urgente/Importante) y aseguramiento de calidad."
        )
    },
    {
        'name': 'Asistente IA UTP Temuco', 
        'slug': 'utp-temuco', 
        'profile_role': 'UTP', 
        'establishment': 'TEMUCO',
        'is_chat_enabled': True,
        'description': 'Gestión curricular y pedagógica - Temuco.',
        'system_instruction': (
            "Área de Acción: Técnico-Pedagógica (Curricular y Pedagógica).\n"
            "Documentos: Reglamento de Evaluación, Decretos 67, 83, 170 y PIE.\n"
            "Foco: Articulación normativa, propuestas evaluativas y vinculación con la familia."
        )
    },
    {
        'name': 'Asistente de Inspector General - Temuco',
        'slug': 'inspector-temuco', 
        'profile_role': 'INSPECTOR', 
        'establishment': 'TEMUCO',
        'is_chat_enabled': True,
        'description': 'Gestión de personal y normativa interna - Temuco.',
        'system_instruction': (
            "Área de Acción: Gestión y Clima Escolar / Personal del establecimiento.\n"
            "Documento Base: RIOHS (Reglamento Interno de Orden, Higiene y Seguridad).\n"
            "Foco: Manejo de conflictos, mediación laboral y clima organizacional."
        )
    },
    {
        'name': 'Asistente de Convivencia Educativa - Temuco',
        'slug': 'convivencia-temuco',
        'profile_role': 'CONVIVENCIA',
        'establishment': 'TEMUCO',
        'is_chat_enabled': True,
        'description': 'Convivencia educativa y resolución de conflictos - Temuco.',
        'system_instruction': (
            "Área de Acción: Convivencia Educativa / Estudiantes y Apoderados.\n"
            "Documento Base: RICE.\n"
            "Foco: Prevención, formación y reparación ante conflictos escolares."
        )
    },
    {
        'name': 'Asistente Representante Legal (Temuco)', 
        'slug': 'representante-temuco', 
        'profile_role': 'REPRESENTANTE', 
        'establishment': 'TEMUCO',
        'is_chat_enabled': True,
        'description': 'Gestión de recursos y contratos - Temuco.',
        'system_instruction': (
            "Área de Acción: Gestión de Contratos y Recursos.\n"
            "Foco: Normativa internacional, Ley 21809, recursos SEP/PIE.\n"
            "Objetivo: Bienestar superior de estudiantes y funcionarios, optimización de recursos."
        )
    },
]

for data in ASSISTANTS:
    assistant, created = AIAssistant.objects.get_or_create(
        slug=data['slug'],
        defaults={k: v for k, v in data.items() if k != 'slug'},
    )
    if not created:
        for key, value in data.items():
            setattr(assistant, key, value)
        assistant.save()
    
    # Sincronizar a la base de conocimiento si es necesario
    try:
        assistant.save(using='knowledge_base')
    except:
        pass

# ── 3. Enriquecimiento de Biblioteca (Descripciones IA) ────────────────────────
print("\n📚 Enriqueciendo descripciones de la biblioteca...")
from library.models import Document
json_path = os.path.join(settings.BASE_DIR, 'library', 'data', 'library_data.json')


if os.path.exists(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        enrichment_data = json.load(f)
    
    count = 0
    # Intentamos emparejar por título (insensible a mayúsculas/minúsculas y espacios)
    for doc in Document.objects.all():
        # Si tiene la descripción genérica, intentamos mejorarla
        if 'Documento importado automáticamente' in doc.description:
            # Buscamos el título exacto o similar en nuestro JSON
            improved_desc = enrichment_data.get(doc.title)
            if improved_desc:
                doc.description = improved_desc
                doc.save()
                count += 1
    
    print(f"✅ Se actualizaron {count} descripciones en la biblioteca.")
else:
    print("⚠️ No se encontró scratch/library_data.json. Saltando enriquecimiento.")

# ── 4. Calendario (Eventos Iniciales) ─────────────────────────────────────────
print("\n📅 Sincronizando eventos del calendario...")
from calendar_red.models import CalendarEvent

CALENDAR_EVENTS = [
    {
        'title': 'Plazo Carga PME - MINEDUC',
        'description': 'Fecha límite para subir el Plan de Mejoramiento Educativo.',
        'event_date': timezone.now().date() + timedelta(days=15),
        'event_type': 'mineduc',
        'is_critical': True
    },
    {
        'title': 'Reunión de Red Mensual',
        'description': 'Coordinación entre directores de la red.',
        'event_date': timezone.now().date() + timedelta(days=5),
        'event_type': 'congregacional',
        'is_critical': False
    },
    {
        'title': 'Cierre de Ciclo de Mejora - Abril',
        'description': 'Verificación de indicadores de abril.',
        'event_date': timezone.now().date() + timedelta(days=20),
        'event_type': 'interno',
        'is_critical': False
    },
]

for ev_data in CALENDAR_EVENTS:
    CalendarEvent.objects.get_or_create(
        title=ev_data['title'],
        event_date=ev_data['event_date'],
        defaults={
            'description': ev_data['description'],
            'event_type': ev_data['event_type'],
            'is_critical': ev_data['is_critical']
        }
    )

print("\n🚀 SEED Temuco completado con éxito.")


