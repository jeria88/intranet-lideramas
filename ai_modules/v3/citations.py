"""
Extractor de citas verificadas desde el contexto RAG — v3 / v3.1.

v3:   whitelist explícita inyectada como instrucción → modelo la ignora si
      puede leer los números directamente en el texto RAG.
v3.1: preprocesar_rag() reemplaza los números NO verificados con '[N°]'
      ANTES de enviarlos al modelo → imposible citar lo que no se puede leer.
"""

import re


# Documentos conocidos y sus palabras clave de detección en el RAG
_DOC_DETECTORES: list[tuple[str, list[str]]] = [
    ('RIOHS',                   ['RIOHS', 'reglamento interno de orden']),
    ('RICE',                    ['RICE', 'reglamento interno de convivencia', 'reglamento de convivencia']),
    ('Reglamento de Evaluación',['REGLAMENTO DE EVALUACIÓN', 'reglamento de evaluación', 'reglamento evaluación']),
    ('Decreto 170',             ['Decreto 170', 'DTO-170', 'decreto 170']),
    ('Decreto 83',              ['Decreto 83', 'decreto 83']),
    ('Decreto 67',              ['Decreto 67', 'decreto 67']),
    ('Ley 20.536',              ['Ley 20.536', '20.536']),
    ('Ley 21.545',              ['Ley 21.545', '21.545']),
]


def extraer_whitelist(relevant_context: str) -> dict:
    """
    Analiza el contexto RAG recuperado y retorna:
    {
        'docs':      ['RIOHS', 'Reglamento de Evaluación', ...],
        'articulos': ['Art. 32 del RIOHS', 'Art. 15 del Decreto 170', ...]
    }
    """
    if not relevant_context:
        return {'docs': [], 'articulos': []}

    ctx_lower = relevant_context.lower()

    # 1. Documentos presentes
    docs_presentes: list[str] = []
    for doc_name, keywords in _DOC_DETECTORES:
        if any(kw.lower() in ctx_lower for kw in keywords):
            docs_presentes.append(doc_name)

    # 2. Artículos verificados por bloque [Doc: ...]
    articulos: list[str] = []
    for block in re.split(r'\[Doc:', relevant_context):
        if not block.strip():
            continue
        header = block[:120].lower()
        doc_label = None
        for doc_name, keywords in _DOC_DETECTORES:
            if any(kw.lower() in header for kw in keywords):
                doc_label = doc_name
                break
        if doc_label is None:
            continue
        nums = re.findall(r'Art(?:ículo)?\.?\s*(\d+)[°º]?\b', block, re.IGNORECASE)
        for n in nums:
            ref = f"Art. {n} del {doc_label}"
            if ref not in articulos:
                articulos.append(ref)

    return {'docs': docs_presentes, 'articulos': articulos}


def preprocesar_rag(relevant_context: str, whitelist: dict) -> str:
    """
    v3.1 — Preprocesa el RAG antes de enviarlo al modelo.

    Recorre bloque por bloque ([Doc: ...]) e identifica el documento al que
    pertenece cada chunk. Dentro de cada bloque, reemplaza los números de
    artículo que NO están en la whitelist verificada por '[N°]', de modo que
    el modelo físicamente no puede leer ni citar esos números.

    Los artículos en la whitelist se preservan intactos.
    """
    if not relevant_context:
        return relevant_context

    # Construir lookup: doc_label → set de números verificados
    verified: dict[str, set[str]] = {}
    for ref in whitelist.get('articulos', []):
        m = re.match(r'Art\.\s*(\d+)\s+del\s+(.+)', ref)
        if m:
            num, doc = m.group(1), m.group(2).strip()
            verified.setdefault(doc, set()).add(num)

    # re.split con grupo capturador preserva el delimitador '[Doc:'
    parts = re.split(r'(\[Doc:)', relevant_context)
    result = []
    i = 0
    while i < len(parts):
        if parts[i] == '[Doc:' and i + 1 < len(parts):
            block = parts[i + 1]
            header = block[:120].lower()
            doc_label = None
            for doc_name, keywords in _DOC_DETECTORES:
                if any(kw.lower() in header for kw in keywords):
                    doc_label = doc_name
                    break
            allowed = verified.get(doc_label, set()) if doc_label else set()

            # Default arg captura el valor actual de 'allowed' (cierre en bucle)
            def _replace(m, _allowed=allowed):
                return m.group(0) if m.group(1) in _allowed else m.group(0).replace(m.group(1), '[N°]', 1)

            result.append('[Doc:')
            result.append(re.sub(r'Art(?:ículo)?\.?\s*(\d+)[°º]?\b', _replace, block, flags=re.IGNORECASE))
            i += 2
        else:
            result.append(parts[i])
            i += 1

    return ''.join(result)


def construir_bloque_citas(whitelist: dict) -> str:
    """
    Construye el bloque '### CITAS VERIFICADAS' que se inyecta en el mensaje
    del usuario (entre el RAG y la consulta).
    """
    lines = ["### CITAS VERIFICADAS (las únicas que puedes citar por nombre):"]

    if whitelist['docs']:
        lines.append(f"Documentos: {', '.join(whitelist['docs'])}")
    else:
        lines.append("Documentos: ninguno identificado en el contexto")

    if whitelist['articulos']:
        # Agrupar por documento para legibilidad
        lines.append(f"Artículos: {', '.join(whitelist['articulos'])}")
    else:
        lines.append("Artículos: ninguno verificado en el contexto")

    lines.append(
        "→ Cualquier otro documento, ley, decreto o número de artículo que conozcas de memoria "
        "NO puede citarse por nombre. Describe la materia sin nombrarlo."
    )
    return "\n".join(lines)
