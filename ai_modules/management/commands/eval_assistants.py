"""
Eval framework completo — Red SFA
Testea: (1) citación real desde RAG, (2) derivación correcta entre roles,
        (3) lenguaje imperativo/conclusivo, (4) artículos prohibidos.

Uso:
    python manage.py eval_assistants                        # todos los casos
    python manage.py eval_assistants --caso TC001           # un caso
    python manage.py eval_assistants --suite derivacion     # solo derivación
    python manage.py eval_assistants --suite cruce --est temuco  # cruce solo Temuco
    python manage.py eval_assistants --est temuco           # todos los casos de Temuco
    python manage.py eval_assistants --sin-juez             # checks básicos sin LLM juez
"""
import json
import os
import re
import requests
from datetime import datetime
from django.conf import settings
from django.core.management.base import BaseCommand
from ai_modules.models import AIAssistant
from ai_modules.services import call_deepseek_ai
from ai_modules.utils import get_relevant_chunks


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 1 — CASOS PEDAGÓGICOS UTP
# Testea: citación normativa, PACI, evaluación diferenciada, urgencia
# ══════════════════════════════════════════════════════════════════════════════

CASOS_UTP = [
    {
        "id": "TC001", "suite": "utp",
        "slug": "utp-temuco",
        "titulo": "Sofía 1° Básico — NEE sin diagnóstico formal",
        "query": (
            "Soy la profesora jefe de 1° Básico A. Sofía (6 años) presenta dificultades graves en "
            "lectura y escritura: no reconoce vocales ni sílabas. Propuse activar el PIE pero la "
            "coordinadora dice que sin diagnóstico formal no puede iniciar adecuaciones. La apoderada "
            "no entregó los informes médicos (plazo vencido: 15 de abril). Sofía tiene promedio 3.8 "
            "y 92% de asistencia. Pido a UTP que medie para evitar la repitencia."
        ),
        "debe_incluir": ["Decreto 83", "adecuaciones"],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "rol_esperado": "SÍ",
        "deriva_a": None,
        "articulos_inventables": [],
        "criterios_juez": [
            "Reconoce que se pueden aplicar medidas provisionales sin diagnóstico formal (Decreto 83)",
            "Propone mediación explícita entre coordinadora PIE, apoderada y docente",
            "No activa denuncia penal",
            "Usa lenguaje imperativo para las medidas (debe, tiene que, es obligatorio)",
        ],
    },
    {
        "id": "TC002", "suite": "utp",
        "slug": "utp-temuco",
        "titulo": "Benjamín 2° Básico — TEL, nota 2.3 por no traer flauta",
        "query": (
            "Mi hijo Benjamín (7 años) recibió 2.3 en Música porque no llevó su flauta. "
            "Tiene TEL mixto diagnosticado (informe entregado al PIE en marzo). El profesor avisó "
            "los materiales solo el día anterior. En su PACI están las adecuaciones curriculares. "
            "Pido que se anule la calificación y se aplique evaluación diferenciada."
        ),
        "debe_incluir": ["PACI", "adecuaciones"],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa", "Ley 21.545"],
        "rol_esperado": "SÍ",
        "deriva_a": None,
        "articulos_inventables": [],
        "criterios_juez": [
            "Declara que la calificación debe anularse por incumplimiento del PACI",
            "Propone nueva evaluación diferenciada con otro instrumento o momento",
            "No activa denuncia penal",
            "No cita Ley 21.545 (es TEL, no TEA)",
        ],
    },
    {
        "id": "TC003", "suite": "utp",
        "slug": "utp-temuco",
        "titulo": "Valentina 5° Básico — descuento por ortografía en Matemática",
        "query": (
            "El profesor de Matemática descontó décimas por ortografía en una prueba de fracciones. "
            "Mi hija obtuvo 5.2 en contenido pero bajó a 4.5. El profesor no informó antes que "
            "descontaría por ortografía. ¿Puede hacer eso? Solicito restituir la nota 5.2."
        ),
        "debe_incluir": ["Decreto 67", "evaluación"],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "rol_esperado": "SÍ",
        "deriva_a": None,
        "articulos_inventables": [],
        "criterios_juez": [
            "Responde SÍ o NO a la pregunta '¿puede hacer eso?' con fundamento normativo",
            "Señala que el docente debió informar los criterios con anticipación (Decreto 67)",
            "No activa denuncia penal",
            "Toma posición sobre restituir o no la nota, no evade la pregunta",
        ],
    },
    {
        "id": "TC004", "suite": "utp",
        "slug": "utp-temuco",
        "titulo": "Matías 6° Básico — TDAH, traspaso incorrecto, PACI no respetado",
        "query": (
            "Mi hijo Matías tiene TDAH. En la prueba marcó respuestas correctas en el fascículo pero "
            "las traspasó mal a la hoja de respuestas. Obtuvo 3.2. En su PACI está especificado que "
            "debe tener apoyo en traspaso de respuestas y tiempo extra. La profesora no le ofreció "
            "ayuda. Pido que se invalide la calificación y se aplique evaluación diferenciada."
        ),
        "debe_incluir": ["PACI", "adecuaciones"],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "rol_esperado": "SÍ",
        "deriva_a": None,
        "articulos_inventables": [],
        "criterios_juez": [
            "Declara que la calificación debe invalidarse por incumplimiento del PACI",
            "Propone nueva evaluación con los ajustes especificados en el PACI",
            "No activa denuncia penal",
            "Menciona la responsabilidad del educador diferencial de estar presente",
        ],
    },
    {
        "id": "TC005", "suite": "utp",
        "slug": "utp-temuco",
        "titulo": "Cristóbal 7° Básico — trabajo grupal, exigen subir nota a 5.0",
        "query": (
            "Mi hijo sin NEE obtuvo 3.3 en Ciencias con rúbrica individual. La profesora registró que "
            "no trabajó en clases. El resto del equipo tuvo 6.0. Reclamo discriminación y exijo "
            "que le suban la nota a 5.0 por el trabajo grupal."
        ),
        "debe_incluir": ["Decreto 67", "evaluación"],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "rol_esperado": "SÍ",
        "deriva_a": None,
        "articulos_inventables": [],
        "criterios_juez": [
            "Reconoce el derecho de la profesora a evaluar desempeño individual",
            "No concede la demanda de subir a 5.0 sin causa normativa",
            "Distingue correctamente entre bajo desempeño individual y discriminación",
            "No activa denuncia penal",
        ],
    },
    {
        "id": "TC006", "suite": "utp",
        "slug": "utp-temuco",
        "titulo": "Ignacio 6° Básico — TEA nivel 1, profesora Inglés no califica carpeta PIE",
        "query": (
            "Mi hijo Ignacio tiene TEA nivel 1. El equipo PIE elaboró una carpeta de trabajo con "
            "ajustes razonables para rendir evaluaciones en sala de recursos. La profesora de Inglés "
            "se niega a calificar esa carpeta. El niño lleva dos evaluaciones sin nota. "
            "Pido que se ordene a la profesora calificar la carpeta."
        ),
        "debe_incluir": ["ajuste", "Decreto"],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "rol_esperado": "SÍ",
        "deriva_a": None,
        "articulos_inventables": [],
        "criterios_juez": [
            "Ordena explícitamente a la profesora calificar la carpeta como evaluación válida",
            "Puede citar Ley 21.545 (caso SÍ es TEA confirmado — uso correcto)",
            "Propone regularizar las dos notas pendientes con la carpeta ya elaborada",
            "No activa denuncia penal",
        ],
    },
    {
        "id": "TC007", "suite": "utp",
        "slug": "utp-temuco",
        "titulo": "Camila 7° Básico — FIL, copiando, PACI no respetado",
        "query": (
            "Soy la educadora diferencial. Camila tiene FIL y su PACI contempla evaluación en espacio "
            "separado con supervisión mía. La profesora la sorprendió copiando y le puso 4.6 sin "
            "respetar esa adecuación. La conducta de copiar está asociada a su ansiedad y baja "
            "memoria operativa. Pido que se anule el 4.6 y se aplique nueva evaluación."
        ),
        "debe_incluir": ["PACI", "adecuaciones"],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "rol_esperado": "SÍ",
        "deriva_a": None,
        "articulos_inventables": [],
        "criterios_juez": [
            "Reconoce que el PACI fue incumplido (evaluación separada no aplicada)",
            "Contextualiza el copiar como conducta asociada al FIL antes de sancionar",
            "Propone nueva evaluación con los apoyos del PACI",
            "Aborda el debido proceso para la docente, no la condena directa",
        ],
    },
    {
        "id": "TC008", "suite": "utp",
        "slug": "utp-temuco",
        "titulo": "Benjamín 8° Básico — Artes, abuela exige 7.0, amenaza Superintendencia",
        "query": (
            "Soy el profesor de Artes. Benjamín no trajo materiales en tres clases. Le facilité desde "
            "UTP pero no trabajó. Apliqué rúbrica firmada por el apoderado: nota 3.3. La abuela "
            "aparece hoy exigiendo 7.0 y amenazando con Superintendencia. Pido que UTP respalde "
            "la calificación."
        ),
        "debe_incluir": ["Reglamento", "evaluación"],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "rol_esperado": "SÍ",
        "deriva_a": None,
        "articulos_inventables": [],
        "criterios_juez": [
            "Respalda al docente si aplicó el reglamento y la rúbrica correctamente",
            "No cede a la demanda de cambiar la nota a 7.0",
            "Informa el canal correcto de reclamo para el apoderado",
            "No activa denuncia penal",
        ],
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 2 — DERIVACIÓN ENTRE ROLES
# Testea: que cada asistente reconozca qué le corresponde y qué no
# ══════════════════════════════════════════════════════════════════════════════

CASOS_DERIVACION = [
    {
        "id": "TD001", "suite": "derivacion",
        "slug": "utp-temuco",
        "titulo": "UTP recibe caso de convivencia pura → debe derivar a Convivencia",
        "query": (
            "Dos estudiantes de 8° básico se agarraron a golpes en el patio durante el recreo. "
            "Uno tiene moretones en la cara. El inspector no estaba presente. ¿Qué hago?"
        ),
        "debe_incluir": [],
        "no_debe_incluir": [],
        "rol_esperado": "NO",
        "deriva_a": "Inspector General",
        "articulos_inventables": [],
        "criterios_juez": [
            "Reconoce que la situación NO corresponde a su rol como UTP",
            "Deriva explícitamente a Inspector General o Convivencia Educativa",
            "No desarrolla PASO 2, 3 ni 4 (o los acota a una sola línea de derivación)",
            "Activa correctamente la alerta de urgencia por violencia física con lesiones",
        ],
    },
    {
        "id": "TD002", "suite": "derivacion",
        "slug": "inspector-temuco",
        "titulo": "Inspector recibe caso de evaluación diferenciada → debe derivar a UTP",
        "query": (
            "Un apoderado llega a Inspectoría reclamando que el profesor de Historia le puso 3.0 "
            "a su hijo porque no tenía su PACI actualizado. El niño tiene TDAH diagnosticado. "
            "El apoderado pide que se anule la nota. ¿Puedo resolver esto desde Inspectoría?"
        ),
        "debe_incluir": [],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "rol_esperado": "NO",
        "deriva_a": "UTP",
        "articulos_inventables": [],
        "criterios_juez": [
            "Reconoce que la situación de evaluación y PACI corresponde a UTP, no a Inspectoría",
            "Deriva explícitamente a Jefatura UTP",
            "No activa denuncia penal",
            "No resuelve el fondo (no anula ni valida la nota — eso es competencia UTP)",
        ],
    },
    {
        "id": "TD003", "suite": "derivacion",
        "slug": "utp-temuco",
        "titulo": "UTP recibe caso de contrato docente → debe derivar a Representante",
        "query": (
            "Soy profesor de Matemática. Me dijeron que este año no me renovarán el contrato "
            "porque 'no cumplo el perfil'. No se me notificó con anticipación y no firmé nada. "
            "¿Qué derechos tengo? ¿UTP puede intervenir?"
        ),
        "debe_incluir": [],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "rol_esperado": "NO",
        "deriva_a": "Representante Legal",
        "articulos_inventables": [],
        "criterios_juez": [
            "Reconoce que la desvinculación docente es competencia del Representante Legal, no UTP",
            "Deriva explícitamente al Representante Legal o Dirección",
            "No activa denuncia penal",
            "No resuelve el fondo ni calcula indemnizaciones",
        ],
    },
    {
        "id": "TD004", "suite": "derivacion",
        "slug": "convivencia-temuco",
        "titulo": "Convivencia recibe caso de ridiculización + docente no interviene",
        "query": (
            "Un estudiante con dislexia está siendo ridiculizado por sus compañeros en clases "
            "por leer despacio. El docente no interviene. El estudiante ya no quiere ir al colegio."
        ),
        "debe_incluir": ["RICE", "protocolo"],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "rol_esperado": "SÍ",
        "deriva_a": None,
        "articulos_inventables": [],
        "criterios_juez": [
            "Reconoce que corresponde a Convivencia Educativa (SÍ es su rol)",
            "No activa denuncia penal para ridiculización verbal",
            "Activa protocolo RICE para la situación de acoso entre pares",
            "Deriva la parte pedagógica (dislexia, PACI) a UTP",
        ],
    },
    {
        "id": "TD005", "suite": "derivacion",
        "slug": "director-temuco",
        "titulo": "Director recibe caso pedagógico que corresponde a UTP",
        "query": (
            "Como director, me llega un apoderado reclamando que el profesor de Lenguaje "
            "no está aplicando las adecuaciones curriculares del PACI de su hijo con dislexia. "
            "El niño tiene notas bajas y el apoderado pide que se cambie al profesor. ¿Qué hago?"
        ),
        "debe_incluir": [],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "rol_esperado": "SÍ",
        "deriva_a": "UTP",
        "articulos_inventables": [],
        "criterios_juez": [
            "El Director reconoce su rol institucional pero delega la parte técnica a UTP",
            "No activa denuncia penal",
            "No accede a cambiar al profesor sin proceso formal",
            "Propone derivar a UTP para verificar aplicación del PACI",
        ],
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 3 — CRUCE ENTRE ROLES (mismo caso → 5 asistentes de Temuco)
# Testea: quién dice SÍ, quién dice NO, y si la derivación es correcta
# ══════════════════════════════════════════════════════════════════════════════

SLUGS_TEMUCO = [
    "utp-temuco",
    "inspector-temuco",
    "convivencia-temuco",
    "director-temuco",
    "representante-temuco",
]

# Mapa de slugs de cruce por establecimiento.
# Añadir nueva entrada cuando se incorpore otro establecimiento.
SLUGS_CRUCE_POR_EST = {
    "temuco": SLUGS_TEMUCO,
}

CASOS_CRUCE = [
    {
        "id": "TX001", "suite": "cruce",
        "titulo": "PACI incumplido — ¿quién responde entre los 5 roles?",
        "query": (
            "Un estudiante de 6° Básico con TDAH y PACI vigente rindió una prueba de Historia. "
            "La profesora no aplicó las adecuaciones (tiempo extra y apoyo en traspaso). "
            "El estudiante marcó las respuestas correctas en el fascículo pero las traspasó "
            "mal y sacó 3.2. ¿Qué hacemos con esta situación?"
        ),
        "slug_propietario": "utp-temuco",
        "esperado_por_slug": {
            "utp-temuco":            {"rol": "SÍ"},
            "inspector-temuco":      {"rol": "NO", "deriva": "UTP"},
            "convivencia-temuco":    {"rol": "NO", "deriva": "UTP"},
            "director-temuco":       {"rol": "SÍ_O_NO", "deriva": "UTP"},  # puede coordinar pero delega técnico a UTP
            "representante-temuco":  {"rol": "NO", "deriva": "UTP"},
        },
        "debe_incluir": ["PACI", "adecuaciones"],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "criterios_propietario": [
            "Señala que la nota aplicada sin respetar el PACI no tiene validez o debe revisarse",
            "Propone nueva evaluación diferenciada o con los apoyos del PACI",
            "No activa urgencia penal",
            "Usa al menos un verbo imperativo o directivo (debe, tiene que, corresponde anular, se debe aplicar)",
        ],
    },
    {
        "id": "TX002", "suite": "cruce",
        "titulo": "Pelea física con lesiones — ¿quién activa el protocolo de urgencia?",
        "query": (
            "Un estudiante de 7° Básico golpeó a otro en el recreo. El agredido tiene un "
            "corte en el labio que sangra y dice que le duele la cabeza. Estoy en la sala "
            "de clases cuando me avisan. ¿Qué hago?"
        ),
        "slug_propietario": "inspector-temuco",
        "esperado_por_slug": {
            "utp-temuco":            {"rol": "NO", "deriva": "Inspector"},
            "inspector-temuco":      {"rol": "SÍ"},
            "convivencia-temuco":    {"rol": "NO", "deriva": "Inspector"},
            "director-temuco":       {"rol": "NO", "deriva": "Inspector"},
            "representante-temuco":  {"rol": "NO", "deriva": "Inspector"},
        },
        "debe_incluir": [],
        "no_debe_incluir": [],
        "criterios_propietario": [
            "Atiende la urgencia médica de forma inmediata",
            "Activa el protocolo de violencia física según RICE",
            "Documenta el incidente y notifica a apoderados de ambos",
            "No activa denuncia penal automática (verifica gravedad de lesiones primero)",
        ],
    },
    {
        "id": "TX003", "suite": "cruce",
        "titulo": "Bullying por redes sociales — ¿quién aplica el RICE?",
        "query": (
            "Un grupo de estudiantes de 8° Básico lleva tres semanas publicando memes "
            "burlándose del peso de una compañera en Instagram. La víctima llora todos "
            "los días y ya no quiere venir al colegio. ¿Qué protocolo activo?"
        ),
        "slug_propietario": "convivencia-temuco",
        "esperado_por_slug": {
            "utp-temuco":            {"rol": "NO", "deriva": "Convivencia"},
            "inspector-temuco":      {"rol": "NO", "deriva": "Convivencia"},
            "convivencia-temuco":    {"rol": "SÍ"},
            "director-temuco":       {"rol": "NO", "deriva": "Convivencia"},
            "representante-temuco":  {"rol": "NO", "deriva": "Convivencia"},
        },
        "debe_incluir": [],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "criterios_propietario": [
            "Activa el protocolo RICE de bullying/acoso escolar",
            "No activa denuncia penal (bullying sin violencia física)",
            "Propone contención para la víctima y proceso formativo para los agresores",
            "Incluye plan de seguimiento y notificación a apoderados",
        ],
    },
    {
        "id": "TX004", "suite": "cruce",
        "titulo": "Renuncia voluntaria de docente — ¿quién gestiona el finiquito?",
        "query": (
            "La profesora de Lenguaje quiere renunciar voluntariamente a fin de mes. "
            "Me pide que le informe cómo procede su finiquito y qué plazos de aviso "
            "debe dar. ¿Desde qué estamento se maneja esto?"
        ),
        "slug_propietario": "representante-temuco",
        "esperado_por_slug": {
            "utp-temuco":            {"rol": "NO", "deriva": "Representante Legal"},
            "inspector-temuco":      {"rol": "NO", "deriva": "Representante Legal"},
            "convivencia-temuco":    {"rol": "NO", "deriva": "Representante Legal"},
            "director-temuco":       {"rol": "NO", "deriva": "Representante Legal"},
            "representante-temuco":  {"rol": "SÍ"},
        },
        "debe_incluir": [],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "criterios_propietario": [
            "Aborda el proceso de renuncia voluntaria y finiquito",
            "Menciona Código del Trabajo o Estatuto Docente sin inventar artículos específicos",
            "No activa urgencia penal",
            "Clarifica los plazos de aviso previo aplicables",
        ],
    },
    {
        "id": "TX005", "suite": "cruce",
        "titulo": "Apoderado amenaza a docente — coordinación multi-estamento",
        "query": (
            "Un apoderado llegó al colegio agresivo y le gritó al profesor de Historia "
            "frente a los estudiantes: 'si no cambia la nota de mi hijo le va a pesar'. "
            "El profesor está muy alterado y pide que se haga algo. ¿Cómo actuamos?"
        ),
        "slug_propietario": "director-temuco",
        # Inspector y Convivencia tienen competencia parcial — también pueden decir SÍ
        "slugs_competencia_parcial": ["inspector-temuco", "convivencia-temuco"],
        "esperado_por_slug": {
            "utp-temuco":            {"rol": "NO", "deriva": "Director"},
            "inspector-temuco":      {"rol": "SÍ_O_NO", "deriva": "Director"},
            "convivencia-temuco":    {"rol": "SÍ_O_NO", "deriva": "Director"},
            "director-temuco":       {"rol": "SÍ"},
            "representante-temuco":  {"rol": "NO", "deriva": "Director"},
        },
        "debe_incluir": [],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "criterios_propietario": [
            "Coordina la respuesta institucional ante el apoderado agresivo",
            "No activa denuncia penal obligatoria (amenaza verbal sin violencia física)",
            "Involucra a Inspector General y Convivencia en el manejo del caso",
            "Protege al docente afectado y documenta el incidente",
        ],
    },
]


TODOS_LOS_CASOS = CASOS_UTP + CASOS_DERIVACION + CASOS_CRUCE


# ══════════════════════════════════════════════════════════════════════════════
# JUEZ LLM — incluye el contexto RAG para verificar si las citas son reales
# ══════════════════════════════════════════════════════════════════════════════

PROMPT_JUEZ = """Eres un evaluador experto en normativa educacional chilena.

ROL ESPERADO: {rol_esperado}
DERIVA A: {deriva_a}

CONTEXTO RAG ENVIADO AL ASISTENTE (documentos reales recuperados):
---
{rag_context}
---

RESPUESTA DEL ASISTENTE:
---
{respuesta}
---

CRITERIOS A EVALUAR:
{criterios}

TAREA ADICIONAL — VERIFICACIÓN DE CITAS:
Revisa si los artículos o anexos específicos citados en la respuesta aparecen efectivamente \
en el contexto RAG. Si el asistente cita artículos con número que NO aparecen literalmente \
en el contexto RAG, son potencialmente inventados. Solo reporta los que veas en la respuesta.

Responde ÚNICAMENTE con JSON válido:
{{"criterios":[{{"criterio":"...","resultado":"PASS o FAIL","razon":"max 15 palabras"}},...],\
"articulos_inventados":["lista de artículos citados sin respaldo en el RAG, o [] si todos tienen respaldo"],\
"articulos_verificados":["lista de artículos que SÍ aparecen en el RAG"],\
"veredicto_general":"PASS o WARN o FAIL",\
"resumen":"max 25 palabras"}}"""


def extraer_decision(respuesta: str) -> str:
    """Extrae SÍ/NO de la fila '¿Corresponde a tu rol?' del PASO 1."""
    # Acepta negrita markdown (**SÍ**, **NO**) además del texto plano
    match = re.search(
        r'Corresponde a tu rol[^\|]*\|\s*\*{0,2}\s*(S[ÍI]|SI|s[íi]|si|NO|No|no)\b',
        respuesta, re.IGNORECASE | re.DOTALL
    )
    if match:
        val = match.group(1).strip().upper()
        return 'SÍ' if val in ('SÍ', 'SI', 'SÌ') else 'NO'
    # Fallback: si dice "Derivo este caso" en los primeros 300 chars → NO
    if 'erivo este caso' in respuesta[:300]:
        return 'NO'
    return '?'


def evaluar_con_juez(respuesta: str, rag_context: str, criterios: list,
                     rol_esperado: str, deriva_a: str) -> dict:
    api_key = getattr(settings, 'DEEPSEEK_API_KEY', None)
    base_url = getattr(settings, 'DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
    if not api_key:
        return {"veredicto_general": "ERROR", "error": "Sin DEEPSEEK_API_KEY"}

    criterios_texto = "\n".join(f"{i+1}. {c}" for i, c in enumerate(criterios))
    rag_preview = (rag_context[:2000] + "...[truncado]") if len(rag_context) > 2000 else (rag_context or "(sin contexto RAG)")
    prompt = PROMPT_JUEZ.format(
        rol_esperado=rol_esperado,
        deriva_a=deriva_a or "N/A",
        rag_context=rag_preview,
        respuesta=respuesta[:2500],
        criterios=criterios_texto,
    )
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.0, "stream": False},
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=60,
        )
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content']
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        return {"veredicto_general": "ERROR", "error": str(e)}
    return {"veredicto_general": "ERROR", "error": "No se pudo parsear JSON"}


# ══════════════════════════════════════════════════════════════════════════════
# COMANDO
# ══════════════════════════════════════════════════════════════════════════════

class Command(BaseCommand):
    help = 'Eval completo: citas RAG, derivación, lenguaje imperativo'

    def add_arguments(self, parser):
        parser.add_argument('--caso', type=str, default=None)
        parser.add_argument('--slug', type=str, default=None)
        parser.add_argument('--suite', type=str, default=None, choices=['utp', 'derivacion', 'cruce'])
        parser.add_argument('--est', type=str, default=None,
                            help='Filtrar por establecimiento (ej: temuco, angol)')
        parser.add_argument('--sin-juez', action='store_true')

    def handle(self, *args, **options):
        casos = TODOS_LOS_CASOS
        if options['caso']:
            casos = [c for c in casos if c['id'] == options['caso']]
        if options['slug']:
            casos = [c for c in casos if c['slug'] == options['slug']]
        if options['suite']:
            casos = [c for c in casos if c['suite'] == options['suite']]

        # Filtro por establecimiento: aplica a slug (casos regulares)
        # y a slug_propietario (casos cruce)
        est = (options.get('est') or '').lower().strip()
        if est:
            casos = [
                c for c in casos
                if est in c.get('slug', '') or est in c.get('slug_propietario', '')
            ]
            # Para cruce, restringir también los slugs de los evaluados
            slugs_est = SLUGS_CRUCE_POR_EST.get(est)
            if not slugs_est:
                # Fallback: derivar slugs desde los casos cruce filtrados
                slugs_est = [
                    s for s in SLUGS_TEMUCO if est in s
                ]
        else:
            slugs_est = None  # sin filtro → usa SLUGS_TEMUCO completo

        if not casos:
            self.stdout.write(self.style.ERROR('Sin casos con esos filtros.')); return

        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
        output_dir = os.path.join(settings.BASE_DIR, 'ai_modules', 'eval_results')
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f'eval_{timestamp}.md')

        lineas = [f"# Eval Report — {timestamp}\n\n"]
        resumen = []

        # Separar cruce de los demás
        casos_regulares = [c for c in casos if c['suite'] != 'cruce']
        casos_cruce = [c for c in casos if c['suite'] == 'cruce']

        for caso in casos_cruce:
            self._eval_cruce(caso, lineas, resumen, options, slugs_est=slugs_est)

        for caso in casos_regulares:
            self.stdout.write(f"\n▶ {caso['id']} — {caso['titulo']}")

            try:
                assistant = AIAssistant.objects.get(slug=caso['slug'])
            except AIAssistant.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"  Asistente no encontrado: {caso['slug']}")); continue

            # Capturar contexto RAG real
            try:
                rag_context = get_relevant_chunks(assistant, caso['query']) or ""
            except Exception as e:
                rag_context = f"ERROR RAG: {e}"
                self.stdout.write(self.style.WARNING(f"  RAG error: {e}"))

            rag_tiene_contenido = bool(rag_context and not rag_context.startswith("No ") and not rag_context.startswith("ERROR"))

            # Llamar al asistente
            messages = [{"role": "user", "content": caso['query']}]
            try:
                respuesta = call_deepseek_ai(assistant, messages, caso['query'])
            except Exception as e:
                respuesta = f"ERROR: {e}"

            # Checks básicos de texto
            checks = {}
            for term in caso.get('debe_incluir', []):
                checks[f"DEBE incluir '{term}'"] = term.lower() in respuesta.lower()
            for term in caso.get('no_debe_incluir', []):
                checks[f"NO debe incluir '{term[:40]}'"] = term not in respuesta

            # Check de derivación
            if caso['rol_esperado'] == 'NO' and caso.get('deriva_a'):
                deriva_ok = caso['deriva_a'].lower() in respuesta.lower()
                checks[f"DEBE derivar a '{caso['deriva_a']}'"] = deriva_ok

            pass_count = sum(1 for v in checks.values() if v)
            total_count = len(checks)
            ratio = pass_count / total_count if total_count else 1
            emoji_b = "✅" if ratio == 1.0 else ("⚠️" if ratio >= 0.7 else "❌")
            self.stdout.write(f"  Checks: {pass_count}/{total_count} {emoji_b} | RAG: {'✅' if rag_tiene_contenido else '❌ vacío'}")

            # Juez LLM
            juicio = None
            if not options['sin_juez'] and caso.get('criterios_juez'):
                self.stdout.write("  Juez evaluando...")
                juicio = evaluar_con_juez(respuesta, rag_context, caso['criterios_juez'],
                                          caso['rol_esperado'], caso.get('deriva_a'))
                vg = juicio.get('veredicto_general', 'ERROR')
                emoji_j = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(vg, "❓")
                inventados = juicio.get('articulos_inventados', [])
                inv_str = f" | Inventados: {inventados}" if inventados else ""
                self.stdout.write(f"  Juez: {emoji_j} {vg}{inv_str} — {juicio.get('resumen', '')}")

            # Reporte
            lineas.append(f"## {caso['id']} — {caso['titulo']}\n\n")
            lineas.append(f"**Asistente:** `{caso['slug']}` | **Rol esperado:** {caso['rol_esperado']}")
            if caso.get('deriva_a'):
                lineas.append(f" | **Deriva a:** {caso['deriva_a']}")
            lineas.append(f"\n**RAG:** {'✅ con contenido' if rag_tiene_contenido else '❌ sin contenido'}\n\n")

            lineas.append("### Checks básicos\n")
            for check, ok in checks.items():
                lineas.append(f"- {'✅' if ok else '❌'} {check}\n")
            lineas.append(f"\n**Resultado básico:** {emoji_b} {pass_count}/{total_count}\n\n")

            if juicio:
                vg = juicio.get('veredicto_general', 'ERROR')
                emoji_j = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(vg, "❓")
                lineas.append("### Criterios juez\n")
                for c in juicio.get('criterios', []):
                    e = "✅" if c.get('resultado') == 'PASS' else "❌"
                    lineas.append(f"- {e} {c.get('criterio', '')} — *{c.get('razon', '')}*\n")

                inventados = juicio.get('articulos_inventados', [])
                verificados = juicio.get('articulos_verificados', [])
                lineas.append("\n### Verificación de citas\n")
                if verificados:
                    lineas.append(f"- ✅ **Con respaldo RAG:** {', '.join(verificados)}\n")
                if inventados:
                    lineas.append(f"- ❌ **Sin respaldo (posible invención):** {', '.join(inventados)}\n")
                if not inventados and not verificados:
                    lineas.append("- ℹ️ No se citaron artículos específicos\n")

                lineas.append(f"\n**Veredicto juez:** {emoji_j} {vg}  \n")
                lineas.append(f"**Resumen:** {juicio.get('resumen', '')}\n\n")

            lineas.append("### RAG context (preview)\n")
            rag_preview = rag_context[:800] + "...[truncado]" if len(rag_context) > 800 else (rag_context or "(vacío)")
            lineas.append(f"```\n{rag_preview}\n```\n\n")

            lineas.append("### Respuesta IA\n\n")
            preview = respuesta[:1500] + "...[truncado]" if len(respuesta) > 1500 else respuesta
            lineas.append(f"```\n{preview}\n```\n\n---\n\n")

            resumen.append({
                "id": caso['id'], "suite": caso['suite'],
                "basico": f"{emoji_b} {pass_count}/{total_count}",
                "rag": "✅" if rag_tiene_contenido else "❌",
                "juez": juicio.get('veredicto_general', '—') if juicio else '—',
                "inventados": juicio.get('articulos_inventados', []) if juicio else [],
            })

        # Tabla resumen
        tabla = "| ID | Suite | Checks | RAG | Juez | Inventados |\n"
        tabla += "|---|---|---|---|---|---|\n"
        for r in resumen:
            inv = ", ".join(r['inventados']) if r['inventados'] else "—"
            tabla += f"| {r['id']} | {r['suite']} | {r['basico']} | {r['rag']} | {r['juez']} | {inv} |\n"
        lineas.insert(1, tabla + "\n---\n\n")

        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(lineas)

        self.stdout.write(self.style.SUCCESS(f"\n✅ Reporte: {output_path}"))

    def _eval_cruce(self, caso, lineas, resumen, options, slugs_est=None):
        """Evalúa un caso cruce contra los asistentes del establecimiento."""
        slugs = slugs_est if slugs_est is not None else SLUGS_TEMUCO
        self.stdout.write(f"\n▶ {caso['id']} — {caso['titulo']}")
        self.stdout.write(f"  Suite: cruce | {caso['id']} | evaluando {len(slugs)} roles...")

        propietario_slug = caso['slug_propietario']
        resultados_por_slug = {}

        for slug in slugs:
            try:
                assistant = AIAssistant.objects.get(slug=slug)
            except AIAssistant.DoesNotExist:
                resultados_por_slug[slug] = {"error": f"Asistente {slug} no encontrado"}
                continue

            try:
                rag_ctx = get_relevant_chunks(assistant, caso['query']) or ""
            except Exception as e:
                rag_ctx = f"ERROR RAG: {e}"

            messages = [{"role": "user", "content": caso['query']}]
            try:
                resp = call_deepseek_ai(assistant, messages, caso['query'])
            except Exception as e:
                resp = f"ERROR: {e}"

            decision = extraer_decision(resp)
            esperado = caso['esperado_por_slug'].get(slug, {})
            rol_esperado = esperado.get('rol', '?')
            deriva_esperada = esperado.get('deriva', None)

            # Determinar si la respuesta es correcta
            if rol_esperado == 'SÍ':
                decision_ok = decision == 'SÍ'
                deriva_ok = None  # no aplica
            elif rol_esperado == 'NO':
                decision_ok = decision == 'NO'
                deriva_ok = (deriva_esperada.lower() in resp.lower()) if deriva_esperada else None
            elif rol_esperado == 'SÍ_O_NO':
                decision_ok = decision in ('SÍ', 'NO')  # ambas aceptables
                deriva_ok = None
            else:
                decision_ok = False
                deriva_ok = None

            rag_ok = bool(rag_ctx and not rag_ctx.startswith("No ") and not rag_ctx.startswith("ERROR"))

            # Juez completo solo para el propietario
            juicio = None
            if slug == propietario_slug and not options['sin_juez'] and caso.get('criterios_propietario'):
                self.stdout.write(f"    [{slug}] juez evaluando...")
                juicio = evaluar_con_juez(
                    resp, rag_ctx, caso['criterios_propietario'],
                    'SÍ', None
                )

            resultados_por_slug[slug] = {
                "decision": decision,
                "decision_ok": decision_ok,
                "deriva_esperada": deriva_esperada,
                "deriva_ok": deriva_ok,
                "rag_ok": rag_ok,
                "rag_ctx": rag_ctx,
                "respuesta": resp,
                "juicio": juicio,
                "rol_esperado": rol_esperado,
            }

            status = "✅" if decision_ok else "❌"
            self.stdout.write(f"    [{slug}] dice {decision} {status} | RAG: {'✅' if rag_ok else '❌'}")

        # ── Reporte cruce ──
        lineas.append(f"## {caso['id']} — {caso['titulo']}\n\n")
        lineas.append(f"**Query:** {caso['query'][:200]}...\n\n" if len(caso['query']) > 200 else f"**Query:** {caso['query']}\n\n")
        lineas.append(f"**Propietario esperado:** `{propietario_slug}`\n\n")

        # Matriz de resultados
        lineas.append("### Matriz de derivación\n\n")
        lineas.append("| Asistente | ¿Corresponde? | Esperado | Correcto | Deriva hacia | RAG |\n")
        lineas.append("|---|---|---|---|---|---|\n")

        todos_ok = True
        for slug in slugs:
            r = resultados_por_slug.get(slug, {})
            if "error" in r:
                lineas.append(f"| {slug} | ❓ | — | ❌ | — | ❌ |\n")
                continue
            decision = r['decision']
            decision_ok = r['decision_ok']
            deriva_esp = r['deriva_esperada'] or '—'
            deriva_ok = r['deriva_ok']
            rag_ok = r['rag_ok']

            # Símbolo de corrección de derivación
            if deriva_ok is None:
                deriva_sym = ''
            elif deriva_ok:
                deriva_sym = '✅'
            else:
                deriva_sym = '❌'
                todos_ok = False

            correcta = "✅" if decision_ok else "❌"
            if not decision_ok:
                todos_ok = False

            propietario_marker = " 👑" if slug == propietario_slug else ""
            lineas.append(f"| `{slug}`{propietario_marker} | {decision} | {r['rol_esperado']} | {correcta} | {deriva_esp} {deriva_sym} | {'✅' if rag_ok else '❌'} |\n")

        lineas.append("\n")

        # Evaluación detallada del propietario
        prop_result = resultados_por_slug.get(propietario_slug, {})
        if prop_result and not prop_result.get("error"):
            lineas.append(f"### Evaluación del propietario (`{propietario_slug}`)\n\n")

            # Checks básicos del propietario
            prop_resp = prop_result['respuesta']
            checks_ok = []
            checks_fail = []
            for term in caso.get('debe_incluir', []):
                if term.lower() in prop_resp.lower():
                    checks_ok.append(f"✅ Incluye '{term}'")
                else:
                    checks_fail.append(f"❌ FALTA '{term}'")
            for term in caso.get('no_debe_incluir', []):
                if term not in prop_resp:
                    checks_ok.append(f"✅ No incluye '{term[:30]}'")
                else:
                    checks_fail.append(f"❌ INCLUYE (no debe) '{term[:30]}'")
            for c in checks_ok + checks_fail:
                lineas.append(f"- {c}\n")
            lineas.append("\n")

            juicio = prop_result.get('juicio')
            if juicio:
                vg = juicio.get('veredicto_general', 'ERROR')
                emoji_j = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(vg, "❓")
                lineas.append(f"**Juez:** {emoji_j} {vg} — {juicio.get('resumen', '')}\n\n")

                inventados = juicio.get('articulos_inventados', [])
                verificados = juicio.get('articulos_verificados', [])
                if verificados:
                    lineas.append(f"**Artículos con respaldo RAG:** {', '.join(verificados)}\n\n")
                if inventados:
                    lineas.append(f"**Artículos sin respaldo:** {', '.join(inventados)}\n\n")
                else:
                    lineas.append("**Artículos sin respaldo:** ninguno ✅\n\n")

                lineas.append("**Criterios detallados:**\n")
                for c in juicio.get('criterios', []):
                    e = "✅" if c.get('resultado') == 'PASS' else "❌"
                    lineas.append(f"- {e} {c.get('criterio', '')} — *{c.get('razon', '')}*\n")
                lineas.append("\n")

            # Preview respuesta propietario
            prev = prop_resp[:1000] + "...[truncado]" if len(prop_resp) > 1000 else prop_resp
            lineas.append(f"<details><summary>Respuesta del propietario (preview)</summary>\n\n```\n{prev}\n```\n</details>\n\n")

        # Respuestas de no-propietarios que fallaron
        for slug in slugs:
            if slug == propietario_slug:
                continue
            r = resultados_por_slug.get(slug, {})
            if r and not r.get('error') and not r.get('decision_ok'):
                lineas.append(f"### ⚠️ Fallo: `{slug}` dijo '{r['decision']}' (esperado: {r['rol_esperado']})\n\n")
                prev = r['respuesta'][:600] + "...[truncado]" if len(r['respuesta']) > 600 else r['respuesta']
                lineas.append(f"```\n{prev}\n```\n\n")

        lineas.append("---\n\n")

        # Resumen para tabla global
        prop_juicio = prop_result.get('juicio') if prop_result else None
        resumen.append({
            "id": caso['id'], "suite": "cruce",
            "basico": "✅" if todos_ok else "❌",
            "rag": "✅",
            "juez": prop_juicio.get('veredicto_general', '—') if prop_juicio else '—',
            "inventados": prop_juicio.get('articulos_inventados', []) if prop_juicio else [],
        })

        juez_str = prop_juicio.get('veredicto_general', '—') if prop_juicio else '—'
        self.stdout.write(f"  Cruce: {'✅ todos correctos' if todos_ok else '❌ hay fallos'} | Juez propietario: {juez_str}")
