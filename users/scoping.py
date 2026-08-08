"""Aislamiento de datos por organización — un solo punto para todo el proyecto.

El aislamiento vive acá y no repartido en las vistas: son 87 templates y decenas
de vistas, y un `filter()` olvidado en cualquiera de ellas es una fuga de datos
entre clientes. Heredar de `ModeloDeOrganizacion` es lo único que hay que hacer
para que un modelo quede aislado.

Qué modelos lo heredan: solo la **raíz de cada agregado**. Los hijos (una
`Pregunta` dentro de una `Prueba`, un `ConversationMessage` dentro de una
`ChatConversation`) no llevan el campo — se filtran por su padre. Duplicar la
FK en cada hijo es denormalización que se desincroniza sola.
"""
from django.db import models


class OrganizacionQuerySet(models.QuerySet):
    def de_organizacion(self, organizacion):
        """Filas de una organización concreta. `None` no devuelve nada.

        Es deliberado: si el llamador no sabe de qué organización habla, la
        respuesta segura es el conjunto vacío y no la tabla completa.
        """
        if organizacion is None:
            return self.none()
        return self.filter(organizacion=organizacion)

    def visibles_para(self, user):
        """Lo que este usuario puede ver.

        - superusuario: todo (soporte técnico del producto).
        - usuario con organización: solo la suya.
        - usuario sin organización: nada.

        `is_staff` NO abre el alcance a otras organizaciones: en este proyecto
        el staff son administradores del colegio, no del proveedor.
        """
        if user is None or not user.is_authenticated:
            return self.none()
        if user.is_superuser:
            return self
        return self.de_organizacion(getattr(user, 'organizacion', None))


def nombre_establecimiento(codigo, organizacion_id=None):
    """Nombre visible de una sede a partir de su código.

    Reemplaza a los diccionarios `ESTABLISHMENT_NAMES` que estaban copiados en
    `ai_modules/v2/services.py` y `v3/services.py` con las 8 sedes de un cliente:
    una organización nueva veía `.title()` del código en vez de su nombre real.
    """
    from users.models import Establecimiento

    if not codigo:
        return ''
    consulta = Establecimiento.objects.filter(codigo=codigo.strip().upper())
    if organizacion_id:
        consulta = consulta.filter(organizacion_id=organizacion_id)
    sede = consulta.first()
    return sede.nombre if sede else codigo.replace('_', ' ').title()


def establecimientos_de(user):
    """Opciones de establecimiento para los formularios de este usuario.

    Reemplaza a `User.ESTABLISHMENT_CHOICES`, que era un enum fijo con los 8
    colegios de un cliente: cualquier organización nueva veía sedes ajenas en sus
    desplegables y no veía las propias.

    Devuelve pares `(codigo, nombre)` — misma forma que los `choices` de Django,
    así que los templates que lo recorren no cambian.
    """
    from users.models import Establecimiento

    if user is None or not getattr(user, 'is_authenticated', False):
        return []
    if not getattr(user, 'organizacion_id', None):
        return []
    return list(
        Establecimiento.objects
        .filter(organizacion_id=user.organizacion_id, activo=True)
        .values_list('codigo', 'nombre')
    )


class ModeloDeOrganizacion(models.Model):
    """Base de todo modelo cuyos datos pertenecen a una organización.

    El campo es nullable durante la transición (`expand-migrate-contract`): las
    filas históricas se rellenan por migración de datos y recién después se
    puede exigir NOT NULL.
    """

    organizacion = models.ForeignKey(
        'users.Organizacion',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='%(app_label)s_%(class)s_set',
        verbose_name='Organización',
        db_index=True,
    )

    objects = OrganizacionQuerySet.as_manager()

    class Meta:
        abstract = True
