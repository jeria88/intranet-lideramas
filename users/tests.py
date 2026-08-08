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
        """`archive_sfa_users` desactiva usuarios en cada deploy: debe cerrar el acceso."""
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

    def test_tenant_por_defecto_es_sfa(self):
        """Default histórico. Si el refactor lo cambia, este test debe cambiarse a conciencia."""
        self.assertEqual(User.objects.create_user(username='x', password='y').tenant, 'sfa')


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
