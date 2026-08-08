from django.db import models
from django.conf import settings
from users.scoping import ModeloDeOrganizacion


class UserActivity(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='activity')
    last_activity = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.last_activity}"


class Circular(ModeloDeOrganizacion):
    """Reemplaza Announcement. Soporta destinatarios y flujo de aprobación."""
    PRIORITY_CHOICES = [
        ('normal', 'Normal'),
        ('importante', 'Importante'),
        ('urgente', 'Urgente'),
    ]
    STATUS_CHOICES = [
        ('borrador', 'Borrador'),
        ('pendiente_aprobacion', 'Pendiente de Aprobación'),
        ('publicado', 'Publicado'),
        ('archivado', 'Archivado'),
    ]

    title = models.CharField(max_length=200, verbose_name='Título')
    body = models.TextField(verbose_name='Contenido')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='circulars'
    )
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='normal')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='borrador')
    # Destinatarios (JSON lists de roles/establecimientos)
    target_roles = models.JSONField(default=list, blank=True, verbose_name='Roles destinatarios')
    target_establishments = models.JSONField(default=list, blank=True, verbose_name='Establecimientos destinatarios')
    # Aprobación
    requires_approval = models.BooleanField(default=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='approved_circulars'
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Circular'
        verbose_name_plural = 'Circulares'

    def __str__(self):
        return f"[{self.get_priority_display()}] {self.title}"

    def is_visible_to(self, user):
        """Retorna True si el usuario es destinatario de esta circular."""
        if self.status != 'publicado':
            return user == self.author or user.can_approve_circulars
        role_match = not self.target_roles or user.role in self.target_roles
        ee_match = not self.target_establishments or user.establishment in self.target_establishments
        return role_match and ee_match
