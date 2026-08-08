import os
import django

# Configurar entorno de Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from ai_modules.models import AIAssistant

User = get_user_model()

# Configuración solicitada
ESTABLISHMENTS = ['TEMUCO', 'ERCILLA', 'IMPERIAL']
ROLES = ['REPRESENTANTE', 'UTP', 'DIRECTOR', 'INSPECTOR', 'CONVIVENCIA']
TEMP_PASSWORD = 'SanFrancisco2026!'

def regularize():
    print("🌱 Iniciando Regularización de Datos para Railway...")

    # 1. Reset passwords for ALL users
    print("\n🔐 1. Reseteando contraseñas para TODOS los usuarios del sistema...")
    all_users = User.objects.all()
    count = 0
    for user in all_users:
        user.set_password(TEMP_PASSWORD)
        user.save()
        count += 1
    print(f"   ✅ {count} usuarios actualizados con la clave temporal: {TEMP_PASSWORD}")

    # 2. Create/Verify users for the 3 active establishments
    print("\n👥 2. Verificando usuarios por establecimiento y rol (3 establecimientos × 5 roles)...")
    for est in ESTABLISHMENTS:
        for role in ROLES:
            username = f"{role.lower()}.{est.lower()}"
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'role': role,
                    'establishment': est,
                    'is_active': True,
                    'first_name': role.capitalize(),
                    'last_name': est.capitalize(),
                    'email': f"{username}@sfa.cl"
                }
            )
            
            # Asegurar que los datos sean correctos si el usuario ya existía
            user.role = role
            user.establishment = est
            user.is_active = True
            user.set_password(TEMP_PASSWORD)
            user.save()
            
            status = "Creado" if created else "Actualizado"
            print(f"   - {username} [{role} - {est}]: {status}")

    # 3. Consolidate AI Assistants (Global Temuco Knowledge Base)
    print("\n🤖 3. Consolidando asistentes IA (Usar base de Temuco para todos)...")
    # Los asistentes que tienen 'TEMUCO' se vuelven globales quitando el establecimiento
    assistants = AIAssistant.objects.filter(establishment='TEMUCO')
    for assistant in assistants:
        old_name = assistant.name
        assistant.establishment = '' # Convertir en global para que coincida con cualquier usuario del mismo rol
        # Opcional: Quitar "Temuco" del nombre para que sea más genérico
        if " - Temuco" in assistant.name:
            assistant.name = assistant.name.replace(" - Temuco", "")
        elif " Temuco" in assistant.name:
            assistant.name = assistant.name.replace(" Temuco", "")
            
        assistant.save()
        print(f"   - Asistente {assistant.slug}: Ahora es GLOBAL (Nombre anterior: {old_name})")

    # Asegurar que el director-general sea global
    dg = AIAssistant.objects.filter(slug='director-general').first()
    if dg:
        dg.establishment = ''
        dg.save()
        print("   - Asistente director-general: Confirmado como GLOBAL.")

    print("\n🚀 Proceso de regularización completado con éxito.")
    print("⚠️  Recuerda ejecutar 'python manage.py collectstatic' si es necesario.")

if __name__ == "__main__":
    regularize()
