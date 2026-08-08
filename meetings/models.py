import uuid
from django.db import models
from django.conf import settings
from users.scoping import ModeloDeOrganizacion


class MeetingRoom(ModeloDeOrganizacion):
    ROOM_TYPES = [
        ('daily', 'Daily.co (Videollamadas)'),
    ]
    name = models.CharField(max_length=100, verbose_name='Nombre de la Sala')
    slug = models.SlugField(unique=True, verbose_name='Slug Identificador')
    description = models.TextField(blank=True)
    room_type = models.CharField(max_length=10, choices=ROOM_TYPES, default='daily')
    daily_identifier = models.CharField(max_length=100, blank=True, help_text='ID al final de la URL de Daily')

    # Para segmentación automática
    target_establishment = models.CharField(max_length=20, blank=True, verbose_name='Establecimiento vinculado')
    target_role = models.CharField(max_length=20, blank=True, verbose_name='Rol vinculado')

    allowed_roles = models.JSONField(default=list, blank=True, verbose_name='Roles permitidos (Manual)')
    is_unlimited = models.BooleanField(default=False, verbose_name='Reuniones ilimitadas')

    class Meta:
        verbose_name = 'Sala de Reunión'
        verbose_name_plural = 'Salas de Reunión'

    def __str__(self):
        return self.name


class MeetingBooking(ModeloDeOrganizacion):
    STATUS_CHOICES = [
        ('programada', 'Programada'),
        ('activa',     'Activa'),
        ('cerrada',    'Cerrada'),
        ('cancelada',  'Cancelada'),
    ]
    room = models.ForeignKey(MeetingRoom, on_delete=models.CASCADE, related_name='bookings')
    booked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookings')
    scheduled_at = models.DateTimeField(verbose_name='Fecha y hora')
    duration_minutes = models.PositiveIntegerField(default=60, verbose_name='Duración (min)')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='programada')
    agenda = models.TextField(blank=True, verbose_name='Agenda')

    # Sincronización con Daily.co y Procesamiento IA
    recording_id = models.CharField(max_length=200, blank=True, null=True, verbose_name='ID de Grabación')
    transcript = models.TextField(blank=True, verbose_name='Transcripción (Whisper)')
    acta = models.TextField(blank=True, verbose_name='Acta de Reunión (DeepSeek)')
    acuerdos_text = models.TextField(blank=True, verbose_name='Acuerdos Extraídos')

    PROCESSING_STATUS = [
        ('sin_grabacion', 'Sin Grabación'),   # Estado inicial — no hay recording aún
        ('pendiente',     'Pendiente'),         # Grabación recibida, esperando proceso IA
        ('procesando',    'Procesando'),        # GitHub Actions está trabajando
        ('completado',    'Completado'),        # IA completó la generación de artefactos
        ('fallido',       'Fallido'),           # El proceso falló, reintentable
    ]
    processing_status = models.CharField(
        max_length=15, choices=PROCESSING_STATUS,
        default='sin_grabacion',               # ← Solo pasa a 'pendiente' cuando llega el webhook
        verbose_name='Estado de Procesamiento IA'
    )

    # Sincronización con Calendario Red
    calendar_event = models.OneToOneField(
        'calendar_red.CalendarEvent', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='meeting_booking'
    )

    recording_url = models.CharField(
        max_length=500, blank=True, null=True,
        verbose_name='URL de Grabación',
        help_text='Enlace al video o identificador de Daily (daily_id:xxx)'
    )
    recording_r2_url = models.URLField(
        max_length=1000, blank=True, null=True,
        verbose_name='URL de Grabación en R2',
        help_text='Enlace permanente al video en Cloudflare R2'
    )
    # Para control de cuota (4 reuniones/mes por rol, excepto RED)
    month_year = models.CharField(max_length=7, verbose_name='Mes-Año (YYYY-MM)', editable=False)

    class Meta:
        ordering = ['-scheduled_at']
        verbose_name = 'Reserva de Reunión'
        verbose_name_plural = 'Reservas de Reuniones'

    def save(self, *args, **kwargs):
        self.month_year = self.scheduled_at.strftime('%Y-%m')
        super().save(*args, **kwargs)

    @property
    def end_time(self):
        """Calcula la hora de finalización basada en la duración."""
        from datetime import timedelta
        return self.scheduled_at + timedelta(minutes=self.duration_minutes)

    def __str__(self):
        return f"{self.room.name} — {self.booked_by} — {self.scheduled_at:%Y-%m-%d %H:%M}"


class MeetingAttendance(models.Model):
    booking = models.ForeignKey(MeetingBooking, on_delete=models.CASCADE, related_name='attendances')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='attendances')
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('booking', 'user')]
        verbose_name = 'Asistencia'

    def __str__(self):
        return f"{self.user} en {self.booking}"


class MeetingParticipant(models.Model):
    """Participantes reales detectados por la API de Daily.co"""
    booking = models.ForeignKey(MeetingBooking, on_delete=models.CASCADE, related_name='detected_participants')
    name = models.CharField(max_length=200, verbose_name='Nombre/Identificador')
    joined_at = models.DateTimeField(null=True, blank=True)
    left_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Participante Detectado'
        verbose_name_plural = 'Participantes Detectados'

    def __str__(self):
        return f"{self.name} — {self.booking}"


class MeetingDocument(models.Model):
    booking = models.ForeignKey(MeetingBooking, on_delete=models.CASCADE, related_name='documents')
    title = models.CharField(max_length=200, verbose_name='Título del Documento')
    file = models.FileField(upload_to='meetings/docs/%Y/%m/', verbose_name='Archivo')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='meeting_docs')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Documento de Reunión'

    def __str__(self):
        return f"{self.title} — {self.booking}"


class MeetingAgreement(models.Model):
    STATUS_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('cumplido',  'Cumplido'),
        ('vencido',   'Vencido'),
    ]
    booking = models.ForeignKey(MeetingBooking, on_delete=models.CASCADE, related_name='agreements')
    description = models.TextField(verbose_name='Acuerdo')
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='agreements'
    )
    deadline = models.DateField(null=True, blank=True, verbose_name='Plazo')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pendiente')

    class Meta:
        verbose_name = 'Acuerdo'
        verbose_name_plural = 'Acuerdos'

    def __str__(self):
        return f"{self.description[:50]}... ({self.get_status_display()})"


class GuestInvite(models.Model):
    """Link de invitación para externos sin cuenta que necesitan unirse a una reunión."""
    booking = models.ForeignKey(MeetingBooking, on_delete=models.CASCADE, related_name='guest_invites')
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    label = models.CharField(max_length=100, blank=True, verbose_name='Etiqueta', help_text='Ej: MINEDUC, Superintendencia')
    is_active = models.BooleanField(default=True, verbose_name='Activo')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Invitación Externo'
        verbose_name_plural = 'Invitaciones Externos'
        ordering = ['-created_at']

    def __str__(self):
        return f"Invitación '{self.label or str(self.token)[:8]}' — {self.booking}"
