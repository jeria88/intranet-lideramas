from django.db import models
from django.conf import settings
from users.scoping import ModeloDeOrganizacion


class EventoCultural(ModeloDeOrganizacion):
    TIPO_CHOICES = [
        ('cultural', 'Cultural'),
        ('deportivo', 'Deportivo'),
    ]
    STATUS_CHOICES = [
        ('borrador', 'Borrador'),
        ('publicado', 'Publicado'),
        ('finalizado', 'Finalizado'),
    ]

    titulo = models.CharField(max_length=200, verbose_name='Título')
    descripcion = models.TextField(verbose_name='Descripción')
    tipo = models.CharField(max_length=15, choices=TIPO_CHOICES, default='cultural', verbose_name='Tipo')
    fecha = models.DateField(verbose_name='Fecha')
    hora = models.TimeField(null=True, blank=True, verbose_name='Hora')
    lugar = models.CharField(max_length=200, verbose_name='Lugar')
    imagen = models.ImageField(upload_to='eventos/', null=True, blank=True, verbose_name='Imagen/Afiche')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='borrador', verbose_name='Estado')

    calendar_event = models.OneToOneField(
        'calendar_red.CalendarEvent', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='evento_cultural'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='eventos_culturales'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-fecha']
        verbose_name = 'Evento Cultural/Deportivo'
        verbose_name_plural = 'Eventos Culturales/Deportivos'

    def __str__(self):
        return f"{self.titulo} ({self.get_tipo_display()}) — {self.fecha}"
