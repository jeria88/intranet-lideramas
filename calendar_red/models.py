from django.db import models
from django.conf import settings
from users.scoping import ModeloDeOrganizacion


class CalendarEvent(ModeloDeOrganizacion):
    EVENT_TYPE_CHOICES = [
        ('mineduc',          'Plazo MINEDUC'),
        ('supereduc',        'Superintendencia de Educación'),
        ('agencia',          'Agencia de Calidad'),
        ('congregacional',   'Congregacional'),
        ('interno',          'Interno EE'),
        ('cultural',         'Cultural'),
        ('deportivo',        'Deportivo'),
    ]

    title = models.CharField(max_length=200, verbose_name='Título')
    description = models.TextField(blank=True, verbose_name='Descripción')
    event_date = models.DateField(verbose_name='Fecha')
    event_time = models.TimeField(null=True, blank=True, verbose_name='Hora')
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES, default='interno', verbose_name='Tipo')
    # Destinatarios (listas vacías = todos)
    applies_to_roles = models.JSONField(default=list, blank=True, verbose_name='Roles')
    applies_to_establishments = models.JSONField(default=list, blank=True, verbose_name='Establecimientos')
    is_critical = models.BooleanField(default=False, verbose_name='Crítico')
    is_active = models.BooleanField(default=True, verbose_name='Activo')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='calendar_events'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Trazabilidad de eliminación
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='deleted_calendar_events'
    )
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['event_date', 'event_time']
        verbose_name = 'Evento del Calendario'
        verbose_name_plural = 'Eventos del Calendario'

    def __str__(self):
        return f"{self.event_date} — {self.title} ({self.get_event_type_display()})"
