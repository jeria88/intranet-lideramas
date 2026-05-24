"""
Servicio de IA v2 — Red LiderA+.

Arquitectura:
- System prompt mínimo (~15 líneas) desde prompts.py, según profile_role del asistente.
- Protocolo específico inyectado dinámicamente en el mensaje del usuario si aplica.
- Post-procesamiento extendido: filtra nombres de documentos Y números de artículo no en RAG.
"""

import requests
from django.conf import settings

from ..utils import get_relevant_chunks
from .prompts import ROLE_PROMPTS
from .protocols import detectar_protocolo
from .postprocess import filtrar_citas_no_rag


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


def _get_system_prompt(assistant) -> str:
    """Retorna el prompt de sistema mínimo según el rol del asistente."""
    role_code = (assistant.profile_role or '').upper()
    prompt_fn = ROLE_PROMPTS.get(role_code)
    if prompt_fn is None:
        return assistant.system_instruction or "Eres un asesor experto en normativa educacional chilena vigente."
    est_code = (assistant.establishment or '').upper()
    est_name = ESTABLISHMENT_NAMES.get(est_code, est_code.title())
    return prompt_fn(est_name)


def call_ai_v2(assistant, messages_history, user_query, temperature=0.3, attached_content=None):
    """
    Llama a DeepSeek con arquitectura v2:
    1. System prompt mínimo por rol (desde prompts.py).
    2. Protocolo inyectado si la consulta lo activa (desde protocols.py).
    3. Contexto RAG (top_n=20).
    4. Filtrado post-procesamiento extendido (artículos + documentos).
    """
    api_key = getattr(settings, 'DEEPSEEK_API_KEY', None)
    base_url = getattr(settings, 'DEEPSEEK_BASE_URL', 'https://api.deepseek.com')

    if not api_key:
        return "Error: DEEPSEEK_API_KEY no configurado."

    # 1. RAG
    try:
        relevant_context = get_relevant_chunks(assistant, user_query, top_n=20)
    except Exception as e:
        print(f"[v2] Error en RAG: {e}")
        relevant_context = ""

    # 2. Sistema mínimo
    system_prompt = _get_system_prompt(assistant)
    messages = [{"role": "system", "content": system_prompt}]

    # 3. Historial previo sin modificar
    prior_history = messages_history[:-1] if len(messages_history) > 1 else []
    current_message = messages_history[-1] if messages_history else {"role": "user", "content": user_query}

    for msg in prior_history:
        messages.append({"role": msg['role'], "content": msg['content']})

    # 4. Construir mensaje actual: protocolo + adjunto + RAG + consulta
    role_code = (assistant.profile_role or '').upper()
    protocol_block = detectar_protocolo(role_code, user_query)

    context_parts = []

    if protocol_block:
        context_parts.append(protocol_block.strip())

    if attached_content:
        context_parts.append(
            "### DOCUMENTO ADJUNTO POR EL USUARIO:\n"
            f"{attached_content}\n"
            "--- FIN DEL DOCUMENTO ADJUNTO ---"
        )

    if relevant_context:
        context_parts.append(
            "### DOCUMENTACIÓN DE REFERENCIA:\n"
            f"{relevant_context}\n"
            "--- FIN DE LA DOCUMENTACIÓN ---"
        )

    if context_parts:
        enriched_content = "\n\n".join(context_parts) + f"\n\n{current_message['content']}"
    else:
        enriched_content = current_message['content']

    messages.append({"role": current_message['role'], "content": enriched_content})

    # 5. Llamada a DeepSeek
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

    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=90,
        )
        response.raise_for_status()
        data = response.json()
        raw = data['choices'][0]['message']['content']
        return filtrar_citas_no_rag(raw, relevant_context)
    except Exception as e:
        print(f"[v2] Error calling DeepSeek: {e}")
        return (
            "Lo siento, hubo un error al procesar tu consulta (DeepSeek API Error). "
            f"Por favor, intenta de nuevo o reporta este error: {str(e)}"
        )
