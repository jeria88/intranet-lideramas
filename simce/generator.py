"""
Generador SIMCE — nueva arquitectura: TextoBiblioteca + PreguntaBanco + RAG MINEDUC.
"""
import json
import os
import re
import random
from openai import OpenAI

DEEPSEEK_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
client = OpenAI(api_key=DEEPSEEK_KEY, base_url='https://api.deepseek.com')

# ── Tipos disponibles por asignatura ──────────────────────────────
TIPOS_POR_ASIGNATURA = {
    'lenguaje':   ['cuento', 'cuento_folclorico', 'fabula', 'leyenda', 'mito',
                   'poema', 'soneto', 'oda', 'noticia', 'reportaje',
                   'articulo_info', 'infografia', 'instructivo', 'receta',
                   'manual', 'biografia', 'carta_formal', 'carta_director',
                   'carta_informal', 'afiche', 'discontinuo'],
    'matematica': ['discontinuo', 'infografia', 'instructivo', 'noticia', 'reportaje'],
    'ciencias':   ['articulo_cient', 'discontinuo', 'infografia', 'instructivo',
                   'noticia', 'reportaje', 'receta'],
    'historia':   ['noticia', 'reportaje', 'carta_formal', 'carta_director',
                   'discontinuo', 'infografia', 'afiche', 'biografia'],
}

# ── Ejes y habilidades SIMCE Lenguaje (Tabla UTP) ─────────────────
# Organizados por eje para inyectarlos en los prompts
EJES_HABILIDADES_LENGUAJE = {
    'LOCALIZAR': [
        'Recordar hechos y detalles',
        'Comprender la secuencia (explícita)',
    ],
    'INTERPRETAR': [
        'Hallar la idea principal',
        'Reconocer causa y efecto',
        'Comparar y contrastar',
        'Hacer predicciones',
        'Hallar significado de palabras por contexto',
        'Sacar conclusiones y hacer inferencias',
        'Interpretar lenguaje figurado',
    ],
    'REFLEXIONAR': [
        'Distinguir entre hecho y opinión',
        'Identificar el propósito del autor',
        'Interpretar ideas implícitas y síntesis',
    ],
}

# Lista plana para uso en prompts genéricos
_HAB_LENGUAJE = [h for habs in EJES_HABILIDADES_LENGUAJE.values() for h in habs]

# Plantillas de pregunta por habilidad y nivel (Tabla UTP)
PLANTILLAS_HABILIDADES_LENGUAJE = {
    'Recordar hechos y detalles': {
        1: 'Según el texto, ¿quién / qué / dónde / cuándo [acción o personaje]?\na) [Opción correcta textual]\nb) [Personaje secundario]\nc) [Lugar diferente]\nd) [Acción no mencionada]',
        2: '¿Qué se afirma en el texto sobre [tema específico]?\na) [Información correcta levemente parafraseada]\nb) [Información de otro párrafo]\nc) [Información similar pero incorrecta]\nd) [No mencionada]',
        3: 'Según la [tabla/gráfico/infografía], ¿cuál afirmación es correcta?\na) [Dato correcto del texto discontinuo]\nb) [Dato incorrecto]\nc) [Dato verdadero de otro contexto]\nd) [No presente]',
    },
    'Comprender la secuencia (explícita)': {
        1: '¿Qué ocurrió PRIMERO en el texto?\na) [Evento correcto del inicio]\nb) [Evento del medio]\nc) [Evento del final]\nd) [Evento que no ocurre]',
        2: '¿Qué ocurrió INMEDIATAMENTE ANTES de que [evento referencia]?\na) [Evento correcto anterior]\nb) [Evento posterior]\nc) [Evento de otra parte]\nd) [Evento inventado]',
        3: 'Si reorganizaras los eventos, ¿cuál NO podría ocurrir al principio sin cambiar el sentido?\na-c) [Eventos que sí podrían ir primero]\nd) [Evento clave que solo tiene sentido al final]',
    },
    'Hallar la idea principal': {
        1: '¿De qué trata PRINCIPALMENTE este texto?\na) [Tema general correcto]\nb) [Detalle secundario]\nc) [Tema no mencionado]\nd) [Personaje o elemento menor]',
        2: '¿Cuál es la IDEA PRINCIPAL del párrafo [N]?\na) [Idea central correcta del párrafo]\nb) [Detalle de apoyo]\nc) [Idea de otro párrafo]\nd) [No presente]',
        3: '¿Cuál resume MEJOR el mensaje global del texto?\na) [Síntesis completa que integra varias ideas]\nb) [Solo la idea del primer párrafo]\nc) [Solo la idea del último párrafo]\nd) [Un detalle aislado]',
    },
    'Reconocer causa y efecto': {
        1: 'Según el texto, ¿por qué [evento/acción]?\na) [Causa correcta explícita]\nb) [Consecuencia del evento]\nc) [Causa de otro evento]\nd) [No relacionada]',
        2: '¿Cuál es la RAZÓN principal por la que [evento]?\na) [Causa inferida correctamente]\nb) [Consecuencia]\nc) [Causa explícita de otro evento]\nd) [Opinión del lector]',
        3: '¿Cuál describe MEJOR la relación causa-efecto?\na) [A] causó [B], que causó [C] (cadena completa)\nb) Solo A causó B (incompleta)\nc) Invierte la relación\nd) Relación falsa',
    },
    'Comparar y contrastar': {
        1: '[Elemento 1] y [Elemento 2] se parecen en que ambos:\na) [Característica común correcta]\nb) [Solo de elemento 1]\nc) [Solo de elemento 2]\nd) [No presente en ninguno]',
        2: '¿Cuál es una DIFERENCIA entre [E1] y [E2] según el texto?\na) [Diferencia correcta]\nb) [Semejanza como diferencia]\nc) [Diferencia de otro contexto]\nd) [No mencionada]',
        3: '¿En qué se DIFERENCIAN fundamentalmente en cuanto a [aspecto]?\na) [Diferencia conceptual profunda]\nb) [Diferencia superficial]\nc) [Semejanza como diferencia]\nd) [No presente]',
    },
    'Hacer predicciones': {
        1: 'Según el título, ¿qué crees que ocurrirá?\na) [Predicción lógica basada en el título]\nb) [Ilógica]\nc) [Descripción sin predicción]\nd) [Evento ya ocurrido]',
        2: 'Basándote en lo leído, ¿qué es lo MÁS PROBABLE que ocurra después?\na) [Predicción coherente con pistas]\nb) [Evento ya ocurrido]\nc) [Ilógica]\nd) [Deseo del lector sin base]',
        3: 'Si [evento clave] NO hubiera ocurrido, ¿qué habría pasado?\na) [Consecuencia lógica de eliminar ese evento]\nb) [Sin relación]\nc) [Lo mismo que ocurrió]\nd) [Imposible de predecir]',
    },
    'Hallar significado de palabras por contexto': {
        1: 'En el texto, la palabra "[X]" significa:\na) [Definición correcta del contexto]\nb) [Significado literal de otro contexto]\nc) [Otra palabra no relacionada]\nd) [Inventado]',
        2: '¿Qué significa la expresión "[X]" en el texto?\na) [Significado inferido del contexto]\nb) [Literal sin contexto]\nc) [Significado de otra expresión]\nd) [Sin relación]',
        3: '¿Cuál significado de "[X]" es el MÁS ADECUADO según el contexto?\na) [Acepción correcta en este contexto]\nb) [Otra acepción válida pero no aplicable]\nc) [Significado opuesto]\nd) [Inventado]',
    },
    'Sacar conclusiones y hacer inferencias': {
        1: 'Al final, [personaje] se sentía:\na) [Emoción correcta inferida de acciones]\nb) [Emoción opuesta]\nc) [No relacionada]\nd) [Información textual sin inferir]',
        2: '¿Cómo era [personaje]?\na) [Característica inferida de múltiples acciones]\nb) [Opuesta]\nc) [Literal dicha por otro personaje]\nd) [Sin relación]',
        3: '¿Cuál expresa MEJOR la enseñanza o moraleja del texto?\na) [Moraleja integrando pistas implícitas]\nb) [Hecho explícito como enseñanza]\nc) [Opinión personal sin base]\nd) [Enseñanza de otro texto]',
    },
    'Interpretar lenguaje figurado': {
        1: 'Cuando el texto dice "[expresión]", quiere decir que:\na) [Interpretación figurada correcta]\nb) [Literal incorrecta]\nc) [Otra expresión del texto]\nd) [Opinión del lector]',
        2: '¿Qué quiere decir la expresión "[metáfora/personificación]"?\na) [Significado figurado correcto]\nb) [Literal sin figura]\nc) [Significado de otra expresión]\nd) [Definición de diccionario sin contexto]',
        3: 'El autor usa "[lenguaje figurado]" para:\na) [Efecto/idea que busca transmitir]\nb) [Decorar sin propósito]\nc) [Confundir al lector]\nd) [Referirse a algo literal posterior]',
    },
    'Distinguir entre hecho y opinión': {
        1: '¿Cuál es un HECHO según el texto?\na) [Afirmación verificable presente]\nb) [Opinión del autor o personaje]\nc) [Inventada]\nd) [De otro texto]',
        2: '¿Cuál es una OPINIÓN del autor o personaje?\na) [Afirmación subjetiva con juicio de valor]\nb) [Dato verificable]\nc) [Hecho científico]\nd) [Información sin juicio]',
        3: '¿El autor mezcla hechos y opiniones? ¿Con qué propósito?\na) [Sí, para persuadir/convencer]\nb) [No, solo hechos]\nc) [Sí, pero es error del autor]\nd) [No, solo opiniones]',
    },
    'Identificar el propósito del autor': {
        1: 'Este texto fue escrito principalmente para:\na) [Propósito correcto según tipo textual]\nb) [Opuesto al género]\nc) [Sin relación]\nd) [Detalle de contenido como propósito]',
        2: '¿Cuál es el PROPÓSITO PRINCIPAL del autor?\na) [Propósito inferido: persuadir/informar/entretener/describir]\nb) [Secundario o no principal]\nc) [Opuesto]\nd) [De otro texto similar]',
        3: 'Si este texto fuera leído por [audiencia diferente], ¿cómo cambiaría su propósito?\na) [Se mantiene, es inherente al texto]\nb) [Cambiaría según la audiencia]\nc) [Se volvería confuso]\nd) [Depende solo del lector]',
    },
    'Interpretar ideas implícitas y síntesis': {
        1: '¿Qué opinas sobre la actitud de [personaje]?\na) [Opinión simple + justificación personal]\nb) [Solo opinión sin justificar]\nc) [Solo repite texto sin opinar]\nd) [Sin relación al texto]',
        2: '¿Estás de acuerdo con la decisión de [personaje]?\na) [Sí/No + justificación basada EN EL TEXTO]\nb) [Solo experiencia personal]\nc) [Sin justificación]\nd) [No toma postura]',
        3: 'El título es "[X]". ¿Es adecuado? Fundamenta.\na) [Sí/No + justificación integrando info EXPLÍCITA e IMPLÍCITA]\nb) [Solo explícita]\nc) [Solo personal]\nd) [Sin fundamentar]',
    },
}

# Información curricular por tipo textual (Tabla UTP — para inyectar en prompts)
TIPO_TEXTUAL_INFO = {
    'cuento': {
        'definicion': 'Narración breve escrita por un autor identificable, con estructura narrativa clara y personajes definidos.',
        'estructura': 'Inicio (presentación), desarrollo (conflicto), desenlace (resolución), personajes, narrador, ambiente.',
        'frecuencia': 'Muy alta',
    },
    'cuento_folclorico': {
        'definicion': 'Narración tradicional de autor anónimo, transmitida oralmente. Incluye cuentos de hadas y maravillosos.',
        'estructura': 'Inicio típico ("Había una vez…"), desarrollo con elementos mágicos, final feliz, personajes arquetípicos, estructura repetitiva.',
        'frecuencia': 'Muy alta',
    },
    'fabula': {
        'definicion': 'Narración breve protagonizada por animales, que concluye con una enseñanza o moraleja explícita.',
        'estructura': 'Introducción breve, conflicto, moraleja explícita al final, personajes animales con rasgos humanos, estructura simple.',
        'frecuencia': 'Media',
    },
    'leyenda': {
        'definicion': 'Relato que mezcla elementos reales y maravillosos, vinculado a un lugar, cultura o hecho histórico.',
        'estructura': 'Ambientación real, elementos fantásticos, propósito explicativo, transmisión oral original, personajes históricos o míticos.',
        'frecuencia': 'Media',
    },
    'mito': {
        'definicion': 'Relato sagrado que explica el origen del mundo o fenómenos naturales, protagonizado por dioses o héroes culturales.',
        'estructura': 'Protagonistas divinos, tiempo remoto, propósito explicativo cosmogónico, estructura simbólica, pertenece a una cultura específica.',
        'frecuencia': 'Media',
    },
    'poema': {
        'definicion': 'Texto lírico que usa lenguaje especial (ritmo, rima, lenguaje figurado) para expresar emociones o crear imágenes.',
        'estructura': 'Versos, estrofas, rima (asonante o consonante) o verso libre, lenguaje figurado (metáforas, personificaciones, símiles).',
        'frecuencia': 'Alta',
    },
    'articulo_info': {
        'definicion': 'Texto expositivo que presenta información objetiva y verificable sobre un tema (ciencia, historia, naturaleza, tecnología).',
        'estructura': 'Título, subtítulos, introducción, desarrollo en párrafos, cierre, lenguaje objetivo, vocabulario específico.',
        'frecuencia': 'Muy alta',
    },
    'articulo_cient': {
        'definicion': 'Texto basado en investigación científica, adaptado para niños. Explica fenómenos, experimentos o descubrimientos.',
        'estructura': 'Título, introducción (pregunta/problema), metodología, resultados, conclusión, gráficos, tablas, glosario, lenguaje preciso.',
        'frecuencia': 'Media',
    },
    'noticia': {
        'definicion': 'Relato breve y objetivo de un suceso actual, relevante y verídico, con estructura de pirámide invertida.',
        'estructura': 'Titular, bajada, lead (qué/quién/cuándo/dónde), cuerpo, foto y epígrafe, fuente, fecha.',
        'frecuencia': 'Alta',
    },
    'infografia': {
        'definicion': 'Representación visual que combina imágenes, gráficos y textos breves para explicar un tema de manera sintética.',
        'estructura': 'Título, imágenes/ilustraciones, texto breve, gráficos/diagramas, iconos, flujo secuencial, paleta de colores.',
        'frecuencia': 'Media',
    },
    'instructivo': {
        'definicion': 'Texto que indica pasos a seguir para realizar una tarea, usar un objeto o resolver un problema.',
        'estructura': 'Título, lista de materiales o ingredientes, pasos numerados, verbos en imperativo, dibujos/diagramas, advertencias.',
        'frecuencia': 'Alta',
    },
    'receta': {
        'definicion': 'Tipo específico de instructivo que indica los pasos para preparar un plato o alimento.',
        'estructura': 'Título, porciones, tiempo de preparación, ingredientes con cantidades, pasos numerados en imperativo, consejos.',
        'frecuencia': 'Media',
    },
    'manual': {
        'definicion': 'Instructivo extenso y detallado para operar un aparato, armar un mueble o usar un software.',
        'estructura': 'Portada, índice, advertencias de seguridad, lista de partes con diagramas, pasos detallados, solución de problemas, glosario.',
        'frecuencia': 'Media',
    },
    'biografia': {
        'definicion': 'Narración de la vida de una persona real o de un acontecimiento histórico relevante.',
        'estructura': 'Introducción (presenta al personaje/hecho), orden cronológico, hitos relevantes, contexto histórico, cierre con legado, ilustraciones.',
        'frecuencia': 'Media',
    },
    'carta_formal': {
        'definicion': 'Texto epistolar formal dirigido a un destinatario específico con estructura definida.',
        'estructura': 'Fecha y lugar, saludo formal (Estimado…), cuerpo, despedida formal (Atentamente…), firma, posdata.',
        'frecuencia': 'Baja',
    },
    'carta_informal': {
        'definicion': 'Carta dirigida a personas cercanas con lenguaje coloquial y tono personal.',
        'estructura': 'Fecha, saludo coloquial (Querido…), cuerpo personal, despedida afectuosa, firma.',
        'frecuencia': 'Baja',
    },
    'afiche': {
        'definicion': 'Texto multimodal con propósito persuasivo: promover un producto, causa, evento o idea.',
        'estructura': 'Imagen central llamativa, título/eslogan, cuerpo breve, llamada a la acción, logo/marca, colores y tipografía impactantes.',
        'frecuencia': 'Media',
    },
}

HABILIDADES_POR_ASIGNATURA = {
    'lenguaje': _HAB_LENGUAJE,
    'matematica': [
        'Resolver operaciones numéricas en contexto',
        'Interpretar datos de tablas y gráficos',
        'Aplicar proporcionalidad y fracciones',
        'Razonar sobre figuras y medidas',
        'Modelar situaciones con operaciones matemáticas',
    ],
    'ciencias': [
        'Describir fenómenos naturales',
        'Interpretar resultados experimentales',
        'Relacionar causa y efecto en procesos naturales',
        'Aplicar conceptos científicos del nivel',
        'Evaluar e interpretar información científica',
    ],
    'historia': [
        'Identificar causas y consecuencias de procesos históricos',
        'Analizar e interpretar fuentes históricas y sociales',
        'Ubicar procesos en tiempo y espacio geográfico',
        'Comparar perspectivas de distintos actores',
        'Evaluar el impacto de procesos históricos en la actualidad',
    ],
}

FORMAT_SPECS = {
    'cuento': (
        "Estructura obligatoria: INICIO (presentación de personajes con nombre y contexto), "
        "NUDO (conflicto central bien definido), DESENLACE (resolución del conflicto). "
        "Narrador en 3ª o 1ª persona, coherente durante todo el texto. "
        "Personajes con nombre propio y características reconocibles. "
        "Lenguaje narrativo, párrafos bien desarrollados."
    ),
    'fabula': (
        "Personajes: animales con nombre propio que hablan y actúan como humanos. "
        "El conflicto debe tener una dimensión moral o ética clara. "
        "OBLIGATORIO: terminar con la MORALEJA escrita explícitamente así: 'Moraleja: [texto]'. "
        "Tono didáctico, lenguaje accesible al nivel del curso."
    ),
    'noticia': (
        "Formato periodístico estricto: "
        "1) TITULAR en mayúsculas. "
        "2) BAJADA: subtítulo que amplía el titular. "
        "3) LEAD: primer párrafo que responde QUÉ, QUIÉN, CUÁNDO, DÓNDE y POR QUÉ. "
        "4) CUERPO: desarrollo con más detalles. "
        "5) Mencionar al menos una fuente con nombre. "
        "Lenguaje objetivo, impersonal, sin opinión."
    ),
    'reportaje': (
        "Texto periodístico extenso y analítico. Incluir: "
        "título, subtítulo, introducción, desarrollo con múltiples ángulos, "
        "datos o citas textuales, conclusión reflexiva."
    ),
    'carta_formal': (
        "Formato obligatorio: lugar y fecha · destinatario con cargo · "
        "saludo formal · cuerpo con asunto claro · despedida formal · firma con cargo. "
        "Sin lenguaje coloquial."
    ),
    'carta_director': (
        "Carta al editor. Encabezado 'Carta al Director', referencia al medio, "
        "postura clara con al menos 2 razones, datos del remitente al final."
    ),
    'carta_informal': (
        "Entre personas cercanas. Saludo coloquial, relato personal emotivo, "
        "preguntas al destinatario, despedida afectuosa."
    ),
    'soneto': (
        "OBLIGATORIO: 14 versos en total, CADA VERSO EN SU PROPIA LÍNEA. "
        "2 cuartetos (4v) + 2 tercetos (3v), separados por línea en blanco. "
        "Rima consonante ABBA ABBA en cuartetos. Temática poética elaborada."
    ),
    'oda': (
        "FORMATO POÉTICO OBLIGATORIO: CADA VERSO EN SU PROPIA LÍNEA (no prosa). "
        "Al menos 10 estrofas de 4-6 versos, separadas por línea en blanco. "
        "Tono celebratorio. Lenguaje con metáforas e imágenes sensoriales."
    ),
    'discontinuo': (
        "TEXTO NO LINEAL: combina prosa con al menos DOS de: "
        "tabla Markdown (|Col|Col|), lista numerada o con viñetas, secciones con subtítulos. "
        "Datos organizados y fáciles de navegar."
    ),
    'infografia': (
        "TÍTULO en mayúsculas · 3-5 secciones con subtítulo · "
        "datos numéricos o porcentajes en cada sección · listas (no párrafos) · "
        "sección FUENTE al final."
    ),
    'instructivo': (
        "TÍTULO · sección MATERIALES con cantidades · "
        "PASOS numerados con verbos en IMPERATIVO · "
        "tiempo estimado o resultado esperado."
    ),
    'afiche': (
        "ESLOGAN en mayúsculas · subtítulo · puntos clave (no párrafos) · "
        "llamado a la acción · datos básicos (lugar/fecha/contacto)."
    ),
    'articulo_cient': (
        "Secciones: INTRODUCCIÓN (pregunta de investigación) · METODOLOGÍA · "
        "RESULTADOS (datos concretos) · DISCUSIÓN · CONCLUSIÓN. "
        "Lenguaje científico formal."
    ),
    'receta': (
        "NOMBRE del plato · PORCIONES y TIEMPO · "
        "INGREDIENTES con cantidades exactas · PREPARACIÓN numerada en imperativo."
    ),
    # Nuevos tipos (Tabla UTP)
    'cuento_folclorico': (
        "Narración tradicional anónima transmitida oralmente. "
        "OBLIGATORIO: inicio con fórmula típica ('Había una vez...'), desarrollo con elementos "
        "mágicos o maravillosos, personajes arquetípicos (héroe, villano, ayudante mágico), "
        "estructura repetitiva si corresponde, final feliz o moralizador. "
        "Lenguaje sencillo y oral."
    ),
    'leyenda': (
        "Relato que mezcla lo real y lo maravilloso. "
        "Ambientación en lugar real y reconocible (ciudad, río, montaña chilena o latinoamericana). "
        "Incluir elemento fantástico que explica un fenómeno o el origen de algo. "
        "Personajes históricos, míticos o mestizos. Tono solemne y épico."
    ),
    'mito': (
        "Relato sagrado de una cultura específica. Protagonistas: dioses, semidioses o héroes culturales. "
        "Tiempo remoto o primordial. Propósito: explicar el origen del mundo, de un fenómeno natural "
        "o de una práctica cultural. Estructura simbólica. Mencionar explícitamente la cultura de origen."
    ),
    'poema': (
        "FORMATO POÉTICO OBLIGATORIO: CADA VERSO EN SU PROPIA LÍNEA (no prosa). "
        "Al menos 4 estrofas de 4 versos, separadas por línea en blanco. "
        "Usar lenguaje figurado: metáforas, personificaciones o símiles visibles. "
        "Puede tener rima o ser verso libre. Expresar una emoción, imagen o reflexión central."
    ),
    'articulo_info': (
        "Texto expositivo con lenguaje objetivo. "
        "ESTRUCTURA: TÍTULO descriptivo · INTRODUCCIÓN al tema · "
        "2-3 párrafos de DESARROLLO con subtítulos (##) · CIERRE o conclusión. "
        "Vocabulario preciso pero accesible al nivel. Sin opinión del autor. "
        "Puede incluir listas o datos numéricos."
    ),
    'manual': (
        "Instructivo extenso. ESTRUCTURA OBLIGATORIA: "
        "1) PORTADA con nombre del manual. "
        "2) ADVERTENCIAS DE SEGURIDAD. "
        "3) LISTA DE PARTES o materiales con etiquetas (Parte 1, Parte 2…). "
        "4) PASOS numerados con verbos en imperativo. "
        "5) SOLUCIÓN DE PROBLEMAS (al menos 2 casos comunes). "
        "Lenguaje claro y directo."
    ),
    'biografia': (
        "Narración en prosa sobre una persona real relevante. "
        "ESTRUCTURA CRONOLÓGICA: INTRODUCCIÓN (¿quién es y por qué importa?) · "
        "ORIGEN Y FORMACIÓN · HITOS PRINCIPALES (al menos 3, con fechas) · "
        "LEGADO o impacto actual. Lenguaje formal pero accesible. "
        "Incluir contexto histórico o social."
    ),
}

SUBJECT_CONTEXT = {
    'lenguaje': (
        "Textos auténticos para comprensión lectora. "
        "Los estudiantes leerán y responderán preguntas sobre el texto."
    ),
    'matematica': (
        "CONTEXTOS DE SITUACIÓN PROBLEMÁTICA. No son textos literarios. "
        "Deben presentar datos numéricos, tablas o gráficos que permitan "
        "formular preguntas de cálculo, interpretación y razonamiento matemático."
    ),
    'ciencias': (
        "Fenómenos naturales, experimentos o procesos biológicos/físicos/químicos "
        "según las Bases Curriculares MINEDUC del nivel. "
        "Incluir datos observables y terminología científica básica."
    ),
    'historia': (
        "Eventos históricos, procesos sociales, geográficos o cívicos del temario SIMCE: "
        "historia de Chile, geografía nacional/latinoamericana, convivencia democrática. "
        "Apropiados para el pensamiento histórico del nivel."
    ),
}

COURSE_CONTEXT = {
    '4B': (
        "4° Básico (9-10 años). Vocabulario cotidiano y concreto. "
        "Oraciones simples. Temas cercanos a la experiencia del estudiante."
    ),
    '6B': (
        "6° Básico (11-12 años). Vocabulario más variado, algunos términos técnicos simples. "
        "Oraciones compuestas. Abstracción moderada."
    ),
}

CHECKLIST_POR_TIPO = {
    'cuento': [
        {'id': 'personajes', 'texto': 'Los personajes tienen nombre propio y características definidas'},
        {'id': 'estructura', 'texto': 'Tiene inicio, desarrollo (nudo) y desenlace'},
        {'id': 'conflicto',  'texto': 'Hay un conflicto central claro'},
        {'id': 'narrador',   'texto': 'El narrador es identificable y coherente'},
        {'id': 'vocabulario','texto': 'El vocabulario es apropiado para el nivel del curso'},
    ],
    'fabula': [
        {'id': 'animales',  'texto': 'Los personajes son animales con nombre que actúan como humanos'},
        {'id': 'conflicto', 'texto': 'El conflicto tiene una dimensión moral o ética clara'},
        {'id': 'moraleja',  'texto': 'La moraleja está escrita explícitamente al final'},
    ],
    'noticia': [
        {'id': 'titular',  'texto': 'Tiene titular informativo'},
        {'id': 'lead',     'texto': 'El primer párrafo responde: qué, quién, cuándo, dónde, por qué'},
        {'id': 'fuentes',  'texto': 'Menciona fuentes o actores con nombre'},
        {'id': 'objetivo', 'texto': 'El lenguaje es objetivo e impersonal'},
    ],
    'reportaje': [
        {'id': 'tema',      'texto': 'El tema es de interés público y relevante'},
        {'id': 'desarrollo','texto': 'Hay un desarrollo extenso con múltiples ángulos'},
        {'id': 'fuentes',   'texto': 'Menciona múltiples fuentes o perspectivas'},
        {'id': 'conclusion','texto': 'Tiene conclusión o cierre temático'},
    ],
    'oda': [
        {'id': 'versos',   'texto': '⚠ CRÍTICO: Está escrito en VERSOS (cada verso en línea separada)'},
        {'id': 'estrofas', 'texto': 'Los versos se agrupan en estrofas separadas por línea en blanco'},
        {'id': 'tono',     'texto': 'El tono es celebratorio o de admiración'},
        {'id': 'extension','texto': 'Tiene al menos 8 estrofas'},
    ],
    'soneto': [
        {'id': 'versos',    'texto': '⚠ CRÍTICO: Tiene exactamente 14 versos'},
        {'id': 'estructura','texto': '⚠ CRÍTICO: 2 cuartetos + 2 tercetos'},
        {'id': 'rima',      'texto': 'Hay rima consonante identificable'},
    ],
    'carta_formal': [
        {'id': 'encabezado',  'texto': 'Tiene lugar, ciudad y fecha al inicio'},
        {'id': 'destinatario','texto': 'El destinatario tiene nombre y/o cargo'},
        {'id': 'saludo',      'texto': 'Saludo formal'},
        {'id': 'despedida',   'texto': 'Despedida formal y firma'},
    ],
    'carta_director': [
        {'id': 'referencia', 'texto': 'Se identifica el medio al que se dirige'},
        {'id': 'argumento',  'texto': 'Hay un argumento central y postura clara'},
        {'id': 'evidencia',  'texto': 'Se aportan razones para sustentar la postura'},
        {'id': 'remitente',  'texto': 'Termina con los datos del remitente'},
    ],
    'carta_informal': [
        {'id': 'saludo',    'texto': 'El saludo es coloquial y cercano'},
        {'id': 'tono',      'texto': 'El tono es personal y emotivo'},
        {'id': 'despedida', 'texto': 'La despedida refleja la relación cercana'},
    ],
    'discontinuo': [
        {'id': 'no_lineal', 'texto': '⚠ CRÍTICO: Incluye elementos no lineales (tablas, listas, esquemas)'},
        {'id': 'datos',     'texto': 'Los datos están organizados claramente'},
    ],
    'infografia': [
        {'id': 'secciones',    'texto': 'Tiene secciones con subtítulos claros'},
        {'id': 'estadisticas', 'texto': 'Incluye estadísticas o datos numéricos'},
        {'id': 'fuente',       'texto': 'Menciona la fuente de los datos'},
    ],
    'instructivo': [
        {'id': 'materiales', 'texto': 'Lista materiales con cantidades'},
        {'id': 'pasos',      'texto': 'Los pasos están numerados'},
        {'id': 'imperativos','texto': 'Usa verbos en imperativo'},
    ],
    'afiche': [
        {'id': 'titulo',  'texto': 'Tiene eslogan llamativo'},
        {'id': 'mensaje', 'texto': 'El mensaje central es claro'},
        {'id': 'cta',     'texto': 'Incluye un llamado a la acción'},
    ],
    'articulo_cient': [
        {'id': 'pregunta',    'texto': 'Plantea una pregunta de investigación'},
        {'id': 'metodologia', 'texto': 'Describe cómo se realizó el estudio'},
        {'id': 'resultados',  'texto': 'Presenta resultados con datos concretos'},
        {'id': 'conclusion',  'texto': 'Hay una conclusión que responde la pregunta'},
    ],
    'receta': [
        {'id': 'nombre',       'texto': 'El nombre del plato está claro'},
        {'id': 'ingredientes', 'texto': 'Lista ingredientes con cantidades'},
        {'id': 'pasos',        'texto': 'Los pasos están numerados'},
    ],
    # Nuevos tipos (Tabla UTP)
    'cuento_folclorico': [
        {'id': 'formula',    'texto': 'Inicia con fórmula oral ("Había una vez…")'},
        {'id': 'magico',     'texto': 'Incluye elementos mágicos o maravillosos'},
        {'id': 'arquetipo',  'texto': 'Personajes arquetípicos identificables'},
        {'id': 'final',      'texto': 'Tiene final feliz o moralizador'},
    ],
    'leyenda': [
        {'id': 'lugar',      'texto': 'Ambientada en lugar real y reconocible'},
        {'id': 'fantastico', 'texto': 'Incluye elemento fantástico que explica algo'},
        {'id': 'origen',     'texto': 'El relato tiene propósito explicativo claro'},
    ],
    'mito': [
        {'id': 'cultura',    'texto': 'Se menciona la cultura de origen'},
        {'id': 'divino',     'texto': 'Protagonistas son dioses, semidioses o héroes culturales'},
        {'id': 'cosmogonia', 'texto': 'Explica el origen de algo (mundo, fenómeno, práctica)'},
    ],
    'poema': [
        {'id': 'versos',     'texto': '⚠ CRÍTICO: Escrito en versos (cada uno en línea propia)'},
        {'id': 'estrofas',   'texto': 'Los versos se agrupan en estrofas separadas'},
        {'id': 'figurado',   'texto': 'Usa al menos una figura literaria visible (metáfora, personificación, símil)'},
        {'id': 'emocion',    'texto': 'Expresa una emoción o imagen central reconocible'},
    ],
    'articulo_info': [
        {'id': 'subtitulos', 'texto': 'Tiene subtítulos que organizan la información'},
        {'id': 'objetivo',   'texto': 'El lenguaje es objetivo y sin opinión del autor'},
        {'id': 'cierre',     'texto': 'Tiene cierre o conclusión'},
    ],
    'manual': [
        {'id': 'advertencias', 'texto': 'Incluye advertencias de seguridad'},
        {'id': 'partes',       'texto': 'Lista las partes o materiales'},
        {'id': 'pasos',        'texto': 'Pasos numerados con verbos en imperativo'},
        {'id': 'problemas',    'texto': 'Tiene sección de solución de problemas'},
    ],
    'biografia': [
        {'id': 'intro',      'texto': 'Presenta quién es el personaje y por qué importa'},
        {'id': 'cronologia', 'texto': 'Sigue orden cronológico con al menos 3 hitos con fechas'},
        {'id': 'contexto',   'texto': 'Incluye contexto histórico o social'},
        {'id': 'legado',     'texto': 'Cierra con el legado o impacto del personaje'},
    ],
}


# ── FASE 1: Generar un texto para la Biblioteca ───────────────────

def generar_texto_biblioteca(asignatura, tipo_textual, dificultad, curso):
    """
    Genera UN texto y lo guarda como TextoBiblioteca (estado='pendiente').
    Retorna el objeto TextoBiblioteca creado.
    """
    from .models import TextoBiblioteca
    from .rag import buscar_contexto_simce

    context_rag = buscar_contexto_simce(asignatura, tipo_textual, n=4)
    spec         = FORMAT_SPECS.get(tipo_textual, 'Respetar la estructura clásica del tipo textual.')
    subject_ctx  = SUBJECT_CONTEXT.get(asignatura, '')
    course_ctx   = COURSE_CONTEXT.get(curso, COURSE_CONTEXT['6B'])
    dif_labels   = {1: 'Básico', 2: 'Intermedio', 3: 'Avanzado'}

    prompt = f"""Eres un experto en evaluación educativa SIMCE y Bases Curriculares de Chile.

CONTEXTO OFICIAL MINEDUC:
{context_rag}

ASIGNATURA: {asignatura.upper()} — {subject_ctx}
NIVEL DEL CURSO: {course_ctx}
DIFICULTAD DEL TEXTO: {dif_labels.get(dificultad, 'Intermedio')}

TAREA: Genera UN texto tipo '{tipo_textual}' para una prueba tipo SIMCE.

ESPECIFICACIONES DEL TIPO TEXTUAL:
{spec}

REQUISITOS:
- Mínimo 1500 caracteres sin espacios (requisito de validez SIMCE).
- Contenido original, no extraído de textos conocidos.
- Alineado con Bases Curriculares y temario SIMCE de la asignatura.
- Para textos poéticos (oda, soneto): OBLIGATORIO usar versos en líneas separadas, NO prosa.

Responde SOLO con JSON válido:
{{"titulo": "Título del texto", "contenido": "Texto completo aquí..."}}"""

    resp = client.chat.completions.create(
        model='deepseek-chat',
        messages=[{'role': 'user', 'content': prompt}],
        max_tokens=5000,
        temperature=0.7,
    )
    data = _cargar_json(resp.choices[0].message.content, 'la generación de texto')

    contenido = data['contenido']
    if len(contenido.replace(' ', '')) < 1500:
        contenido = _ampliar_texto(contenido, tipo_textual, asignatura, curso)

    checklist = CHECKLIST_POR_TIPO.get(tipo_textual, [])

    obj = TextoBiblioteca.objects.create(
        asignatura=asignatura,
        tipo_textual=tipo_textual,
        titulo=data.get('titulo', 'Sin título'),
        contenido=contenido,
        dificultad=dificultad,
        estado='pendiente',
        checklist_admin={item['id']: False for item in checklist},
    )
    return obj


def generar_lote_textos_biblioteca(asignatura, curso, n=6):
    """
    Genera N textos para la biblioteca para una asignatura/curso.
    Retorna lista de TextoBiblioteca. Puede lanzar excepción.
    """
    tipos_disponibles = TIPOS_POR_ASIGNATURA.get(asignatura, TIPOS_POR_ASIGNATURA['lenguaje'])
    tipos = random.sample(tipos_disponibles, min(n, len(tipos_disponibles)))
    if len(tipos) < n:
        extras = random.choices(tipos_disponibles, k=n - len(tipos))
        tipos += extras

    dificultades = [1] * (n // 3) + [2] * (n // 3) + [3] * (n - 2 * (n // 3))
    random.shuffle(dificultades)

    resultados = []
    for tipo, dif in zip(tipos, dificultades):
        obj = generar_texto_biblioteca(asignatura, tipo, dif, curso)
        resultados.append(obj)
    return resultados


# ── FASE 2: Generar preguntas para un texto del banco ─────────────

def _build_framework_lenguaje(tipo_textual):
    """
    Construye el bloque de texto del framework curricular UTP para inyectar en el prompt.
    """
    info = TIPO_TEXTUAL_INFO.get(tipo_textual, {})
    partes = []
    if info:
        partes.append(
            f"TIPO TEXTUAL: {tipo_textual}\n"
            f"Definición: {info['definicion']}\n"
            f"Estructura: {info['estructura']}\n"
            f"Frecuencia SIMCE: {info['frecuencia']}"
        )

    partes.append("\nEJES Y HABILIDADES SIMCE LENGUAJE:")
    for eje, habilidades in EJES_HABILIDADES_LENGUAJE.items():
        partes.append(f"  EJE {eje}: {' | '.join(habilidades)}")

    partes.append("\nPLANTILLAS DE PREGUNTA POR HABILIDAD (úsalas como modelo estructural):")
    for hab, niveles_dict in PLANTILLAS_HABILIDADES_LENGUAJE.items():
        partes.append(f"\n  [{hab}]")
        for nv, tmpl in niveles_dict.items():
            label = {1: 'Inicial', 2: 'Intermedio', 3: 'Avanzado'}[nv]
            partes.append(f"    Nivel {label}: {tmpl[:120]}…")

    return "\n".join(partes)


def generar_preguntas_banco(texto_obj, n_nivel1=1, n_nivel2=2, n_nivel3=3):
    """
    Genera preguntas para un TextoBiblioteca y las guarda en PreguntaBanco.
    Retorna lista de PreguntaBanco creados.
    """
    from .models import PreguntaBanco, AlternativaBanco

    asignatura  = texto_obj.asignatura
    habilidades = HABILIDADES_POR_ASIGNATURA.get(asignatura, HABILIDADES_POR_ASIGNATURA['lenguaje'])
    subject_ctx = SUBJECT_CONTEXT.get(asignatura, '')

    niveles = [1] * n_nivel1 + [2] * n_nivel2 + [3] * n_nivel3
    random.shuffle(niveles)
    n_total = len(niveles)

    alts_correctas = _distribuir_alternativas(n_total)

    # Framework curricular del UTP (solo lenguaje)
    framework_bloque = ""
    if asignatura == 'lenguaje':
        framework_bloque = f"\nFRAMEWORK CURRICULAR UTP:\n{_build_framework_lenguaje(texto_obj.tipo_textual)}\n"

    prompt = f"""Eres un experto en construcción de ítems SIMCE, Bases Curriculares Chile.

ASIGNATURA: {asignatura.upper()} — {subject_ctx}
{framework_bloque}
TEXTO DE REFERENCIA:
Tipo: {texto_obj.tipo_textual}
Título: {texto_obj.titulo}
Contenido:
{texto_obj.contenido}

TAREA: Crea exactamente {n_total} preguntas de selección múltiple para este texto.
Distribución de niveles: {niveles} (1=Inicial, 2=Intermedio, 3=Avanzado).
Alternativas correctas PRE-ASIGNADAS (en ese orden): {alts_correctas}.

REGLAS:
- 4 alternativas por pregunta (A, B, C, D), solo una correcta.
- Distractores plausibles, similar extensión a la correcta.
- Habilidades variadas de: {', '.join(habilidades)}.
- Para lenguaje: respetar los ejes SIMCE (LOCALIZAR / INTERPRETAR / REFLEXIONAR) y usar las plantillas como guía estructural.
- Para matemática: las preguntas deben requerir cálculo u operaciones sobre los datos del texto.
- Pista 1: orientación sutil sin revelar la respuesta.
- Pista 2: pista más directa pero que aún requiere razonamiento.
- Justifica brevemente habilidad y nivel (indicar eje SIMCE para lenguaje).

Responde SOLO con JSON válido:
{{"preguntas": [
  {{
    "enunciado": "¿Pregunta...?",
    "nivel": 3,
    "habilidad": "Nombre habilidad",
    "habilidad_justificacion": "...",
    "nivel_justificacion": "...",
    "alternativa_correcta": "B",
    "pista_1": "...",
    "pista_2": "...",
    "alternativas": [
      {{"letra": "A", "texto": "...", "es_correcta": false, "justificacion": "..."}},
      {{"letra": "B", "texto": "...", "es_correcta": true,  "justificacion": "..."}},
      {{"letra": "C", "texto": "...", "es_correcta": false, "justificacion": "..."}},
      {{"letra": "D", "texto": "...", "es_correcta": false, "justificacion": "..."}}
    ]
  }}
]}}"""

    resp = client.chat.completions.create(
        model='deepseek-chat',
        messages=[{'role': 'user', 'content': prompt}],
        max_tokens=6000,
        temperature=0.5,
    )
    data = _cargar_json(resp.choices[0].message.content, 'la generación de preguntas')

    creadas = []
    for p in data['preguntas']:
        alternativas = _barajar_alternativas(p.get('alternativas', []))
        correcta = next(
            (a['letra'] for a in alternativas if a.get('es_correcta')),
            p['alternativa_correcta'],
        )

        pregunta_obj = PreguntaBanco.objects.create(
            texto=texto_obj,
            enunciado=p['enunciado'],
            nivel=p['nivel'],
            habilidad=p['habilidad'],
            habilidad_justificacion=p.get('habilidad_justificacion', ''),
            nivel_justificacion=p.get('nivel_justificacion', ''),
            alternativa_correcta=correcta,
            pista_1=p.get('pista_1', ''),
            pista_2=p.get('pista_2', ''),
            estado='pendiente',
        )
        for alt in alternativas:
            AlternativaBanco.objects.create(
                pregunta=pregunta_obj,
                letra=alt['letra'],
                texto=alt['texto'],
                es_correcta=alt.get('es_correcta', False),
                justificacion=alt.get('justificacion', ''),
            )
        creadas.append(pregunta_obj)
    return creadas


def _barajar_alternativas(alternativas):
    """Reparte la alternativa correcta entre A-D en vez de dejarla donde la puso
    el modelo.

    El modelo la ponía sistemáticamente en D: seis de seis preguntas del primer
    ensayo real quedaron con la correcta en la misma letra. Eso lo detecta la
    propia rúbrica (`distribucion_alternativas` → `A:0 B:0 C:0 D:6`, no aprobada),
    así que ninguna prueba generada llegaba a publicarse — y para un estudiante un
    patrón así es una pista, no una evaluación.

    Se reordena el contenido y se reasignan las letras en orden; el texto de cada
    alternativa viaja con su `es_correcta`, así que nada queda desalineado.
    """
    if not alternativas:
        return []

    barajadas = list(alternativas)
    random.shuffle(barajadas)
    for letra, alt in zip('ABCD', barajadas):
        alt['letra'] = letra
    return barajadas


# ── FASE 3: Crear preguntas del test desde el banco ───────────────

def poblar_preguntas_prueba_texto(prueba_texto_obj):
    """
    Para un PruebaTexto dado, crea Pregunta+Alternativa usando:
    1. Preguntas aprobadas del banco (nivel matching n_nivel1/2/3)
    2. Si faltan, genera nuevas con IA y las añade al banco primero.
    Retorna lista de Pregunta creadas.
    """
    from .models import Pregunta, Alternativa, PreguntaBanco, AlternativaBanco

    texto   = prueba_texto_obj.texto
    n_req   = {1: prueba_texto_obj.n_nivel1, 2: prueba_texto_obj.n_nivel2, 3: prueba_texto_obj.n_nivel3}
    orden_actual = 0
    creadas = []

    for nivel in [1, 2, 3]:
        n = n_req[nivel]
        if n <= 0:
            continue

        banco_qs = PreguntaBanco.objects.filter(
            texto=texto, nivel=nivel, estado='aprobado'
        ).exclude(usos_en_pruebas__prueba_texto__prueba=prueba_texto_obj.prueba).order_by('?')[:n]
        banco_list = list(banco_qs)

        # Si faltan, generar nuevas
        faltantes = n - len(banco_list)
        if faltantes > 0:
            n1 = faltantes if nivel == 1 else 0
            n2 = faltantes if nivel == 2 else 0
            n3 = faltantes if nivel == 3 else 0
            nuevas = generar_preguntas_banco(texto, n1, n2, n3)
            for p in nuevas:
                p.estado = 'aprobado'
                p.save(update_fields=['estado'])
            banco_list += nuevas

        for pregunta_banco in banco_list[:n]:
            orden_actual += 1
            pregunta = Pregunta.objects.create(
                prueba_texto=prueba_texto_obj,
                desde_banco=pregunta_banco,
                orden=orden_actual,
                enunciado=pregunta_banco.enunciado,
                nivel=pregunta_banco.nivel,
                habilidad=pregunta_banco.habilidad,
                habilidad_justificacion=pregunta_banco.habilidad_justificacion,
                nivel_justificacion=pregunta_banco.nivel_justificacion,
                alternativa_correcta=pregunta_banco.alternativa_correcta,
                pista_1=pregunta_banco.pista_1,
                pista_2=pregunta_banco.pista_2,
            )
            for alt_banco in pregunta_banco.alternativas.all():
                Alternativa.objects.create(
                    pregunta=pregunta,
                    letra=alt_banco.letra,
                    texto=alt_banco.texto,
                    es_correcta=alt_banco.es_correcta,
                    justificacion=alt_banco.justificacion,
                )
            creadas.append(pregunta)

    rebalancear_alternativas(creadas)
    return creadas


def rebalancear_alternativas(preguntas):
    """Reparte las respuestas correctas entre A-D a lo largo de toda la prueba.

    Barajar cada pregunta por separado no alcanza: con 6 preguntas y azar, lo
    normal es que alguna letra quede en cero, y la rúbrica exige las cuatro
    (`distribucion_alternativas`). Se vio en la primera prueba real: A:3 B:1 C:0 D:2.

    Acá la letra objetivo se asigna en round-robin sobre el orden de la prueba, y
    después se permutan las alternativas de cada pregunta para que la correcta
    caiga ahí. El contenido no cambia: solo la letra con la que se rotula.
    """
    from .models import Alternativa

    objetivo = 'ABCD'
    for indice, pregunta in enumerate(preguntas):
        alternativas = list(pregunta.alternativas.all())
        if len(alternativas) != 4:
            continue  # sin las cuatro no hay nada que balancear

        letra_destino = objetivo[indice % 4]
        correcta = next((a for a in alternativas if a.es_correcta), None)
        if correcta is None or correcta.letra == letra_destino:
            continue

        # Intercambio en tres pasos y no en uno: hay `unique_together(pregunta,
        # letra)`, así que escribir las dos letras a la vez deja un instante con
        # la misma letra repetida y la base lo rechaza. La letra puente sale del
        # juego A-D justamente para no chocar con ninguna existente.
        ocupante = next(a for a in alternativas if a.letra == letra_destino)
        letra_original = correcta.letra

        ocupante.letra = '_'
        ocupante.save(update_fields=['letra'])
        correcta.letra = letra_destino
        correcta.save(update_fields=['letra'])
        ocupante.letra = letra_original
        ocupante.save(update_fields=['letra'])

        pregunta.alternativa_correcta = letra_destino
        pregunta.save(update_fields=['alternativa_correcta'])

    return preguntas


# ── Ajuste de texto (largo o dificultad) ─────────────────────────

def ajustar_texto(texto_obj, accion, curso='6B'):
    """
    Ajusta TextoBiblioteca según la acción.
    accion: 'aumentar_largo' | 'disminuir_largo' | 'aumentar_dificultad' | 'disminuir_dificultad'
    Retorna dict con titulo, contenido, char_count, word_count, dificultad.
    """
    tipo       = texto_obj.tipo_textual
    spec       = FORMAT_SPECS.get(tipo, 'Respetar la estructura clásica del tipo textual.')
    asignatura = texto_obj.asignatura
    dif_actual = texto_obj.dificultad
    dif_labels = {1: 'Básico', 2: 'Intermedio', 3: 'Avanzado'}

    if accion == 'aumentar_largo':
        instruccion    = "Reescribe el texto haciéndolo MÁS LARGO (al menos 400 caracteres adicionales)."
        nueva_dif      = dif_actual
    elif accion == 'disminuir_largo':
        instruccion    = "Reescribe el texto MÁS CORTO (mínimo 1500 caracteres sin espacios)."
        nueva_dif      = dif_actual
    elif accion == 'aumentar_dificultad':
        nueva_dif      = min(3, dif_actual + 1)
        instruccion    = f"Reescribe aumentando dificultad a {dif_labels[nueva_dif]}: vocabulario más técnico, oraciones más complejas."
    elif accion == 'disminuir_dificultad':
        nueva_dif      = max(1, dif_actual - 1)
        instruccion    = f"Reescribe reduciendo dificultad a {dif_labels[nueva_dif]}: vocabulario simple, oraciones cortas."
    else:
        raise ValueError(f'Acción desconocida: {accion}')

    prompt = f"""Eres un experto en textos educativos para SIMCE Chile.

TEXTO ORIGINAL (tipo '{tipo}', asignatura {asignatura}):
Título: {texto_obj.titulo}
{texto_obj.contenido}

ESPECIFICACIONES DEL TIPO:
{spec}

INSTRUCCIÓN: {instruccion}

REQUISITOS: Mantener mismo tipo textual y formato. Mínimo 1500 caracteres sin espacios.
Para textos poéticos: mantener formato en VERSOS.

Responde SOLO con JSON:
{{"titulo": "...", "contenido": "...", "dificultad": {nueva_dif}}}"""

    resp = client.chat.completions.create(
        model='deepseek-chat',
        messages=[{'role': 'user', 'content': prompt}],
        max_tokens=5000,
        temperature=0.6,
    )
    result = _cargar_json(resp.choices[0].message.content, 'el ajuste de texto')

    contenido = result['contenido']
    return {
        'titulo':     result.get('titulo', texto_obj.titulo),
        'contenido':  contenido,
        'char_count': len(contenido.replace(' ', '')),
        'word_count': len(contenido.split()),
        'dificultad': result.get('dificultad', nueva_dif),
    }


# ── Validación rúbrica de prueba ──────────────────────────────────

def validar_rubrica_prueba(prueba):
    """Valida la distribución de preguntas de una Prueba. Retorna dict rubrica."""
    from .models import Pregunta

    preguntas = list(Pregunta.objects.filter(prueba_texto__prueba=prueba))
    total     = len(preguntas)
    n_textos  = prueba.prueba_textos.count()
    niveles   = [p.nivel for p in preguntas]
    n1, n2, n3 = niveles.count(1), niveles.count(2), niveles.count(3)
    letras    = [p.alternativa_correcta for p in preguntas]
    dist      = {l: letras.count(l) for l in ['A', 'B', 'C', 'D']}
    habs      = len(set(p.habilidad for p in preguntas))

    rubrica = {
        'criterios': {
            'textos_configurados': {
                'ok': n_textos > 0,
                'detalle': f'{n_textos} texto(s) en la prueba',
            },
            'total_preguntas': {
                'ok': total > 0,
                'detalle': f'Total:{total} | Nivel1:{n1} Nivel2:{n2} Nivel3:{n3}',
            },
            'distribucion_alternativas': {
                'ok': all(v > 0 for v in dist.values()),
                'detalle': f"A:{dist['A']} B:{dist['B']} C:{dist['C']} D:{dist['D']}",
            },
            'cobertura_habilidades': {
                'ok': habs >= 3,
                'detalle': f'{habs} habilidades distintas',
            },
        },
        'aprobado': True,
        'observaciones': [],
    }

    for key, val in rubrica['criterios'].items():
        if not val['ok']:
            rubrica['aprobado'] = False
            rubrica['observaciones'].append(val['detalle'])

    return rubrica


# ── Helpers ───────────────────────────────────────────────────────

def _clean_json(text):
    """Deja el JSON del modelo en algo que `json.loads` pueda leer.

    Un LLM devuelve JSON casi válido, y el "casi" tumbaba la generación entera:
    una coma de más antes de un `}` reventaba con `JSONDecodeError` y el UTP veía
    la prueba en estado `error` sin explicación. Pasó en producción al armar el
    primer ensayo de demostración.

    Se corrigen solo defectos de formato, nunca contenido: si el modelo devolvió
    algo que no es JSON, tiene que seguir fallando.
    """
    text = (text or '').strip()

    # Vallas de código, con o sin etiqueta de lenguaje, en cualquier posición.
    text = re.sub(r'^```[a-zA-Z]*\s*', '', text)
    text = re.sub(r'\s*```$', '', text)

    # Prosa antes o después del objeto ("Aquí tienes el JSON:").
    inicio, fin = text.find('{'), text.rfind('}')
    if inicio > 0 or (fin != -1 and fin < len(text) - 1):
        if inicio != -1 and fin > inicio:
            text = text[inicio:fin + 1]

    # Comas finales antes de cerrar objeto o lista: el defecto más común.
    text = re.sub(r',(\s*[}\]])', r'\1', text)

    return text.strip()


def _cargar_json(raw, contexto=''):
    """`json.loads` con un segundo intento y un error que dice qué pasó.

    Sin esto, el traceback muestra la posición del carácter pero no el texto, y
    diagnosticar por qué falló una generación exige reproducirla entera.
    """
    limpio = _clean_json(raw)
    try:
        return json.loads(limpio)
    except json.JSONDecodeError as exc:
        # Último recurso: quedarse con el bloque balanceado más largo.
        recorte = limpio[:limpio.rfind('}') + 1] if '}' in limpio else limpio
        try:
            return json.loads(recorte)
        except json.JSONDecodeError:
            fragmento = limpio[max(0, exc.pos - 120):exc.pos + 120]
            raise ValueError(
                f"El modelo devolvió JSON inválido{' en ' + contexto if contexto else ''}: "
                f"{exc.msg} (posición {exc.pos}).\n…{fragmento}…"
            ) from exc


def _ampliar_texto(contenido, tipo_textual, asignatura, curso):
    spec = FORMAT_SPECS.get(tipo_textual, '')
    course_ctx = COURSE_CONTEXT.get(curso, '')
    prompt = (
        f"El texto tipo '{tipo_textual}' para {asignatura}/{curso} tiene menos de 1500 caracteres sin espacios. "
        f"Amplíalo conservando la estructura y tipo.\n\n{spec}\n\nTexto actual:\n{contenido}\n\n"
        "Responde SOLO con JSON: {\"contenido\": \"...\"}"
    )
    resp = client.chat.completions.create(
        model='deepseek-chat',
        messages=[{'role': 'user', 'content': prompt}],
        max_tokens=4000,
        temperature=0.6,
    )
    return _cargar_json(resp.choices[0].message.content, 'la ampliación de texto').get('contenido', contenido)


def _distribuir_alternativas(n):
    por_letra = n // 4
    pool = ['A'] * por_letra + ['B'] * por_letra + ['C'] * por_letra + ['D'] * (n - por_letra * 3)
    random.shuffle(pool)
    return pool
