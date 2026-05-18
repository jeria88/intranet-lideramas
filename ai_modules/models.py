from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta


class AIAssistant(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    profile_role = models.CharField(max_length=20, verbose_name='Rol objetivo')
    description = models.TextField(blank=True)
    use_cases = models.TextField(blank=True, verbose_name='Casos de uso (uno por línea)')
    image_name = models.CharField(max_length=100, verbose_name='Nombre de imagen')
    establishment = models.CharField(max_length=20, blank=True, verbose_name='Establecimiento (opcional)')
    system_instruction = models.TextField(blank=True, verbose_name='Instrucción de Sistema (Prompt)')
    context_text = models.TextField(blank=True, verbose_name='Contexto Extraído (RAG)')
    is_chat_enabled = models.BooleanField(default=False, verbose_name='¿Habilitar Chat Interno?')
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.profile_role})"

    def get_use_cases_list(self):
        return [u.strip() for u in self.use_cases.splitlines() if u.strip()]

    def update_context_text(self):
        """Agrega el texto de todos los documentos procesados al contexto principal."""
        texts = self.knowledge_base.filter(is_processed=True).values_list('extracted_text', flat=True)
        self.context_text = "\n\n".join(texts)
        self.save(update_fields=['context_text'])


class AIKnowledgeBase(models.Model):
    NIVEL_CHOICES = [
        ('institucional',  'Institucional (solo este colegio)'),
        ('congregacional', 'Congregacional (toda la red SFA)'),
        ('nacional',       'Nacional (normativa pública)'),
    ]

    assistant = models.ForeignKey(
        AIAssistant, on_delete=models.CASCADE, related_name='knowledge_base'
    )
    name = models.CharField(max_length=255, verbose_name='Nombre del documento')
    file = models.FileField(upload_to='ai_knowledge/', verbose_name='Archivo PDF')
    nivel = models.CharField(
        max_length=20, choices=NIVEL_CHOICES, default='institucional',
        verbose_name='Nivel de acceso'
    )
    extracted_text = models.TextField(blank=True, verbose_name='Texto extraído')
    is_processed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.assistant.name}"


class AIQuery(models.Model):
    STATUS_CHOICES = [
        ('pendiente',   'Pendiente'),
        ('en_proceso',  'En Proceso'),
        ('respondida',  'Respondida'),
        ('vencida',     'Vencida'),
    ]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ai_queries'
    )
    assistant = models.ForeignKey(
        AIAssistant, on_delete=models.CASCADE, related_name='queries'
    )
    question = models.TextField(verbose_name='Consulta')
    attachment = models.FileField(upload_to='ai_queries/', blank=True, null=True, verbose_name='Archivo adjunto')
    submitted_at = models.DateTimeField(auto_now_add=True)
    deadline = models.DateTimeField(verbose_name='Plazo de respuesta (24h)', editable=False)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pendiente')
    # Respuesta del admin
    answer = models.TextField(blank=True, verbose_name='Respuesta')
    ai_suggestion = models.TextField(blank=True, verbose_name='Sugerencia de la IA (RAG)')
    answered_at = models.DateTimeField(null=True, blank=True)
    answered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='ai_answers'
    )

    class Meta:
        ordering = ['deadline']
        verbose_name = 'Consulta IA'
        verbose_name_plural = 'Consultas IA'

    def save(self, *args, **kwargs):
        if not self.pk:
            # Calcular deadline al crear (usar submitted_at o timezone.now())
            base_time = self.submitted_at or timezone.now()
            sla_hours = getattr(settings, 'AI_QUERY_SLA_HOURS', 24)
            self.deadline = base_time + timedelta(hours=sla_hours)
        super().save(*args, **kwargs)

    @property
    def is_overdue(self):
        return timezone.now() > self.deadline and self.status not in ('respondida',)

    @property
    def hours_remaining(self):
        delta = self.deadline - timezone.now()
        return max(0, delta.total_seconds() / 3600)

    def __str__(self):
        return f"[{self.get_status_display()}] {self.user} → {self.assistant.name}"


class AIChatMessage(models.Model):
    ROLE_CHOICES = [
        ('user', 'Usuario'),
        ('assistant', 'IA'),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ai_chat_messages')
    assistant = models.ForeignKey(AIAssistant, on_delete=models.CASCADE, related_name='chat_messages')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']
        verbose_name = 'Mensaje de Chat IA'
        verbose_name_plural = 'Mensajes de Chat IA'

    def __str__(self):
        return f"{self.user.username} ({self.role}): {self.content[:50]}..."


class AIKnowledgeChunk(models.Model):
    assistant = models.ForeignKey(
        AIAssistant, on_delete=models.CASCADE, related_name='chunks'
    )
    content = models.TextField(verbose_name='Contenido del fragmento')
    metadata = models.JSONField(default=dict, verbose_name='Metadatos (Establecimiento, Rol, Doc)')
    chunk_id = models.CharField(max_length=100, unique=True, verbose_name='ID Único del fragmento')
    document_name = models.CharField(max_length=255, null=True, blank=True, verbose_name='Nombre del documento fuente')
    index = models.IntegerField(default=0, verbose_name='Índice de secuencia en el documento')
    embedding = models.JSONField(null=True, blank=True, verbose_name='Vector Embedding (OpenAI)')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Fragmento de Conocimiento'
        verbose_name_plural = 'Fragmentos de Conocimiento'

    def __str__(self):
        return f"Chunk {self.chunk_id} - {self.assistant.slug}"

class AICase(models.Model):
    STATUS_CHOICES = [
        ('abierto', 'Abierto (En Proceso)'),
        ('cerrado', 'Cerrado (Resuelto)'),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ai_cases')
    assistant = models.ForeignKey(AIAssistant, on_delete=models.CASCADE)
    title = models.CharField(max_length=255, verbose_name='Título del Caso')
    
    # Origen del Caso
    user_query = models.TextField(blank=True, verbose_name='Consulta Original del Usuario')
    
    # Contenido del Análisis (Secciones A, B, C)
    sustento = models.TextField(verbose_name='Sustento Normativo (Sección A)')
    ruta = models.TextField(verbose_name='Hoja de Ruta (Sección B)')
    checklist = models.TextField(verbose_name='Checklist (Sección C)')
    
    # Resultado de Defensa
    descargos = models.TextField(blank=True, verbose_name='Redacción de Descargos')
    
    # Comentarios manuales
    observations = models.TextField(blank=True, verbose_name='Observaciones del Usuario')
    
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='abierto')
    is_active = models.BooleanField(default=True, verbose_name='Activo')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Caso Normativo'
        verbose_name_plural = 'Repositorio de Casos'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_status_display()}] {self.title} - {self.user.username}"

class ChatConversation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='conversations')
    assistant = models.ForeignKey(AIAssistant, on_delete=models.CASCADE, related_name='conversations')
    title = models.CharField(max_length=200, default='Nueva conversación')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    case = models.ForeignKey('AICase', on_delete=models.SET_NULL, null=True, blank=True, related_name='conversations')

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Conversación'
        verbose_name_plural = 'Conversaciones'

    def __str__(self):
        return f"{self.user.username} — {self.title}"


class ConversationMessage(models.Model):
    ROLE_CHOICES = [('user', 'Usuario'), ('assistant', 'IA')]
    conversation = models.ForeignKey(ChatConversation, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"{self.conversation.id} [{self.role}] {self.content[:40]}"


class CaseObservation(models.Model):
    """Log cronológico de observaciones para un caso."""
    case = models.ForeignKey(AICase, on_delete=models.CASCADE, related_name='obs_log')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    content = models.TextField(verbose_name='Comentario')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Obs {self.created_at:%d/%m/%Y} - {self.case.title}"


class PilotFeedback(models.Model):
    ORIGIN_CHOICES = [('banner', 'Banner de pilotaje'), ('respuesta_ia', 'Respuesta IA')]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    origin = models.CharField(max_length=20, choices=ORIGIN_CHOICES)
    message = models.ForeignKey(ConversationMessage, on_delete=models.SET_NULL, null=True, blank=True, related_name='feedbacks')
    feedback_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Feedback Piloto'
        verbose_name_plural = 'Feedbacks Piloto'

    def __str__(self):
        return f"[{self.origin}] {self.user} — {self.created_at:%d/%m/%Y %H:%M}"
