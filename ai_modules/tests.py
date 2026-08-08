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
            username='utp_temuco', password='x', tenant='sfa',
            role='UTP', establishment='TEMUCO',
        )
        cls.utp_angol = User.objects.create_user(
            username='utp_angol', password='x', tenant='sfa',
            role='UTP', establishment='ANGOL',
        )
        cls.director_temuco = User.objects.create_user(
            username='dir_temuco', password='x', tenant='sfa',
            role='DIRECTOR', establishment='TEMUCO',
        )
        cls.soporte = User.objects.create_user(
            username='soporte', password='x', tenant='sfa',
            role='INSPECTOR', establishment='ANGOL', is_staff=True,
        )

        cls.asistente_utp_temuco = AIAssistant.objects.create(
            slug='utp-temuco', name='UTP Temuco', profile_role='UTP',
            establishment='TEMUCO', image_name='asistente-utp.jpg',
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
        cls.asistente = AIAssistant.objects.create(
            slug='utp-temuco', name='UTP Temuco', profile_role='UTP',
            establishment='TEMUCO', image_name='asistente-utp.jpg',
            is_chat_enabled=True, is_active=True,
        )
        cls.ajeno = User.objects.create_user(
            username='ajeno', password='clave', tenant='sfa',
            role='DIRECTOR', establishment='ANGOL',
        )
        cls.propio = User.objects.create_user(
            username='propio', password='clave', tenant='sfa',
            role='UTP', establishment='TEMUCO',
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


class SlugDeAsistenteTests(TestCase):
    """El slug `rol-establecimiento` es la convención de la que hoy cuelga el RAG.

    `ai_modules/utils.py` parsea `slug.split('-')` para filtrar chunks por rol y
    establecimiento. Es acoplamiento por convención de nombre, y el refactor lo
    va a reemplazar por FKs — este test documenta el contrato vigente.
    """

    def test_el_slug_codifica_rol_y_establecimiento(self):
        asistente = AIAssistant.objects.create(
            slug='inspector-lautaro', name='Inspector Lautaro',
            profile_role='INSPECTOR', establishment='LAUTARO',
            image_name='asistente-inspector.jpg',
        )
        rol, establecimiento = asistente.slug.split('-')[:2]
        self.assertEqual(rol.upper(), asistente.profile_role)
        self.assertEqual(establecimiento.upper(), asistente.establishment)

    def test_el_slug_es_unico(self):
        AIAssistant.objects.create(
            slug='utp-temuco', name='A', profile_role='UTP',
            establishment='TEMUCO', image_name='x.jpg',
        )
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            AIAssistant.objects.create(
                slug='utp-temuco', name='B', profile_role='UTP',
                establishment='TEMUCO', image_name='x.jpg',
            )

    def test_use_cases_se_parsea_por_lineas_ignorando_vacias(self):
        asistente = AIAssistant.objects.create(
            slug='utp-angol', name='UTP', profile_role='UTP',
            establishment='ANGOL', image_name='x.jpg',
            use_cases='  Caso uno  \n\n Caso dos \n   \n',
        )
        self.assertEqual(asistente.get_use_cases_list(), ['Caso uno', 'Caso dos'])
