"""
Protocolos inyectables para asistentes IA v2 — Red LiderA+.

Cada protocolo es un bloque de texto que se inserta dinámicamente en el mensaje
del usuario cuando las palabras clave de su consulta lo activan.

Arquitectura: el modelo recibe el protocolo como contexto adicional ANTES de la
pregunta, no como regla en el system prompt. Esto evita la dilución de atención
que ocurre cuando hay 150 reglas en el sistema.
"""

# ---------------------------------------------------------------------------
# PROTOCOLOS UTP
# ---------------------------------------------------------------------------

PACI_INCUMPLIDO = """
### PROTOCOLO ACTIVO: PACI INCUMPLIDO
El docente no aplicó las adecuaciones del PACI. Esto es de competencia exclusiva de la UTP.

ACCIONES OBLIGATORIAS:
1. Solicita al docente una explicación escrita del incumplimiento (plazo: 48 horas).
2. Revisa el PACI vigente del estudiante con el educador diferencial.
3. Emite una indicación escrita al docente con las adecuaciones que debe aplicar retroactivamente.
4. Si el incumplimiento afectó calificaciones: invalida la nota y solicita nueva evaluación con adecuaciones.
5. Registra el incidente en el expediente del estudiante y en el registro UTP.

VEREDICTO OBLIGATORIO: indica explícitamente si la calificación afectada debe o no anularse.
"""

TRASPASO_PACI = """
### PROTOCOLO ACTIVO: TRASPASO INCORRECTO / PACI NO TRANSFERIDO
El PACI del estudiante no fue aplicado correctamente al cambiar de nivel, curso o establecimiento.

ACCIONES OBLIGATORIAS:
1. Localiza el PACI anterior y verifica su vigencia con el educador diferencial.
2. Convoca reunión entre UTP, educador diferencial y docente jefe para actualizar el PACI.
3. Notifica a todos los docentes del estudiante sobre las adecuaciones vigentes (por escrito).
4. Si hubo evaluaciones sin adecuaciones: invalida las notas y programa nuevas instancias.
5. Informa al apoderado por escrito sobre la regularización.

VEREDICTO OBLIGATORIO: indica explícitamente si las calificaciones anteriores deben o no anularse.
"""

INSTRUMENTO_PIE = """
### PROTOCOLO ACTIVO: DOCENTE NO CALIFICA INSTRUMENTO PIE
Un docente se niega a calificar o no califica el instrumento adaptado del estudiante PIE.

ACCIONES OBLIGATORIAS:
1. Cita al docente y al educador diferencial a una reunión de coordinación PIE.
2. Recuérdales por escrito que las adecuaciones de acceso y curriculares del PIE son de aplicación obligatoria.
3. Establece un plazo máximo de 5 días hábiles para que el docente regularice la calificación.
4. Si el docente persiste en no calificar: escala a la Dirección para medida administrativa.
5. Registra toda la gestión en el expediente del estudiante.

VEREDICTO OBLIGATORIO: la calificación del instrumento PIE sí debe registrarse; si el docente se
niega, la nota pendiente no puede mantenerse indefinidamente.
"""

DESCUENTO_CRITERIO_AJENO = """
### PROTOCOLO ACTIVO: DESCUENTO POR CRITERIO AJENO A LA ASIGNATURA
Un docente descontó puntos por un criterio que no corresponde a los objetivos de su asignatura
(ej. ortografía en Matemática, presentación en Educación Física).

ACCIONES OBLIGATORIAS:
1. Responde PRIMERO la pregunta directa: ¿puede el docente descontar por ESE criterio en ESA asignatura? SÍ o NO.
2. Si NO puede: indica que la nota debe restituirse y proporciona el plazo (máximo 5 días hábiles).
3. Emite instrucción escrita al docente con los criterios de evaluación permitidos para esa asignatura.
4. Si el docente se niega a restituir: escala a Dirección para resolución administrativa.

VEREDICTO OBLIGATORIO (primera línea de tu respuesta al fondo):
"VEREDICTO: ¿Puede el docente descontar por [criterio] en [asignatura]? NO / SÍ. [Razón breve]."
"VEREDICTO: ¿Debe restituirse la nota? SÍ / NO."
"""

NEE_INFRACCION = """
### PROTOCOLO ACTIVO: ESTUDIANTE CON NEE SIN DIAGNÓSTICO FORMAL
Se detecta un estudiante con posibles necesidades educativas especiales que no tiene evaluación ni diagnóstico formal.

ACCIONES OBLIGATORIAS:
1. Aplica medidas provisionales de apoyo mientras se gestiona el diagnóstico (no esperes el diagnóstico para actuar).
2. Solicita evaluación al educador diferencial del establecimiento.
3. Deriva al equipo de apoyo (psicólogo, fonoaudiólogo) si está disponible.
4. Informa al apoderado sobre el proceso y solicita su autorización para la evaluación especializada.
5. Registra las medidas provisionales adoptadas en el expediente del estudiante.

INSTRUCCIÓN: No uses lenguaje condicional. Indica qué DEBE hacerse, no qué "podría" hacerse.
"""

# ---------------------------------------------------------------------------
# PROTOCOLOS INSPECTOR
# ---------------------------------------------------------------------------

PELEA_FISICA = """
### PROTOCOLO ACTIVO: PELEA FÍSICA CON LESIONES
Situación de urgencia con riesgo físico. Este protocolo es de competencia exclusiva del Inspector/a General.

ACCIONES OBLIGATORIAS EN ORDEN:
1. Separa a los involucrados de inmediato; asegura la integridad física de todos.
2. Llama a servicios de emergencia (SAMU / carabineros) si hay lesiones visibles.
3. Notifica al Director/a del establecimiento.
4. Llama a los apoderados de todos los involucrados.
5. Registra el incidente con testigos y documenta lesiones (fotografías si procede).
6. Inicia el procedimiento disciplinario según el reglamento interno.
7. Si hay indicios de delito: activa protocolo de denuncia obligatoria.
"""

DENUNCIA_OBLIGATORIA = """
### PROTOCOLO ACTIVO: DENUNCIA OBLIGATORIA
Situación que puede constituir delito (VIF, abuso sexual, maltrato grave). La denuncia es obligatoria por ley.

ACCIONES OBLIGATORIAS:
1. No investigues ni cuestiones el relato del estudiante: escucha y registra.
2. Informa al Director/a de inmediato.
3. Realiza la denuncia ante Carabineros, PDI o Fiscalía dentro de las 24 horas siguientes.
4. No confrontes al presunto agresor ni lo informes del relato.
5. Garantiza la seguridad del estudiante mientras dure el proceso.
6. Registra todas las acciones con hora y fecha.
"""

# ---------------------------------------------------------------------------
# PROTOCOLO CONVIVENCIA
# ---------------------------------------------------------------------------

BULLYING_CIBERACOSO = """
### PROTOCOLO ACTIVO: BULLYING O CIBERACOSO
Situación de hostigamiento sostenido. Este protocolo es de competencia exclusiva del/la Encargado/a de Convivencia.

ACCIONES OBLIGATORIAS:
1. Entrevista por separado a la víctima, al agresor y a los testigos (no los enfrentes).
2. Documenta los hechos con fechas, lugares y evidencia (capturas si es ciberbullying).
3. Informa a los apoderados de ambas partes.
4. Aplica las medidas del reglamento de convivencia: desde reflexión hasta derivación disciplinaria.
5. Si hay riesgo para la integridad del estudiante: notifica al Inspector/a General para medidas disciplinarias paralelas.
6. Establece un plan de seguimiento semanal por al menos 4 semanas.
"""

# ---------------------------------------------------------------------------
# PROTOCOLO DIRECTOR
# ---------------------------------------------------------------------------

APODERADO_AMENAZANTE = """
### PROTOCOLO ACTIVO: APODERADO AMENAZANTE O AGRESIVO
Situación que involucra a un apoderado que amenaza o agrede a un funcionario del establecimiento.

ACCIONES OBLIGATORIAS (Director/a ejecuta personalmente):
1. Retira al apoderado del espacio escolar de inmediato; si se resiste, llama a Carabineros.
2. Documenta el incidente con testigos y hora exacta.
3. Notifica al sostenedor y al Representante Legal del establecimiento.
4. Evalúa con el Representante Legal si procede denuncia por amenazas o agresión.
5. Emite medida de restricción de acceso al establecimiento si corresponde.
6. Informa al docente o funcionario afectado sobre el respaldo institucional y las acciones tomadas.
"""

# ---------------------------------------------------------------------------
# Tabla de detección de protocolo por rol
# ---------------------------------------------------------------------------

_PROTOCOLO_MAP: list[dict] = [
    # UTP
    {
        'protocolo': PACI_INCUMPLIDO,
        'roles': {'UTP'},
        'keywords': ['paci', 'adecuación curricular', 'adecuacion curricular',
                     'plan de adecuación', 'plan de adecuacion', 'incumplió', 'incumplió el paci',
                     'no aplicó', 'no aplico', 'no respetó el paci', 'no respeto el paci',
                     'incumplido', 'no siguió el paci'],
    },
    {
        'protocolo': TRASPASO_PACI,
        'roles': {'UTP'},
        'keywords': ['traspaso', 'cambio de nivel', 'cambio de curso', 'traslado',
                     'paci no fue transferido', 'paci no estaba', 'paci anterior',
                     'nuevo colegio', 'nuevo establecimiento', 'vino de otro'],
    },
    {
        'protocolo': INSTRUMENTO_PIE,
        'roles': {'UTP'},
        'keywords': ['pie', 'instrumento pie', 'carpeta pie', 'no califica', 'no calificó',
                     'no quiere calificar', 'se niega a calificar', 'no evalúa',
                     'programa de integración', 'educación diferencial'],
    },
    {
        'protocolo': DESCUENTO_CRITERIO_AJENO,
        'roles': {'UTP'},
        'keywords': ['descuento', 'descontó', 'descontó puntos', 'ortografía en',
                     'caligrafía en', 'presentación en', 'criterio ajeno',
                     'descuento por', 'restituir nota', 'anular nota', 'anular calificación'],
    },
    {
        'protocolo': NEE_INFRACCION,
        'roles': {'UTP'},
        'keywords': ['nee', 'necesidades educativas especiales', 'sin diagnóstico',
                     'sin diagnostico', 'sin evaluación formal', 'posible tea',
                     'posible tdah', 'posible nee', 'sospecha de', 'derivar a evaluación',
                     'no tiene diagnóstico'],
    },
    # Inspector
    {
        'protocolo': PELEA_FISICA,
        'roles': {'INSPECTOR'},
        'keywords': ['pelea', 'pelea física', 'pelea fisica', 'golpes', 'agresión física',
                     'agresion fisica', 'lesiones', 'herido', 'herida', 'sangre',
                     'urgencia', 'emergencia', 'riesgo físico', 'riesgo fisico',
                     'hospitalizar', 'samu', 'ambulancia'],
    },
    {
        'protocolo': DENUNCIA_OBLIGATORIA,
        'roles': {'INSPECTOR'},
        'keywords': ['denuncia', 'denuncia obligatoria', 'vif', 'violencia intrafamiliar',
                     'abuso sexual', 'maltrato', 'carabineros', 'pdi', 'fiscalía',
                     'fiscalia', 'delito', 'agresión sexual', 'agresion sexual'],
    },
    # Convivencia
    {
        'protocolo': BULLYING_CIBERACOSO,
        'roles': {'CONVIVENCIA'},
        'keywords': ['bullying', 'acoso', 'hostigamiento', 'ciberacoso', 'redes sociales',
                     'intimidación', 'intimidacion', 'matonaje', 'insultos repetidos',
                     'exclusión social', 'exclusion social', 'violencia psicológica',
                     'violencia psicologica', 'rice'],
    },
    # Director
    {
        'protocolo': APODERADO_AMENAZANTE,
        'roles': {'DIRECTOR'},
        'keywords': ['apoderado amenaza', 'apoderado agresivo', 'apoderado violento',
                     'amenaza al docente', 'amenazó', 'amenazó al', 'agredió',
                     'amenaza de', 'apoderado se puso', 'apoderado alterado',
                     'apoderado golpeó', 'apoderado insultó'],
    },
]


def detectar_protocolo(role_code: str, query: str) -> str | None:
    """
    Retorna el bloque de protocolo que aplica para el rol y la consulta dada.
    Si no hay match, retorna None (no se inyecta nada).

    role_code debe ser uno de: 'UTP', 'INSPECTOR', 'CONVIVENCIA', 'DIRECTOR', 'REPRESENTANTE'
    """
    q_lower = query.lower()
    for entry in _PROTOCOLO_MAP:
        if role_code not in entry['roles']:
            continue
        if any(kw in q_lower for kw in entry['keywords']):
            return entry['protocolo']
    return None
