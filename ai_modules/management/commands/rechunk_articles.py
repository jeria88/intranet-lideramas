"""
Rechunking por artículo — Red SFA
Genera chunks finos (1 artículo = 1 chunk) para documentos normativos.

Los nuevos chunks usan document_name = "<original>__art" y coexisten
con los chunks originales sin borrarlos. El RAG los recupera por similitud
coseno — si son más específicos que los chunks actuales, ganarán.

Uso:
    python manage.py rechunk_articles                        # todos los docs configurados
    python manage.py rechunk_articles --doc DTO-170          # filtrar por nombre parcial
    python manage.py rechunk_articles --dry-run              # ver cuántos artículos detecta
    python manage.py rechunk_articles --assistant utp-temuco # asistente destino
"""
import json
import re
import gc
import os
from django.conf import settings
from django.core.management.base import BaseCommand
from ai_modules.models import AIAssistant, AIKnowledgeChunk
from ai_modules.utils import get_openai_embedding


# ── Documentos configurados para rechunking ──────────────────────────────────
# Cada entrada define el document_name exacto en la BD y el patrón de artículos.
DOCS_CONFIG = [
    {
        "doc": "DTO-170_21-ABR-2010.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.º\-]",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "Decreto-170_21-ABR-2010.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.º\-]",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "Decreto-83-EXENTO_05-FEB-2015.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.º\-]",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "decreto-83-2015.pdf",
        "patron": r"^ARTÍCULO\s+(\d+)\s*[\.º\-]",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "Decreto-67_31-DIC-2018 (2).pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.º\-]",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "REGLAMENTO DE EVALUACIÓN 2025_1.pdf",
        "patron": r"^Artículo\s+(\d+)[°º]?\b",
        "nivel": "institucional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "RIOHS_2025_temuco.md",
        "patron": r"^Art\.\s+(\d+)[°º]?\s*[:\-]",
        "nivel": "institucional",
        "establecimiento": "temuco",
        "rol": None,
        "source_file": "RIOHS_2025_temuco.md",
        "deduplicar": False,  # tiene Art.1° en múltiples secciones independientes
    },
    {
        "doc": "RICE_2025_temuco.md",
        "patron": r"^#{1,3}\s+\*{0,2}(.+?)\*{0,2}\s*$",  # split por sección ## / ###
        "nivel": "institucional",
        "establecimiento": "temuco",
        "rol": None,
        "source_file": "RICE_2025_temuco.md",
        "mode": "sections",  # modo sección en vez de artículo numerado
    },
    # ── Leyes nacionales — rechunking por artículo ───────────────────────────
    {
        "doc": "Ley-21545_10-MAR-2023.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "LEY NÚM. 20.536.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "DFL-1_22-ENE-1997.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "DFL-2_28-NOV-1998.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "Ley-20370_12-SEP-2009.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "Ley-20903_01-ABR-2016.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "Ley-20845_08-JUN-2015.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "Ley-20609_24-JUL-2012.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "Ley-20584_24-ABR-2012.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "LEY-20248_01-FEB-2008.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "Ley-21430_15-MAR-2022.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "Ley-21595_17-AGO-2023.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "Ley-21643_15-ENE-2024.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "Ley-21809_01-ABR-2026.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "Ley-21109_02-OCT-2018.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "Ley-21128_27-DIC-2018 (1).pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "Ley-20529_27-AGO-2011.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "LEY-20285_20-AGO-2008.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "LEY-20084_07-DIC-2005.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "LEY-16744_01-FEB-1968.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "LEY-19628_28-AGO-1999.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
    {
        "doc": "LEY-19886_30-JUL-2003.pdf",
        "patron": r"^Artículo\s+(\d+)\s*[\.°º\-]?",
        "nivel": "nacional",
        "establecimiento": "temuco",
        "rol": None,
    },
]

# Artículos cortos (<= MIN_CHARS) se fusionan con el siguiente
MIN_CHARS = 150
MAX_CHARS = 2000  # si un artículo supera esto, hacer split adicional


def reconstruir_texto_desde_chunks(document_name):
    """Reconstruye el texto completo de un documento concatenando sus chunks en orden."""
    chunks = (
        AIKnowledgeChunk.objects
        .using('knowledge_base')
        .filter(document_name=document_name)
        .order_by('index')
        .values_list('content', flat=True)
    )
    partes = []
    for c in chunks:
        # Quitar el header [Doc: X]
        texto = re.sub(r'^\[Doc:[^\]]+\]\s*', '', c)
        partes.append(texto)
    return " ".join(partes)


def leer_texto_desde_archivo(filename):
    """Lee un archivo de la knowledge_base local."""
    path = os.path.join(settings.BASE_DIR, 'ai_modules', 'knowledge_base', filename)
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def split_por_seccion(texto, doc_name):
    """Divide texto por secciones ## / ### de Markdown."""
    partes = re.split(r'\n(?=#{1,3}\s)', texto)
    secciones = []
    for i, parte in enumerate(partes):
        parte = parte.strip()
        if not parte:
            continue
        # Si es muy corta, fusionar con la siguiente
        if len(parte) < MIN_CHARS and i + 1 < len(partes):
            continue
        titulo = parte.split('\n')[0].strip()
        titulo = re.sub(r'^#+\s*\*{0,2}|\*{0,2}\s*$', '', titulo).strip()
        secciones.append({"numero": i + 1, "texto": parte, "titulo": titulo})
    return secciones


def split_por_articulo(texto, patron, doc_name):
    """
    Divide el texto en chunks por artículo usando el patrón regex dado.
    Retorna lista de dicts: {numero, texto}
    """
    matches = list(re.finditer(patron, texto, re.IGNORECASE | re.MULTILINE | re.UNICODE))
    if not matches:
        return []

    articulos = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(texto)
        art_texto = texto[start:end].strip()
        numero = int(m.group(1)) if m.lastindex and m.group(1).isdigit() else i + 1
        articulos.append({"numero": numero, "texto": art_texto})

    # Fusionar artículos muy cortos con el siguiente
    fusionados = []
    buffer = None
    for art in articulos:
        if buffer is None:
            buffer = art.copy()
        elif len(buffer["texto"]) < MIN_CHARS:
            buffer["texto"] += "\n\n" + art["texto"]
        else:
            fusionados.append(buffer)
            buffer = art.copy()
    if buffer:
        fusionados.append(buffer)

    # Dividir artículos muy largos
    resultado = []
    for art in fusionados:
        if len(art["texto"]) <= MAX_CHARS:
            resultado.append(art)
        else:
            # Split simple por mitad conservando número
            mid = MAX_CHARS
            resultado.append({"numero": art["numero"], "texto": art["texto"][:mid]})
            resultado.append({"numero": art["numero"], "texto": art["texto"][mid:]})

    return resultado


class Command(BaseCommand):
    help = 'Rechunking por artículo de documentos normativos (aditivo, no borra originales)'

    def add_arguments(self, parser):
        parser.add_argument('--doc', type=str, default=None,
                            help='Filtrar por nombre parcial del documento')
        parser.add_argument('--assistant', type=str, default='global-knowledge',
                            help='Slug del asistente destino (default: global-knowledge)')
        parser.add_argument('--dry-run', action='store_true',
                            help='Mostrar cuántos artículos detecta sin guardar')

    def handle(self, *args, **options):
        doc_filter = options.get('doc')
        dry_run = options['dry_run']
        assistant_slug = options['assistant']

        try:
            assistant = AIAssistant.objects.using('knowledge_base').get(slug=assistant_slug)
        except AIAssistant.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Asistente no encontrado: {assistant_slug}'))
            return

        docs = DOCS_CONFIG
        if doc_filter:
            docs = [d for d in docs if doc_filter.lower() in d['doc'].lower()]
        if not docs:
            self.stdout.write(self.style.ERROR('No hay documentos que coincidan con el filtro.'))
            return

        total_chunks_creados = 0

        for cfg in docs:
            doc_name = cfg['doc']
            patron = cfg['patron']
            self.stdout.write(f'\n📄 {doc_name}')

            # Obtener texto
            source_file = cfg.get('source_file')
            if source_file:
                texto = leer_texto_desde_archivo(source_file)
                if not texto:
                    self.stdout.write(self.style.WARNING(f'  ⚠️ Archivo local no encontrado: {source_file}'))
                    continue
            else:
                texto = reconstruir_texto_desde_chunks(doc_name)
                if not texto.strip():
                    self.stdout.write(self.style.WARNING(f'  ⚠️ No hay chunks en BD para: {doc_name}'))
                    continue

            self.stdout.write(f'  Texto reconstruido: {len(texto):,} chars')

            mode = cfg.get('mode', 'articles')
            deduplicar = cfg.get('deduplicar', True)
            if mode == 'sections':
                articulos = split_por_seccion(texto, doc_name)
                self.stdout.write(f'  Secciones detectadas: {len(articulos)}')
            else:
                articulos = split_por_articulo(texto, patron, doc_name)
                if deduplicar:
                    por_numero = {}
                    for art in articulos:
                        n = art['numero']
                        if n not in por_numero or len(art['texto']) > len(por_numero[n]['texto']):
                            por_numero[n] = art
                    articulos = sorted(por_numero.values(), key=lambda a: a['numero'])
                    self.stdout.write(f'  Artículos detectados (deduplicados): {len(articulos)}')
                else:
                    self.stdout.write(f'  Artículos detectados (sin deduplicar): {len(articulos)}')

            if not articulos:
                self.stdout.write(self.style.WARNING('  ⚠️ Sin artículos detectados — verificar patrón'))
                continue

            if dry_run:
                for art in articulos[:5]:
                    self.stdout.write(f'    Art.{art["numero"]:3d} ({len(art["texto"])} chars): {art["texto"][:80]}...')
                if len(articulos) > 5:
                    self.stdout.write(f'    ... y {len(articulos) - 5} más')
                continue

            # Nombre del documento versionado (coexiste con original)
            doc_name_art = f"{doc_name}__art"

            # Borrar solo los chunks __art anteriores de este documento (no los originales)
            deleted = AIKnowledgeChunk.objects.using('knowledge_base').filter(
                document_name=doc_name_art
            ).delete()
            if deleted[0]:
                self.stdout.write(f'  ♻️  Borrados {deleted[0]} chunks __art anteriores')

            # Generar embeddings y guardar
            nuevos = []
            for i, art in enumerate(articulos):
                contenido = f"[Doc: {doc_name}] Art.{art['numero']} — {art['texto']}"
                embedding = get_openai_embedding(contenido)
                if not embedding:
                    self.stdout.write(self.style.WARNING(f'  ⚠️ Sin embedding para Art.{art["numero"]}'))
                    continue

                chunk_id = f"{doc_name_art}-{art['numero']}-{i}"
                nuevos.append(AIKnowledgeChunk(
                    assistant=assistant,
                    content=contenido,
                    embedding=embedding,
                    metadata={
                        'nivel': cfg['nivel'],
                        'establecimiento': cfg['establecimiento'],
                        'rol': cfg.get('rol'),
                        'fuente_archivo': doc_name,
                        'chunking_strategy': 'article',
                        'articulo_numero': art['numero'],
                    },
                    chunk_id=chunk_id,
                    document_name=doc_name_art,
                    index=i,
                ))

                if (i + 1) % 10 == 0:
                    self.stdout.write(f'  → {i+1}/{len(articulos)} embeddings...')
                    gc.collect()

            if nuevos:
                AIKnowledgeChunk.objects.using('knowledge_base').bulk_create(
                    nuevos, ignore_conflicts=True
                )
                self.stdout.write(self.style.SUCCESS(
                    f'  ✅ {len(nuevos)} chunks por artículo guardados → {doc_name_art}'
                ))
                total_chunks_creados += len(nuevos)
            gc.collect()

        self.stdout.write(self.style.SUCCESS(f'\n✅ Total chunks creados: {total_chunks_creados}'))
        self.stdout.write(
            '💡 Los chunks originales NO fueron borrados. El RAG usará ambos por similitud coseno.'
        )
