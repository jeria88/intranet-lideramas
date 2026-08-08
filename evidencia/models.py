from django.db import models
from django.conf import settings
from users.scoping import ModeloDeOrganizacion


class EvaluationForm(ModeloDeOrganizacion):
    SESSION_CHOICES = [
        ('presencial', 'Reunión Presencial'),
        ('virtual',    'Reunión Virtual'),
    ]
    title = models.CharField(max_length=300, verbose_name='Título del Formulario')
    description = models.TextField(blank=True)
    form_url = models.URLField(verbose_name='Link al Formulario (Google Forms)')
    results_url = models.URLField(blank=True, verbose_name='Link a Resultados (PDF)')
    session_type = models.CharField(max_length=15, choices=SESSION_CHOICES, default='presencial')
    applied_at = models.DateField(null=True, blank=True, verbose_name='Fecha de aplicación')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='evaluation_forms'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-applied_at']
        verbose_name = 'Formulario de Evaluación'
        verbose_name_plural = 'Formularios de Evaluación'

    def __str__(self):
        return self.title


class EvidenceDocument(ModeloDeOrganizacion):
    """Documentos de evidencia de reuniones (presentaciones, actas, fotos)."""
    CATEGORY_CHOICES = [
        ('presentacion', 'Presentación'),
        ('acta',         'Acta'),
        ('foto',         'Fotografía'),
        ('otro',         'Otro'),
    ]
    SESSION_CHOICES = [
        ('presencial', 'Reunión Presencial'),
        ('virtual',    'Reunión Virtual'),
    ]
    title = models.CharField(max_length=200, verbose_name='Título')
    file = models.FileField(upload_to='evidencia/%Y/%m/', null=True, blank=True)
    external_url = models.URLField(blank=True, verbose_name='URL externa (si aplica)')
    category = models.CharField(max_length=15, choices=CATEGORY_CHOICES, default='otro')
    session_type = models.CharField(max_length=15, choices=SESSION_CHOICES, default='presencial')
    session_date = models.DateField(null=True, blank=True, verbose_name='Fecha de la reunión')
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='evidence_docs'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-session_date']
        verbose_name = 'Documento de Evidencia'

    def __str__(self):
        return f"{self.title} ({self.get_category_display()})"
