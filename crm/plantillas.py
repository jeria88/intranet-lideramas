"""Plantillas de primer contacto y seguimiento.

No son un generador: son el punto de partida que se edita antes de enviar. Un
mensaje que se manda tal cual sale se nota, y lo que convierte es que el otro
sienta que le escribió una persona.

Reglas que siguen todas, y que vienen de lo que ya se probó en el ecosistema:
  - Español de Chile, tratamiento de usted, cero voseo rioplatense.
  - Sin promesa de resultados que el producto no pueda sostener.
  - Una sola pregunta al final: el objetivo del primer mensaje es una respuesta,
    no una venta.
  - Nada de "espero que estés muy bien" ni presentación de tres párrafos.
"""

PRIMER_CONTACTO = {
    'educacion_utp': {
        'etiqueta': 'UTP / Jefe de UTP — ensayos SIMCE',
        'asunto': 'Ensayos SIMCE para {establecimiento}',
        'cuerpo': (
            'Hola {contacto}, le escribo de LíderA+.\n\n'
            'Armamos una herramienta que genera ensayos SIMCE con el formato de la '
            'prueba real: usted elige curso y asignatura, y queda listo para imprimir '
            'o para que lo rindan en línea. Cuando lo rinden, muestra qué pregunta '
            'falló cada estudiante y por qué alternativa se fue.\n\n'
            'La construí trabajando un año con equipos directivos de una red de ocho '
            'colegios, así que está pensada desde el trabajo de UTP y no desde afuera.\n\n'
            '¿Le sirve que le muestre un ensayo generado para {curso}? Son diez minutos '
            'y se lo dejo hecho, use o no la herramienta.'
        ),
    },
    'educacion_director': {
        'etiqueta': 'Director/a — plataforma completa',
        'asunto': 'Tiempo administrativo del equipo directivo',
        'cuerpo': (
            'Hola {contacto}, le escribo de LíderA+.\n\n'
            'Trabajé un año con los equipos directivos de una red de ocho colegios y el '
            'patrón se repetía: el acta de una reunión tomaba más que la reunión, y las '
            'consultas de normativa se resolvían de memoria o llamando a alguien.\n\n'
            'Con eso armamos una plataforma que hace el acta sola desde la grabación, '
            'ordena el ciclo de mejora con responsables y plazos, y genera ensayos SIMCE.\n\n'
            '¿Tiene veinte minutos esta semana para que se lo muestre funcionando con '
            'los datos de {establecimiento}?'
        ),
    },
    'educacion_sostenedor': {
        'etiqueta': 'Sostenedor / red — varios establecimientos',
        'asunto': 'Gestión de {establecimiento} en una sola plataforma',
        'cuerpo': (
            'Hola {contacto}, le escribo de LíderA+.\n\n'
            'Trabajamos con redes de colegios: una vista por establecimiento y otra '
            'transversal para el equipo central, con los planes de mejora, las actas y '
            'los resultados de ensayos en el mismo lugar.\n\n'
            'Cada colegio ve lo suyo y el equipo central ve todo, sin planillas cruzadas.\n\n'
            '¿Vale la pena que se lo muestre? Veinte minutos, con sus establecimientos '
            'cargados para que lo vea con datos propios y no con una demo genérica.'
        ),
    },
}

SEGUIMIENTO = {
    'sin_respuesta': (
        'Hola {contacto}, le escribí la semana pasada y entiendo que agosto es un mes '
        'difícil.\n\n'
        'Le dejo algo concreto por si sirve más que una reunión: si me dice curso y '
        'asignatura, le genero un ensayo SIMCE y se lo mando. Sin compromiso, lo usa '
        'o lo descarta.\n\n'
        '¿Le sirve?'
    ),
    'tras_demo': (
        'Hola {contacto}, gracias por el rato de ayer.\n\n'
        'Le dejo el acceso para que lo pruebe con su equipo: {enlace}\n\n'
        'Cualquier cosa que no funcione o no se entienda, dígamela — eso me sirve más '
        'que un cumplido.'
    ),
    'reactivacion': (
        'Hola {contacto}, cierro el tema por mi lado para no seguir insistiendo.\n\n'
        'Si en algún momento le sirve ver la herramienta de ensayos SIMCE, escríbame y '
        'la retomamos. Que le vaya bien con el cierre de semestre.'
    ),
}


def redactar(lead, clave='educacion_utp', **extra):
    """Rellena una plantilla con los datos del lead. Lo que falta queda visible.

    Los huecos se marcan con «...» a propósito: un marcador sin reemplazar tiene
    que saltar a la vista antes de enviar, no viajar dentro del mensaje.
    """
    plantilla = PRIMER_CONTACTO.get(clave) or {'asunto': '', 'cuerpo': SEGUIMIENTO.get(clave, '')}
    datos = {
        'contacto': lead.contacto or '¿...?',
        'establecimiento': lead.nombre,
        'curso': '4° básico',
        'enlace': '...',
    }
    datos.update({k: v for k, v in extra.items() if v})
    return {
        'asunto': plantilla.get('asunto', '').format(**datos),
        'cuerpo': plantilla['cuerpo'].format(**datos),
    }
