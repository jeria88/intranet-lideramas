"""
Tests del control de acceso a los asistentes IA.

`_check_assistant_access` (`ai_modules/views.py`) es hoy el único punto que decide
si un usuario puede abrir un asistente, y lo hace comparando dos CharFields:
`user.role == assistant.profile_role` y `user.establishment == assistant.establishment`.

Cuando el refactor convierta `establishment` en FK a una tabla, la SEMÁNTICA que
estos tests fijan debe seguir siendo la misma:
  - staff entra a todo,
  - el rol tiene que coincidir,
  - un asistente sin establecimiento es transversal,
  - un asistente con establecimiento solo lo ve ese establecimiento.
"""
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from ai_modules.models import AIAssistant
from ai_modules.views import _check_assistant_access

User = get_user_model()


class ControlDeAccesoAAsistentesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.utp_temuco = User.objects.create_user(
            username='utp_norte', password='x', tenant='colegio_demo',
            role='UTP', establishment='SEDE_NORTE',
        )
        cls.utp_angol = User.objects.create_user(
            username='utp_sur', password='x', tenant='colegio_demo',
            role='UTP', establishment='SEDE_SUR',
        )
        cls.director_temuco = User.objects.create_user(
            username='dir_norte', password='x', tenant='colegio_demo',
            role='DIRECTOR', establishment='SEDE_NORTE',
        )
        cls.soporte = User.objects.create_user(
            username='soporte', password='x', tenant='colegio_demo',
            role='INSPECTOR', establishment='SEDE_SUR', is_staff=True,
        )

        cls.asistente_utp_temuco = AIAssistant.objects.create(
            slug='demo-utp-norte', name='UTP Sede Norte', profile_role='UTP',
            establishment='SEDE_NORTE', image_name='asistente-utp.jpg',
        )
        cls.asistente_transversal = AIAssistant.objects.create(
            slug='red', name='Asistente RED', profile_role='UTP',
            establishment='', image_name='asistente-utp.jpg',
        )

    def _request(self, user):
        request = RequestFactory().get('/ia/')
        request.user = user
        return request

    def test_rol_y_establecimiento_correctos_entran(self):
        self.assertTrue(_check_assistant_access(self._request(self.utp_temuco), self.asistente_utp_temuco))

    def test_mismo_rol_en_otro_establecimiento_no_entra(self):
        """La fuga que el refactor multi-tenant tiene que preservar cerrada."""
        self.assertFalse(_check_assistant_access(self._request(self.utp_angol), self.asistente_utp_temuco))

    def test_otro_rol_en_el_mismo_establecimiento_no_entra(self):
        self.assertFalse(_check_assistant_access(self._request(self.director_temuco), self.asistente_utp_temuco))

    def test_asistente_sin_establecimiento_es_transversal_dentro_del_rol(self):
        self.assertTrue(_check_assistant_access(self._request(self.utp_temuco), self.asistente_transversal))
        self.assertTrue(_check_assistant_access(self._request(self.utp_angol), self.asistente_transversal))

    def test_asistente_transversal_sigue_exigiendo_el_rol(self):
        self.assertFalse(_check_assistant_access(self._request(self.director_temuco), self.asistente_transversal))

    def test_staff_entra_a_cualquier_asistente(self):
        request = self._request(self.soporte)
        self.assertTrue(_check_assistant_access(request, self.asistente_utp_temuco))
        self.assertTrue(_check_assistant_access(request, self.asistente_transversal))


class VistasDeAsistenteTests(TestCase):
    """El acceso denegado no puede ser un 403 crudo: se responde con una página."""

    @classmethod
    def setUpTestData(cls):
        from users.models import Organizacion

        # Dentro de un request el manager filtra por la organización del usuario:
        # un asistente sin organización no lo ve nadie, ni siquiera quien tiene el
        # rol correcto. Por eso acá todo pertenece a la misma organización.
        cls.org = Organizacion.objects.create(slug='colegio_demo', nombre='Colegio Demo')
        cls.asistente = AIAssistant.objects.create(
            slug='demo-utp-norte', name='UTP Sede Norte', profile_role='UTP',
            establishment='SEDE_NORTE', image_name='asistente-utp.jpg',
            is_chat_enabled=True, is_active=True, organizacion=cls.org,
        )
        cls.ajeno = User.objects.create_user(
            username='ajeno', password='clave', tenant='colegio_demo',
            role='DIRECTOR', establishment='SEDE_SUR', organizacion=cls.org,
        )
        cls.propio = User.objects.create_user(
            username='propio', password='clave', tenant='colegio_demo',
            role='UTP', establishment='SEDE_NORTE', organizacion=cls.org,
        )

    def test_anonimo_es_redirigido_al_login(self):
        resp = self.client.get(reverse('ai_modules:conversation_list', args=[self.asistente.slug]))
        self.assertIn(resp.status_code, (301, 302))

    def test_usuario_sin_permiso_recibe_pagina_de_no_acceso_no_un_403(self):
        self.client.force_login(self.ajeno)
        resp = self.client.get(reverse('ai_modules:conversation_list', args=[self.asistente.slug]))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'ai_modules/no_access.html')

    def test_usuario_con_permiso_abre_el_chat(self):
        self.client.force_login(self.propio)
        resp = self.client.get(reverse('ai_modules:conversation_list', args=[self.asistente.slug]))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'ai_modules/chat_app.html')

    def test_asistente_inactivo_da_404(self):
        self.asistente.is_active = False
        self.asistente.save(update_fields=['is_active'])
        self.client.force_login(self.propio)
        resp = self.client.get(reverse('ai_modules:conversation_list', args=[self.asistente.slug]))
        self.assertEqual(resp.status_code, 404)

    def test_un_asistente_de_otra_organizacion_no_existe_para_este_usuario(self):
        """Sin tocar la vista: el manager filtra por el alcance del request, así que
        el asistente del vecino ni siquiera se encuentra."""
        from users.models import Organizacion

        otra = Organizacion.objects.create(slug='colegio_vecino', nombre='Colegio Vecino')
        ajeno = AIAssistant.objects.create(
            slug='vecino-utp-sede', name='UTP del vecino', profile_role='UTP',
            establishment='SEDE_NORTE', image_name='x.jpg',
            is_chat_enabled=True, is_active=True, organizacion=otra,
        )

        self.client.force_login(self.propio)
        resp = self.client.get(reverse('ai_modules:conversation_list', args=[ajeno.slug]))
        self.assertEqual(resp.status_code, 404)

    def test_un_asistente_sin_organizacion_no_es_visible_en_la_vista(self):
        huerfano = AIAssistant.objects.create(
            slug='huerfano', name='Huérfano', profile_role='UTP',
            establishment='SEDE_NORTE', image_name='x.jpg',
            is_chat_enabled=True, is_active=True,
        )
        self.client.force_login(self.propio)
        resp = self.client.get(reverse('ai_modules:conversation_list', args=[huerfano.slug]))
        self.assertEqual(resp.status_code, 404)


class DespachoDeMotorTests(TestCase):
    """Qué motor responde. Antes se decidía por el sufijo del slug.

    Ese acoplamiento al nombre se rompió solo: al prefijar los slugs por
    organización (`<org>-<rol>-<sede>`) ningún asistente termina en `-v3`, así
    que todos habrían pasado a responder con v1 sin que nada lo avisara.
    """

    def _asistente(self, **extra):
        datos = dict(
            slug='demo-utp-sede', name='UTP', profile_role='UTP',
            establishment='SEDE', image_name='x.jpg',
        )
        datos.update(extra)
        return AIAssistant.objects.create(**datos)

    def test_el_motor_por_defecto_es_v3(self):
        """v3 es el único con pipeline de citas verificadas, que es lo que ataca
        la alucinación de artículos normativos."""
        self.assertEqual(self._asistente().motor, 'v3')

    def test_despacha_al_motor_configurado(self):
        from unittest.mock import patch

        from ai_modules.motores import responder

        for motor, objetivo in (
            ('v1', 'ai_modules.motores.call_deepseek_ai'),
            ('v2', 'ai_modules.motores.call_ai_v2'),
            ('v3', 'ai_modules.motores.call_ai_v3'),
        ):
            with self.subTest(motor=motor):
                asistente = self._asistente(slug=f'demo-{motor}', motor=motor)
                with patch(objetivo, return_value=f'respuesta {motor}') as llamado:
                    salida = responder(asistente, [], 'hola')
                llamado.assert_called_once()
                self.assertEqual(salida, f'respuesta {motor}')

    def test_el_sufijo_del_slug_ya_no_decide(self):
        """Un slug que termina en '-v2' con motor v3 responde con v3."""
        from unittest.mock import patch

        from ai_modules.motores import responder

        asistente = self._asistente(slug='demo-utp-v2', motor='v3')
        with patch('ai_modules.motores.call_ai_v3', return_value='v3') as v3:
            responder(asistente, [], 'hola')
        v3.assert_called_once()

    def test_un_motor_desconocido_cae_al_por_defecto(self):
        """Un valor raro en la BD no puede dejar al usuario sin respuesta."""
        from unittest.mock import patch

        from ai_modules.motores import responder

        asistente = self._asistente(motor='v9')
        with patch('ai_modules.motores.call_ai_v3', return_value='ok') as v3:
            self.assertEqual(responder(asistente, [], 'hola'), 'ok')
        v3.assert_called_once()


class SlugDeAsistenteTests(TestCase):
    """El slug ya NO codifica el alcance del RAG.

    Antes `ai_modules/utils.py` hacía `slug.split('-')` para sacar rol y
    establecimiento, con `else 'temuco'` de reserva — un default global cuyo valor
    era el establecimiento de un cliente concreto. Ahora el slug lleva prefijo de
    organización (`<org>-<rol>-<sede>`) y el alcance sale de los campos.
    """

    def test_el_alcance_del_rag_sale_de_los_campos_no_del_slug(self):
        asistente = AIAssistant.objects.create(
            slug='colegio-andes-inspector-sede_norte', name='Inspector Sede Norte',
            profile_role='INSPECTOR', establishment='SEDE_NORTE',
            image_name='asistente-inspector.jpg',
        )
        # Parsear el slug por posición daría 'colegio' como rol: por eso ya no se hace.
        self.assertNotEqual(asistente.slug.split('-')[0].upper(), asistente.profile_role)
        self.assertEqual(asistente.profile_role, 'INSPECTOR')
        self.assertEqual(asistente.establishment, 'SEDE_NORTE')

    def test_un_asistente_sin_establecimiento_no_hereda_el_de_otro_cliente(self):
        """La regresión concreta: el default `'temuco'` que había en utils.py."""
        asistente = AIAssistant.objects.create(
            slug='transversal', name='Transversal', profile_role='UTP',
            establishment='', image_name='x.jpg',
        )
        self.assertEqual(asistente.establishment, '')

    def test_el_slug_es_unico(self):
        AIAssistant.objects.create(
            slug='demo-utp-norte', name='A', profile_role='UTP',
            establishment='SEDE_NORTE', image_name='x.jpg',
        )
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            AIAssistant.objects.create(
                slug='demo-utp-norte', name='B', profile_role='UTP',
                establishment='SEDE_NORTE', image_name='x.jpg',
            )

    def test_use_cases_se_parsea_por_lineas_ignorando_vacias(self):
        asistente = AIAssistant.objects.create(
            slug='utp-angol', name='UTP', profile_role='UTP',
            establishment='SEDE_SUR', image_name='x.jpg',
            use_cases='  Caso uno  \n\n Caso dos \n   \n',
        )
        self.assertEqual(asistente.get_use_cases_list(), ['Caso uno', 'Caso dos'])
