"""Tests del CRM comercial.

Se prueban las tres cosas que este dominio ya rompió en los otros dos CRMs del
ecosistema y que se copiaron acá justamente para no repetirlas: el criterio de
deduplicación, la asignación de etapa inicial y el scoring.
"""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from crm.models import Ciudad, Contacto, Etapa, Lead, Target, Vertical, normalizar_nombre

User = get_user_model()


def _target(vertical='Educación', ciudad='Temuco'):
    v, _ = Vertical.objects.get_or_create(
        nombre=vertical, defaults={'slug': vertical.lower()[:8], 'activa': True},
    )
    c, _ = Ciudad.objects.get_or_create(nombre=ciudad)
    t, _ = Target.objects.get_or_create(vertical=v, ciudad=c)
    t.crear_etapas_por_defecto()
    return t


class NormalizacionTests(TestCase):
    def test_ignora_tildes_mayusculas_y_puntuacion(self):
        self.assertEqual(
            normalizar_nombre('Colegio San José  S.A.'),
            normalizar_nombre('colegio san jose sa'),
        )

    def test_el_guion_separa_pero_el_punto_no(self):
        """Los dos casos tiran para lados opuestos y hay que atender ambos."""
        self.assertEqual(normalizar_nombre('Colegio-San José'), 'colegio san jose')
        self.assertEqual(normalizar_nombre('Colegio S.A.'), 'colegio sa')

    def test_nombres_distintos_no_colapsan(self):
        self.assertNotEqual(normalizar_nombre('Liceo Norte'), normalizar_nombre('Liceo Sur'))

    def test_tolera_vacio(self):
        self.assertEqual(normalizar_nombre(''), '')
        self.assertEqual(normalizar_nombre(None), '')


class DeduplicacionTests(TestCase):
    def setUp(self):
        self.target = _target()

    def test_el_mismo_colegio_escrito_distinto_es_un_solo_lead(self):
        Lead.objects.create(target=self.target, nombre='Colegio San José')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Lead.objects.create(target=self.target, nombre='colegio san jose')

    def test_el_hash_no_incluye_el_telefono(self):
        """Incluirlo parece más preciso y es peor: la misma escuela de dos fuentes,
        una con teléfono y otra sin él, dejaría de colisionar."""
        primero = Lead.objects.create(
            target=self.target, nombre='Escuela Los Robles', telefono='+56912345678',
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Lead.objects.create(target=self.target, nombre='Escuela Los Robles')

        self.assertEqual(Lead.objects.filter(nombre__icontains='Robles').count(), 1)
        self.assertEqual(primero.telefono, '+56912345678')

    def test_dos_colegios_distintos_conviven(self):
        Lead.objects.create(target=self.target, nombre='Liceo Norte')
        Lead.objects.create(target=self.target, nombre='Liceo Sur')
        self.assertEqual(Lead.objects.count(), 2)


class EtapaInicialTests(TestCase):
    """El bug que en ARQlead dejó 20 leads invisibles: `stage_id` NULL y el kanban
    agrupa por etapa, así que no aparecían en ninguna columna ni daban error."""

    def setUp(self):
        self.target = _target()

    def test_un_lead_nuevo_cae_en_la_primera_etapa(self):
        lead = Lead.objects.create(target=self.target, nombre='Colegio A')
        self.assertIsNotNone(lead.etapa)
        self.assertEqual(lead.etapa.orden, 1)

    def test_la_etapa_inicial_se_resuelve_por_orden_no_por_nombre(self):
        """Las etapas se renombran desde la UI: buscar 'nuevo' por nombre rompe."""
        primera = self.target.etapas.order_by('orden').first()
        primera.nombre = 'sin trabajar todavía'
        primera.save(update_fields=['nombre'])

        lead = Lead.objects.create(target=self.target, nombre='Colegio B')
        self.assertEqual(lead.etapa, primera)

    def test_ningun_lead_queda_sin_etapa(self):
        for i in range(5):
            Lead.objects.create(target=self.target, nombre=f'Colegio {i}')
        self.assertEqual(Lead.objects.filter(etapa__isnull=True).count(), 0)

    def test_una_etapa_explicita_gana(self):
        ganado = self.target.etapas.get(orden=5)
        lead = Lead.objects.create(target=self.target, nombre='Colegio C', etapa=ganado)
        self.assertEqual(lead.etapa, ganado)

    def test_crear_etapas_es_idempotente(self):
        n = self.target.etapas.count()
        self.target.crear_etapas_por_defecto()
        self.assertEqual(self.target.etapas.count(), n)


class ScoreTests(TestCase):
    def setUp(self):
        self.target = _target()

    def test_sin_datos_de_contacto_es_cero(self):
        self.assertEqual(Lead.objects.create(target=self.target, nombre='Sin datos').score, 0)

    def test_completo_es_seis(self):
        lead = Lead.objects.create(
            target=self.target, nombre='Completo',
            email='a@b.cl', telefono='+56912345678',
            web='https://ejemplo.cl', direccion='Calle 1',
        )
        self.assertEqual(lead.score, 6)

    def test_email_y_telefono_pesan_mas_que_web_y_direccion(self):
        contactable = Lead.objects.create(
            target=self.target, nombre='Contactable', email='a@b.cl', telefono='+569123',
        )
        vitrina = Lead.objects.create(
            target=self.target, nombre='Vitrina', web='https://x.cl', direccion='Calle 2',
        )
        self.assertGreater(contactable.score, vitrina.score)

    def test_se_recalcula_al_completar_datos(self):
        lead = Lead.objects.create(target=self.target, nombre='Incompleto')
        lead.email = 'a@b.cl'
        lead.save()
        self.assertEqual(lead.score, 2)


class ContactoTests(TestCase):
    def setUp(self):
        self.target = _target()
        self.lead = Lead.objects.create(target=self.target, nombre='Colegio X')
        self.franco = User.objects.create_user(username='franco', password='x', is_staff=True)

    def test_registrar_un_envio_actualiza_el_ultimo_contacto_del_lead(self):
        """Sin esto el kanban miente sobre cuándo fue el último toque, que es el
        dato con el que se prioriza el día."""
        self.assertIsNone(self.lead.ultimo_contacto)

        contacto = Contacto.objects.create(
            lead=self.lead, canal='whatsapp', enviado='Hola, te escribo porque…',
            enviado_por=self.franco,
        )

        self.lead.refresh_from_db()
        self.assertEqual(self.lead.ultimo_contacto, contacto.fecha)

    def test_sin_respuesta_no_cuenta_como_respondido(self):
        contacto = Contacto.objects.create(lead=self.lead, enviado='Hola')
        self.assertFalse(contacto.respondio)

    def test_una_respuesta_en_blanco_tampoco_cuenta(self):
        contacto = Contacto.objects.create(lead=self.lead, enviado='Hola', respuesta='   ')
        self.assertFalse(contacto.respondio)

    def test_con_respuesta_cuenta(self):
        contacto = Contacto.objects.create(
            lead=self.lead, enviado='Hola', respuesta='Me interesa, cuéntame más',
        )
        self.assertTrue(contacto.respondio)

    def test_el_historial_queda_ordenado_del_mas_reciente(self):
        Contacto.objects.create(lead=self.lead, enviado='Primero')
        Contacto.objects.create(lead=self.lead, enviado='Segundo')
        self.assertEqual(self.lead.contactos.first().enviado, 'Segundo')


class AccesoAlCrmTests(TestCase):
    """El CRM es del proveedor, no del cliente: no lo ve un usuario cualquiera."""

    def setUp(self):
        self.target = _target()
        self.lead = Lead.objects.create(target=self.target, nombre='Colegio X')

    def test_un_anonimo_no_entra(self):
        resp = self.client.get('/crm/')
        self.assertIn(resp.status_code, (301, 302))

    def test_un_usuario_normal_no_entra(self):
        User.objects.create_user(username='profe', password='clave', tenant='colegio_a')
        self.client.login(username='profe', password='clave')
        resp = self.client.get('/crm/')
        self.assertIn(resp.status_code, (301, 302))

    def test_el_staff_ve_el_tablero(self):
        User.objects.create_user(username='franco', password='clave', is_staff=True)
        self.client.login(username='franco', password='clave')
        resp = self.client.get('/crm/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Conversaciones hoy')

    def test_el_crm_no_se_aisla_por_organizacion(self):
        """Los modelos del CRM no heredan el mixin: si lo hicieran, Franco vería
        cero leads por no pertenecer a ninguna organización cliente."""
        from users.scoping import ModeloDeOrganizacion
        for Modelo in (Vertical, Ciudad, Target, Etapa, Lead, Contacto):
            self.assertFalse(
                issubclass(Modelo, ModeloDeOrganizacion),
                f'{Modelo.__name__} no debe aislarse: el CRM es del proveedor',
            )


class TableroYRegistroTests(TestCase):
    def setUp(self):
        self.target = _target()
        self.lead = Lead.objects.create(target=self.target, nombre='Colegio X')
        self.franco = User.objects.create_user(username='franco', password='clave', is_staff=True)
        self.client.login(username='franco', password='clave')

    def test_el_tablero_agrupa_los_leads_por_etapa(self):
        resp = self.client.get('/crm/')
        columnas = {c['etapa'].nombre: c['leads'] for c in resp.context['columnas']}
        self.assertIn(self.lead, columnas['nuevo'])
        self.assertEqual(columnas['ganado'], [])

    def test_mover_un_lead_cambia_su_etapa(self):
        ganado = self.target.etapas.get(orden=5)
        resp = self.client.post(f'/crm/lead/{self.lead.pk}/mover/', {'etapa': ganado.pk})

        self.lead.refresh_from_db()
        self.assertEqual(self.lead.etapa, ganado)
        self.assertEqual(resp.status_code, 302)

    def test_no_se_puede_mover_a_una_etapa_de_otro_target(self):
        """Cada kanban es de su target: aceptar una etapa ajena dejaría el lead en
        una columna que su tablero no muestra."""
        otro = _target('Salud', 'Santiago')
        ajena = otro.etapas.first()

        resp = self.client.post(f'/crm/lead/{self.lead.pk}/mover/', {'etapa': ajena.pk})
        self.assertEqual(resp.status_code, 404)

    def test_registrar_un_contacto_desde_la_ficha(self):
        resp = self.client.post(
            f'/crm/lead/{self.lead.pk}/contacto/',
            {'canal': 'whatsapp', 'enviado': 'Hola, te escribo porque…', 'respuesta': ''},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.lead.contactos.count(), 1)
        self.assertEqual(self.lead.contactos.first().enviado_por, self.franco)

    def test_un_contacto_vacio_no_se_registra(self):
        resp = self.client.post(
            f'/crm/lead/{self.lead.pk}/contacto/', {'canal': 'whatsapp', 'enviado': '   '}, follow=True,
        )
        self.assertEqual(self.lead.contactos.count(), 0)
        self.assertTrue(any('falta el texto' in str(m) for m in resp.context['messages']))

    def test_conversaciones_hoy_usa_la_fecha_local_no_la_utc(self):
        """Entre las 20:00 y la medianoche de Chile ya es el día siguiente en UTC:
        con `now().date()` el contador del día se vaciaba justo en la franja en que
        se hacen las llamadas."""
        from django.utils import timezone

        Contacto.objects.create(lead=self.lead, enviado='Hola')
        resp = self.client.get('/crm/')

        self.assertEqual(resp.context['metricas']['conversaciones_hoy'], 1)
        self.assertEqual(
            Contacto.objects.filter(fecha__date=timezone.localdate()).count(), 1,
        )

    def test_las_metricas_cuentan_conversaciones_no_leads(self):
        """La métrica que decide el día es conversaciones con desconocidos: es la
        única que no depende de un algoritmo ajeno."""
        Contacto.objects.create(lead=self.lead, enviado='Hola')
        resp = self.client.get('/crm/')
        self.assertEqual(resp.context['metricas']['conversaciones_hoy'], 1)
        self.assertEqual(resp.context['metricas']['sin_contactar'], 0)


class ImportarLeadsTests(TestCase):
    """El importador es agnóstico de la fuente a propósito: sirve para el padrón
    del MINEDUC, una exportación de LinkedIn o una lista escrita a mano."""

    def _csv(self, contenido):
        import tempfile
        archivo = tempfile.NamedTemporaryFile(
            'w', suffix='.csv', delete=False, encoding='utf-8', newline='',
        )
        archivo.write(contenido)
        archivo.close()
        return archivo.name

    def _importar(self, contenido, **extra):
        from io import StringIO

        from django.core.management import call_command

        salida = StringIO()
        opciones = {
            'csv': self._csv(contenido), 'vertical': 'educacion',
            'ciudad': 'Temuco', 'stdout': salida,
        }
        opciones.update(extra)
        call_command('importar_leads', **opciones)
        return salida.getvalue()

    def test_importa_y_crea_el_target_con_sus_etapas(self):
        self._importar('nombre,email\nColegio Uno,uno@x.cl\nColegio Dos,dos@x.cl\n')

        self.assertEqual(Lead.objects.count(), 2)
        target = Target.objects.get()
        self.assertEqual(target.etapas.count(), 6)
        self.assertTrue(all(l.etapa is not None for l in Lead.objects.all()))

    def test_reconoce_alias_de_cabecera(self):
        """Cada fuente nombra las columnas a su manera."""
        self._importar('establecimiento,correo,fono,RBD\nEscuela Alfa,a@x.cl,+56911,12345\n')

        lead = Lead.objects.get()
        self.assertEqual(lead.nombre, 'Escuela Alfa')
        self.assertEqual(lead.email, 'a@x.cl')
        self.assertEqual(lead.telefono, '+56911')
        self.assertEqual(lead.rbd, '12345')

    def test_reimportar_no_duplica(self):
        contenido = 'nombre,email\nColegio Uno,uno@x.cl\n'
        self._importar(contenido)
        self._importar(contenido)
        self.assertEqual(Lead.objects.count(), 1)

    def test_completa_huecos_sin_pisar_lo_que_ya_habia(self):
        """Un dato cargado a mano vale más que uno de un padrón."""
        self._importar('nombre,email\nColegio Uno,viejo@x.cl\n')
        self._importar('nombre,email,telefono\nColegio Uno,nuevo@x.cl,+56922\n')

        lead = Lead.objects.get()
        self.assertEqual(lead.email, 'viejo@x.cl', 'pisó un dato que ya existía')
        self.assertEqual(lead.telefono, '+56922', 'no completó el hueco')

    def test_las_filas_sin_nombre_se_descartan_y_se_informan(self):
        salida = self._importar('nombre,email\n,huerfano@x.cl\nColegio Uno,uno@x.cl\n')
        self.assertEqual(Lead.objects.count(), 1)
        self.assertIn('descartados: 1', salida)

    def test_simular_no_escribe_nada(self):
        salida = self._importar('nombre,email\nColegio Uno,uno@x.cl\n', simular=True)
        self.assertEqual(Lead.objects.count(), 0)
        self.assertIn('SIMULACIÓN', salida)
        self.assertIn('nuevos:      1', salida)

    def test_un_archivo_inexistente_falla_claro(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command('importar_leads', csv='/no/existe.csv', vertical='educacion', ciudad='Temuco')

    def test_un_csv_vacio_falla_claro(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self._importar('')

    def test_el_score_se_calcula_al_importar(self):
        self._importar('nombre,email,telefono,web,direccion\nCompleto,a@x.cl,+569,https://x.cl,Calle 1\n')
        self.assertEqual(Lead.objects.get().score, 6)


class PlantillasTests(TestCase):
    """El borrador tiene que llegar escrito: si hay que redactar de cero cada vez,
    el bloque de contacto no se sostiene."""

    def setUp(self):
        self.target = _target()
        self.lead = Lead.objects.create(
            target=self.target, nombre='Colegio San Marcos', contacto='Ana Rivera',
        )
        self.franco = User.objects.create_user(username='franco', password='clave', is_staff=True)
        self.client.login(username='franco', password='clave')

    def test_el_borrador_usa_el_nombre_del_contacto_y_del_colegio(self):
        from crm.plantillas import redactar

        b = redactar(self.lead)
        self.assertIn('Ana Rivera', b['cuerpo'])
        self.assertIn('Colegio San Marcos', b['asunto'])

    def test_un_lead_sin_contacto_deja_el_hueco_visible(self):
        """Un marcador sin reemplazar tiene que saltar a la vista antes de enviar,
        no viajar dentro del mensaje."""
        from crm.plantillas import redactar

        sin_nombre = Lead.objects.create(target=self.target, nombre='Escuela Sin Contacto')
        self.assertIn('¿...?', redactar(sin_nombre)['cuerpo'])

    def test_ninguna_plantilla_tiene_voseo_rioplatense(self):
        import re

        from crm.plantillas import PRIMER_CONTACTO, SEGUIMIENTO

        textos = [p['cuerpo'] for p in PRIMER_CONTACTO.values()] + list(SEGUIMIENTO.values())
        patron = r'\b(ten[eé]s|quer[eé]s|pod[eé]s|escribinos|escribime|sos|and[aá]|mir[aá])\b'
        for texto in textos:
            self.assertIsNone(re.search(patron, texto, re.IGNORECASE), f'voseo en: {texto[:60]}')

    def test_ninguna_plantilla_deja_marcadores_sin_cerrar(self):
        from crm.plantillas import PRIMER_CONTACTO, redactar

        for clave in PRIMER_CONTACTO:
            b = redactar(self.lead, clave)
            self.assertNotIn('{', b['cuerpo'], f'marcador sin reemplazar en {clave}')
            self.assertNotIn('{', b['asunto'], f'marcador sin reemplazar en {clave}')

    def test_la_ficha_trae_el_borrador_cargado(self):
        resp = self.client.get(f'/crm/lead/{self.lead.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Ana Rivera')
        self.assertEqual(resp.context['plantilla_activa'], 'educacion_utp')

    def test_se_puede_elegir_otra_plantilla(self):
        resp = self.client.get(f'/crm/lead/{self.lead.pk}/?plantilla=educacion_director')
        self.assertEqual(resp.context['plantilla_activa'], 'educacion_director')
        self.assertIn('equipos directivos', resp.context['borrador']['cuerpo'].lower())

    def test_una_plantilla_inexistente_no_rompe_la_ficha(self):
        resp = self.client.get(f'/crm/lead/{self.lead.pk}/?plantilla=no_existe')
        self.assertEqual(resp.status_code, 200)


class VerticalesTests(TestCase):
    """Liderazgo es transversal: educación es la primera vertical, no la única."""

    def test_un_mismo_lead_puede_existir_en_otra_vertical(self):
        educacion = _target('Educación', 'Temuco')
        salud = _target('Salud', 'Temuco')

        Lead.objects.create(target=educacion, nombre='Fundación Andes')
        # El dedupe es global por nombre: si la misma entidad aparece en dos
        # verticales, es la misma entidad y se trabaja una sola vez.
        with self.assertRaises(IntegrityError), transaction.atomic():
            Lead.objects.create(target=salud, nombre='Fundación Andes')

    def test_las_verticales_nuevas_nacen_inactivas(self):
        v = Vertical.objects.create(nombre='Empresa', slug='empresa')
        self.assertFalse(v.activa, 'una vertical no debe prospectarse sin decidirlo')

    def test_un_target_es_unico_por_vertical_y_ciudad(self):
        educacion = _target('Educación', 'Temuco')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Target.objects.create(vertical=educacion.vertical, ciudad=educacion.ciudad)
