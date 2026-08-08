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
