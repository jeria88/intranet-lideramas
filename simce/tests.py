"""
Tests del módulo SIMCE — la primera pieza que sale a mercado.

Fijan dos cosas que el refactor no puede romper:
  1. La aritmética de puntajes (la promesa comercial: "te digo qué falló cada uno").
  2. Que una `Prueba` sepa quién la creó — hoy vía `creada_por`, mañana vía organización.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from simce.models import (
    TIPO_TEXTUAL_CHOICES, Alternativa, Pregunta, Prueba, PruebaTexto,
    RespuestaEstudiante, SesionEstudiante, TextoBiblioteca,
)

User = get_user_model()


def _cadena_minima(titulo='Prueba de control', n_preguntas=4):
    """Prueba → PruebaTexto → Pregunta(s), lo mínimo para poder responder."""
    texto = TextoBiblioteca.objects.create(
        asignatura='lenguaje',
        tipo_textual=TIPO_TEXTUAL_CHOICES[0][0],
        titulo='Texto de control',
        contenido='palabra ' * 400,
    )
    prueba = Prueba.objects.create(titulo=titulo, asignatura='lenguaje', curso='4B')
    pt = PruebaTexto.objects.create(prueba=prueba, texto=texto, orden=1)
    preguntas = [
        Pregunta.objects.create(
            prueba_texto=pt, orden=i, enunciado=f'Pregunta {i}',
            nivel=1, habilidad='LOCALIZAR', alternativa_correcta='A',
        )
        for i in range(1, n_preguntas + 1)
    ]
    return prueba, preguntas


class CalculoDePuntajesTests(TestCase):
    """`SesionEstudiante.calcular_puntajes` — `simce/models.py`."""

    def _sesion(self, prueba, modo='simce'):
        return SesionEstudiante.objects.create(
            prueba=prueba, nombre='Ana Pérez', rut='11111111-1',
            establecimiento='TEMUCO', curso='4B', letra_curso='A', modo=modo,
        )

    def test_modo_simce_todo_correcto_da_el_puntaje_maximo(self):
        prueba, preguntas = _cadena_minima(n_preguntas=4)
        sesion = self._sesion(prueba)
        for p in preguntas:
            RespuestaEstudiante.objects.create(sesion=sesion, pregunta=p, puntaje_obtenido=1)

        sesion.calcular_puntajes()

        self.assertEqual(sesion.puntaje_bruto, 4)
        self.assertEqual(float(sesion.porcentaje_logro), 100.0)
        self.assertEqual(sesion.puntaje_simce, 350)  # 150 + 100% * 200
        self.assertTrue(sesion.completada)
        self.assertIsNotNone(sesion.finalizada_en)

    def test_modo_simce_todo_incorrecto_da_el_piso_de_la_escala(self):
        prueba, preguntas = _cadena_minima(n_preguntas=4)
        sesion = self._sesion(prueba)
        for p in preguntas:
            RespuestaEstudiante.objects.create(sesion=sesion, pregunta=p, puntaje_obtenido=0)

        sesion.calcular_puntajes()

        self.assertEqual(sesion.puntaje_bruto, 0)
        self.assertEqual(float(sesion.porcentaje_logro), 0.0)
        self.assertEqual(sesion.puntaje_simce, 150)  # el piso, no 0

    def test_modo_simce_mitad_correcta(self):
        prueba, preguntas = _cadena_minima(n_preguntas=4)
        sesion = self._sesion(prueba)
        for i, p in enumerate(preguntas):
            RespuestaEstudiante.objects.create(sesion=sesion, pregunta=p, puntaje_obtenido=1 if i < 2 else 0)

        sesion.calcular_puntajes()

        self.assertEqual(float(sesion.porcentaje_logro), 50.0)
        self.assertEqual(sesion.puntaje_simce, 250)

    def test_modo_pistas_usa_maximo_4_por_pregunta(self):
        """En modo pistas el máximo es 4 por pregunta (4-3-2-0), no 1."""
        prueba, preguntas = _cadena_minima(n_preguntas=2)
        sesion = self._sesion(prueba, modo='pistas')
        for p in preguntas:
            RespuestaEstudiante.objects.create(sesion=sesion, pregunta=p, puntaje_obtenido=4)

        sesion.calcular_puntajes()

        self.assertEqual(sesion.puntaje_bruto, 8)
        self.assertEqual(float(sesion.porcentaje_logro), 100.0)

    def test_modo_pistas_acierto_al_segundo_intento_no_es_100(self):
        """3 de 4 puntos = 75%: el mismo acierto vale menos si costó una pista."""
        prueba, preguntas = _cadena_minima(n_preguntas=2)
        sesion = self._sesion(prueba, modo='pistas')
        for p in preguntas:
            RespuestaEstudiante.objects.create(sesion=sesion, pregunta=p, puntaje_obtenido=3)

        sesion.calcular_puntajes()

        self.assertEqual(float(sesion.porcentaje_logro), 75.0)
        self.assertEqual(sesion.puntaje_simce, 300)

    def test_sesion_sin_respuestas_no_divide_por_cero(self):
        prueba, _ = _cadena_minima()
        sesion = self._sesion(prueba)

        sesion.calcular_puntajes()

        self.assertEqual(float(sesion.porcentaje_logro), 0.0)
        self.assertEqual(sesion.puntaje_simce, 150)

    def test_una_respuesta_por_pregunta(self):
        prueba, preguntas = _cadena_minima(n_preguntas=1)
        sesion = self._sesion(prueba)
        RespuestaEstudiante.objects.create(sesion=sesion, pregunta=preguntas[0], puntaje_obtenido=1)
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            RespuestaEstudiante.objects.create(sesion=sesion, pregunta=preguntas[0], puntaje_obtenido=1)


class PruebaTests(TestCase):
    def test_contadores_de_la_prueba(self):
        prueba, _ = _cadena_minima(n_preguntas=5)
        self.assertEqual(prueba.total_preguntas, 5)
        self.assertEqual(prueba.total_textos, 1)

    def test_estado_inicial_es_borrador(self):
        prueba, _ = _cadena_minima()
        self.assertEqual(prueba.estado, 'borrador')
        self.assertFalse(prueba.rubrica_ok)

    def test_una_prueba_registra_a_su_autor(self):
        """`creada_por` es el gancho del aislamiento por dueño (hoy sin filtrar en las vistas)."""
        autor = User.objects.create_user(username='utp', password='x', tenant='colegio_a')
        prueba, _ = _cadena_minima()
        prueba.creada_por = autor
        prueba.save(update_fields=['creada_por'])

        self.assertEqual(Prueba.objects.filter(creada_por=autor).count(), 1)
        self.assertEqual(autor.pruebas_simce.count(), 1)

    def test_dos_autores_distintos_tienen_sus_propias_pruebas(self):
        """Fija la expectativa del aislamiento: hoy pasa por `creada_por`; el refactor
        debe conservar esta separación cuando el filtro sea por organización."""
        a = User.objects.create_user(username='utp_a', password='x', tenant='colegio_a')
        b = User.objects.create_user(username='utp_b', password='x', tenant='colegio_b')

        pa, _ = _cadena_minima(titulo='De A')
        pa.creada_por = a
        pa.save(update_fields=['creada_por'])

        pb, _ = _cadena_minima(titulo='De B')
        pb.creada_por = b
        pb.save(update_fields=['creada_por'])

        self.assertEqual(list(Prueba.objects.filter(creada_por=a).values_list('titulo', flat=True)), ['De A'])
        self.assertEqual(list(Prueba.objects.filter(creada_por=b).values_list('titulo', flat=True)), ['De B'])


class RendicionPublicaTests(TestCase):
    """El estudiante rinde SIN cuenta: `prueba_identificacion` y compañía no llevan
    `@login_required`.

    Eso choca con el aislamiento por request: un anónimo no tiene organización, y
    el manager por defecto le devolvería cero filas — la prueba daría 404 aunque
    esté publicada y el link sea correcto. Estas vistas tienen que consultar sin
    el filtro, apoyándose en el gate que ya existe (`estado='publicada'`).
    """

    def setUp(self):
        from users.models import Organizacion

        self.org = Organizacion.objects.create(slug='colegio_x', nombre='Colegio X')
        self.prueba, self.preguntas = _cadena_minima(n_preguntas=2)
        self.prueba.organizacion = self.org
        self.prueba.estado = 'publicada'
        self.prueba.save(update_fields=['organizacion', 'estado'])

    def test_un_anonimo_puede_abrir_la_identificacion_de_una_prueba_publicada(self):
        from django.urls import reverse

        resp = self.client.get(reverse('simce:prueba_identificacion', args=[self.prueba.pk, 'simce']))
        self.assertEqual(
            resp.status_code, 200,
            'el estudiante anónimo no puede abrir una prueba publicada: el filtro '
            'por organización lo está dejando fuera',
        )

    def test_un_anonimo_puede_identificarse_y_empezar(self):
        from django.urls import reverse

        resp = self.client.post(
            reverse('simce:prueba_identificacion', args=[self.prueba.pk, 'simce']),
            {'nombre': 'Ana Pérez', 'rut': '11111111-1', 'curso': '4B',
             'letra': 'A', 'establecimiento': 'SEDE', 'rbd': '12345'},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(SesionEstudiante.objects.count(), 1)

    def test_un_anonimo_puede_rendir_y_ver_su_resultado(self):
        from django.urls import reverse

        sesion = SesionEstudiante.objects.create(
            prueba=self.prueba, nombre='Ana', rut='11111111-1',
            establecimiento='SEDE', curso='4B', letra_curso='A',
        )
        self.assertEqual(
            self.client.get(reverse('simce:prueba_rendir', args=[sesion.pk])).status_code, 200
        )

        sesion.calcular_puntajes()
        self.assertEqual(
            self.client.get(reverse('simce:prueba_resultado', args=[sesion.pk])).status_code, 200
        )

    def test_el_formulario_ofrece_las_sedes_de_la_organizacion_de_la_prueba(self):
        from django.urls import reverse

        from users.models import Establecimiento, Organizacion

        Establecimiento.objects.create(organizacion=self.org, codigo='NORTE', nombre='Sede Norte')
        otra_org = Organizacion.objects.create(slug='colegio_y', nombre='Colegio Y')
        Establecimiento.objects.create(organizacion=otra_org, codigo='AJENA', nombre='Sede Ajena')

        resp = self.client.get(
            reverse('simce:prueba_identificacion', args=[self.prueba.pk, 'simce'])
        )
        sedes = dict(resp.context['sedes'])
        self.assertIn('NORTE', sedes)
        self.assertNotIn('AJENA', sedes, 'ofrece sedes de otra organización')

    def test_lo_declarado_se_resuelve_a_una_sede_real(self):
        from django.urls import reverse

        from users.models import Establecimiento

        norte = Establecimiento.objects.create(
            organizacion=self.org, codigo='NORTE', nombre='Sede Norte',
        )
        self.client.post(
            reverse('simce:prueba_identificacion', args=[self.prueba.pk, 'simce']),
            {'nombre': 'Ana', 'rut': '11111111-1', 'curso': '4B',
             'letra': 'A', 'establecimiento': 'norte', 'rbd': ''},
        )
        sesion = SesionEstudiante.objects.get()
        self.assertEqual(sesion.sede, norte, 'no resolvió pese a diferir solo en mayúsculas')
        self.assertEqual(sesion.establecimiento, 'norte', 'se pierde lo que declaró el estudiante')

    def test_lo_declarado_que_no_coincide_no_inventa_sede(self):
        from django.urls import reverse

        self.client.post(
            reverse('simce:prueba_identificacion', args=[self.prueba.pk, 'simce']),
            {'nombre': 'Ana', 'rut': '11111111-1', 'curso': '4B',
             'letra': 'A', 'establecimiento': 'Colegio Que No Existe', 'rbd': ''},
        )
        sesion = SesionEstudiante.objects.get()
        self.assertIsNone(sesion.sede)
        self.assertEqual(sesion.establecimiento, 'Colegio Que No Existe')

    def test_una_prueba_no_publicada_sigue_sin_ser_accesible(self):
        """Quitar el filtro por organización no puede abrir lo que no está publicado."""
        from django.urls import reverse

        self.prueba.estado = 'borrador'
        self.prueba.save(update_fields=['estado'])
        resp = self.client.get(reverse('simce:prueba_identificacion', args=[self.prueba.pk, 'simce']))
        self.assertEqual(resp.status_code, 404)


class ParseoDeJsonDelModeloTests(TestCase):
    """Un LLM devuelve JSON *casi* válido, y el "casi" tumbaba la generación.

    Caso real en producción al armar el primer ensayo de demostración:
    `JSONDecodeError: Expecting property name enclosed in double quotes`, y el UTP
    veía la prueba en estado `error` sin ninguna explicación.
    """

    def _cargar(self, crudo):
        from simce.generator import _cargar_json
        return _cargar_json(crudo, 'prueba')

    def test_tolera_coma_final_antes_de_llave(self):
        self.assertEqual(self._cargar('{"a": 1, "b": 2,}'), {'a': 1, 'b': 2})

    def test_tolera_coma_final_antes_de_corchete(self):
        self.assertEqual(self._cargar('{"xs": [1, 2, 3,]}'), {'xs': [1, 2, 3]})

    def test_tolera_vallas_de_codigo_con_y_sin_lenguaje(self):
        self.assertEqual(self._cargar('```json\n{"a": 1}\n```'), {'a': 1})
        self.assertEqual(self._cargar('```\n{"a": 1}\n```'), {'a': 1})

    def test_tolera_prosa_alrededor(self):
        self.assertEqual(self._cargar('Aquí tienes:\n{"a": 1}\nEspero que sirva.'), {'a': 1})

    def test_tolera_comas_finales_anidadas(self):
        datos = self._cargar('{"preguntas": [{"n": 1, "alts": ["a", "b",],}, ]}')
        self.assertEqual(datos['preguntas'][0]['n'], 1)

    def test_lo_que_no_es_json_sigue_fallando(self):
        """Se arreglan defectos de formato, nunca contenido: si el modelo devolvió
        cualquier cosa, tiene que notarse."""
        with self.assertRaises(ValueError):
            self._cargar('esto no es json en absoluto')

    def test_el_error_dice_que_paso_y_muestra_el_fragmento(self):
        with self.assertRaises(ValueError) as ctx:
            self._cargar('{"a": 1, "b": }')
        mensaje = str(ctx.exception)
        self.assertIn('JSON inválido', mensaje)
        self.assertIn('prueba', mensaje, 'el error no dice en qué paso falló')


class BarajadoDeAlternativasTests(TestCase):
    """El modelo ponía la correcta siempre en D: 6 de 6 en el primer ensayo real.

    La rúbrica lo detecta (`A:0 B:0 C:0 D:6` → no aprobada), así que ninguna prueba
    generada llegaba a publicarse. Y para un estudiante, esa regularidad es una
    pista, no una evaluación.
    """

    def _alternativas(self, correcta='D'):
        return [
            {'letra': l, 'texto': f'Opción {l}', 'es_correcta': l == correcta,
             'justificacion': f'j{l}'}
            for l in 'ABCD'
        ]

    def test_reparte_la_correcta_entre_las_cuatro_letras(self):
        from simce.generator import _barajar_alternativas

        letras = set()
        for _ in range(60):
            barajadas = _barajar_alternativas(self._alternativas('D'))
            letras.add(next(a['letra'] for a in barajadas if a['es_correcta']))
        self.assertEqual(letras, set('ABCD'), f'no cubrió las cuatro letras: {letras}')

    def test_el_texto_viaja_con_su_marca_de_correcta(self):
        """Lo que no puede pasar: reordenar las letras y dejar la marca en otra."""
        from simce.generator import _barajar_alternativas

        for _ in range(30):
            barajadas = _barajar_alternativas(self._alternativas('B'))
            correcta = next(a for a in barajadas if a['es_correcta'])
            self.assertEqual(correcta['texto'], 'Opción B')
            self.assertEqual(correcta['justificacion'], 'jB')

    def test_conserva_las_cuatro_y_no_repite_letras(self):
        from simce.generator import _barajar_alternativas

        barajadas = _barajar_alternativas(self._alternativas())
        self.assertEqual(len(barajadas), 4)
        self.assertEqual(sorted(a['letra'] for a in barajadas), list('ABCD'))
        self.assertEqual(sum(1 for a in barajadas if a['es_correcta']), 1)

    def test_sin_alternativas_no_revienta(self):
        from simce.generator import _barajar_alternativas
        self.assertEqual(_barajar_alternativas([]), [])


class RebalanceoDeLaPruebaTests(TestCase):
    """Barajar cada pregunta por separado no alcanza: con 6 preguntas y azar, lo
    normal es que alguna letra quede en cero y la rúbrica exige las cuatro.
    Se vio en la primera prueba real: A:3 B:1 C:0 D:2."""

    def _prueba_con(self, n_preguntas, correcta_en='D'):
        prueba, preguntas = _cadena_minima(n_preguntas=n_preguntas)
        for pregunta in preguntas:
            pregunta.alternativa_correcta = correcta_en
            pregunta.save(update_fields=['alternativa_correcta'])
            for letra in 'ABCD':
                Alternativa.objects.create(
                    pregunta=pregunta, letra=letra, texto=f'Opción {letra} de P{pregunta.orden}',
                    es_correcta=(letra == correcta_en),
                )
        return prueba, preguntas

    def _distribucion(self, prueba):
        from simce.models import Pregunta
        letras = [p.alternativa_correcta for p in Pregunta.objects.filter(prueba_texto__prueba=prueba)]
        return {l: letras.count(l) for l in 'ABCD'}

    def test_con_cuatro_preguntas_cubre_las_cuatro_letras(self):
        from simce.generator import rebalancear_alternativas

        prueba, preguntas = self._prueba_con(4)
        self.assertEqual(self._distribucion(prueba), {'A': 0, 'B': 0, 'C': 0, 'D': 4})

        rebalancear_alternativas(preguntas)

        self.assertEqual(self._distribucion(prueba), {'A': 1, 'B': 1, 'C': 1, 'D': 1})

    def test_con_ocho_preguntas_queda_parejo(self):
        from simce.generator import rebalancear_alternativas

        prueba, preguntas = self._prueba_con(8)
        rebalancear_alternativas(preguntas)
        self.assertEqual(self._distribucion(prueba), {'A': 2, 'B': 2, 'C': 2, 'D': 2})

    def test_la_prueba_pasa_la_rubrica_despues_de_rebalancear(self):
        """El criterio que bloqueaba la publicación de toda prueba generada."""
        from simce.generator import rebalancear_alternativas, validar_rubrica_prueba

        prueba, preguntas = self._prueba_con(6)
        antes = validar_rubrica_prueba(prueba)['criterios']['distribucion_alternativas']
        self.assertFalse(antes['ok'], 'el caso de partida ya estaba bien, no prueba nada')

        rebalancear_alternativas(preguntas)

        despues = validar_rubrica_prueba(prueba)['criterios']['distribucion_alternativas']
        self.assertTrue(despues['ok'], f"sigue sin pasar: {despues['detalle']}")

    def test_el_texto_correcto_sigue_siendo_el_correcto(self):
        """Lo que no puede pasar: mover la letra y que la respuesta buena cambie."""
        from simce.generator import rebalancear_alternativas

        prueba, preguntas = self._prueba_con(4)
        textos_correctos = {
            p.pk: p.alternativas.get(es_correcta=True).texto for p in preguntas
        }

        rebalancear_alternativas(preguntas)

        for pregunta in preguntas:
            pregunta.refresh_from_db()
            correcta = pregunta.alternativas.get(es_correcta=True)
            self.assertEqual(correcta.texto, textos_correctos[pregunta.pk])
            self.assertEqual(correcta.letra, pregunta.alternativa_correcta)

    def test_cada_pregunta_conserva_sus_cuatro_letras(self):
        from simce.generator import rebalancear_alternativas

        prueba, preguntas = self._prueba_con(5)
        rebalancear_alternativas(preguntas)

        for pregunta in preguntas:
            letras = sorted(pregunta.alternativas.values_list('letra', flat=True))
            self.assertEqual(letras, list('ABCD'))
            self.assertEqual(pregunta.alternativas.filter(es_correcta=True).count(), 1)


class PermisosDelPanelTests(TestCase):
    """Quién administra ensayos. El UTP es quien los arma y quien compra el módulo:
    si no puede entrar, no hay demo que mostrarle."""

    @classmethod
    def setUpTestData(cls):
        from users.models import Organizacion

        cls.org = Organizacion.objects.create(slug='colegio_p', nombre='Colegio P')
        cls.otra = Organizacion.objects.create(slug='colegio_q', nombre='Colegio Q')

        def usuario(nombre, rol, org=cls.org, **extra):
            return User.objects.create_user(
                username=nombre, password='clave', tenant=org.slug if org else '',
                role=rol, organizacion=org, **extra,
            )

        cls.utp = usuario('utp', 'UTP')
        cls.director = usuario('director', 'DIRECTOR')
        cls.inspector = usuario('inspector', 'INSPECTOR')
        cls.suelto = usuario('suelto', 'UTP', org=None)
        cls.soporte = User.objects.create_superuser(username='soporte', password='clave')

    def _abre_panel(self, user):
        self.client.force_login(user)
        return self.client.get('/simce/').status_code

    def test_el_utp_entra(self):
        self.assertEqual(self._abre_panel(self.utp), 200)

    def test_el_director_entra(self):
        self.assertEqual(self._abre_panel(self.director), 200)

    def test_el_soporte_entra(self):
        self.assertEqual(self._abre_panel(self.soporte), 200)

    def test_un_rol_que_no_arma_ensayos_no_entra(self):
        self.assertNotEqual(self._abre_panel(self.inspector), 200)

    def test_un_utp_sin_organizacion_no_entra(self):
        """Sin organización el alcance sería nulo: entraría a un panel vacío y,
        peor, sin nada que lo acote."""
        self.assertNotEqual(self._abre_panel(self.suelto), 200)

    def test_el_anonimo_no_entra(self):
        self.assertNotEqual(self.client.get('/simce/').status_code, 200)

    def test_cada_utp_ve_solo_las_pruebas_de_su_colegio(self):
        """El permiso se abre, pero el aislamiento sigue mandando."""
        mia, _ = _cadena_minima(titulo='De mi colegio')
        mia.organizacion = self.org
        mia.save(update_fields=['organizacion'])

        ajena, _ = _cadena_minima(titulo='Del colegio vecino')
        ajena.organizacion = self.otra
        ajena.save(update_fields=['organizacion'])

        self.client.force_login(self.utp)
        resp = self.client.get('/simce/')

        titulos = [p.titulo for p in resp.context['pruebas']]
        self.assertIn('De mi colegio', titulos)
        self.assertNotIn('Del colegio vecino', titulos)


class TextoBibliotecaTests(TestCase):
    def test_word_count_y_char_count_se_calculan_al_guardar(self):
        texto = TextoBiblioteca.objects.create(
            asignatura='lenguaje', tipo_textual=TIPO_TEXTUAL_CHOICES[0][0],
            titulo='T', contenido='hola mundo cruel',
        )
        self.assertEqual(texto.word_count, 3)
        self.assertEqual(texto.char_count, len('holamundocruel'))

    def test_umbral_de_validez_simce_son_1500_caracteres(self):
        """`generator.py` lo llama 'requisito de validez SIMCE'."""
        corto = TextoBiblioteca.objects.create(
            asignatura='lenguaje', tipo_textual=TIPO_TEXTUAL_CHOICES[0][0],
            titulo='corto', contenido='a ' * 100,
        )
        largo = TextoBiblioteca.objects.create(
            asignatura='lenguaje', tipo_textual=TIPO_TEXTUAL_CHOICES[0][0],
            titulo='largo', contenido='a' * 1500,
        )
        self.assertFalse(corto.cumple_extension())
        self.assertTrue(largo.cumple_extension())


class AlternativasTests(TestCase):
    def test_una_pregunta_tiene_su_alternativa_correcta(self):
        _, preguntas = _cadena_minima(n_preguntas=1)
        pregunta = preguntas[0]
        for letra in ('A', 'B', 'C', 'D'):
            Alternativa.objects.create(
                pregunta=pregunta, letra=letra, texto=f'Opción {letra}',
                es_correcta=(letra == pregunta.alternativa_correcta),
            )
        correctas = Alternativa.objects.filter(pregunta=pregunta, es_correcta=True)
        self.assertEqual(correctas.count(), 1)
        self.assertEqual(correctas.first().letra, 'A')
