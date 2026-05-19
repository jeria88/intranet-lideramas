import re
import requests
from django.conf import settings
from .utils import get_relevant_chunks


def _filtrar_articulos_no_rag(respuesta: str, relevant_context: str) -> str:
    """
    Elimina de la respuesta cualquier número de artículo que no aparezca
    literalmente en el contexto RAG. Si el artículo va con nombre de documento
    ("Art. 5 del Reglamento de Evaluación"), mantiene solo el nombre.
    Si va solo ("Art. 32°"), lo elimina.
    """
    if not relevant_context or not respuesta:
        return respuesta

    # Construir whitelist de números verificados en el RAG
    # \s* para capturar tanto "Art. 26" como "Art.26"
    nums_rag = set(re.findall(
        r'Art(?:ículo)?\.?\s*(\d+)[°º]?\b',
        relevant_context, re.IGNORECASE
    ))
    anexos_rag = set(re.findall(r'Anexo\s*(\d+)', relevant_context, re.IGNORECASE))

    # Patrón principal: "Art. X°" / "Artículo X" seguido opcionalmente de "del Documento"
    # Captura: (prefijo)(número)(sufijo)(del Documento)?
    PAT_ART = re.compile(
        r'(Art(?:ículos?)?\.?\s+)'
        r'(\d+)'
        r'([°º]?(?:\s*bis)?)'
        r'((?:\s*(?:y|e)\s*\d+[°º]?)*)'          # rangos adicionales: "y 6", "y 7"
        r'((?:\s+(?:del?|de\s+la|de\s+los)\s+[A-ZÁÉÍÓÚÑ\w][^,\.\n;\|]{2,50})?)',
        re.IGNORECASE,
    )
    PAT_ANEXO = re.compile(
        r'(Anexo\s+)(\d+)'
        r'((?:\s+(?:del?|de\s+la)\s+[A-ZÁÉÍÓÚÑ\w][^,\.\n;\|]{2,50})?)',
        re.IGNORECASE,
    )

    def _doc_name(doc_fragment: str) -> str:
        """Quita el conector 'del/de la/de los' y retorna solo el nombre."""
        return re.sub(
            r'^\s*(?:del?|de\s+la|de\s+los)\s+', '', doc_fragment, flags=re.IGNORECASE
        ).strip()

    def _reemplazar_art(m: re.Match) -> str:
        num = m.group(2)
        if num in nums_rag:
            return m.group(0)           # verificado → sin cambio
        doc = _doc_name(m.group(5)) if m.group(5) else ''
        if doc:
            return doc                  # "Art. 5 del Reglamento" → "Reglamento"
        # Sin doc: dejar referencia genérica para no romper la oración
        return 'el artículo correspondiente'

    def _reemplazar_anexo(m: re.Match) -> str:
        num = m.group(2)
        if num in anexos_rag:
            return m.group(0)
        doc = _doc_name(m.group(3)) if m.group(3) else ''
        if doc:
            return doc
        return 'el anexo correspondiente'

    respuesta = PAT_ART.sub(_reemplazar_art, respuesta)
    respuesta = PAT_ANEXO.sub(_reemplazar_anexo, respuesta)

    # Limpiar artefactos de puntuación y espacios dobles
    respuesta = re.sub(r' {2,}', ' ', respuesta)
    # Doble artículo: "El el", "La la", "Los los", etc.
    respuesta = re.sub(r'\b(el|la|los|las)\s+\1\b', r'\1', respuesta, flags=re.IGNORECASE)
    respuesta = re.sub(r'\| {0,3}\|', '| — |', respuesta)   # celdas de tabla vacías
    respuesta = re.sub(r'(?m)^\s*[\|]\s*[\|]\s*$', '', respuesta)

    return respuesta


def call_deepseek_ai(assistant, messages_history, user_query, temperature=1.0, attached_content=None):
    """
    Realiza una llamada a la API de DeepSeek inyectando el contexto RAG
    y el historial de la conversación.
    """
    api_key = getattr(settings, 'DEEPSEEK_API_KEY', None)
    base_url = getattr(settings, 'DEEPSEEK_BASE_URL', 'https://api.deepseek.com')

    if not api_key:
        return "Error: DEEPSEEK_API_KEY no configurado."

    # RAG: Recuperar fragmentos relevantes de la BD
    try:
        relevant_context = get_relevant_chunks(assistant, user_query)
    except Exception as e:
        print(f"Error en RAG: {e}")
        relevant_context = ""

    # System message: ÚNICAMENTE el system_instruction editable desde el admin.
    # No se agrega nada más aquí — el RAG y los adjuntos van en el mensaje del usuario.
    system_instruction = assistant.system_instruction or "Eres un asesor experto en normativa educacional chilena vigente."
    messages = [{"role": "system", "content": system_instruction}]

    # Historial previo sin modificar (todos excepto el mensaje actual)
    prior_history = messages_history[:-1] if len(messages_history) > 1 else []
    current_message = messages_history[-1] if messages_history else {"role": "user", "content": user_query}

    for msg in prior_history:
        messages.append({"role": msg['role'], "content": msg['content']})

    # Enriquecer el mensaje actual con adjunto y contexto documental
    context_parts = []
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

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "stream": False
    }

    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=90
        )
        response.raise_for_status()
        data = response.json()
        raw = data['choices'][0]['message']['content']
        return _filtrar_articulos_no_rag(raw, relevant_context)
    except Exception as e:
        print(f"Error calling DeepSeek: {e}")
        return f"Lo siento, hubo un error al procesar tu consulta (DeepSeek API Error). Por favor, intenta de nuevo en unos momentos o reporta este error: {str(e)}"
