"""Punto único de despacho a los motores de respuesta.

Coexisten tres implementaciones. Hasta ahora se elegían por el **sufijo del
slug** del asistente (`ai_modules/views.py`: `slug.endswith('-v3')`), que es
acoplar el comportamiento al nombre: al prefijar los slugs por organización
(`<org>-<rol>-<sede>`) ningún asistente terminaba en `-v3` y todos pasaban a
responder con v1 sin que nada lo avisara.

Ahora la elección es un campo del modelo (`AIAssistant.motor`) y este módulo es
el único lugar que la resuelve.

Por qué siguen los tres: v3 es el recomendado y el default de fábrica — dos
etapas (competencia y respuesta) con bloque de citas verificadas, que es lo que
ataca la alucinación de artículos normativos. v1 y v2 se conservan hasta que
`manage.py eval_assistants` confirme que v3 no regresiona ningún caso que ellos
resuelvan bien. Borrarlos antes de esa medición sería descartar comportamiento a
ciegas; ver la tarea F2 del loop.
"""
from .services import call_deepseek_ai
from .v2.services import call_ai_v2
from .v3.services import call_ai_v3

MOTOR_POR_DEFECTO = 'v3'

# Nombres, no referencias: guardar la función directa la congela en el momento
# del import y deja el despacho fuera del alcance de cualquier `patch`, que es
# como se prueba esto sin gastar llamadas reales al proveedor.
_MOTORES = {
    'v1': 'call_deepseek_ai',
    'v2': 'call_ai_v2',
    'v3': 'call_ai_v3',
}


def responder(assistant, history, user_query, attached_content=None):
    """Responde con el motor configurado en el asistente."""
    elegido = getattr(assistant, 'motor', None) or MOTOR_POR_DEFECTO
    # Un valor desconocido en la BD no puede dejar al usuario sin respuesta.
    nombre = _MOTORES.get(elegido, _MOTORES[MOTOR_POR_DEFECTO])
    return globals()[nombre](assistant, history, user_query, attached_content=attached_content)
