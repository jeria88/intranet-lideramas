import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User
from ai_modules.models import AIAssistant, AICase

def setup_users():
    establishments = [
        'TEMUCO', 'LAUTARO', 'RENAICO', 'SANTIAGO', 'IMPERIAL', 'ERCILLA', 'ARAUCO', 'ANGOL'
    ]
    password = "Admin.1234"
    
    # 1. Crear/Habilitar 8 Directores
    for ee in establishments:
        username = f"director.{ee.lower()}"
        if ee == 'SANTIAGO':
            username = "director.santiago" # Normalizado
        
        user, created = User.objects.get_or_create(username=username)
        user.role = 'DIRECTOR'
        user.establishment = ee
        user.set_password(password)
        user.is_active = True
        user.save()
        print(f"{'Created' if created else 'Updated'} user: {username}")

    # 1.1 Crear usuarios de red
    for username in ['luis.jeria', 'ricardo.acuña']:
        user, created = User.objects.get_or_create(username=username)
        user.role = 'RED'
        user.establishment = 'RED'
        user.set_password(password)
        user.is_active = True
        user.save()
        print(f"{'Created' if created else 'Updated'} network user: {username}")

    # 2. Crear director.admin
    admin_user, created = User.objects.get_or_create(username='director.admin')
    admin_user.role = 'DIRECTOR'
    admin_user.establishment = 'RED'
    admin_user.is_staff = False
    admin_user.set_password(password)
    admin_user.is_active = True
    admin_user.save()
    print(f"{'Created' if created else 'Updated'} user: director.admin (Staff)")

def setup_assistants():
    # Obtener el asistente de Temuco como base
    base_assistant = AIAssistant.objects.filter(profile_role='DIRECTOR', establishment='TEMUCO').first()
    if not base_assistant:
        print("Error: No se encontró el asistente base de Temuco (DIRECTOR).")
        return

    establishments = [
        'TEMUCO', 'LAUTARO', 'RENAICO', 'SANTIAGO', 'IMPERIAL', 'ERCILLA', 'ARAUCO', 'ANGOL', 'RED'
    ]

    for ee in establishments:
        slug = f"director-{ee.lower()}"
        name = f"Asistente Estratégico (Director) - {ee.capitalize()}"
        
        assistant, created = AIAssistant.objects.get_or_create(slug=slug)
        assistant.name = name
        assistant.profile_role = 'DIRECTOR'
        assistant.establishment = ee if ee != 'RED' else '' # RED usa genérico o vacío
        assistant.system_instruction = base_assistant.system_instruction
        assistant.context_text = base_assistant.context_text
        assistant.image_name = base_assistant.image_name
        assistant.notebook_url = base_assistant.notebook_url
        assistant.is_chat_enabled = True
        assistant.is_active = True
        assistant.save()
        print(f"{'Created' if created else 'Updated'} assistant: {slug}")

def reset_repositories():
    count = AICase.objects.all().count()
    AICase.objects.all().delete()
    print(f"Reseted repositories: Deleted {count} cases.")

if __name__ == "__main__":
    print("--- Setting up users ---")
    setup_users()
    print("\n--- Setting up assistants ---")
    setup_assistants()
    print("\n--- Resetting repositories ---")
    reset_repositories()
    print("\nSetup complete.")
