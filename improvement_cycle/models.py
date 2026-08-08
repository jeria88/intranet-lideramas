from django.db import models
from django.conf import settings
from users.models import User
from users.scoping import ModeloDeOrganizacion


class ImprovementGoal(ModeloDeOrganizacion):
    STATUS_CHOICES = [
        ('en_progreso', 'En Progreso'),
        ('cumplido',    'Cumplido'),
        ('en_riesgo',   'En Riesgo'),
        ('vencido',     'Vencido'),
    ]
    SUBVENTION_CHOICES = [
        ('SEP', 'SEP'),
        ('PIE', 'PIE'),
        ('MANTENCION', 'Mantención'),
        ('PRO_RETENCION', 'Pro-Retención'),
        ('NO_CORRESPONDE', 'No corresponde'),
        ('OTRO', 'Otro'),
    ]
    establishment = models.CharField(
        max_length=20, blank=True, default='', verbose_name='Establecimiento (código)'
    )
    profile_role = models.CharField(
        max_length=20, choices=User.ROLE_CHOICES, blank=True, verbose_name='Rol responsable'
    )
    subvention_type = models.CharField(
        max_length=20, choices=SUBVENTION_CHOICES, default='SEP', verbose_name='Tipo de Subvención'
    )
    title = models.CharField(max_length=200, verbose_name='Meta')
    description = models.TextField(blank=True, verbose_name='Resumen/Descripción')
    target_value = models.FloatField(verbose_name='Valor meta')
    current_value = models.FloatField(default=0, verbose_name='Valor actual')
    measurement_unit = models.CharField(max_length=50, verbose_name='Unidad')  # %, reuniones, docs
    deadline = models.DateField(verbose_name='Plazo')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='en_progreso')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='goals'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # --- Nuevos campos para automatización ---
    strategic_objectives = models.JSONField(default=list, blank=True, verbose_name='Objetivos Estratégicos')
    is_meeting_cycle = models.BooleanField(default=False, verbose_name='Es ciclo de reunión')
    associated_booking = models.ForeignKey(
        'meetings.MeetingBooking', on_delete=models.SET_NULL, null=True, blank=True, related_name='improvement_cycles'
    )
    process_route = models.JSONField(default=list, blank=True, verbose_name='Ruta de Procesos (IA)')
    indicators = models.JSONField(default=list, blank=True, verbose_name='Indicadores de Logro (IA)')
    is_generating = models.BooleanField(default=False, verbose_name='IA Redactando')
    edit_history = models.JSONField(default=list, blank=True, verbose_name='Historial de Ediciones')
    # ----------------------------------------



    class Meta:
        ordering = ['deadline', 'establishment']
        verbose_name = 'Meta de Mejora'
        verbose_name_plural = 'Metas de Mejora'

    @property
    def actions_summary(self):
        total = self.actions.count()
        completed = self.actions.filter(status='completado').count()
        return f"{completed} de {total} acciones"

    @property
    def progress_pct(self):
        """Calcula el progreso basado en las acciones si existen, si no usa current_value."""
        actions = self.actions.all()
        if actions.exists():
            total_weight = sum(a.weight for a in actions if a.weight is not None)
            if total_weight == 0: return 0
            completed_weight = sum(a.weight for a in actions if a.status == 'completado' and a.weight is not None)
            return round((completed_weight / total_weight) * 100, 1)
        
        if self.target_value == 0: return 0
        current = self.current_value or 0
        target = self.target_value or 1
        return min(100, round((current / target) * 100, 1))


    def __str__(self):
        return f"{self.establishment} — {self.title} ({self.progress_pct}%)"


class ImprovementAction(models.Model):
    STATUS_CHOICES = [
        ('pendiente',   'Pendiente'),
        ('en_progreso', 'En Progreso'),
        ('completado',  'Completado'),
        ('cancelado',   'Cancelado'),
    ]
    goal = models.ForeignKey(ImprovementGoal, on_delete=models.CASCADE, related_name='actions')
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, 
        limit_choices_to={'is_active': True}, verbose_name='Responsable'
    )
    title = models.CharField(max_length=200, verbose_name='Acción/Hito')
    description = models.TextField(blank=True, verbose_name='Descripción de la acción')
    evidence = models.TextField(blank=True, verbose_name='Evidencia / Observaciones')
    deadline = models.DateField(verbose_name='Plazo de la acción')
    weight = models.FloatField(default=1.0, verbose_name='Peso/Importancia (1-100)')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pendiente')
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='completed_actions', verbose_name='Completado por'
    )
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='Completado el')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['deadline', 'created_at']
        verbose_name = 'Acción de Mejora'
        verbose_name_plural = 'Acciones de Mejora'

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"


class RiskAlert(ModeloDeOrganizacion):
    ALERT_TYPE_CHOICES = [
        ('plazo_mineduc',       'Plazo MINEDUC'),
        ('brecha_normativa',    'Brecha Normativa'),
        ('documento_vencido',   'Documento Vencido'),
        ('meta_en_riesgo',      'Meta en Riesgo'),
        ('consulta_ia_vencida', 'Consulta IA Vencida'),
        ('reunion_cuota',       'Cuota de Reuniones Alcanzada'),
    ]
    alert_type = models.CharField(max_length=25, choices=ALERT_TYPE_CHOICES, verbose_name='Tipo de Alerta')
    description = models.TextField(verbose_name='Descripción')
    affected_establishments = models.JSONField(default=list, verbose_name='Establecimientos afectados')
    triggered_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    # Referencia genérica al objeto que generó la alerta
    related_object_info = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['-triggered_at']
        verbose_name = 'Alerta de Riesgo'
        verbose_name_plural = 'Alertas de Riesgo'

    def resolve(self):
        from django.utils import timezone
        self.is_active = False
        self.resolved_at = timezone.now()
        self.save(update_fields=['is_active', 'resolved_at'])

    def __str__(self):
        return f"[{self.get_alert_type_display()}] {self.description[:60]}"
