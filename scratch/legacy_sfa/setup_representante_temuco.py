import json
import os
import uuid
from django.conf import settings
from django.core.management.base import BaseCommand
from ai_modules.models import AIAssistant, AIKnowledgeChunk

class Command(BaseCommand):
    help = 'Configura el asistente Representante Temuco e ingesta su base de conocimientos JSON'

    def handle(self, *args, **options):
        json_path = os.path.join(settings.BASE_DIR, 'ai_modules', 'knowledge_base', 'representante_temuco.json')
        assistant_slug = 'representante-temuco'

        # Limpiar cualquier configuración previa incorrecta (con punto)
        AIAssistant.objects.filter(slug='representante.temuco').delete()

        # 1. Obtener o crear el asistente
        assistant, created = AIAssistant.objects.get_or_create(
            slug=assistant_slug,
            defaults={
                'name': 'Asistente Representante Legal (Temuco)',
                'profile_role': 'REPRESENTANTE',
                'establishment': 'TEMUCO',
                'is_chat_enabled': True,
                'is_active': True,
            }
        )

        # 2. Actualizar el Prompt Maestro
        system_instruction = (
            "Eres la Representante Legal y Administradora Superior del Colegio de Temuco. Tu asesoría es estrictamente técnico-normativa. "
            "\n\n### FUENTES PRIMARIAS DE VERDAD (PRIORIDAD 0 - OBLIGATORIAS):\n"
            "1. '2.-Ley-21809_01-ABR-2026.pdf': Base legal de toda decisión administrativa.\n"
            "2. '3.- Manual-de-cuentas-2026_baja.pdf': ÚNICA fuente para códigos de cuenta SEP y PIE.\n"
            "\n\n### REGLA DE ORO DE LOS CÓDIGOS DE CUENTA:\n"
            "- DEBES buscar el código exacto (ej. 411 802) en el 'CONTEXTO DE DOCUMENTOS' proporcionado.\n"
            "- COINCIDENCIA LITERAL OBLIGATORIA: Prohibido asociar ítems por 'parecido' (ej. no asocies un monitor de ajedrez galáctico con honorarios si no existe la descripción exacta).\n"
            "- Si no hay coincidencia exacta para el gasto buscado, indica: 'No se visualiza la descripción exacta ni el código de cuenta específico en el Manual de Cuentas 2026 para este ítem'.\n"
            "\n\n### FORMATO DE RESPUESTA REQUERIDO (NO MODIFICAR SECCIONES):\n"
            "A.- BIENESTAR SUPERIOR DEL ESTUDIANTE Y LA COMUNIDAD EDUCATIVA\n"
            "1.- Contextualización del caso.\n"
            "2.- Categorización de prioridad (Baja/Media/Alta) con fundamento legal.\n"
            "3.- Normativa vigente (Cita siempre la Ley 21809 y el Manual de Cuentas si aplica). No cites el Código del Trabajo a menos que sea estrictamente necesario y secundario.\n"
            "4.- Elemento del MBDLE que facilitará el desarrollo positivo del caso.\n\n"
            "B.- RECURSOS Y PLAN A IMPLEMENTAR PARA RESOLVER EL CASO\n"
            "1.- Priorización de recursos SEP: Aplica categoría y CÓDIGO DE CUENTA exacto del manual.\n"
            "2.- Priorización de recursos PIE: Aplica categoría y CÓDIGO DE CUENTA exacto del manual.\n"
            "3.- Redes de apoyo externas.\n\n"
            "C.- ESCALAMIENTO DE EMERGENTE\n"
            "1.- Equipo interno responsable (Director, Inspector, UTP, etc.).\n\n"
            "D.- CHECK LIST\n"
            "Pasos lógicos para el monitoreo del proceso y su paso a paso."
        )
        assistant.system_instruction = system_instruction
        assistant.save()
        self.stdout.write(self.style.SUCCESS(f'Prompt del asistente "{assistant_slug}" actualizado.'))

        # 3. Ingesta de Chunks
        if not os.path.exists(json_path):
            self.stdout.write(self.style.ERROR(f'Archivo JSON no encontrado en: {json_path}'))
            return

        self.stdout.write(f'Cargando JSON desde {json_path}...')
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            chunks_data = data.get('chunks', [])
            # Liberar el contenedor principal
            del data
            import gc
            gc.collect()

        total_chunks = len(chunks_data)
        self.stdout.write(f'Fragmentos totales encontrados: {total_chunks}')
        
        # Obtener IDs existentes para evitar N-consultas en el loop (Optimización para RAM/CPU)
        existing_ids = set(AIKnowledgeChunk.objects.filter(assistant=assistant).values_list('chunk_id', flat=True))
        self.stdout.write(f'Fragmentos ya existentes en BD: {len(existing_ids)}')

        # Definir prioridades
        # 3_-_Manual-de-cuentas-2026_baja.pdf es el nombre en el JSON
        # Ley 21809 es prioritaria
        # Página 112 del manual es hiperprioritaria (Códigos de cuenta)
        
        def get_priority_level(item):
            metadata = item.get('legal_metadata', {})
            doc = metadata.get('source_file', '')
            pages = metadata.get('page_map', [])
            
            # Nivel -1: Hiperprioridad (Códigos de Cuenta en Manual pág 110-140 aprox)
            if "Manual-de-cuentas" in doc and any(110 <= p <= 140 for p in pages):
                return -1
            
            # Nivel 0: Alta prioridad (Ley 21809 y Manual de Cuentas general)
            if doc == "2.-Ley-21809_01-ABR-2026.pdf" or "Manual-de-cuentas-2026" in doc:
                return 0
                
            return 1 # Normal

        self.stdout.write('Ordenando fragmentos por prioridad...')
        chunks_data.sort(key=get_priority_level)

        # Necesitamos openai para esta fase inicial
        import openai
        api_key_val = getattr(settings, 'OPENAI_API_KEY', os.environ.get('OPENAI_API_KEY'))
        if not api_key_val:
            self.stdout.write(self.style.ERROR('OPENAI_API_KEY no encontrada. No se pueden generar embeddings.'))
            return
            
        client = openai.OpenAI(api_key=api_key_val)

        self.stdout.write('Iniciando procesamiento por lotes...')

        # Contador de documentos para generar IDs secuenciales
        doc_counters = {}
        
        # Procesar de forma que no mantengamos referencias innecesarias
        processed_count = 0
        skipped_count = 0
        batch_size = 20 # Reducido para mayor estabilidad en 4GB RAM

        def get_batch():
            chunks_batch = []
            texts_batch = []
            nonlocal processed_count, skipped_count
            
            for item in chunks_data:
                text_content = item.get('text_content', '')
                if not text_content: continue

                metadata = item.get('legal_metadata', {})
                doc_name = metadata.get('source_file', 'unknown')
                
                if doc_name not in doc_counters:
                    doc_counters[doc_name] = 0
                
                # Generar ID único basado en el documento y el índice local
                unique_chunk_id = f"rep_tem_{doc_name}_{doc_counters[doc_name]}".replace(" ", "_").replace(".", "_")
                doc_counters[doc_name] += 1

                if unique_chunk_id in existing_ids:
                    skipped_count += 1
                    continue

                chunks_batch.append(AIKnowledgeChunk(
                    assistant=assistant,
                    chunk_id=unique_chunk_id,
                    content=text_content,
                    metadata=metadata,
                    document_name=doc_name,
                    index=doc_counters[doc_name] - 1
                ))
                texts_batch.append(text_content)

                if len(texts_batch) >= batch_size:
                    yield chunks_batch, texts_batch
                    chunks_batch = []
                    texts_batch = []
                    import gc
                    gc.collect()

            if texts_batch:
                yield chunks_batch, texts_batch

        # Ejecutar procesamiento
        for c_batch, t_batch in get_batch():
            try:
                self.process_batch(client, c_batch, t_batch)
                processed_count += len(c_batch)
                self.stdout.write(f'PROGRESO: {processed_count + skipped_count}/{total_chunks} fragmentos analizados...')
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Fallo crítico en lote: {e}'))
                # No salimos, intentamos el siguiente lote para no perder todo el progreso
                continue

        self.stdout.write(self.style.SUCCESS(
            f'LOGRO: {processed_count} nuevos fragmentos inyectados, {skipped_count} omitidos.'
        ))

        # Generar caché vectorial inmediatamente para evitar timeouts al primer usuario
        import gc
        gc.collect()
        self.stdout.write('Generando caché vectorial optimizada (modo bajo RAM)...')
        from ai_modules.utils import get_relevant_chunks
        get_relevant_chunks(assistant, "Caché inicial")
        self.stdout.write(self.style.SUCCESS('Caché vectorial lista.'))

    def process_batch(self, client, chunks_batch, texts_batch):
        """Genera embeddings y guarda en la base de datos."""
        response = client.embeddings.create(
            input=texts_batch,
            model="text-embedding-3-small"
        )
        for j, emb_data in enumerate(response.data):
            chunks_batch[j].embedding = emb_data.embedding
        
        AIKnowledgeChunk.objects.bulk_create(chunks_batch)
        # Limpieza explícita de referencias
        del chunks_batch
        del texts_batch
