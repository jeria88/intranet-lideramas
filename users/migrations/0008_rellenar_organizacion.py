"""Rellena `organizacion` en las filas históricas de todos los modelos aislados.

Una sola migración para los 18 modelos en vez de una por app: la lógica de
"¿de qué organización es esta fila?" es la misma en todos, y repetirla diez veces
es diez lugares donde puede divergir.

Orden de inferencia, del dato más fuerte al más débil:
  1. Si el modelo tiene FK a un usuario que ya tiene organización → esa.
  2. Si tiene un CharField de establecimiento → la organización de esa sede.
  3. Si existe una única organización en la base → esa.
  4. Si no → se deja NULL. Preferible a adivinar: una fila sin organización no
     se le muestra a nadie (`visibles_para` devuelve `none()`), mientras que una
     fila con la organización equivocada se le muestra al cliente equivocado.
"""
from django.db import migrations

# (app_label, modelo). Solo raíces de agregado: los hijos se filtran por su padre.
MODELOS_AISLADOS = [
    ('ai_modules', 'AIAssistant'),
    ('ai_modules', 'ChatConversation'),
    ('ai_modules', 'AICase'),
    ('ai_modules', 'AIQuery'),
    ('portal', 'Circular'),
    ('library', 'Category'),
    ('library', 'Document'),
    ('calendar_red', 'CalendarEvent'),
    ('messaging', 'Message'),
    ('meetings', 'MeetingRoom'),
    ('meetings', 'MeetingBooking'),
    ('improvement_cycle', 'ImprovementGoal'),
    ('simce', 'Prueba'),
    ('simce', 'TextoBiblioteca'),
    ('simce', 'SimceDocumento'),
    ('eventos', 'EventoCultural'),
    ('evidencia', 'EvaluationForm'),
    ('evidencia', 'EvidenceDocument'),
]

# Nombres de CharField que apuntan a un establecimiento, por preferencia.
CAMPOS_ESTABLECIMIENTO = ('establishment', 'target_establishment')


def _campos_de_usuario(Model, User):
    """FKs a usuario, en orden de autoría: quien creó la fila manda sobre quien la aprobó."""
    preferidos = ('created_by', 'creada_por', 'author', 'booked_by', 'user',
                  'uploaded_by', 'sender', 'responsible')
    nombres = [
        f.name for f in Model._meta.get_fields()
        if getattr(f, 'many_to_one', False) and getattr(f, 'related_model', None) is User
    ]
    return sorted(nombres, key=lambda n: preferidos.index(n) if n in preferidos else 99)


def rellenar(apps, schema_editor):
    Organizacion = apps.get_model('users', 'Organizacion')
    Establecimiento = apps.get_model('users', 'Establecimiento')
    User = apps.get_model('users', 'User')

    organizaciones = list(Organizacion.objects.all())
    unica = organizaciones[0] if len(organizaciones) == 1 else None

    sedes_por_codigo = {}
    for est in Establecimiento.objects.all():
        sedes_por_codigo.setdefault(est.codigo, est.organizacion_id)

    for app_label, nombre in MODELOS_AISLADOS:
        Model = apps.get_model(app_label, nombre)
        pendientes = Model.objects.filter(organizacion__isnull=True)
        if not pendientes.exists():
            continue

        campos_usuario = _campos_de_usuario(Model, User)
        campo_sede = next(
            (c for c in CAMPOS_ESTABLECIMIENTO
             if c in {f.name for f in Model._meta.get_fields()}),
            None,
        )

        for fila in pendientes.iterator():
            org_id = None

            for campo in campos_usuario:
                usuario = getattr(fila, campo, None)
                if usuario is not None and usuario.organizacion_id:
                    org_id = usuario.organizacion_id
                    break

            if org_id is None and campo_sede:
                codigo = (getattr(fila, campo_sede, '') or '').strip().upper()
                org_id = sedes_por_codigo.get(codigo)

            if org_id is None and unica is not None:
                org_id = unica.pk

            if org_id is not None:
                Model.objects.filter(pk=fila.pk).update(organizacion_id=org_id)


def vaciar(apps, schema_editor):
    for app_label, nombre in MODELOS_AISLADOS:
        apps.get_model(app_label, nombre).objects.update(organizacion=None)


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0007_consolidar_establecimientos_duplicados'),
        ('ai_modules', '0025_aiassistant_organizacion_aicase_organizacion_and_more'),
        ('portal', '0003_circular_organizacion'),
        ('library', '0004_category_organizacion_document_organizacion_and_more'),
        ('calendar_red', '0004_calendarevent_organizacion_and_more'),
        ('messaging', '0003_message_organizacion'),
        ('meetings', '0012_meetingbooking_organizacion_meetingroom_organizacion'),
        ('improvement_cycle', '0010_improvementgoal_organizacion_and_more'),
        ('simce', '0006_alter_sesionestudiante_options_prueba_organizacion_and_more'),
        ('eventos', '0002_eventocultural_organizacion'),
        ('evidencia', '0003_evaluationform_organizacion_and_more'),
    ]

    operations = [
        migrations.RunPython(rellenar, vaciar),
    ]
