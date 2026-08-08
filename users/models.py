from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.validators import UnicodeUsernameValidator


class Organizacion(models.Model):
    """El cliente que contrata LíderA+. Reemplaza a `User.tenant` (CharField).

    Durante la transición ambos conviven: `slug` es exactamente el valor que hoy
    lleva `User.tenant`, así que la migración de datos es una equivalencia 1:1 y
    el login por path (`/<tenant>/login/`) sigue funcionando sin cambios.
    """
    slug = models.SlugField(unique=True, verbose_name='Identificador (URL)')
    nombre = models.CharField(max_length=150)
    activa = models.BooleanField(default=True)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Organización'
        verbose_name_plural = 'Organizaciones'

    def __str__(self):
        return self.nombre


class Establecimiento(models.Model):
    """Una sede/colegio dentro de una organización.

    Reemplaza a `User.ESTABLISHMENT_CHOICES`, que estaba hardcodeado con los 8
    colegios de la Red SFA y se reusaba como `choices` en
    `improvement_cycle/models.py` y `library/models.py`. `codigo` conserva los
    valores del enum viejo (TEMUCO, ANGOL, …) para que la migración de datos sea
    directa y los registros existentes no queden huérfanos.
    """
    organizacion = models.ForeignKey(
        Organizacion, on_delete=models.CASCADE, related_name='establecimientos',
    )
    codigo = models.CharField(max_length=20, verbose_name='Código')
    nombre = models.CharField(max_length=150)
    rbd = models.CharField(max_length=10, blank=True, verbose_name='RBD')
    es_equipo_central = models.BooleanField(
        default=False,
        verbose_name='Equipo central / RED',
        help_text='Cuota de reuniones ilimitada y visión transversal de la organización.',
    )
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['organizacion', 'nombre']
        unique_together = [('organizacion', 'codigo')]

    def __str__(self):
        return f"{self.nombre} ({self.organizacion.slug})"


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

    # ── Transición a multi-tenancy real ───────────────────────────────────────
    # Conviven con `tenant`/`establishment` mientras se migran las lecturas.
    # `tenant` es la fuente de verdad hasta que `organizacion` esté poblado en
    # todos los usuarios; después se invierte y los CharFields se retiran.
    organizacion = models.ForeignKey(
        Organizacion, null=True, blank=True, on_delete=models.PROTECT,
        related_name='usuarios', verbose_name='Organización',
    )
    establecimiento = models.ForeignKey(
        Establecimiento, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='usuarios', verbose_name='Establecimiento (nuevo)',
    )
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True, verbose_name='Foto de perfil')
    bio = models.TextField(blank=True, verbose_name='Descripción')
    phone = models.CharField(max_length=20, blank=True, verbose_name='Teléfono')
    must_change_password = models.BooleanField(default=False, verbose_name='Debe cambiar contraseña')

    @property
    def is_red_team(self):
        """Equipo Red tiene reuniones ilimitadas.

        Durante la transición se resuelve por cualquiera de los dos caminos: el
        CharField histórico o el flag de la tabla nueva. Cuando `establishment`
        se retire, queda solo la segunda condición.
        """
        if self.establecimiento_id and self.establecimiento.es_equipo_central:
            return True
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
