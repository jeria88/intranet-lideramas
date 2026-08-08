"""CRM comercial de LíderA+ — a quién le vendemos el producto.

Ojo con la dirección: estos NO son datos de un cliente, son los datos con los que
se consigue un cliente. Por eso los modelos de esta app **no** heredan de
`ModeloDeOrganizacion`: no pertenecen a ninguna organización, pertenecen al
proveedor. El acceso se restringe por `is_staff`, no por aislamiento.

El esquema es un espejo deliberado del de `acme-leads` (Cloudflare + D1), que ya
resolvió este dominio. Se copian sus decisiones caras de aprender:

  - `hash_dedupe` sobre el nombre normalizado y NADA más. Incluir el teléfono
    parece más preciso y es peor: dos fuentes del mismo colegio, una con teléfono
    y otra sin él, dejarían de colisionar y quedarían duplicadas.
  - `score` 0-6 por completitud de contacto, calculado una vez al ingresar.
  - Una etapa inicial obligatoria al crear el lead, resuelta por `MIN(orden)` y no
    por nombre. En ARQlead esto fue un bug real: 20 leads existían en la base y no
    aparecían en ningún lado porque su `stage_id` era NULL y el kanban agrupa por
    etapa.
"""
import hashlib
import re
import unicodedata

from django.conf import settings
from django.db import models


def normalizar_nombre(nombre):
    """Minúsculas, sin tildes, sin puntuación, espacios colapsados.

    Los puntos se BORRAN y el resto de la puntuación pasa a espacio. Los dos casos
    tiran para lados opuestos y hay que atender ambos:
      'Colegio San José S.A.'  → 'colegio san jose sa'     (punto borrado)
      'Colegio-San José'       → 'colegio san jose'        (guión a espacio)
    Tratar el punto como el resto daría 's a', y la misma entidad quedaría
    duplicada según cómo la escribió cada fuente.
    """
    texto = unicodedata.normalize('NFKD', (nombre or '').strip().lower())
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    texto = texto.replace('.', '')
    texto = re.sub(r'[^a-z0-9\s]', ' ', texto)
    return re.sub(r'\s+', ' ', texto).strip()


def hash_de(nombre):
    return hashlib.sha1(normalizar_nombre(nombre).encode()).hexdigest()


class Vertical(models.Model):
    """Mercado al que se le vende. Educación es el primero, no el único.

    Liderazgo es transversal: salud, familia y empresa son el mismo producto con
    otro vocabulario. Por eso es una tabla y no un enum.
    """
    nombre = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(unique=True)
    activa = models.BooleanField(default=False)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nombre']
        verbose_name_plural = 'Verticales'

    def __str__(self):
        return self.nombre


class Ciudad(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    region = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ['nombre']
        verbose_name_plural = 'Ciudades'

    def __str__(self):
        return self.nombre


class Target(models.Model):
    """Vertical × ciudad: la unidad de prospección."""
    vertical = models.ForeignKey(Vertical, on_delete=models.CASCADE, related_name='targets')
    ciudad = models.ForeignKey(Ciudad, on_delete=models.CASCADE, related_name='targets')
    activo = models.BooleanField(default=True)
    meta_leads_dia = models.PositiveSmallIntegerField(default=20)

    class Meta:
        unique_together = [('vertical', 'ciudad')]
        ordering = ['vertical', 'ciudad']

    def __str__(self):
        return f'{self.vertical} · {self.ciudad}'

    def etapa_inicial(self):
        """Por `MIN(orden)`, nunca por nombre: las etapas se renombran desde la UI."""
        return self.etapas.order_by('orden').first()

    def crear_etapas_por_defecto(self):
        """Kanban estándar. Idempotente."""
        por_defecto = [
            ('nuevo', 1, False),
            ('contactado', 2, False),
            ('respondió', 3, False),
            ('demo agendada', 4, False),
            ('ganado', 5, True),
            ('perdido', 6, True),
        ]
        for nombre, orden, terminal in por_defecto:
            Etapa.objects.get_or_create(
                target=self, orden=orden,
                defaults={'nombre': nombre, 'es_terminal': terminal},
            )
        return self.etapas.all()


class Etapa(models.Model):
    """Columna del kanban. Personalizable por target."""
    target = models.ForeignKey(Target, on_delete=models.CASCADE, related_name='etapas')
    nombre = models.CharField(max_length=60)
    orden = models.PositiveSmallIntegerField()
    es_terminal = models.BooleanField(default=False, verbose_name='Cierra el lead')

    class Meta:
        unique_together = [('target', 'orden')]
        ordering = ['target', 'orden']

    def __str__(self):
        return f'{self.target} → {self.nombre}'


class Lead(models.Model):
    ORIGEN_CHOICES = [
        ('manual', 'Carga manual'),
        ('directorio', 'Directorio público'),
        ('referido', 'Referido'),
        ('inbound', 'Llegó solo'),
    ]

    target = models.ForeignKey(Target, on_delete=models.PROTECT, related_name='leads')
    etapa = models.ForeignKey(Etapa, on_delete=models.PROTECT, related_name='leads')

    nombre = models.CharField(max_length=200)
    contacto = models.CharField(max_length=150, blank=True, verbose_name='Persona de contacto')
    cargo = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=40, blank=True)
    web = models.URLField(blank=True)
    direccion = models.CharField(max_length=200, blank=True)
    # Rol de Base de Datos: identificador oficial de un establecimiento chileno.
    # Vive acá y no en un modelo aparte porque solo aplica a la vertical educación.
    rbd = models.CharField(max_length=10, blank=True, verbose_name='RBD')

    origen = models.CharField(max_length=12, choices=ORIGEN_CHOICES, default='manual')
    hash_dedupe = models.CharField(max_length=40, unique=True, editable=False)
    score = models.PositiveSmallIntegerField(default=0, editable=False)

    notas = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    valor_estimado = models.PositiveIntegerField(null=True, blank=True, verbose_name='Valor estimado (CLP)')

    ultimo_contacto = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-creado_en']

    def __str__(self):
        return self.nombre

    def calcular_score(self):
        """0-6 por completitud de contacto. Mismo criterio que acme-leads/ARQlead."""
        return (
            (2 if self.email else 0)
            + (2 if self.telefono else 0)
            + (1 if self.web else 0)
            + (1 if self.direccion else 0)
        )

    def save(self, *args, **kwargs):
        self.hash_dedupe = hash_de(self.nombre)
        self.score = self.calcular_score()
        if not self.etapa_id and self.target_id:
            inicial = self.target.etapa_inicial()
            if inicial:
                self.etapa = inicial
        super().save(*args, **kwargs)


class Contacto(models.Model):
    """Un toque real: el mensaje que salió y lo que contestaron.

    El envío lo hace Franco a mano (WhatsApp, correo, LinkedIn). Acá se registra,
    porque la métrica que importa es 'conversaciones con desconocidos' y esa no la
    da ninguna plataforma.
    """
    CANAL_CHOICES = [
        ('whatsapp', 'WhatsApp'),
        ('email', 'Correo'),
        ('linkedin', 'LinkedIn'),
        ('instagram', 'Instagram'),
        ('telefono', 'Teléfono'),
        ('presencial', 'Presencial'),
    ]

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='contactos')
    canal = models.CharField(max_length=12, choices=CANAL_CHOICES, default='whatsapp')
    enviado = models.TextField(verbose_name='Mensaje enviado')
    respuesta = models.TextField(blank=True)
    respondio = models.BooleanField(default=False, verbose_name='¿Respondió?')
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='contactos_crm',
    )
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha']

    def __str__(self):
        return f'{self.lead} · {self.get_canal_display()} · {self.fecha:%d-%m-%Y}'

    def save(self, *args, **kwargs):
        # Marcar respuesta y no actualizar el lead deja el kanban mintiendo sobre
        # cuándo fue el último toque, que es el dato con el que se prioriza el día.
        self.respondio = bool(self.respuesta.strip())
        super().save(*args, **kwargs)
        Lead.objects.filter(pk=self.lead_id).update(ultimo_contacto=self.fecha)
