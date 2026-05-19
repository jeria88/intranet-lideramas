"""
Eval framework para asistentes IA — Red SFA
Uso:
    python manage.py eval_assistants                    # todos los casos
    python manage.py eval_assistants --caso TC001       # un caso específico
    python manage.py eval_assistants --slug utp-temuco  # solo ese asistente
    python manage.py eval_assistants --sin-juez         # solo checks básicos, sin llamada extra a DeepSeek
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


# ── Casos de prueba ────────────────────────────────────────────────────────────

CASOS = [
    {
        "id": "TC001",
        "slug": "utp-temuco",
        "titulo": "Sofía 1° Básico — NEE sin diagnóstico formal, apoderada no entrega informes",
        "query": (
            "Soy la profesora jefe de 1° Básico A. La estudiante Sofía (6 años) presenta serias "
            "dificultades en lectura y escritura: no reconoce vocales ni sílabas directas, y no logra "
            "escribir su nombre completo. Propuse activar el PIE y evaluación diagnóstica, pero la "
            "coordinadora del PIE dice que sin diagnóstico formal no puede iniciar adecuaciones. "
            "La apoderada no entregó los informes médicos (plazo vencido: 15 de abril). "
            "Sofía tiene calificaciones bajo 4.0 y promedio 3.8. La apoderada pide más oportunidades. "
            "Pido a UTP que medie para evitar la repitencia. Sofía tiene 92% de asistencia."
        ),
        "debe_incluir": ["Decreto 83", "adecuaciones"],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "criterios_juez": [
            "Reconoce que se pueden aplicar medidas de apoyo provisionales sin diagnóstico formal",
            "Cita Decreto 83/2015 o normativa de adecuaciones curriculares",
            "No activa denuncia penal ni menciona Carabineros para este caso",
            "Propone mediación entre coordinadora PIE, apoderada y docente",
        ],
    },
    {
        "id": "TC002",
        "slug": "utp-temuco",
        "titulo": "Benjamín 2° Básico — TEL, calificación 2.3 por no traer flauta",
        "query": (
            "Mi hijo Benjamín (7 años) recibió 2.3 en Música porque no llevó su flauta. "
            "Tiene TEL mixto diagnosticado (informe entregado al PIE en marzo). "
            "El profesor sabía del diagnóstico. El reglamento de evaluación diferenciada indica "
            "que deben aplicarse adecuaciones. El profesor avisó los materiales solo el día anterior. "
            "Pido que se anule la calificación y se aplique evaluación diferenciada."
        ),
        "debe_incluir": ["PACI", "adecuaciones"],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa", "Ley 21.545"],
        "criterios_juez": [
            "Reconoce que la calificación puede ser inválida por incumplimiento del PACI",
            "Propone evaluación diferenciada con otro instrumento o momento",
            "No activa denuncia penal",
            "No cita Ley 21.545 (este caso es TEL, no TEA — esa ley no aplica)",
        ],
    },
    {
        "id": "TC003",
        "slug": "utp-temuco",
        "titulo": "Valentina 5° Básico — descuento por ortografía en prueba de Matemática",
        "query": (
            "El profesor de Matemática descontó décimas por faltas de ortografía en una prueba de "
            "fracciones. Mi hija obtuvo 5.2 en contenido, bajó a 4.5. El profesor dice que la ortografía "
            "es transversal. No informó antes que descontaría por ortografía. "
            "Solicito restituir la nota 5.2 porque mi hija demostró dominio del contenido matemático."
        ),
        "debe_incluir": ["Decreto 67", "evaluación"],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "criterios_juez": [
            "Analiza si el descuento por ortografía en Matemática es normativamente procedente",
            "Señala que el docente debió informar los criterios de evaluación con anticipación (Decreto 67)",
            "No activa denuncia penal",
            "Toma posición fundada, no elude la pregunta principal del apoderado",
        ],
    },
    {
        "id": "TC004",
        "slug": "utp-temuco",
        "titulo": "Matías 6° Básico — TDAH, traspaso incorrecto de respuestas, PACI no respetado",
        "query": (
            "Mi hijo Matías tiene TDAH diagnosticado. En la prueba de Lenguaje marcó respuestas correctas "
            "en el fascículo pero las traspasó mal a la hoja de respuestas. La profesora puso 3.2 y se "
            "niega a cambiar. En su PACI está especificado que debe tener apoyo en traspaso de respuestas "
            "y tiempo extra. La profesora no le ofreció ayuda. El educador diferencial no estuvo presente. "
            "Pido que se invalide la calificación y se aplique evaluación diferenciada."
        ),
        "debe_incluir": ["PACI", "adecuaciones"],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "criterios_juez": [
            "Reconoce que el PACI fue incumplido (apoyo en traspaso no aplicado)",
            "Propone invalidar la calificación y aplicar nueva evaluación con ajustes",
            "Menciona la responsabilidad del educador diferencial de estar presente",
            "No activa denuncia penal",
        ],
    },
    {
        "id": "TC005",
        "slug": "utp-temuco",
        "titulo": "Cristóbal 7° Básico — trabajo grupal, apoderado exige subir nota a 5.0",
        "query": (
            "Mi hijo Cristóbal sin NEE trabaja en equipo en Ciencias. La profesora evaluó con rúbrica: "
            "autoevaluación 20%, coevaluación 20%, observación directa 60%. Registró que Cristóbal "
            "no trabajó en clases y su nota fue 3.3. El resto del equipo tuvo 6.0. "
            "Reclamo discriminación. Exijo que le suban la nota a 5.0 por el trabajo del grupo."
        ),
        "debe_incluir": ["Decreto 67", "evaluación"],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "criterios_juez": [
            "Reconoce que la profesora tiene derecho a evaluar desempeño individual",
            "No concede la demanda de subir a 5.0 sin sustento normativo",
            "Distingue correctamente entre desempeño individual bajo y discriminación",
            "No activa denuncia penal",
        ],
    },
    {
        "id": "TC006",
        "slug": "utp-temuco",
        "titulo": "Ignacio 6° Básico — TEA nivel 1, profesora Inglés no califica carpeta PIE",
        "query": (
            "Mi hijo Ignacio tiene TEA nivel 1. El equipo PIE elaboró una carpeta de trabajo con ajustes "
            "razonables para que rinda evaluaciones en sala de recursos o en casa. La profesora de Inglés "
            "se niega a calificar esa carpeta y exige que rinda en sala regular. El niño lleva dos "
            "evaluaciones sin nota. La educadora diferencial ya intervino sin éxito. "
            "Acuso discriminación por condición de discapacidad. Pido que se ordene calificar la carpeta."
        ),
        "debe_incluir": ["ajuste", "Decreto"],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "criterios_juez": [
            "Indica que la profesora está incumpliendo el ajuste razonable del equipo PIE",
            "Ordena o recomienda calificar la carpeta como evaluación válida",
            "Puede citar Ley 21.545 (caso SÍ involucra TEA confirmado — uso correcto)",
            "No activa denuncia penal",
            "Propone regularizar las dos notas pendientes",
        ],
    },
    {
        "id": "TC007",
        "slug": "utp-temuco",
        "titulo": "Camila 7° Básico — FIL, copiando en prueba, PACI de evaluación separada no respetado",
        "query": (
            "Soy la educadora diferencial PIE. Atiendo a Camila con Funcionamiento Intelectual Límite (FIL). "
            "En Historia, la profesora la sorprendió copiando tres veces y le quitó la prueba, calificó 4.6. "
            "El PACI de Camila contempla evaluación en espacio separado con supervisión de educadora diferencial. "
            "La profesora no respetó esa adecuación. La conducta de copiar está asociada a su ansiedad y "
            "baja memoria operativa, no a mala intención. Pido que se anule el 4.6 y se aplique nueva evaluación."
        ),
        "debe_incluir": ["PACI", "adecuaciones"],
        "no_debe_incluir": ["🚨 DENUNCIA OBLIGATORIA E INMEDIATA\nEsta situación activa"],
        "criterios_juez": [
            "Reconoce que el PACI fue incumplido (evaluación separada no aplicada)",
            "Contextualiza la conducta de copiar en relación al FIL y la ansiedad",
            "Propone nueva evaluación con los apoyos del PACI",
            "Aborda el debido proceso para la docente, no la condena directa",
            "No activa denuncia penal",
        ],
    },
    {
        "id": "TC008",
        "slug": "utp-temuco",
        "titulo": "Benjamín 8° Básico — Artes, abuela exige 7.0 y amenaza con Superintendencia",
        "query": (
            "Soy el profesor de Artes Visuales. Benjamín no trajo materiales en tres clases consecutivas. "
            "Le facilité materiales desde UTP pero igual no trabajó. Apliqué rúbrica de proceso: nota 3.3. "
            "La rúbrica fue firmada por el apoderado dos semanas antes. Hoy la abuela exige que le ponga 7.0 "
            "y amenaza con ir a Superintendencia. Me niego porque apliqué el reglamento correctamente. "
            "Pido a UTP que respalde la calificación."
        ),
        "debe_incluir": ["Reglamento", "evaluación"],
        "no_debe_incluir": ["Carabineros", "Fiscalía", "🚨"],
        "criterios_juez": [
            "Respalda al docente si la calificación se aplicó conforme al reglamento y rúbrica",
            "No cede a la demanda de cambiar la nota a 7.0 sin causa normativa",
            "Informa cuál es el canal correcto de reclamo para el apoderado si lo tiene",
            "No activa denuncia penal",
        ],
    },
]


# ── Juez LLM — llamada directa a DeepSeek (sin RAG ni assistant) ──────────────

PROMPT_JUEZ = (
    "Eres un evaluador experto en normativa educacional chilena.\n"
    "Evalúa si la respuesta del asistente cumple los criterios indicados.\n\n"
    "RESPUESTA A EVALUAR:\n{respuesta}\n\n"
    "CRITERIOS (evalúa cada uno como PASS o FAIL con razón de máximo 15 palabras):\n"
    "{criterios}\n\n"
    "Responde ÚNICAMENTE con JSON válido:\n"
    '{{"criterios":[{{"criterio":"...","resultado":"PASS o FAIL","razon":"..."}},...], '
    '"veredicto_general":"PASS o WARN o FAIL","resumen":"una frase de max 25 palabras"}}'
)


def evaluar_con_juez(respuesta: str, criterios: list) -> dict:
    api_key = getattr(settings, 'DEEPSEEK_API_KEY', None)
    base_url = getattr(settings, 'DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
    if not api_key:
        return {"veredicto_general": "ERROR", "error": "Sin DEEPSEEK_API_KEY"}

    criterios_texto = "\n".join(f"{i+1}. {c}" for i, c in enumerate(criterios))
    prompt = PROMPT_JUEZ.format(respuesta=respuesta[:3000], criterios=criterios_texto)

    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "stream": False,
            },
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=60,
        )
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content']
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        return {"veredicto_general": "ERROR", "error": str(e)}
    return {"veredicto_general": "ERROR", "error": "No se pudo parsear JSON del juez"}


# ── Comando ────────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = 'Evalúa asistentes IA con casos de prueba predefinidos y guarda reporte Markdown'

    def add_arguments(self, parser):
        parser.add_argument('--caso', type=str, default=None, help='ID del caso (ej: TC001)')
        parser.add_argument('--slug', type=str, default=None, help='Filtrar por slug de asistente')
        parser.add_argument('--sin-juez', action='store_true', help='Solo checks básicos, sin juez LLM')

    def handle(self, *args, **options):
        casos = CASOS
        if options['caso']:
            casos = [c for c in CASOS if c['id'] == options['caso']]
        if options['slug']:
            casos = [c for c in casos if c['slug'] == options['slug']]
        if not casos:
            self.stdout.write(self.style.ERROR('No se encontraron casos con esos filtros.'))
            return

        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
        output_dir = os.path.join(settings.BASE_DIR, 'ai_modules', 'eval_results')
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f'eval_{timestamp}.md')

        lineas = [f"# Eval Report — {timestamp}\n\n"]
        resumen_global = []

        for caso in casos:
            self.stdout.write(f"\n▶ {caso['id']} — {caso['titulo']}")

            try:
                assistant = AIAssistant.objects.get(slug=caso['slug'])
            except AIAssistant.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"  Asistente no encontrado: {caso['slug']}"))
                continue

            # Llamar al asistente real (con RAG + prompt completo)
            messages = [{"role": "user", "content": caso['query']}]
            try:
                respuesta = call_deepseek_ai(
                    assistant,
                    messages,
                    caso['query'],
                )
            except Exception as e:
                respuesta = f"ERROR llamando al asistente: {e}"

            # Checks básicos de texto
            checks = {}
            for term in caso.get('debe_incluir', []):
                checks[f"DEBE incluir '{term}'"] = term.lower() in respuesta.lower()
            for term in caso.get('no_debe_incluir', []):
                checks[f"NO debe incluir '{term}'"] = term not in respuesta

            pass_count = sum(1 for v in checks.values() if v)
            total_count = len(checks)
            ratio = pass_count / total_count if total_count else 1
            emoji_basico = "✅" if ratio == 1.0 else ("⚠️" if ratio >= 0.7 else "❌")

            self.stdout.write(f"  Checks: {pass_count}/{total_count} {emoji_basico}")

            # Juez LLM
            juicio = None
            if not options['sin_juez'] and caso.get('criterios_juez'):
                self.stdout.write("  Juez LLM evaluando...")
                juicio = evaluar_con_juez(respuesta, caso['criterios_juez'])
                vg = juicio.get('veredicto_general', 'ERROR')
                emoji_juez = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(vg, "❓")
                self.stdout.write(f"  Juez: {emoji_juez} {vg} — {juicio.get('resumen', '')}")

            # Sección del reporte
            lineas.append(f"## {caso['id']} — {caso['titulo']}\n\n")
            lineas.append(f"**Asistente:** `{caso['slug']}`\n\n")

            lineas.append("### Checks básicos\n")
            for check, ok in checks.items():
                lineas.append(f"- {'✅' if ok else '❌'} {check}\n")
            lineas.append(f"\n**Resultado básico:** {emoji_basico} {pass_count}/{total_count}\n\n")

            if juicio:
                vg = juicio.get('veredicto_general', 'ERROR')
                emoji_juez = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(vg, "❓")
                lineas.append("### Criterios juez\n")
                for c in juicio.get('criterios', []):
                    e = "✅" if c.get('resultado') == 'PASS' else "❌"
                    lineas.append(f"- {e} {c.get('criterio', '')} — *{c.get('razon', '')}*\n")
                lineas.append(f"\n**Veredicto juez:** {emoji_juez} {vg}  \n")
                lineas.append(f"**Resumen:** {juicio.get('resumen', '')}\n\n")

            lineas.append("### Respuesta IA\n\n")
            preview = respuesta[:2500] + ("...(truncado)" if len(respuesta) > 2500 else "")
            lineas.append(f"```\n{preview}\n```\n\n---\n\n")

            resumen_global.append({
                "id": caso['id'],
                "basico": f"{emoji_basico} {pass_count}/{total_count}",
                "juez": juicio.get('veredicto_general', '—') if juicio else '—',
            })

        # Tabla resumen al inicio
        tabla = "| Caso | Checks | Juez |\n|------|--------|------|\n"
        for r in resumen_global:
            tabla += f"| {r['id']} | {r['basico']} | {r['juez']} |\n"
        lineas.insert(1, tabla + "\n---\n\n")

        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(lineas)

        self.stdout.write(self.style.SUCCESS(f"\n✅ Reporte guardado en:\n   {output_path}"))
