import requests
from django.conf import settings
from .utils import get_relevant_chunks

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
            "### CONTEXTO DOCUMENTAL (RAG):\n"
            f"{relevant_context}\n"
            "--- FIN DEL CONTEXTO ---"
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
        return data['choices'][0]['message']['content']
    except Exception as e:
        print(f"Error calling DeepSeek: {e}")
        return f"Lo siento, hubo un error al procesar tu consulta (DeepSeek API Error). Por favor, intenta de nuevo en unos momentos o reporta este error: {str(e)}"
