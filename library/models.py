from django.db import models
from django.conf import settings
from users.models import User
from users.scoping import ModeloDeOrganizacion


class Category(ModeloDeOrganizacion):
    name = models.CharField(max_length=100, unique=True, verbose_name='Categoría')
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Categorías"
        ordering = ['name']


class Document(ModeloDeOrganizacion):
    title = models.CharField(max_length=255, verbose_name='Título')
    file = models.FileField(upload_to='documents/%Y/%m/%d/', verbose_name='Archivo')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='documents')
    establishment = models.CharField(
        max_length=20, blank=True, default='', verbose_name='Establecimiento (código)'
    )
    description = models.TextField(verbose_name='Reseña/Descripción')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='uploaded_documents'
    )
    upload_date = models.DateTimeField(auto_now_add=True)
    # Control de versiones
    version = models.CharField(max_length=20, default='1.0', verbose_name='Versión')
    parent_document = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='versions',
        verbose_name='Documento base'
    )
    # Metadatos adicionales
    cargo_type = models.CharField(
        max_length=20, choices=User.ROLE_CHOICES, blank=True, verbose_name='Cargo destinatario'
    )
    materia = models.CharField(max_length=100, blank=True, verbose_name='Materia/Área')
    is_mandatory = models.BooleanField(default=False, verbose_name='Documento obligatorio')
    expiry_alert_date = models.DateField(null=True, blank=True, verbose_name='Alerta de obsolescencia')

    class Meta:
        ordering = ['-upload_date']
        verbose_name = 'Documento'

    def __str__(self):
        return f"{self.title} v{self.version}"
