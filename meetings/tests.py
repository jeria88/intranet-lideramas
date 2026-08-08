"""Tests del pipeline de actas: webhook de Daily.co → worker → acta.

Este pipeline no tiene usuario en ningún tramo — lo dispara Daily.co y lo procesa
un worker externo con `X-Internal-API-Key`. Por eso es el primero que rompe un
aislamiento por request: sin usuario no hay organización, y un manager filtrado
devuelve cero filas. La grabación no se procesa, el acta no llega, y nadie ve un
error: la reunión simplemente se queda en 'pendiente' para siempre.
"""
import json

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from meetings.models import MeetingBooking, MeetingRoom
from users.models import Organizacion, User

CLAVE = 'clave-de-prueba'


@override_settings(INTERNAL_API_KEY=CLAVE)
class ApiInternaDelWorkerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organizacion.objects.create(slug='colegio_x', nombre='Colegio X')
        cls.quien_reservo = User.objects.create_user(
            username='director', password='x', tenant='colegio_x', organizacion=cls.org,
        )
        cls.sala = MeetingRoom.objects.create(
            name='Sala 1', slug='sala-1', daily_identifier='sala-1', room_type='daily',
            organizacion=cls.org,
        )
        cls.reserva = MeetingBooking.objects.create(
            room=cls.sala, organizacion=cls.org, booked_by=cls.quien_reservo,
            scheduled_at=timezone.now(), duration_minutes=60,
            recording_url='https://ejemplo/grabacion.mp4',
            processing_status='pendiente',
        )

    def test_el_worker_ve_las_reuniones_pendientes_sin_estar_logueado(self):
        """La regresión concreta: con el manager filtrado esto devolvía lista vacía."""
        resp = self.client.get(
            reverse('meetings:api_pending_meetings'), HTTP_X_INTERNAL_API_KEY=CLAVE,
        )
        self.assertEqual(resp.status_code, 200)
        datos = json.loads(resp.content)
        pendientes = datos if isinstance(datos, list) else datos.get('meetings', datos.get('data', []))
        self.assertEqual(len(pendientes), 1, 'el worker no encuentra la reunión pendiente')

    def test_sin_la_clave_no_pasa(self):
        resp = self.client.get(reverse('meetings:api_pending_meetings'))
        self.assertEqual(resp.status_code, 401)

    def test_con_clave_incorrecta_no_pasa(self):
        resp = self.client.get(
            reverse('meetings:api_pending_meetings'), HTTP_X_INTERNAL_API_KEY='otra',
        )
        self.assertEqual(resp.status_code, 401)

    def test_el_worker_marca_en_proceso_sin_estar_logueado(self):
        resp = self.client.post(
            reverse('meetings:api_start_processing', args=[self.reserva.pk]),
            HTTP_X_INTERNAL_API_KEY=CLAVE,
        )
        self.assertEqual(resp.status_code, 200)
        self.reserva.refresh_from_db()
        self.assertEqual(self.reserva.processing_status, 'procesando')

    def test_el_worker_entrega_el_acta_sin_estar_logueado(self):
        resp = self.client.post(
            reverse('meetings:api_update_meeting', args=[self.reserva.pk]),
            data=json.dumps({
                'transcript': 'Texto transcrito',
                'acta': 'Acta generada',
                'acuerdos_text': 'Acuerdo 1',
            }),
            content_type='application/json',
            HTTP_X_INTERNAL_API_KEY=CLAVE,
        )
        self.assertEqual(resp.status_code, 200)

        self.reserva.refresh_from_db()
        self.assertEqual(self.reserva.processing_status, 'completado')
        self.assertEqual(self.reserva.acta, 'Acta generada')

    def test_una_reunion_de_otra_organizacion_tambien_se_procesa(self):
        """El worker es del proveedor y atiende a todos los clientes: acotar su
        alcance a una organización dejaría al resto sin actas."""
        otra = Organizacion.objects.create(slug='colegio_y', nombre='Colegio Y')
        sala = MeetingRoom.objects.create(
            name='Sala Y', slug='sala-y', daily_identifier='sala-y', room_type='daily',
            organizacion=otra,
        )
        MeetingBooking.objects.create(
            room=sala, organizacion=otra, booked_by=self.quien_reservo,
            scheduled_at=timezone.now(), duration_minutes=60,
            recording_url='https://ejemplo/otra.mp4', processing_status='pendiente',
        )

        resp = self.client.get(
            reverse('meetings:api_pending_meetings'), HTTP_X_INTERNAL_API_KEY=CLAVE,
        )
        datos = json.loads(resp.content)
        pendientes = datos if isinstance(datos, list) else datos.get('meetings', datos.get('data', []))
        self.assertEqual(len(pendientes), 2)


class CuotaDeReunionesTests(TestCase):
    """4 reuniones/mes por perfil, salvo el equipo central."""

    def test_el_equipo_central_no_tiene_cuota(self):
        from users.models import Establecimiento, User

        org = Organizacion.objects.create(slug='colegio_z', nombre='Colegio Z')
        central = Establecimiento.objects.create(
            organizacion=org, codigo='CENTRAL', nombre='Central', es_equipo_central=True,
        )
        normal = Establecimiento.objects.create(
            organizacion=org, codigo='SEDE', nombre='Sede',
        )

        del_central = User.objects.create_user(
            username='coordinador', password='x', tenant='colegio_z',
            organizacion=org, establecimiento=central,
        )
        de_sede = User.objects.create_user(
            username='dir_sede', password='x', tenant='colegio_z',
            organizacion=org, establecimiento=normal,
        )

        self.assertTrue(del_central.is_red_team)
        self.assertFalse(de_sede.is_red_team)
