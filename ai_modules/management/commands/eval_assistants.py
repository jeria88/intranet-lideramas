"""
Eval framework completo — Red SFA
Testea: (1) citación real desde RAG, (2) derivación correcta entre roles,
        (3) lenguaje imperativo/conclusivo, (4) artículos prohibidos.

Uso:
    python manage.py eval_assistants                      # todos los casos
    python manage.py eval_assistants --caso TC001         # un caso
    python manage.py eval_assistants --suite derivacion   # solo derivación
    python manage.py eval_assistants --sin-juez           # checks básicos
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


TODOS_LOS_CASOS = CASOS_UTP + CASOS_DERIVACION


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
Revisa si los artículos o anexos específicos citados en la respuesta (ej: "Art. 32°", "Anexo 13", \
"Art. 94") aparecen efectivamente en el contexto RAG. Si el asistente cita artículos que NO \
están en el RAG, son potencialmente inventados.

Responde ÚNICAMENTE con JSON válido:
{{"criterios":[{{"criterio":"...","resultado":"PASS o FAIL","razon":"max 15 palabras"}},...],\
"articulos_inventados":["lista de artículos citados sin respaldo en el RAG, o [] si todos tienen respaldo"],\
"articulos_verificados":["lista de artículos que SÍ aparecen en el RAG"],\
"veredicto_general":"PASS o WARN o FAIL",\
"resumen":"max 25 palabras"}}"""


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
        parser.add_argument('--suite', type=str, default=None, choices=['utp', 'derivacion'])
        parser.add_argument('--sin-juez', action='store_true')

    def handle(self, *args, **options):
        casos = TODOS_LOS_CASOS
        if options['caso']:
            casos = [c for c in casos if c['id'] == options['caso']]
        if options['slug']:
            casos = [c for c in casos if c['slug'] == options['slug']]
        if options['suite']:
            casos = [c for c in casos if c['suite'] == options['suite']]
        if not casos:
            self.stdout.write(self.style.ERROR('Sin casos con esos filtros.')); return

        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
        output_dir = os.path.join(settings.BASE_DIR, 'ai_modules', 'eval_results')
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f'eval_{timestamp}.md')

        lineas = [f"# Eval Report — {timestamp}\n\n"]
        resumen = []

        for caso in casos:
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
