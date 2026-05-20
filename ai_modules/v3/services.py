"""
Servicio de IA v3.1 — pipeline de dos etapas + RAG preprocesado.

Etapa 1 (temperature=0.0): decide COMPETENCIA SÍ/NO con prompt de 5 líneas.
  → Si NO: retorna mensaje de derivación directamente. Sin segunda llamada.
  → Si SÍ: continúa a etapa 2.

Etapa 2 (temperature=0.3): genera respuesta completa con:
  - Identidad mínima del rol (2 líneas)
  - Protocolo específico si aplica (desde v2/protocols.py)
  - Contexto RAG *preprocesado* (números de artículo no verificados → '[N°]')
  - Bloque CITAS VERIFICADAS (whitelist explícita desde citations.py)
  - Consulta del usuario

v3.1 vs v3:
- Preprocess RAG: borra números no verificados del texto de entrada (previene
  citas que el modelo podría leer directamente en el RAG).
- Postprocess output: aplica filtrar_citas_no_rag() igual que en v2 (previene
  citas que el modelo genera desde su conocimiento de entrenamiento).
"""

import re
import requests
from django.conf import settings

from ..utils import get_relevant_chunks
from ..v2.protocols import detectar_protocolo
from ..v2.postprocess import filtrar_citas_no_rag
from .prompts import prompt_etapa1, prompt_etapa2
from .citations import extraer_whitelist, construir_bloque_citas, preprocesar_rag


ESTABLISHMENT_NAMES: dict[str, str] = {
    'TEMUCO':   'Temuco',
    'LAUTARO':  'Lautaro',
    'RENAICO':  'Renaico',
    'SANTIAGO': 'Santiago',
    'IMPERIAL': 'Imperial',
    'ERCILLA':  'Ercilla',
    'ARAUCO':   'Arauco',
    'ANGOL':    'Angol',
}


def _extraer_competencia(texto: str) -> tuple[str, str]:
    """
    Parsea la respuesta de etapa 1.
    Retorna ('SÍ', razón) o ('NO', razón).
    """
    m = re.search(r'COMPETENCIA:\s*(S[ÍI]|SI|NO)\s*[—\-–]?\s*(.*)', texto, re.IGNORECASE)
    if m:
        decision = 'SÍ' if m.group(1).upper() in ('SÍ', 'SI') else 'NO'
        razon = m.group(2).strip()
        return decision, razon
    # Fallback: si dice "derivo" → NO
    if 'erivo' in texto.lower()[:300]:
        return 'NO', texto.strip()
    return 'SÍ', ''  # si no puede determinarse → responde (mejor que silencio)


def _llamar_deepseek(messages: list, temperature: float, api_key: str, base_url: str) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    response = requests.post(
        f"{base_url}/chat/completions",
        json=payload,
        headers=headers,
        timeout=90,
    )
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content']


def call_ai_v3(assistant, messages_history, user_query, temperature=0.3, attached_content=None):
    """
    Pipeline v3 de dos etapas:
    1. Decisión de competencia (temperature=0.0, prompt mínimo).
    2. Respuesta completa con whitelist de citas explícita (temperature=0.3).
    """
    api_key = getattr(settings, 'DEEPSEEK_API_KEY', None)
    base_url = getattr(settings, 'DEEPSEEK_BASE_URL', 'https://api.deepseek.com')

    if not api_key:
        return "Error: DEEPSEEK_API_KEY no configurado."

    role_code = (assistant.profile_role or '').upper()
    est_code = (assistant.establishment or '').upper()
    est_name = ESTABLISHMENT_NAMES.get(est_code, est_code.title())

    # ── ETAPA 1: decisión de competencia ────────────────────────────────────
    try:
        system_e1 = prompt_etapa1(role_code, est_name)
        messages_e1 = [
            {"role": "system", "content": system_e1},
            {"role": "user",   "content": user_query},
        ]
        raw_e1 = _llamar_deepseek(messages_e1, temperature=0.0, api_key=api_key, base_url=base_url)
    except Exception as e:
        print(f"[v3] Error etapa 1: {e}")
        return f"Error al procesar tu consulta (etapa 1). Intenta de nuevo. ({e})"

    competencia, razon_e1 = _extraer_competencia(raw_e1)

    # Si no corresponde → derivar sin segunda llamada
    if competencia == 'NO':
        return f"COMPETENCIA: NO\n{razon_e1 or raw_e1.strip()}"

    # ── ETAPA 2: respuesta completa ──────────────────────────────────────────
    # RAG
    try:
        relevant_context = get_relevant_chunks(assistant, user_query, top_n=20)
    except Exception as e:
        print(f"[v3] Error en RAG: {e}")
        relevant_context = ""

    # Whitelist de citas desde el RAG
    whitelist = extraer_whitelist(relevant_context)
    bloque_citas = construir_bloque_citas(whitelist)

    # v3.1: preprocesar RAG — borra números de artículo no verificados
    rag_procesado = preprocesar_rag(relevant_context, whitelist)

    # Protocolo específico si aplica
    protocol_block = detectar_protocolo(role_code, user_query)

    # Construir el mensaje enriquecido
    prior_history = messages_history[:-1] if len(messages_history) > 1 else []
    current_message = messages_history[-1] if messages_history else {"role": "user", "content": user_query}

    system_e2 = prompt_etapa2(role_code, est_name)
    messages_e2 = [{"role": "system", "content": system_e2}]

    for msg in prior_history:
        messages_e2.append({"role": msg['role'], "content": msg['content']})

    context_parts = []
    if protocol_block:
        context_parts.append(protocol_block.strip())
    if attached_content:
        context_parts.append(
            "### DOCUMENTO ADJUNTO:\n"
            f"{attached_content}\n"
            "--- FIN DEL DOCUMENTO ---"
        )
    if rag_procesado:
        context_parts.append(
            "### DOCUMENTACIÓN DE REFERENCIA:\n"
            f"{rag_procesado}\n"
            "--- FIN DE LA DOCUMENTACIÓN ---"
        )
    context_parts.append(bloque_citas)

    enriched = "\n\n".join(context_parts) + f"\n\n{current_message['content']}"
    messages_e2.append({"role": current_message['role'], "content": enriched})

    try:
        respuesta = _llamar_deepseek(messages_e2, temperature=temperature, api_key=api_key, base_url=base_url)
        # Postprocesado: elimina citas no respaldadas (training-data hallucinations)
        # Se usa relevant_context original para construir whitelist correcta
        respuesta = filtrar_citas_no_rag(respuesta, relevant_context)
        # Prefijo para que el eval pueda detectar competencia SÍ en propietarios
        return "COMPETENCIA: SÍ\n" + respuesta
    except Exception as e:
        print(f"[v3] Error etapa 2: {e}")
        return f"Error al generar la respuesta (etapa 2). Intenta de nuevo. ({e})"
