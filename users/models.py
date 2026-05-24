from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.validators import UnicodeUsernameValidator


class User(AbstractUser):
    # Override to remove global unique — uniqueness is enforced per (username, tenant)
    username = models.CharField(
        max_length=150,
        validators=[UnicodeUsernameValidator()],
        verbose_name='username',
        error_messages={'unique': 'Ya existe un usuario con ese nombre en este proyecto.'},
    )
    tenant = models.CharField(max_length=50, default='sfa', verbose_name='Proyecto')

    ROLE_CHOICES = [
        ('REPRESENTANTE', 'Representante Legal'),
        ('UTP', 'Unidad Técnica Pedagógica'),
        ('DIRECTOR', 'Director/a'),
        ('INSPECTOR', 'Inspector/a General'),
        ('CONVIVENCIA', 'Coordinador/a de Convivencia Educativa'),
        ('RED', 'Equipo Red'),
    ]
    ESTABLISHMENT_CHOICES = [
        ('TEMUCO', 'Temuco'),
        ('LAUTARO', 'Lautaro'),
        ('RENAICO', 'Renaico'),
        ('SANTIAGO', 'Santiago'),
        # FLORIDA fusionado con SANTIAGO
        ('IMPERIAL', 'Imperial'),
        ('ERCILLA', 'Ercilla'),
        ('ARAUCO', 'Arauco'),
        ('ANGOL', 'Angol'),
        ('RED', 'Equipo Red Congregacional'),
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='DIRECTOR', verbose_name='Cargo')
    establishment = models.CharField(max_length=20, choices=ESTABLISHMENT_CHOICES, default='ANGOL', verbose_name='Establecimiento')
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True, verbose_name='Foto de perfil')
    bio = models.TextField(blank=True, verbose_name='Descripción')
    phone = models.CharField(max_length=20, blank=True, verbose_name='Teléfono')
    must_change_password = models.BooleanField(default=False, verbose_name='Debe cambiar contraseña')

    @property
    def is_red_team(self):
        """Equipo Red tiene reuniones ilimitadas."""
        return self.role == 'RED' or self.establishment == 'RED'

    @property
    def can_approve_circulars(self):
        """Director, UTP, Representante y Staff pueden aprobar circulares."""
        return self.role in ['REPRESENTANTE', 'DIRECTOR', 'UTP'] or self.is_staff

    class Meta:
        unique_together = [('username', 'tenant')]

    @property
    def short_username(self):
        return self.username

    def __str__(self):
        return f"{self.get_full_name() or self.username} — {self.get_role_display()} ({self.get_establishment_display()})"
