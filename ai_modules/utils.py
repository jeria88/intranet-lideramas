import os
from pypdf import PdfReader
from django.conf import settings
import math
import numpy as np
import json
import gc

# Caché en memoria para evitar recargas constantes en servidores con RAM limitada
# Caché en memoria limitada para evitar saturar los 512MB de Railway
_VECTOR_RESOURCES = {}
MAX_CACHE_SIZE = 3 # Máximo 3 asistentes en RAM simultáneamente

import docx

def extract_text_from_pdf(file_input):
    """Extrae el texto de un archivo PDF usando pypdf, con fallback a OCR para escaneados."""
    text = ""
    try:
        if hasattr(file_input, 'seek'):
            file_input.seek(0)
            
        reader = PdfReader(file_input)
        for page in reader.pages:
            content = page.extract_text()
            if content:
                text += content + "\n"
                
    # Fallback a OCR si el texto es muy corto (probablemente escaneado)
        if len(text.strip()) < 50:
            try:
                import pdf2image
                import pytesseract
                import tempfile
                from PIL import Image
                
                # Para ahorrar RAM, guardamos a un archivo temporal en lugar de bytes en memoria
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_pdf:
                    if hasattr(file_input, 'seek'):
                        file_input.seek(0)
                        temp_pdf.write(file_input.read())
                    else:
                        with open(file_input, 'rb') as f:
                            temp_pdf.write(f.read())
                    temp_path = temp_pdf.name

                try:
                    # Obtenemos info del PDF sin cargarlo todo
                    info = pdf2image.pdfinfo_from_path(temp_path)
                    max_pages = info.get("Pages", 0)
                    
                    ocr_text = ""
                    # Procesamos página por página para no saturar los 512MB de RAM
                    for i in range(1, max_pages + 1):
                        # 120 DPI es suficiente para OCR y consume menos RAM que 150/300
                        page_images = pdf2image.convert_from_path(
                            temp_path, 
                            first_page=i, 
                            last_page=i, 
                            dpi=120
                        )
                        if page_images:
                            ocr_text += pytesseract.image_to_string(page_images[0], lang='spa') + "\n"
                            # Liberar memoria explícitamente
                            page_images[0].close()
                            del page_images
                            import gc
                            gc.collect()
                            
                    if len(ocr_text.strip()) > len(text.strip()):
                        text = ocr_text
                finally:
                    # Siempre limpiar el archivo temporal
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                        
            except Exception as ocr_e:
                print(f"Error en OCR fallback: {ocr_e}")

                
    except Exception as e:
        print(f"Error extrayendo texto de PDF: {e}")
    return text

def extract_text_from_docx(file_path):
    """Extrae el texto de un archivo Word (.docx)."""
    text = ""
    try:
        doc = docx.Document(file_path)
        for para in doc.paragraphs:
            text += para.text + "\n"
    except Exception as e:
        print(f"Error extrayendo texto de Word: {e}")
    return text

def extract_text_from_file(file_obj):
    """
    Detecta el tipo de archivo y extrae el texto.
    Soporta PDF, DOCX, TXT, MD.
    """
    if not file_obj:
        return ""
    
    # El file_obj puede ser un path o un objeto de archivo de Django
    filename = getattr(file_obj, 'name', str(file_obj)).lower()
    
    # Si es un objeto de archivo (InmemoryUploadedFile o similar), necesitamos leerlo
    # Para librerías que requieren paths, a veces es mejor guardar temporalmente
    # Pero PdfReader y Document pueden aceptar streams en muchos casos.
    
    try:
        if filename.endswith('.pdf'):
            return extract_text_from_pdf(file_obj)
        elif filename.endswith('.docx'):
            return extract_text_from_docx(file_obj)
        elif filename.endswith(('.txt', '.md', '.json')):
            if hasattr(file_obj, 'read'):
                content = file_obj.read()
                if isinstance(content, bytes):
                    return content.decode('utf-8', errors='ignore')
                return content
            else:
                with open(file_obj, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
    except Exception as e:
        print(f"Error general en extracción: {e}")
    
    return ""

def chunk_text(text, chunk_size=1000, overlap=150):
    """Divide texto en fragmentos con overlap para el RAG."""
    # Normalizar espacios y saltos de línea excesivos
    import re
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        # Intentar cortar en punto o salto de párrafo para no partir palabras
        if end < len(text):
            cut = max(text.rfind('. ', start, end), text.rfind('\n', start, end))
            if cut > start + chunk_size // 2:
                end = cut + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
        if start >= len(text):
            break
    return chunks


def index_knowledge_base_file(kb_obj):
    """
    Pipeline completo: extrae texto → chunkea → genera embeddings → guarda en RAG.
    Llama desde el admin o management commands.
    Retorna (chunks_creados, error_msg). error_msg es None si todo fue OK.
    """
    import hashlib
    from .models import AIKnowledgeChunk

    # 1. Extraer texto
    text = extract_text_from_file(kb_obj.file)
    if not text.strip():
        return 0, f"No se pudo extraer texto de '{kb_obj.name}'."

    # 2. Chunkear
    chunks_text = chunk_text(text)
    if not chunks_text:
        return 0, f"El documento '{kb_obj.name}' quedó vacío tras el chunking."

    # 3. Metadatos inferidos del asistente
    assistant = kb_obj.assistant
    establecimiento = assistant.establishment.lower() if assistant.establishment else 'red'
    rol = assistant.profile_role.lower()
    nivel = kb_obj.nivel
    doc_slug = hashlib.md5(kb_obj.name.encode()).hexdigest()[:8]

    # 4. Eliminar chunks anteriores del mismo documento para este asistente
    AIKnowledgeChunk.objects.using('knowledge_base').filter(
        assistant_id=assistant.pk,
        document_name=kb_obj.name,
    ).delete()

    # 5. Generar embeddings en lotes y guardar
    embedding_fn = get_openai_embedding  # ya definida en este módulo
    new_chunks = []
    batch_size = 50

    try:
        import openai
        from django.conf import settings as dj_settings
        api_key_val = getattr(dj_settings, 'OPENAI_API_KEY', os.environ.get('OPENAI_API_KEY'))
        if not api_key_val:
            return 0, "OPENAI_API_KEY no configurada."
        client = openai.OpenAI(api_key=api_key_val)

        for i in range(0, len(chunks_text), batch_size):
            batch = chunks_text[i:i + batch_size]
            response = client.embeddings.create(input=batch, model="text-embedding-3-small")
            for j, emb_data in enumerate(response.data):
                idx = i + j
                chunk_id = f"{assistant.slug}-{doc_slug}-{idx}"
                new_chunks.append(AIKnowledgeChunk(
                    assistant_id=assistant.pk,
                    content=batch[j],
                    metadata={
                        'nivel':         nivel,
                        'establecimiento': establecimiento,
                        'rol':           rol,
                        'fuente_archivo': kb_obj.name,
                        'chunk_id':      chunk_id,
                    },
                    chunk_id=chunk_id,
                    document_name=kb_obj.name,
                    index=idx,
                    embedding=emb_data.embedding,
                ))
    except Exception as e:
        return 0, f"Error al generar embeddings: {e}"

    if new_chunks:
        AIKnowledgeChunk.objects.using('knowledge_base').bulk_create(
            new_chunks, ignore_conflicts=True
        )

    # 6. Marcar como procesado y guardar texto extraído
    kb_obj.extracted_text = text[:50000]  # límite para no saturar BD
    kb_obj.is_processed = True
    kb_obj.save(update_fields=['extracted_text', 'is_processed'])

    # 7. Invalidar caché de vectores en memoria para este asistente
    from .utils import _VECTOR_RESOURCES
    _VECTOR_RESOURCES.pop(assistant.slug, None)

    return len(new_chunks), None


def process_knowledge_base_file(knowledge_base_obj):
    """Procesa un objeto AIKnowledgeBase, extrae su texto y actualiza el asistente."""
    if not knowledge_base_obj.file:
        return
    
    file_path = knowledge_base_obj.file.path
    extracted_text = extract_text_from_pdf(file_path)
    
    knowledge_base_obj.extracted_text = extracted_text
    knowledge_base_obj.is_processed = True
    knowledge_base_obj.save(update_fields=['extracted_text', 'is_processed'])
    
    knowledge_base_obj.assistant.update_context_text()


# ── Motor de Embeddings API (Cero consumo RAM) ──────────────────────────

def cosine_similarity(v1, v2):
    """Calcula similitud coseno en Python puro."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_v1 = math.sqrt(sum(a * a for a in v1))
    norm_v2 = math.sqrt(sum(b * b for b in v2))
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    return dot_product / (norm_v1 * norm_v2)

def get_openai_embedding(text):
    import openai
    api_key_val = getattr(settings, 'OPENAI_API_KEY', os.environ.get('OPENAI_API_KEY'))
    if not api_key_val:
        print("Falta configurar OPENAI_API_KEY en .env")
        return None
    try:
        client = openai.OpenAI(api_key=api_key_val)
        response = client.embeddings.create(
            input=[text],
            model="text-embedding-3-small"
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"Error generando embedding: {e}")
        return None

def get_relevant_chunks(assistant, query, top_n=10):
    """
    Busca fragmentos relevantes usando similitud coseno con sistema de caché binario.
    Optimizado para evitar timeouts en servidores con recursos limitados (Railway Free).
    """
    from .models import AIKnowledgeChunk
    import json
    import numpy as np
    import time

    cache_dir = os.path.join(settings.BASE_DIR, 'ai_modules', 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    
    matrix_path = os.path.join(cache_dir, f'vectors_{assistant.slug}.npy')
    meta_path = os.path.join(cache_dir, f'meta_{assistant.slug}.json')

    # 1. Convertir la consulta en embedding
    query_embedding = get_openai_embedding(query)
    if not query_embedding:
        return "No hay contexto documental disponible. Responde con base en tu conocimiento general de normativa educacional chilena vigente."

    # 2. Intentar cargar desde caché (Memoria RAM persistente en el proceso)
    cached = _VECTOR_RESOURCES.get(assistant.slug)
    
    # Lógica de filtros jerárquicos: 
    # Si el slug es 'global-knowledge' o termina en '-general' o '-global', permitimos acceso total
    is_global = assistant.slug == 'global-knowledge' or \
                assistant.slug.endswith(('-general', '-global')) or \
                not '-' in assistant.slug
    
    # Filtro base para la base de datos
    from django.db.models import Q
    
    if not is_global:
        # Extraer rol y establecimiento del slug (ej: utp-temuco)
        slug_parts = assistant.slug.split('-')
        rol_obj = slug_parts[0]
        est_obj = slug_parts[1] if len(slug_parts) > 1 else 'temuco'
        
        # El filtro recupera: Nacional + Institucional (del establecimiento) + Rol (del establecimiento)
        filter_q = Q(metadata__nivel__in=['nacional', 'congregacional']) | \
                   (Q(metadata__establecimiento=est_obj) & Q(metadata__nivel='institucional')) | \
                   (Q(metadata__establecimiento=est_obj) & Q(metadata__rol=rol_obj))
    else:
        # Global ve TODO (Requerimiento piloto: Todos los directores ven toda la base de Temuco/Nacional)
        filter_q = Q()

    # Conteo para trigger de caché
    db_count_trigger = AIKnowledgeChunk.objects.using('knowledge_base').filter(filter_q).exclude(embedding__isnull=True).count()

    cache_ready = False

    if cached and cached['meta']['count'] == db_count_trigger:
        ids = cached['ids']
        doc_names = cached['doc_names']
        indices = cached['indices']
        matrix = cached['matrix']
        priority_mask = cached['priority_mask']
        cache_ready = True
    elif os.path.exists(matrix_path) and os.path.exists(meta_path):
        try:
            with open(meta_path, 'r') as f:
                meta = json.load(f)
            
            if meta['count'] == db_count_trigger:
                ids = meta['ids']
                doc_names = meta['doc_names']
                indices = meta['indices']
                # Leer como memmap (binario crudo, sin header .npy)
                matrix = np.memmap(matrix_path, dtype='float32', mode='r', shape=(meta['count'], 1536))
                
                # Pre-calcular el priority_mask una sola vez para ahorrar CPU
                p_patterns = ["2.-Ley-21809", "Manual-de-cuentas-2026"]
                p_mask = np.zeros(len(doc_names), dtype=bool)
                for pattern in p_patterns:
                    p_mask |= np.array([pattern in str(d) for d in doc_names])
                
                # Guardar en el singleton del proceso
                _VECTOR_RESOURCES[assistant.slug] = {
                    'ids': ids,
                    'doc_names': doc_names,
                    'indices': indices,
                    'matrix': matrix,
                    'meta': meta,
                    'priority_mask': p_mask
                }
                priority_mask = p_mask
                cache_ready = True
        except Exception as e:
            print(f"Error cargando caché: {e}")
            if assistant.slug in _VECTOR_RESOURCES:
                del _VECTOR_RESOURCES[assistant.slug]
            import gc
            gc.collect()

    # 3. Control de Limpieza de Caché (LRU básico)
    if not cache_ready:
        if len(_VECTOR_RESOURCES) >= MAX_CACHE_SIZE:
            print("Limpiando caché de vectores para liberar RAM...")
            _VECTOR_RESOURCES.clear()
            import gc
            gc.collect()

    # 3. Si no hay caché o está desactualizado, reconstruir desde BD
    if not cache_ready:
        import gc
        print(f"Reconstruyendo caché JERÁRQUICO para {assistant.slug}...")
        
        queryset = AIKnowledgeChunk.objects.using('knowledge_base').filter(
            filter_q
        ).exclude(
            embedding__isnull=True
        ).only('id', 'embedding', 'document_name', 'index')

        db_count = queryset.count()
        if db_count == 0:
            return "No hay documentos específicos cargados para este asistente. Responde con base en tu conocimiento general de normativa educacional chilena vigente."

        # Usar memmap para reconstruir la matriz directamente en disco sin saturar la RAM
        matrix = np.memmap(matrix_path, dtype='float32', mode='w+', shape=(db_count, 1536))
        ids = [None] * db_count
        doc_names = [None] * db_count
        indices = [None] * db_count

        # Procesar en bloques para no saturar memoria
        for i, chunk in enumerate(queryset.iterator(chunk_size=500)):
            ids[i] = chunk.id
            doc_names[i] = chunk.document_name
            indices[i] = chunk.index
            
            emb = chunk.embedding
            if isinstance(emb, str):
                emb = json.loads(emb)
            matrix[i] = emb
            
            # Limpieza periódica de referencias de Django
            if i % 1000 == 0:
                gc.collect()

        # Guardar caché para la próxima vez
        try:
            matrix.flush()
            del matrix # Liberar puntero de memmap
            meta_payload = {
                'count': db_count,
                'ids': ids,
                'doc_names': doc_names,
                'indices': indices
            }
            with open(meta_path, 'w') as f:
                json.dump(meta_payload, f)
            
            # Recargar como read-only memmap (mismo formato binario crudo, no .npy)
            matrix = np.memmap(matrix_path, dtype='float32', mode='r', shape=(db_count, 1536))

            p_patterns = ["2.-Ley-21809", "Manual-de-cuentas-2026"]
            priority_mask = np.zeros(len(doc_names), dtype=bool)
            for pattern in p_patterns:
                priority_mask |= np.array([pattern in str(d) for d in doc_names])

            _VECTOR_RESOURCES[assistant.slug] = {
                'ids': ids,
                'doc_names': doc_names,
                'indices': indices,
                'matrix': matrix,
                'meta': meta_payload,
                'priority_mask': priority_mask
            }
            gc.collect()
        except Exception as e:
            print(f"Advertencia: No se pudo guardar caché en disco: {e}")
            # matrix fue del-eada arriba — recargar desde el archivo memmap ya escrito
            matrix = np.memmap(matrix_path, dtype='float32', mode='r', shape=(db_count, 1536))
            p_patterns = ["2.-Ley-21809", "Manual-de-cuentas-2026"]
            priority_mask = np.zeros(db_count, dtype=bool)
            for pattern in p_patterns:
                priority_mask |= np.array([pattern in str(d) for d in doc_names])

    # 4. Cálculo de Similitud
    q_vec = np.array(query_embedding, dtype=np.float32)
    similarities = np.dot(matrix, q_vec)

    # 5. Boosting Normativo EXTREMO (Optimizado con máscara pre-calculada)
    query_lower = query.lower()
    account_keywords = ["codigo", "cuenta", "item", "clase", "sep", "pie", "801", "802", "803", "804"]
    is_account_query = any(k in query_lower for k in account_keywords)

    convivencia_keywords = ["rice", "riohs", "convivencia", "falta", "sanción", "sancion", "conducta",
                            "disciplina", "amonestación", "amonestacion", "suspension", "suspensión",
                            "acoso", "bullying", "ridiculiz", "reglamento interno", "protocolo"]
    is_convivencia_query = any(k in query_lower for k in convivencia_keywords)

    # Máscara RICE/RIOHS — boost contextual para consultas de convivencia
    rice_riohs_mask = np.array(
        ["RICE_2025_temuco" in str(d) or "RIOHS_2025_temuco" in str(d) for d in doc_names],
        dtype=bool
    )

    # Priorización agresiva para asegurar que la Ley y el Manual siempre estén arriba
    similarities[priority_mask] *= 500.0
    if is_account_query:
        similarities[priority_mask] *= 10.0

    # Boost RICE/RIOHS solo cuando la consulta es de convivencia o disciplina
    if is_convivencia_query:
        similarities[rice_riohs_mask] *= 300.0

    # 6. Selección por "Cubos" (Garantiza presencia de normativa oficial)
    # Cubo A: Fragmentos de Ley/Manual (Prioridad Legal)
    sacred_idxs = np.where(priority_mask)[0]
    sacred_top_n = min(len(sacred_idxs), 7)
    sacred_top = sacred_idxs[np.argsort(similarities[sacred_idxs])[::-1][:sacred_top_n]]

    # Cubo A2: RICE/RIOHS en consultas de convivencia (garantiza al menos 3 chunks)
    if is_convivencia_query and rice_riohs_mask.any():
        rice_idxs = np.where(rice_riohs_mask)[0]
        rice_top = rice_idxs[np.argsort(similarities[rice_idxs])[::-1][:3]]
    else:
        rice_top = np.array([], dtype=int)

    # Cubo B: Resto de documentos (Contexto Institucional)
    combined_priority = priority_mask | (rice_riohs_mask if is_convivencia_query else np.zeros_like(priority_mask, dtype=bool))
    other_idxs = np.where(~combined_priority)[0]
    other_top_n = min(len(other_idxs), top_n - len(sacred_top) - len(rice_top))
    other_top = other_idxs[np.argsort(similarities[other_idxs])[::-1][:other_top_n]]
    
    # Combinar manteniendo el orden de relevancia
    top_indices = np.concatenate([sacred_top, rice_top, other_top])
    top_indices = np.unique(top_indices)  # evitar duplicados si RICE ya estaba en sacred
    
    scored_results = []
    for idx in top_indices:
        # Umbral dinámico: más restrictivo para evitar alucinaciones por ruido (Ajedrez galáctico ~0.25)
        threshold = 0.25 if priority_mask[idx] else 0.35
        if similarities[idx] > threshold:
            scored_results.append({
                'id': ids[idx],
                'doc': doc_names[idx],
                'index': indices[idx]
            })

    if not scored_results:
        return "No se encontraron fragmentos relevantes para tu consulta."

    # 7. Expansión y Contenido (Optimización: Una sola consulta)
    # Recolectar todos los índices necesarios para minimizar hits a la BD
    needed_indices = []
    for item in scored_results:
        needed_indices.extend([item['index']-1, item['index'], item['index']+1])
    
    # Traer todos los fragmentos vecinos de una vez
    relevant_docs = set(item['doc'] for item in scored_results)
    neighbors = AIKnowledgeChunk.objects.using('knowledge_base').filter(
        filter_q,
        document_name__in=relevant_docs,
        index__in=needed_indices
    ).order_by('document_name', 'index')

    final_chunks = list(neighbors)
    final_chunks.sort(key=lambda c: (c.document_name or '', c.index or 0))

    return "\n\n---\n\n".join(
        [f"[Fuente: {c.document_name} - Sec: {c.index}]\n{c.content}" for c in final_chunks]
    )
