"""Aislamiento de datos entre organizaciones.

Es el criterio que decide si LíderA+ puede venderse a más de un cliente: dos
organizaciones en la misma instancia no pueden verse los datos. Todo pasa por
`OrganizacionQuerySet.visibles_para`, así que se prueba ahí y no vista por vista.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from ai_modules.models import AIAssistant
from library.models import Category
from simce.models import Prueba
from users.models import Establecimiento, Organizacion
from users.scoping import ModeloDeOrganizacion

User = get_user_model()


class AislamientoEntreOrganizacionesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organizacion.objects.create(slug='colegio_a', nombre='Colegio A')
        cls.org_b = Organizacion.objects.create(slug='colegio_b', nombre='Colegio B')

        cls.sede_a = Establecimiento.objects.create(organizacion=cls.org_a, codigo='SEDE_A', nombre='Sede A')
        cls.sede_b = Establecimiento.objects.create(organizacion=cls.org_b, codigo='SEDE_B', nombre='Sede B')

        cls.user_a = User.objects.create_user(
            username='director', password='x', tenant='colegio_a',
            organizacion=cls.org_a, establecimiento=cls.sede_a,
        )
        cls.user_b = User.objects.create_user(
            username='director', password='x', tenant='colegio_b',
            organizacion=cls.org_b, establecimiento=cls.sede_b,
        )
        cls.soporte = User.objects.create_superuser(
            username='soporte', password='x', tenant='interno',
        )
        cls.sin_org = User.objects.create_user(username='huerfano', password='x', tenant='ninguno')

        # Un dato de cada tipo en cada organización.
        cls.asistente_a = AIAssistant.objects.create(
            slug='utp-a', name='UTP A', profile_role='UTP', image_name='x.jpg', organizacion=cls.org_a,
        )
        cls.asistente_b = AIAssistant.objects.create(
            slug='utp-b', name='UTP B', profile_role='UTP', image_name='x.jpg', organizacion=cls.org_b,
        )
        cls.categoria_a = Category.objects.create(name='Normativa A', organizacion=cls.org_a)
        cls.categoria_b = Category.objects.create(name='Normativa B', organizacion=cls.org_b)
        cls.prueba_a = Prueba.objects.create(
            titulo='Ensayo A', asignatura='lenguaje', curso='4B',
            creada_por=cls.user_a, organizacion=cls.org_a,
        )
        cls.prueba_b = Prueba.objects.create(
            titulo='Ensayo B', asignatura='lenguaje', curso='4B',
            creada_por=cls.user_b, organizacion=cls.org_b,
        )

    def test_cada_organizacion_ve_solo_lo_suyo(self):
        for Modelo, propio_a, propio_b in (
            (AIAssistant, self.asistente_a, self.asistente_b),
            (Category, self.categoria_a, self.categoria_b),
            (Prueba, self.prueba_a, self.prueba_b),
        ):
            with self.subTest(modelo=Modelo.__name__):
                vistos_a = set(Modelo.objects.visibles_para(self.user_a).values_list('pk', flat=True))
                vistos_b = set(Modelo.objects.visibles_para(self.user_b).values_list('pk', flat=True))

                self.assertIn(propio_a.pk, vistos_a)
                self.assertNotIn(propio_b.pk, vistos_a, f'{Modelo.__name__}: A ve datos de B')
                self.assertIn(propio_b.pk, vistos_b)
                self.assertNotIn(propio_a.pk, vistos_b, f'{Modelo.__name__}: B ve datos de A')
                self.assertEqual(vistos_a & vistos_b, set())

    def test_el_superusuario_ve_todo(self):
        """Soporte del producto. Es el único que cruza organizaciones."""
        vistos = set(AIAssistant.objects.visibles_para(self.soporte).values_list('pk', flat=True))
        self.assertIn(self.asistente_a.pk, vistos)
        self.assertIn(self.asistente_b.pk, vistos)

    def test_staff_del_colegio_no_cruza_organizaciones(self):
        """`is_staff` administra SU colegio, no el del vecino."""
        self.user_a.is_staff = True
        self.user_a.save(update_fields=['is_staff'])

        vistos = set(AIAssistant.objects.visibles_para(self.user_a).values_list('pk', flat=True))
        self.assertNotIn(self.asistente_b.pk, vistos)

    def test_usuario_sin_organizacion_no_ve_nada(self):
        self.assertEqual(AIAssistant.objects.visibles_para(self.sin_org).count(), 0)

    def test_anonimo_no_ve_nada(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertEqual(AIAssistant.objects.visibles_para(AnonymousUser()).count(), 0)
        self.assertEqual(AIAssistant.objects.visibles_para(None).count(), 0)

    def test_de_organizacion_con_none_devuelve_vacio_no_todo(self):
        """La falla seria: que un `organizacion=None` se lea como 'sin filtro'."""
        self.assertEqual(AIAssistant.objects.de_organizacion(None).count(), 0)

    def test_una_fila_sin_organizacion_no_es_visible_para_nadie(self):
        huerfana = AIAssistant.objects.create(
            slug='sin-org', name='Huérfana', profile_role='UTP', image_name='x.jpg',
        )
        self.assertNotIn(huerfana.pk, AIAssistant.objects.visibles_para(self.user_a).values_list('pk', flat=True))
        self.assertNotIn(huerfana.pk, AIAssistant.objects.visibles_para(self.user_b).values_list('pk', flat=True))

    def test_no_se_puede_borrar_una_organizacion_con_usuarios(self):
        """`User.organizacion` es PROTECT: borrar un cliente activo no es un accidente
        de un clic. Primero hay que resolver qué pasa con sus usuarios."""
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            self.org_b.delete()

    def test_borrar_la_organizacion_arrastra_sus_datos(self):
        """Resueltos los usuarios, el resto cae por CASCADE: no quedan datos sueltos.

        Se usa una organización propia del test y sin asistentes: al cascadear,
        `AIAssistant` arrastra `AIKnowledgeChunk`, que el router manda a la base
        `knowledge_base` — un alias que en tests es otra base y no tiene esa
        tabla. Es una restricción del entorno de pruebas, no del aislamiento.
        """
        org_c = Organizacion.objects.create(slug='colegio_c', nombre='Colegio C')
        categoria_c = Category.objects.create(name='Normativa C', organizacion=org_c)
        prueba_c = Prueba.objects.create(
            titulo='Ensayo C', asignatura='lenguaje', curso='4B', organizacion=org_c,
        )

        org_c.delete()

        self.assertFalse(Category.objects.filter(pk=categoria_c.pk).exists())
        self.assertFalse(Prueba.objects.filter(pk=prueba_c.pk).exists())
        # Las otras organizaciones quedan intactas.
        self.assertTrue(Category.objects.filter(pk=self.categoria_a.pk).exists())
        self.assertTrue(Category.objects.filter(pk=self.categoria_b.pk).exists())


class AlcanceImplicitoTests(TestCase):
    """El filtro automático del manager. Es implícito, así que se prueba explícito.

    Sustituye a acordarse de filtrar en 81 consultas repartidas en 11 vistas.
    """

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organizacion.objects.create(slug='org_a', nombre='Org A')
        cls.org_b = Organizacion.objects.create(slug='org_b', nombre='Org B')
        cls.cat_a = Category.objects.create(name='De A', organizacion=cls.org_a)
        cls.cat_b = Category.objects.create(name='De B', organizacion=cls.org_b)
        cls.huerfana = Category.objects.create(name='Sin dueño')

        cls.user_a = User.objects.create_user(
            username='ana', password='x', tenant='org_a', organizacion=cls.org_a,
        )
        cls.soporte = User.objects.create_superuser(username='root', password='x')

    def test_fuera_de_request_no_filtra(self):
        """Comandos, migraciones y shell siguen viendo todo, como antes."""
        from users.scoping import FUERA_DE_REQUEST, alcance_actual

        self.assertIs(alcance_actual(), FUERA_DE_REQUEST)
        self.assertEqual(Category.objects.count(), 3)

    def test_dentro_de_un_alcance_solo_se_ve_esa_organizacion(self):
        from users.scoping import alcance

        with alcance(self.org_a):
            nombres = set(Category.objects.values_list('name', flat=True))
        self.assertEqual(nombres, {'De A'})

    def test_el_alcance_se_restaura_al_salir(self):
        """Un contextvar que quedara fijado contaminaría la siguiente operación."""
        from users.scoping import FUERA_DE_REQUEST, alcance, alcance_actual

        with alcance(self.org_a):
            pass
        self.assertIs(alcance_actual(), FUERA_DE_REQUEST)
        self.assertEqual(Category.objects.count(), 3)

    def test_alcance_none_no_devuelve_nada(self):
        """Usuario sin organización o anónimo: cero filas, no la tabla entera."""
        from users.scoping import alcance

        with alcance(None):
            self.assertEqual(Category.objects.count(), 0)

    def test_el_superusuario_no_filtra(self):
        from users.scoping import TODAS, alcance

        with alcance(TODAS):
            self.assertEqual(Category.objects.count(), 3)

    def test_una_fila_sin_organizacion_no_aparece_dentro_de_ningun_alcance(self):
        from users.scoping import alcance

        for organizacion in (self.org_a, self.org_b):
            with alcance(organizacion):
                self.assertNotIn(
                    'Sin dueño', set(Category.objects.values_list('name', flat=True))
                )

    def test_el_manager_todos_nunca_filtra(self):
        """`todos` es el base_manager: si filtrara, resolver una FK podría reventar
        a mitad de un request con un DoesNotExist sobre una fila que sí existe."""
        from users.scoping import alcance

        with alcance(self.org_a):
            self.assertEqual(Category.todos.count(), 3)

    def test_el_middleware_fija_el_alcance_segun_el_usuario(self):
        """Prueba de extremo a extremo: mismo request, distinta organización."""
        from users.scoping import alcance_de

        self.assertEqual(alcance_de(self.user_a), self.org_a)

        from django.contrib.auth.models import AnonymousUser
        self.assertIsNone(alcance_de(AnonymousUser()))

        from users.scoping import TODAS
        self.assertIs(alcance_de(self.soporte), TODAS)

    def test_crear_dentro_de_un_alcance_asigna_la_organizacion(self):
        """Sin esto, una vista que crea produce una fila que el propio filtro
        vuelve invisible: ni siquiera la ve quien acaba de crearla."""
        from users.scoping import alcance

        with alcance(self.org_b):
            nueva = Category.objects.create(name='Creada en B')

        self.assertEqual(nueva.organizacion, self.org_b)

        with alcance(self.org_b):
            self.assertIn('Creada en B', set(Category.objects.values_list('name', flat=True)))
        with alcance(self.org_a):
            self.assertNotIn('Creada en B', set(Category.objects.values_list('name', flat=True)))

    def test_crear_con_organizacion_explicita_gana_sobre_el_alcance(self):
        from users.scoping import alcance

        with alcance(self.org_a):
            nueva = Category.objects.create(name='Explícita', organizacion=self.org_b)
        self.assertEqual(nueva.organizacion, self.org_b)

    def test_crear_fuera_de_request_no_inventa_organizacion(self):
        """Comandos y migraciones deciden ellos: no se les asigna nada por detrás."""
        nueva = Category.objects.create(name='De comando')
        self.assertIsNone(nueva.organizacion)

    def test_guardar_una_fila_existente_no_le_cambia_la_organizacion(self):
        from users.scoping import alcance

        with alcance(self.org_b):
            self.cat_a.name = 'De A renombrada'
            self.cat_a.save()

        self.cat_a.refresh_from_db()
        self.assertEqual(self.cat_a.organizacion, self.org_a)

    def test_el_alcance_no_se_filtra_entre_requests(self):
        """El middleware restaura en `finally`; si no, el segundo request heredaría
        el alcance del primero en el mismo worker."""
        from users.scoping import FUERA_DE_REQUEST, alcance_actual

        self.client.force_login(self.user_a)
        self.client.get('/')
        self.assertIs(alcance_actual(), FUERA_DE_REQUEST)


class ModulosContratadosTests(TestCase):
    """Vender los módulos por separado exige poder no dárselos a quien no los pagó."""

    def setUp(self):
        self.org = Organizacion.objects.create(slug='colegio_m', nombre='Colegio M')
        self.user = User.objects.create_user(
            username='director', password='clave', tenant='colegio_m', organizacion=self.org,
        )
        self.client.force_login(self.user)

    def test_sin_lista_de_modulos_tiene_todo(self):
        """Default seguro: el campo se agregó sobre organizaciones que ya usaban
        todo, y quitarles el acceso de un día para otro sería el bug."""
        for codigo in Organizacion.CODIGOS_MODULO:
            self.assertTrue(self.org.tiene_modulo(codigo), codigo)

    def test_con_lista_solo_tiene_lo_contratado(self):
        self.org.modulos = ['simce']
        self.org.save(update_fields=['modulos'])

        self.assertTrue(self.org.tiene_modulo('simce'))
        self.assertFalse(self.org.tiene_modulo('asistentes'))

    def test_un_modulo_no_contratado_no_se_abre(self):
        self.org.modulos = ['simce']
        self.org.save(update_fields=['modulos'])

        resp = self.client.get('/ia/', follow=True)
        self.assertNotEqual(resp.status_code, 403, 'no debe ser un 403 crudo')
        mensajes = [str(m) for m in resp.context['messages']]
        self.assertTrue(
            any('no está incluido en el plan' in m for m in mensajes),
            f'no se explicó por qué se denegó: {mensajes}',
        )

    def test_el_modulo_contratado_si_se_abre(self):
        self.org.modulos = ['simce']
        self.org.save(update_fields=['modulos'])

        resp = self.client.get('/simce/', follow=True)
        mensajes = [str(m) for m in getattr(resp, 'context', {}).get('messages', [])]
        self.assertFalse(any('no está incluido en el plan' in m for m in mensajes))

    def test_los_modulos_base_no_se_cortan(self):
        """Portal, mensajería y calendario van incluidos: no están en el mapa."""
        self.org.modulos = ['simce']
        self.org.save(update_fields=['modulos'])

        from users.middleware import ModuloContratadoMiddleware
        for prefijo in ('/', '/mensajes/', '/calendario/', '/notificaciones/'):
            self.assertNotIn(prefijo, ModuloContratadoMiddleware.PREFIJOS)

    def test_el_mapa_de_prefijos_apunta_a_rutas_reales(self):
        """Si alguien renombra una ruta en config/urls.py, el corte deja de aplicar
        y el módulo queda abierto sin que nada falle."""
        from django.urls import resolve

        from users.middleware import ModuloContratadoMiddleware
        for prefijo in ModuloContratadoMiddleware.PREFIJOS:
            try:
                resolve(prefijo)
            except Exception as exc:  # noqa: BLE001 - queremos el mensaje concreto
                self.fail(f'el prefijo {prefijo} no resuelve a ninguna vista: {exc}')

    def test_todos_los_modulos_declarados_tienen_prefijo(self):
        from users.middleware import ModuloContratadoMiddleware

        cubiertos = set(ModuloContratadoMiddleware.PREFIJOS.values())
        self.assertEqual(
            set(Organizacion.CODIGOS_MODULO) - cubiertos, set(),
            'hay un módulo que se cobra pero que nadie corta',
        )


class CoberturaDelAislamientoTests(TestCase):
    """Meta-test: que no se agregue un modelo de negocio sin aislar.

    Sin esto, el aislamiento se degrada en silencio: alguien crea un modelo
    nuevo, se olvida del mixin, y sus filas quedan visibles para todos.
    """

    # Modelos que legítimamente NO pertenecen a una organización.
    EXENTOS = {
        'users.User', 'users.Organizacion', 'users.Establecimiento',
        'portal.UserActivity', 'notifications.Notification', 'encuesta.EncuestaSemana',
    }
    APPS_DE_NEGOCIO = [
        'ai_modules', 'portal', 'library', 'calendar_red', 'messaging',
        'meetings', 'improvement_cycle', 'simce', 'eventos', 'evidencia',
    ]

    @staticmethod
    def _alcanza_una_raiz_aislada(Modelo, visitados=None):
        """¿Se llega a un modelo aislado siguiendo FKs, a cualquier profundidad?

        La cadena real tiene más de un salto: `PilotFeedback` → `AIChatMessage`
        → `AIAssistant`, y `RespuestaEstudiante` → `SesionEstudiante` → `Prueba`.
        Mirar un solo nivel daba falsos positivos.
        """
        from django.db import models as djm

        if visitados is None:
            visitados = set()
        if Modelo in visitados:
            return False
        visitados.add(Modelo)

        for campo in Modelo._meta.get_fields():
            if not isinstance(campo, (djm.ForeignKey, djm.OneToOneField)):
                continue
            padre = campo.related_model
            if padre is None or padre is Modelo:
                continue
            if issubclass(padre, ModeloDeOrganizacion):
                return True
            if CoberturaDelAislamientoTests._alcanza_una_raiz_aislada(padre, visitados):
                return True
        return False

    def test_todo_modelo_de_negocio_esta_aislado_o_cuelga_de_algo_aislado(self):
        from django.apps import apps as django_apps

        sin_aislar = []
        for app_label in self.APPS_DE_NEGOCIO:
            for Modelo in django_apps.get_app_config(app_label).get_models():
                etiqueta = f'{app_label}.{Modelo.__name__}'
                if etiqueta in self.EXENTOS or issubclass(Modelo, ModeloDeOrganizacion):
                    continue
                if not self._alcanza_una_raiz_aislada(Modelo):
                    sin_aislar.append(etiqueta)

        self.assertEqual(
            sorted(sin_aislar), [],
            'modelos sin organización y sin ningún ancestro aislado: sus filas son '
            'visibles para cualquier organización. Heredá de ModeloDeOrganizacion '
            'o agregalos a EXENTOS con su razón.',
        )
