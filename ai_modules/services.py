import re
import requests
from django.conf import settings
from .utils import get_relevant_chunks


_DOC_KEYWORDS = {
    # clave canónica → palabras que identifican ese documento en el contexto
    'riohs':      ['RIOHS', 'riohs'],
    'rice':       ['RICE', 'rice'],
    'regl_eval':  ['REGLAMENTO DE EVALUACIÓN', 'Reglamento de Evaluación', 'Regl. Evaluación', 'reglamento de evaluación'],
    'dto170':     ['DTO-170', 'Decreto-170', 'Decreto 170', 'decreto 170'],
    'dto83':      ['Decreto-83', 'Decreto 83', 'decreto 83'],
    'dto67':      ['Decreto-67', 'Decreto 67', 'decreto 67'],
}

# Aliases de documento en el texto de la RESPUESTA → clave canónica
_DOC_ALIAS = {
    'riohs': 'riohs',
    'rice': 'rice',
    'reglamento de evaluación': 'regl_eval',
    'reglamento de evaluacion': 'regl_eval',
    'regl. de evaluación': 'regl_eval',
    'regl. evaluación': 'regl_eval',
    'decreto 170': 'dto170',
    'decreto 170/2009': 'dto170',
    'dto-170': 'dto170',
    'decreto 83': 'dto83',
    'decreto 83/2015': 'dto83',
    'decreto 67': 'dto67',
    'decreto 67/2018': 'dto67',
}


def _construir_whitelist_doc(relevant_context: str) -> dict:
    """
    Retorna {doc_key: set_of_article_numbers} con los artículos
    verificados por documento dentro del contexto recuperado.
    """
    whitelist: dict = {k: set() for k in _DOC_KEYWORDS}
    # Buscar bloques [Doc: ...] Art.N
    for block in re.split(r'\[Doc:', relevant_context):
        if not block.strip():
            continue
        header = block[:120].lower()
        doc_key = None
        for key, keywords in _DOC_KEYWORDS.items():
            if any(kw.lower() in header for kw in keywords):
                doc_key = key
                break
        if doc_key is None:
            continue
        nums = re.findall(r'Art(?:ículo)?\.?\s*(\d+)[°º]?\b', block, re.IGNORECASE)
        for n in nums:
            whitelist[doc_key].add(n)
        anexos = re.findall(r'Anexo\s*(\d+)', block, re.IGNORECASE)
        for a in anexos:
            whitelist[doc_key].add(f'A{a}')   # prefijo 'A' para distinguir de artículos
    return whitelist


def _resolver_doc_key(doc_fragment: str) -> str | None:
    """Mapea un nombre de documento (del texto de respuesta) a su clave canónica."""
    low = doc_fragment.lower().strip()
    for alias, key in _DOC_ALIAS.items():
        if alias in low:
            return key
    return None


def _filtrar_articulos_no_rag(respuesta: str, relevant_context: str) -> str:
    """
    Post-procesamiento document-aware: elimina de la respuesta artículos
    cuyo número no aparezca en el bloque [Doc: X] correspondiente del contexto.
    - "Art. 32° del RIOHS" → se verifica que el nº 32 esté en chunks RIOHS.
    - "Art. 32°" (sin doc) → se verifica en todos los docs; si no está → elimina.
    """
    if not relevant_context or not respuesta:
        return respuesta

    whitelist = _construir_whitelist_doc(relevant_context)
    # Whitelist plana (todos los docs combinados) para artículos sin doc explícito
    nums_global: set = set()
    for nums in whitelist.values():
        nums_global |= {n for n in nums if not n.startswith('A')}
    anexos_global: set = {n[1:] for vals in whitelist.values() for n in vals if n.startswith('A')}

    PAT_ART = re.compile(
        r'(Art(?:ículos?)?\.?\s+)'
        r'(\d+)'
        r'([°º]?(?:\s*bis)?)'
        r'((?:\s*(?:y|e)\s*\d+[°º]?)*)'
        r'((?:\s+(?:del?|de\s+la|de\s+los)\s+[A-ZÁÉÍÓÚÑ\w][^,\.\n;\|]{2,60})?)',
        re.IGNORECASE,
    )
    PAT_ANEXO = re.compile(
        r'(Anexo\s+(?:N[°º]?\s*)?)(\d+)'
        r'((?:\s+(?:del?|de\s+la)\s+[A-ZÁÉÍÓÚÑ\w][^,\.\n;\|]{2,60})?)',
        re.IGNORECASE,
    )

    def _doc_name(s: str) -> str:
        return re.sub(r'^\s*(?:del?|de\s+la|de\s+los)\s+', '', s, flags=re.IGNORECASE).strip()

    def _reemplazar_art(m: re.Match) -> str:
        num = m.group(2)
        doc_frag = m.group(5) or ''
        doc_name = _doc_name(doc_frag)

        if doc_name:
            doc_key = _resolver_doc_key(doc_name)
            if doc_key and num in whitelist.get(doc_key, set()):
                return m.group(0)       # verificado en ese documento específico
            # Número no verificado para ese documento
            return doc_name             # mantener solo el nombre del documento

        # Sin documento explícito: verificar en whitelist global
        if num in nums_global:
            return m.group(0)
        return 'el artículo correspondiente'

    def _reemplazar_anexo(m: re.Match) -> str:
        num = m.group(2)
        doc_frag = m.group(3) or ''
        doc_name = _doc_name(doc_frag)
        if doc_name:
            doc_key = _resolver_doc_key(doc_name)
            if doc_key and f'A{num}' in whitelist.get(doc_key, set()):
                return m.group(0)
            return doc_name
        if num in anexos_global:
            return m.group(0)
        return 'el anexo correspondiente'

    respuesta = PAT_ART.sub(_reemplazar_art, respuesta)
    respuesta = PAT_ANEXO.sub(_reemplazar_anexo, respuesta)
    respuesta = re.sub(r' {2,}', ' ', respuesta)
    respuesta = re.sub(r'\b(el|la|los|las)\s+\1\b', r'\1', respuesta, flags=re.IGNORECASE)
    respuesta = re.sub(r'\| {0,3}\|', '| — |', respuesta)
    respuesta = re.sub(r'(?m)^\s*[\|]\s*[\|]\s*$', '', respuesta)
    return respuesta


def call_deepseek_ai(assistant, messages_history, user_query, temperature=0.3, attached_content=None):
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
        relevant_context = get_relevant_chunks(assistant, user_query, top_n=20)
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
