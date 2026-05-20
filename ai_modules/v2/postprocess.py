"""
Post-procesamiento v2 — filtro de citas no respaldadas por RAG.

Extiende el filtro de v1 (números de artículo) con filtro de nombres de documentos:
si el modelo cita un documento por nombre pero ese documento no aparece en el
contexto RAG recuperado, el nombre es reemplazado por una descripción genérica.
"""

import re


# ---------------------------------------------------------------------------
# Documentos conocidos y sus palabras clave de detección en el RAG
# ---------------------------------------------------------------------------

_DOC_KEYWORDS: dict[str, list[str]] = {
    'riohs':     ['RIOHS', 'riohs', 'reglamento interno de orden', 'reglamento de orden higiene'],
    'rice':      ['RICE', 'rice', 'reglamento interno de convivencia', 'reglamento de convivencia'],
    'regl_eval': ['REGLAMENTO DE EVALUACIÓN', 'reglamento de evaluación', 'reglamento de evaluacion',
                  'Regl. Evaluación', 'reglamento evaluación'],
    'dto170':    ['DTO-170', 'Decreto-170', 'Decreto 170', 'decreto 170'],
    'dto83':     ['Decreto-83', 'Decreto 83', 'decreto 83'],
    'dto67':     ['Decreto-67', 'Decreto 67', 'decreto 67'],
    'ley20536':  ['Ley 20.536', 'ley 20.536', 'Ley 20536', '20.536'],
    'ley21545':  ['Ley 21.545', 'ley 21.545', 'Ley 21545', '21.545'],
    'pei':       ['PEI', 'Proyecto Educativo Institucional'],
}

# Patrones de texto que el modelo genera al citar estos documentos (en respuesta)
_DOC_RESPONSE_PATTERNS: list[tuple[str, str, str]] = [
    # (regex_en_respuesta, doc_key, reemplazo_si_no_en_rag)
    (r'(?:la\s+)?Ley\s+20[\.·]?536(?:\s+(?:sobre|de)\s+[Vv]iolencia\s+[Ee]scolar)?', 'ley20536', 'la normativa sobre violencia escolar'),
    (r'(?:la\s+)?Ley\s+21[\.·]?545(?:\s+(?:sobre|de)\s+[Tt]rastorno(?:s)?\s+del\s+[Ee]spectro\s+[Aa]utista)?', 'ley21545', 'la normativa sobre TEA'),
    (r'(?:la\s+)?Ley\s+General\s+de\s+Educaci[oó]n(?:\s+\([^)]{1,40}\))?', None, 'la normativa general de educación'),
    (r'(?:el\s+)?RIOHS', 'riohs', 'el reglamento interno de orden, higiene y seguridad'),
    (r'(?:el\s+)?RICE', 'rice', 'el reglamento de convivencia escolar'),
    (r'(?:el\s+)?Reglamento\s+(?:Interno\s+)?de\s+Convivencia\s+Escolar(?:\s+\([^)]{1,40}\))?', 'rice', 'el reglamento de convivencia escolar'),
    (r'(?:el\s+)?Decreto\s+170(?:/2009)?', 'dto170', 'la normativa de necesidades educativas especiales'),
    (r'(?:el\s+)?Decreto\s+83(?:/2015)?', 'dto83', 'la normativa de diversificación curricular'),
    (r'(?:el\s+)?Decreto\s+67(?:/2018)?', 'dto67', 'la normativa de evaluación y promoción'),
    (r'(?:el\s+)?PEI(?:\s+del\s+(?:colegio|establecimiento|[A-ZÁÉÍÓÚ][^,\.\n]{0,50}))?', 'pei', 'el proyecto educativo institucional'),
]

# Patrones de metadatos de chunks que el modelo puede citar como si fueran artículos.
# Ej: "sección 5385", "Reglamento de Evaluación 2025_1.pdf (artículo 2, sección i)"
_CHUNK_META_PATTERNS: list[tuple[str, str]] = [
    # IDs numéricos de chunks citados como "sección N"
    (r'\bsecci[oó]n\s+\d{4,}\b(?:\s*[-–]\s*\d{4,})?', 'la sección correspondiente'),
    # Nombres de archivo PDF citados directamente
    (r'\b[\w\s\-]+\.pdf\s*\([^)]{1,80}\)', 'el documento de referencia'),
]

# Alias en respuesta → doc_key (para el filtro de artículos)
_DOC_ALIAS: dict[str, str] = {
    'riohs': 'riohs',
    'rice': 'rice',
    'reglamento de convivencia': 'rice',
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
    'ley 20.536': 'ley20536',
    'ley 20536': 'ley20536',
    'ley 21.545': 'ley21545',
    'ley 21545': 'ley21545',
}


def _docs_presentes_en_rag(relevant_context: str) -> set[str]:
    """Retorna el conjunto de doc_keys que aparecen en el contexto RAG."""
    present: set[str] = set()
    ctx_lower = relevant_context.lower()
    for doc_key, keywords in _DOC_KEYWORDS.items():
        if any(kw.lower() in ctx_lower for kw in keywords):
            present.add(doc_key)
    return present


def _construir_whitelist_articulos(relevant_context: str) -> dict[str, set[str]]:
    """Retorna {doc_key: set_of_article_numbers} verificados en el RAG."""
    whitelist: dict[str, set[str]] = {k: set() for k in _DOC_KEYWORDS}
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
            whitelist[doc_key].add(f'A{a}')
    return whitelist


def _resolver_doc_key(doc_fragment: str) -> str | None:
    low = doc_fragment.lower().strip()
    for alias, key in _DOC_ALIAS.items():
        if alias in low:
            return key
    return None


def filtrar_citas_no_rag(respuesta: str, relevant_context: str) -> str:
    """
    Filtra de la respuesta:
    1. Nombres de documentos no presentes en el RAG (Type B inventados).
    2. Números de artículo no verificados en el RAG (Type A inventados).
    """
    if not relevant_context or not respuesta:
        return respuesta

    docs_rag = _docs_presentes_en_rag(relevant_context)
    whitelist = _construir_whitelist_articulos(relevant_context)

    # Whitelist plana para artículos sin doc explícito
    nums_global: set[str] = set()
    for nums in whitelist.values():
        nums_global |= {n for n in nums if not n.startswith('A')}
    anexos_global: set[str] = {n[1:] for vals in whitelist.values() for n in vals if n.startswith('A')}

    # --- PASO 0: filtrar metadatos de chunks (Type C) ---
    for pattern, reemplazo in _CHUNK_META_PATTERNS:
        respuesta = re.sub(pattern, reemplazo, respuesta, flags=re.IGNORECASE)

    # --- PASO 1: filtrar nombres de documentos (Type B) ---
    for pattern, doc_key, reemplazo in _DOC_RESPONSE_PATTERNS:
        if doc_key is not None and doc_key in docs_rag:
            continue  # documento presente en RAG → no filtrar
        if doc_key is None:
            # siempre filtrar (ley no en _DOC_KEYWORDS, nunca en RAG)
            respuesta = re.sub(pattern, reemplazo, respuesta, flags=re.IGNORECASE)
            continue
        respuesta = re.sub(pattern, reemplazo, respuesta, flags=re.IGNORECASE)

    # --- PASO 2: filtrar números de artículo (Type A) ---
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
                return m.group(0)
            return doc_name
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

    # Limpieza cosmética
    respuesta = re.sub(r' {2,}', ' ', respuesta)
    respuesta = re.sub(r'\b(el|la|los|las)\s+\1\b', r'\1', respuesta, flags=re.IGNORECASE)
    respuesta = re.sub(r'\| {0,3}\|', '| — |', respuesta)
    respuesta = re.sub(r'(?m)^\s*[\|]\s*[\|]\s*$', '', respuesta)

    return respuesta
