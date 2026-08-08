from django.db import models
from django.conf import settings
from django.utils import timezone
from users.scoping import ModeloDeOrganizacion

# ── Choices ───────────────────────────────────────────────────────

ASIGNATURA_CHOICES = [
    ('lenguaje',   'Lenguaje y Comunicación'),
    ('matematica', 'Matemática'),
    ('ciencias',   'Ciencias Naturales'),
    ('historia',   'Historia, Geografía y Cs. Sociales'),
]

CURSO_CHOICES = [
    ('4B', '4° Básico'),
    ('6B', '6° Básico'),
    ('8B', '8° Básico'),
    ('2M', '2° Medio'),
]

LETRA_CHOICES  = [('A','A'), ('B','B'), ('C','C'), ('D','D')]
NIVEL_CHOICES  = [(1,'⭐ Inicial'), (2,'⭐⭐ Intermedio'), (3,'⭐⭐⭐ Avanzado')]
ALT_CHOICES    = [('A','A'), ('B','B'), ('C','C'), ('D','D')]
DIFICULTAD_TEXTO = [(1,'Básico'), (2,'Intermedio'), (3,'Avanzado')]

ESTADO_OBJETO = [
    ('pendiente',  'Pendiente'),
    ('aprobado',   'Aprobado'),
    ('rechazado',  'Rechazado'),
]

TIPO_TEXTUAL_CHOICES = [
    # Literarios
    ('cuento',           'Cuento de Autor'),
    ('cuento_folclorico','Cuento Folclórico / Popular'),
    ('fabula',           'Fábula'),
    ('leyenda',          'Leyenda'),
    ('mito',             'Mito'),
    ('poema',            'Poema'),
    ('soneto',           'Soneto'),
    ('oda',              'Oda'),
    # No Literarios
    ('noticia',          'Noticia'),
    ('reportaje',        'Reportaje'),
    ('articulo_info',    'Artículo Informativo'),
    ('articulo_cient',   'Artículo Científico (Divulgativo)'),
    ('infografia',       'Infografía'),
    ('instructivo',      'Instrucciones / Instructivo'),
    ('receta',           'Receta de Cocina'),
    ('manual',           'Manual de Instrucciones'),
    ('biografia',        'Biografía / Relato Histórico'),
    ('carta_formal',     'Carta Formal'),
    ('carta_director',   'Carta al Director'),
    ('carta_informal',   'Carta Informal'),
    ('afiche',           'Afiche Publicitario'),
    ('discontinuo',      'Texto Informativo Discontinuo'),
]

ESTADO_PRUEBA = [
    ('generando_textos',    'Generando textos…'),
    ('generando_preguntas', 'Generando preguntas…'),
    ('borrador',            'Borrador'),
    ('error',               'Error'),
    ('revision',            'En Revisión'),
    ('aprobada',            'Aprobada'),
    ('publicada',           'Publicada'),
    ('cerrada',             'Cerrada'),
]

MODO_SESION = [
    ('simce',  'Estilo SIMCE (1 pt, sin pistas)'),
    ('pistas', 'Con pistas e intentos (4-3-2-0)'),
]

ASIGNATURA_DOC_CHOICES = ASIGNATURA_CHOICES + [('general', 'General (todas)')]


# ── Biblioteca de Textos ──────────────────────────────────────────

class TextoBiblioteca(ModeloDeOrganizacion):
    asignatura      = models.CharField(max_length=20, choices=ASIGNATURA_CHOICES, db_index=True)
    tipo_textual    = models.CharField(max_length=20, choices=TIPO_TEXTUAL_CHOICES)
    titulo          = models.CharField(max_length=200)
    contenido       = models.TextField()
    dificultad      = models.PositiveSmallIntegerField(choices=DIFICULTAD_TEXTO, default=2)
    estado          = models.CharField(max_length=10, choices=ESTADO_OBJETO, default='pendiente', db_index=True)
    word_count      = models.PositiveIntegerField(default=0)
    char_count      = models.PositiveIntegerField(default=0)
    checklist_admin = models.JSONField(default=dict)
    creada_por      = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name='textos_simce')
    creada_en       = models.DateTimeField(auto_now_add=True)
    actualizada_en  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-creada_en']
        verbose_name = 'Texto biblioteca'
        verbose_name_plural = 'Textos biblioteca'

    def save(self, *args, **kwargs):
        self.char_count = len(self.contenido.replace(' ', ''))
        self.word_count = len(self.contenido.split())
        super().save(*args, **kwargs)

    def cumple_extension(self):
        return self.char_count >= 1500

    def n_preguntas_banco(self):
        return self.preguntas_banco.count()

    def n_preguntas_aprobadas(self):
        return self.preguntas_banco.filter(estado='aprobado').count()

    def __str__(self):
        return f"[{self.get_asignatura_display()}] {self.get_tipo_textual_display()} — {self.titulo}"


# ── Banco de Preguntas ────────────────────────────────────────────

class PreguntaBanco(models.Model):
    texto                   = models.ForeignKey(TextoBiblioteca, on_delete=models.CASCADE,
                                                related_name='preguntas_banco')
    enunciado               = models.TextField()
    nivel                   = models.PositiveSmallIntegerField(choices=NIVEL_CHOICES)
    habilidad               = models.CharField(max_length=200)
    habilidad_justificacion = models.TextField(blank=True)
    nivel_justificacion     = models.TextField(blank=True)
    alternativa_correcta    = models.CharField(max_length=1, choices=ALT_CHOICES)
    pista_1                 = models.TextField(blank=True)
    pista_2                 = models.TextField(blank=True)
    estado                  = models.CharField(max_length=10, choices=ESTADO_OBJETO,
                                               default='pendiente', db_index=True)
    creada_en               = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nivel', 'creada_en']
        verbose_name = 'Pregunta banco'
        verbose_name_plural = 'Preguntas banco'

    def nivel_estrellas(self):
        return '⭐' * self.nivel

    def __str__(self):
        return f"[N{self.nivel}] {self.enunciado[:60]}"


class AlternativaBanco(models.Model):
    pregunta      = models.ForeignKey(PreguntaBanco, on_delete=models.CASCADE, related_name='alternativas')
    letra         = models.CharField(max_length=1, choices=ALT_CHOICES)
    texto         = models.TextField()
    es_correcta   = models.BooleanField(default=False)
    justificacion = models.TextField(blank=True)

    class Meta:
        ordering = ['letra']
        unique_together = ['pregunta', 'letra']
        verbose_name = 'Alternativa banco'

    def __str__(self):
        return f"{self.letra}{'✓' if self.es_correcta else ''}: {self.texto[:50]}"


# ── Prueba (Test) ─────────────────────────────────────────────────

class Prueba(ModeloDeOrganizacion):
    titulo       = models.CharField(max_length=200)
    asignatura   = models.CharField(max_length=20, choices=ASIGNATURA_CHOICES)
    curso        = models.CharField(max_length=3, choices=CURSO_CHOICES)
    anio         = models.PositiveSmallIntegerField(default=timezone.now().year)
    estado       = models.CharField(max_length=22, choices=ESTADO_PRUEBA, default='borrador')
    creada_por   = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='pruebas_simce')
    creada_en    = models.DateTimeField(auto_now_add=True)
    aprobada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='pruebas_aprobadas')
    aprobada_en  = models.DateTimeField(null=True, blank=True)
    rubrica_ok   = models.BooleanField(default=False)
    rubrica_log  = models.JSONField(default=dict)

    class Meta:
        ordering = ['-creada_en']
        verbose_name = 'Prueba SIMCE'
        verbose_name_plural = 'Pruebas SIMCE'

    def __str__(self):
        return f"{self.get_asignatura_display()} {self.get_curso_display()} {self.anio}"

    @property
    def total_preguntas(self):
        return Pregunta.objects.filter(prueba_texto__prueba=self).count()

    @property
    def total_textos(self):
        return self.prueba_textos.count()


# ── PruebaTexto (Junction) ────────────────────────────────────────

class PruebaTexto(models.Model):
    prueba   = models.ForeignKey(Prueba, on_delete=models.CASCADE, related_name='prueba_textos')
    texto    = models.ForeignKey(TextoBiblioteca, on_delete=models.PROTECT,
                                 related_name='usos_en_pruebas')
    orden    = models.PositiveSmallIntegerField()
    n_nivel1 = models.PositiveSmallIntegerField(default=1, verbose_name='Preguntas Inicial')
    n_nivel2 = models.PositiveSmallIntegerField(default=1, verbose_name='Preguntas Intermedio')
    n_nivel3 = models.PositiveSmallIntegerField(default=3, verbose_name='Preguntas Avanzado')

    class Meta:
        ordering = ['orden']
        unique_together = ['prueba', 'texto']
        verbose_name = 'Texto en prueba'

    def total_preguntas_config(self):
        return self.n_nivel1 + self.n_nivel2 + self.n_nivel3

    def __str__(self):
        return f"T{self.orden} en prueba {self.prueba_id}: {self.texto.titulo[:40]}"


# ── Pregunta (en test específico) ─────────────────────────────────

class Pregunta(models.Model):
    prueba_texto            = models.ForeignKey(PruebaTexto, on_delete=models.CASCADE,
                                                related_name='preguntas')
    desde_banco             = models.ForeignKey(PreguntaBanco, null=True, blank=True,
                                                on_delete=models.SET_NULL,
                                                related_name='usos_en_pruebas')
    orden                   = models.PositiveSmallIntegerField()
    enunciado               = models.TextField()
    nivel                   = models.PositiveSmallIntegerField(choices=NIVEL_CHOICES)
    habilidad               = models.CharField(max_length=200)
    habilidad_justificacion = models.TextField(blank=True)
    nivel_justificacion     = models.TextField(blank=True)
    alternativa_correcta    = models.CharField(max_length=1, choices=ALT_CHOICES)
    pista_1                 = models.TextField(blank=True)
    pista_2                 = models.TextField(blank=True)

    class Meta:
        ordering = ['orden']
        verbose_name = 'Pregunta'
        verbose_name_plural = 'Preguntas'

    def nivel_estrellas(self):
        return '⭐' * self.nivel

    def __str__(self):
        return f"P{self.orden} [N{self.nivel}] — {self.enunciado[:60]}"


class Alternativa(models.Model):
    pregunta      = models.ForeignKey(Pregunta, on_delete=models.CASCADE, related_name='alternativas')
    letra         = models.CharField(max_length=1, choices=ALT_CHOICES)
    texto         = models.TextField()
    es_correcta   = models.BooleanField(default=False)
    justificacion = models.TextField(blank=True)

    class Meta:
        ordering = ['letra']
        unique_together = ['pregunta', 'letra']
        verbose_name = 'Alternativa'

    def __str__(self):
        return f"{self.letra}{'✓' if self.es_correcta else ''}: {self.texto[:50]}"


# ── RAG: Base de conocimiento SIMCE ──────────────────────────────

class SimceDocumento(ModeloDeOrganizacion):
    nombre     = models.CharField(max_length=200)
    asignatura = models.CharField(max_length=20, choices=ASIGNATURA_DOC_CHOICES, default='general')
    file_path  = models.CharField(max_length=500, blank=True)
    procesado  = models.BooleanField(default=False)
    n_chunks   = models.PositiveIntegerField(default=0)
    subido_en  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['asignatura', 'nombre']
        verbose_name = 'Documento SIMCE'
        verbose_name_plural = 'Documentos SIMCE'

    def __str__(self):
        return f"{self.nombre} [{self.asignatura}]"


class SimceChunk(models.Model):
    documento   = models.ForeignKey(SimceDocumento, on_delete=models.CASCADE, related_name='chunks')
    asignatura  = models.CharField(max_length=20, db_index=True)
    contenido   = models.TextField()
    embedding   = models.JSONField(null=True, blank=True)
    chunk_index = models.PositiveIntegerField()

    class Meta:
        ordering = ['documento', 'chunk_index']
        verbose_name = 'Chunk SIMCE'

    def __str__(self):
        return f"Chunk {self.chunk_index} — {self.documento.nombre}"


# ── Sesión Estudiante ─────────────────────────────────────────────

class SesionEstudiante(models.Model):
    prueba          = models.ForeignKey(Prueba, on_delete=models.CASCADE, related_name='sesiones')
    nombre          = models.CharField(max_length=150)
    rut             = models.CharField(max_length=12)
    establecimiento = models.CharField(max_length=20)
    rbd             = models.CharField(max_length=10, blank=True)
    curso           = models.CharField(max_length=3, choices=CURSO_CHOICES)
    letra_curso     = models.CharField(max_length=1, choices=LETRA_CHOICES)
    modo            = models.CharField(max_length=8, choices=MODO_SESION, default='simce')
    iniciada_en     = models.DateTimeField(auto_now_add=True)
    finalizada_en   = models.DateTimeField(null=True, blank=True)
    completada      = models.BooleanField(default=False)
    puntaje_bruto   = models.PositiveSmallIntegerField(default=0)
    porcentaje_logro= models.DecimalField(max_digits=5, decimal_places=2, default=0)
    puntaje_simce   = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['-iniciada_en']
        verbose_name = 'Sesión estudiante'

    def __str__(self):
        return f"{self.nombre} ({self.rut}) — {self.prueba}"

    def calcular_puntajes(self):
        respuestas = self.respuestas.all()
        total = respuestas.count()
        puntaje = sum(r.puntaje_obtenido for r in respuestas)
        pts_max = total * (4 if self.modo == 'pistas' else 1)
        self.puntaje_bruto    = puntaje
        self.porcentaje_logro = round((puntaje / pts_max * 100), 2) if pts_max else 0
        self.puntaje_simce    = int(150 + (self.porcentaje_logro / 100) * 200)
        self.finalizada_en    = timezone.now()
        self.completada       = True
        self.save()


class RespuestaEstudiante(models.Model):
    sesion              = models.ForeignKey(SesionEstudiante, on_delete=models.CASCADE,
                                            related_name='respuestas')
    pregunta            = models.ForeignKey(Pregunta, on_delete=models.CASCADE)
    alternativa_elegida = models.ForeignKey(Alternativa, on_delete=models.SET_NULL,
                                            null=True, blank=True)
    intentos            = models.PositiveSmallIntegerField(default=1)
    puntaje_obtenido    = models.PositiveSmallIntegerField(default=0)
    respondida_en       = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['sesion', 'pregunta']
        verbose_name = 'Respuesta'

    def __str__(self):
        c = self.alternativa_elegida.es_correcta if self.alternativa_elegida else False
        l = self.alternativa_elegida.letra if self.alternativa_elegida else '—'
        return f"P{self.pregunta.orden} → {l} {'✓' if c else '✗'}"
