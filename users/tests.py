"""
Tests del aislamiento por tenant.

Estos tests fijan el comportamiento que el refactor multi-tenant NO puede romper:
hoy el aislamiento vive en (username, tenant) + TenantAuthBackend, y cuando
`tenant` pase de CharField a FK contra `Organizacion` estos tests deben seguir
pasando sin cambios de semántica.
"""
from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from users.models import Establecimiento, Organizacion

User = get_user_model()


class TenantAuthBackendTests(TestCase):
    """El backend es el único punto donde se decide 'este usuario es de este tenant'."""

    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user(
            username='director', password='clave-a', tenant='colegio_a',
            role='DIRECTOR', establishment='TEMUCO',
        )
        cls.b = User.objects.create_user(
            username='director', password='clave-b', tenant='colegio_b',
            role='DIRECTOR', establishment='ANGOL',
        )

    def test_mismo_username_en_dos_tenants_son_usuarios_distintos(self):
        self.assertNotEqual(self.a.pk, self.b.pk)
        self.assertEqual(User.objects.filter(username='director').count(), 2)

    def test_autentica_dentro_de_su_tenant(self):
        user = authenticate(username='director', password='clave-a', tenant='colegio_a')
        self.assertEqual(user, self.a)

    def test_no_autentica_con_la_clave_del_otro_tenant(self):
        """La fuga más obvia: misma cuenta, clave del vecino."""
        self.assertIsNone(authenticate(username='director', password='clave-b', tenant='colegio_a'))

    def test_no_autentica_contra_un_tenant_ajeno(self):
        """Credenciales válidas de A no sirven para entrar como A en B."""
        self.assertIsNone(authenticate(username='director', password='clave-a', tenant='colegio_b'))

    def test_tenant_inexistente_no_autentica(self):
        self.assertIsNone(authenticate(username='director', password='clave-a', tenant='no_existe'))

    def test_sin_tenant_solo_pasa_staff(self):
        """Login sin tenant es la puerta de /admin/: un usuario normal no entra."""
        self.assertIsNone(authenticate(username='director', password='clave-a'))

        staff = User.objects.create_user(
            username='soporte', password='clave-staff', tenant='colegio_a', is_staff=True,
        )
        self.assertEqual(authenticate(username='soporte', password='clave-staff'), staff)

    def test_usuario_inactivo_no_autentica(self):
        """Dar de baja a alguien debe cerrarle el acceso, no solo ocultarle la UI."""
        self.a.is_active = False
        self.a.save(update_fields=['is_active'])
        self.assertIsNone(authenticate(username='director', password='clave-a', tenant='colegio_a'))

    def test_username_inexistente_no_revienta(self):
        self.assertIsNone(authenticate(username='fantasma', password='x', tenant='colegio_a'))

    def test_sin_username_devuelve_none(self):
        self.assertIsNone(authenticate(username=None, password='x', tenant='colegio_a'))


class UnicidadPorTenantTests(TestCase):
    def test_username_repetido_en_el_mismo_tenant_falla(self):
        User.objects.create_user(username='utp', password='x', tenant='colegio_a')
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username='utp', password='y', tenant='colegio_a')

    def test_username_repetido_en_otro_tenant_se_permite(self):
        User.objects.create_user(username='utp', password='x', tenant='colegio_a')
        User.objects.create_user(username='utp', password='y', tenant='colegio_b')
        self.assertEqual(User.objects.filter(username='utp').count(), 2)

    def test_un_usuario_sin_organizacion_no_cae_en_ninguna(self):
        """Antes el default era el slug de un cliente concreto: todo usuario creado
        sin especificar organización aterrizaba dentro de la suya."""
        user = User.objects.create_user(username='x', password='y')
        self.assertEqual(user.tenant, '')
        self.assertIsNone(user.organizacion)


class LoginPorPathTests(TestCase):
    """`/<tenant>/login/` — la ruta debe respetar el tenant de la URL, no el del formulario."""

    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user(username='director', password='clave-a', tenant='colegio_a')
        cls.b = User.objects.create_user(username='director', password='clave-b', tenant='colegio_b')

    def test_login_correcto_deja_el_tenant_en_sesion(self):
        resp = self.client.post(
            reverse('tenant-login', args=['colegio_a']),
            {'username': 'director', 'password': 'clave-a'},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.session['_auth_user_id'], str(self.a.pk))
        self.assertEqual(self.client.session['tenant'], 'colegio_a')

    def test_credenciales_de_otro_tenant_no_entran_por_esta_puerta(self):
        resp = self.client.post(
            reverse('tenant-login', args=['colegio_a']),
            {'username': 'director', 'password': 'clave-b'},
        )
        self.assertEqual(resp.status_code, 200)  # vuelve al formulario, no redirige
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_get_muestra_el_formulario(self):
        resp = self.client.get(reverse('tenant-login', args=['colegio_a']))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['tenant'], 'colegio_a')


class MigracionAOrganizacionesTests(TestCase):
    """La migración de datos 0006 — es la que toca filas reales, así que se prueba.

    Se invocan las funciones de la migración contra el registro de apps real: en
    este punto el modelo histórico y el actual coinciden, y así el test corre en
    la suite normal sin andamiaje de migraciones.
    """

    @staticmethod
    def _migracion():
        import importlib
        return importlib.import_module('users.migrations.0006_poblar_organizaciones')

    def _poblar(self):
        from django.apps import apps as global_apps
        self._migracion().poblar(global_apps, None)

    def _despoblar(self):
        from django.apps import apps as global_apps
        self._migracion().despoblar(global_apps, None)

    def setUp(self):
        User.objects.create_user(username='a1', password='x', tenant='colegio_demo', establishment='TEMUCO')
        User.objects.create_user(username='a2', password='x', tenant='colegio_demo', establishment='TEMUCO')
        User.objects.create_user(username='a3', password='x', tenant='colegio_demo', establishment='ANGOL')
        User.objects.create_user(username='b1', password='x', tenant='colegio_b', establishment='SANTIAGO')

    def test_crea_una_organizacion_por_tenant(self):
        """Una org por valor distinto de `tenant`, sin duplicar.

        Ojo: la BD de test NO está vacía — `ai_modules/0017_create_director_general.py`
        y `0021_set_director_admin_password.py` crean usuarios durante las
        migraciones. Por eso se comprueba la relación tenant→org, no un conteo.
        """
        self._poblar()
        tenants = set(User.objects.values_list('tenant', flat=True))
        self.assertEqual(set(Organizacion.objects.values_list('slug', flat=True)), tenants)
        self.assertIn('colegio_demo', tenants)
        self.assertIn('colegio_b', tenants)

    def test_crea_los_establecimientos_de_cada_organizacion_sin_mezclarlos(self):
        """Lo que importa no es cuántos hay, sino que ninguno cruce de organización."""
        self._poblar()
        demo = Organizacion.objects.get(slug='colegio_demo')
        otra = Organizacion.objects.get(slug='colegio_b')

        codigos_demo = set(demo.establecimientos.values_list('codigo', flat=True))
        codigos_otra = set(otra.establecimientos.values_list('codigo', flat=True))

        self.assertTrue({'ANGOL', 'TEMUCO'}.issubset(codigos_demo))
        self.assertEqual(codigos_otra, {'SANTIAGO'})
        self.assertEqual(codigos_demo & codigos_otra, set(), 'un establecimiento cruzó de organización')

    def test_cada_establecimiento_corresponde_a_un_usuario_real_de_esa_organizacion(self):
        """No se inventan sedes: cada una sale de un `User.establishment` existente."""
        self._poblar()
        for est in Establecimiento.objects.all():
            self.assertTrue(
                User.objects.filter(tenant=est.organizacion.slug, establishment=est.codigo).exists(),
                f'{est.codigo} no corresponde a ningún usuario de {est.organizacion.slug}',
            )

    def test_asigna_las_fk_a_cada_usuario(self):
        self._poblar()
        a1 = User.objects.get(username='a1', tenant='colegio_demo')
        b1 = User.objects.get(username='b1', tenant='colegio_b')

        self.assertEqual(a1.organizacion.slug, 'colegio_demo')
        self.assertEqual(a1.establecimiento.codigo, 'TEMUCO')
        self.assertEqual(b1.organizacion.slug, 'colegio_b')
        self.assertEqual(b1.establecimiento.codigo, 'SANTIAGO')

    def test_no_deja_ningun_usuario_sin_organizacion(self):
        self._poblar()
        self.assertEqual(User.objects.filter(organizacion__isnull=True).count(), 0)

    def test_el_equipo_red_queda_marcado_como_central(self):
        User.objects.create_user(username='red1', password='x', tenant='colegio_demo', establishment='RED')
        self._poblar()
        red = Establecimiento.objects.get(organizacion__slug='colegio_demo', codigo='RED')
        self.assertTrue(red.es_equipo_central)
        self.assertTrue(User.objects.get(username='red1').is_red_team)

    def test_es_idempotente(self):
        """Correrla dos veces no duplica nada — se re-ejecuta en cada deploy sin miedo."""
        self._poblar()
        orgs, ests = Organizacion.objects.count(), Establecimiento.objects.count()

        self._poblar()

        self.assertEqual(Organizacion.objects.count(), orgs)
        self.assertEqual(Establecimiento.objects.count(), ests)

    def test_no_pisa_una_asignacion_manual_previa(self):
        """Si alguien ya movió un usuario a mano, la migración lo respeta."""
        self._poblar()
        otra_org = Organizacion.objects.get(slug='colegio_b')
        especial = Establecimiento.objects.create(
            organizacion=otra_org, codigo='ESPECIAL', nombre='Sede especial',
        )
        a1 = User.objects.get(username='a1')
        a1.establecimiento = especial
        a1.save(update_fields=['establecimiento'])

        self._poblar()

        self.assertEqual(User.objects.get(username='a1').establecimiento, especial)

    def test_es_reversible(self):
        self._poblar()
        self._despoblar()

        self.assertEqual(Organizacion.objects.count(), 0)
        self.assertEqual(Establecimiento.objects.count(), 0)
        self.assertEqual(User.objects.filter(organizacion__isnull=False).count(), 0)
        # Los CharFields nunca se tocaron: el estado previo queda intacto.
        self.assertEqual(User.objects.get(username='a1').tenant, 'colegio_demo')
        self.assertEqual(User.objects.get(username='a1').establishment, 'TEMUCO')

    def test_usuario_sin_establecimiento_igual_recibe_organizacion(self):
        User.objects.create_user(username='sin_est', password='x', tenant='colegio_demo', establishment='')
        self._poblar()
        user = User.objects.get(username='sin_est')
        self.assertEqual(user.organizacion.slug, 'colegio_demo')
        self.assertIsNone(user.establecimiento)


class ConsolidacionDeDuplicadosTests(TestCase):
    """Migración 0007 — `unique_together` no distingue 'TEMUCO' de 'temuco'.

    Caso real: la base traía ambas variantes y quedaron como dos sedes.
    """

    @staticmethod
    def _consolidar():
        import importlib
        from django.apps import apps as global_apps
        mod = importlib.import_module('users.migrations.0007_consolidar_establecimientos_duplicados')
        mod.consolidar(global_apps, None)

    def setUp(self):
        self.org = Organizacion.objects.create(slug='org_x', nombre='Org X')
        # `save()` normaliza, así que para reproducir el estado sucio hay que
        # escribir el código en minúsculas saltándose el modelo.
        self.canonico = Establecimiento.objects.create(organizacion=self.org, codigo='TEMUCO', nombre='Temuco')
        # El duplicado nace con un código provisional y se renombra por UPDATE:
        # `save()` lo normalizaría a 'TEMUCO' y chocaría con el unique_together.
        self.duplicado = Establecimiento.objects.create(
            organizacion=self.org, codigo='TEMUCO_SUCIO', nombre='Temuco',
        )
        Establecimiento.objects.filter(pk=self.duplicado.pk).update(codigo='temuco')
        self.duplicado.refresh_from_db()

    def test_el_modelo_normaliza_el_codigo_al_guardar(self):
        est = Establecimiento.objects.create(organizacion=self.org, codigo='  angol  ', nombre='Angol')
        self.assertEqual(est.codigo, 'ANGOL')

    def test_consolida_las_dos_sedes_en_una(self):
        self._consolidar()
        sedes = Establecimiento.objects.filter(organizacion=self.org, codigo__iexact='TEMUCO')
        self.assertEqual(sedes.count(), 1)
        self.assertEqual(sedes.first().codigo, 'TEMUCO')

    def test_los_usuarios_del_duplicado_se_mudan_al_canonico(self):
        user = User.objects.create_user(
            username='testuser', password='x', tenant='org_x', establishment='temuco',
        )
        user.establecimiento = self.duplicado
        user.save(update_fields=['establecimiento'])

        self._consolidar()

        user.refresh_from_db()
        self.assertEqual(user.establecimiento_id, self.canonico.pk)
        self.assertEqual(user.establishment, 'TEMUCO', 'el CharField también se normaliza')
        self.assertFalse(Establecimiento.objects.filter(pk=self.duplicado.pk).exists())

    def test_no_pierde_el_flag_de_equipo_central_del_duplicado(self):
        Establecimiento.objects.filter(pk=self.duplicado.pk).update(es_equipo_central=True)
        self._consolidar()
        self.assertTrue(Establecimiento.objects.get(pk=self.canonico.pk).es_equipo_central)

    def test_no_pierde_el_rbd_que_solo_tenia_el_duplicado(self):
        Establecimiento.objects.filter(pk=self.duplicado.pk).update(rbd='12345')
        self._consolidar()
        self.assertEqual(Establecimiento.objects.get(pk=self.canonico.pk).rbd, '12345')

    def test_no_toca_sedes_de_otra_organizacion_con_el_mismo_codigo(self):
        """Dos organizaciones pueden tener una sede 'TEMUCO' cada una."""
        otra = Organizacion.objects.create(slug='org_y', nombre='Org Y')
        suya = Establecimiento.objects.create(organizacion=otra, codigo='TEMUCO', nombre='Temuco')

        self._consolidar()

        self.assertTrue(Establecimiento.objects.filter(pk=suya.pk).exists())
        self.assertEqual(Establecimiento.objects.filter(codigo='TEMUCO').count(), 2)

    def test_es_idempotente(self):
        self._consolidar()
        n = Establecimiento.objects.count()
        self._consolidar()
        self.assertEqual(Establecimiento.objects.count(), n)


class PropiedadesDeUsuarioTests(TestCase):
    """Reglas de negocio que hoy cuelgan de CharFields y que el refactor va a mover."""

    def test_is_red_team_por_rol_o_por_establecimiento(self):
        por_rol = User.objects.create_user(username='r1', password='x', role='RED', establishment='TEMUCO')
        por_est = User.objects.create_user(username='r2', password='x', role='DIRECTOR', establishment='RED')
        normal = User.objects.create_user(username='r3', password='x', role='DIRECTOR', establishment='TEMUCO')
        self.assertTrue(por_rol.is_red_team)
        self.assertTrue(por_est.is_red_team)
        self.assertFalse(normal.is_red_team)

    def test_quien_aprueba_circulares(self):
        for rol in ('REPRESENTANTE', 'DIRECTOR', 'UTP'):
            user = User.objects.create_user(username=f'ok-{rol}', password='x', role=rol)
            self.assertTrue(user.can_approve_circulars, rol)

        for rol in ('INSPECTOR', 'CONVIVENCIA'):
            user = User.objects.create_user(username=f'no-{rol}', password='x', role=rol)
            self.assertFalse(user.can_approve_circulars, rol)

    def test_staff_aprueba_circulares_aunque_su_rol_no_lo_permita(self):
        user = User.objects.create_user(username='s', password='x', role='INSPECTOR', is_staff=True)
        self.assertTrue(user.can_approve_circulars)
