import json
import os
import uuid
import gc
from django.core.management.base import BaseCommand
from django.conf import settings
from ai_modules.models import AIAssistant, AIKnowledgeChunk
from ai_modules.utils import get_openai_embedding

class Command(BaseCommand):
    help = 'Ingesta un archivo Markdown en la base de conocimientos de Supabase'

    def add_arguments(self, parser):
        parser.add_argument('--file', type=str, required=True, help='Nombre del archivo en ai_modules/knowledge_base/')
        parser.add_argument('--nivel', type=str, default='institucional', choices=['nacional', 'institucional', 'congregacional'])
        parser.add_argument('--establecimiento', type=str, default='temuco')
        parser.add_argument('--rol', type=str, default=None)
        parser.add_argument('--assistant', type=str, default='global-knowledge', help='Slug del asistente destino')
        parser.add_argument('--dry-run', action='store_true', help='No guarda en BD ni actualiza el JSON')

    def handle(self, *args, **options):
        filename = options['file']
        nivel = options['nivel']
        est = options['establecimiento']
        rol = options['rol']
        assistant_slug = options['assistant']
        dry_run = options['dry_run']

        file_path = os.path.join(settings.BASE_DIR, 'ai_modules', 'knowledge_base', filename)
        
        if not os.path.exists(file_path):
            self.stdout.write(self.style.ERROR(f'No se encontró el archivo: {file_path}'))
            return

        try:
            assistant = AIAssistant.objects.using('knowledge_base').get(slug=assistant_slug)
        except AIAssistant.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'No existe el asistente: {assistant_slug}'))
            return

        self.stdout.write(self.style.SUCCESS(f'Iniciando procesamiento de {filename}...'))

        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()

        # Chunking: 1500 caracteres con 300 de solapamiento
        chunk_size = 1500
        overlap = 300
        chunks_data = []
        
        start = 0
        index = 0
        while start < len(text):
            end = start + chunk_size
            chunk_text = text[start:end]
            
            # Formato estándar para el contenido (prefijo del documento)
            content_with_header = f"[Doc: {filename}] {chunk_text}"
            
            metadata = {
                "fuente": filename,
                "nivel": nivel,
                "establecimiento": est,
                "rol": rol
            }

            chunks_data.append({
                "content": content_with_header,
                "metadata": metadata,
                "index": index
            })
            
            start += (chunk_size - overlap)
            index += 1

        total = len(chunks_data)
        self.stdout.write(self.style.NOTICE(f'Se generaron {total} fragmentos.'))

        if dry_run:
            self.stdout.write(self.style.WARNING('MODO DRY-RUN: No se realizaron cambios.'))
            return

        # 2. Generar embeddings y guardar en BD (batch de 25 para no saturar RAM)
        batch_size = 25
        batch = []
        
        for i, item in enumerate(chunks_data):
            self.stdout.write(f'Procesando chunk {i+1}/{total}...')
            
            embedding = get_openai_embedding(item['content'])
            
            chunk = AIKnowledgeChunk(
                assistant=assistant,
                content=item['content'],
                embedding=json.dumps(embedding) if embedding else None,
                metadata=item['metadata'],
                chunk_id=f"ingest_{uuid.uuid4().hex[:8]}_{i}",
                document_name=filename,
                index=item['index']
            )
            batch.append(chunk)
            
            if len(batch) >= batch_size:
                AIKnowledgeChunk.objects.using('knowledge_base').bulk_create(batch)
                batch = []
                gc.collect()

        if batch:
            AIKnowledgeChunk.objects.using('knowledge_base').bulk_create(batch)

        # 3. Actualizar el JSON maestro (opcional pero recomendado)
        json_master_path = os.path.join(settings.BASE_DIR, 'ai_modules', 'knowledge_base', 'base_conocimientos_supabase.json')
        if os.path.exists(json_master_path):
            self.stdout.write(self.style.NOTICE('Actualizando base_conocimientos_supabase.json...'))
            try:
                with open(json_master_path, 'r', encoding='utf-8') as f:
                    master_data = json.load(f)
                
                # Convertir al formato del JSON
                new_json_entries = []
                for item in chunks_data:
                    new_json_entries.append({
                        "texto_contenido": item['content'],
                        "metadatos": item['metadata']
                    })
                
                master_data.extend(new_json_entries)
                
                with open(json_master_path, 'w', encoding='utf-8') as f:
                    json.dump(master_data, f, ensure_ascii=False, indent=2)
                
                self.stdout.write(self.style.SUCCESS('JSON maestro actualizado.'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error al actualizar el JSON: {e}'))

        self.stdout.write(self.style.SUCCESS(f'ÉXITO: {total} fragmentos subidos a Supabase y sincronizados.'))
