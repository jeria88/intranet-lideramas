import json
import threading
import traceback
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Count, Avg, Q
from django.views.decorators.http import require_POST, require_http_methods

from .models import (
    Prueba, PruebaTexto, TextoBiblioteca, PreguntaBanco, AlternativaBanco,
    Pregunta, Alternativa, SesionEstudiante, RespuestaEstudiante,
    ASIGNATURA_CHOICES, CURSO_CHOICES, TIPO_TEXTUAL_CHOICES,
    NIVEL_CHOICES, DIFICULTAD_TEXTO, ALT_CHOICES,
)
from .generator import (
    generar_lote_textos_biblioteca, generar_preguntas_banco,
    poblar_preguntas_prueba_texto, ajustar_texto,
    validar_rubrica_prueba, CHECKLIST_POR_TIPO,
)

CURSOS_SIMCE = [('4B', '4° Básico'), ('6B', '6° Básico')]
def is_staff(u):
    """Quién puede administrar ensayos SIMCE.

    Se llamaba así porque solo dejaba pasar a `is_staff`, y eso dejaba fuera al
    UTP — que es justamente quien arma los ensayos y quien compra este módulo.
    Un colegio cliente no tiene usuarios `is_staff`: los crea el proveedor.

    Abrirlo a UTP y Director es seguro porque el alcance ya está resuelto en otra
    capa: el manager filtra por la organización del request, así que cada uno ve
    únicamente las pruebas de su propio colegio.

    El nombre se conserva para no tocar los 26 decoradores que lo usan.
    """
    if not u.is_authenticated:
        return False
    if u.is_staff or u.is_superuser:
        return True
    return u.role in ('UTP', 'DIRECTOR') and u.organizacion_id is not None


# ── Helpers de fondo ──────────────────────────────────────────────

def _set_error(prueba_pk, error_str, tb_str):
    from django.db import connection
    connection.close()
    try:
        prueba = Prueba.objects.get(pk=prueba_pk)
        prueba.estado = 'error'
        prueba.rubrica_log = {'error': error_str, 'traceback': tb_str}
        prueba.save()
    except Exception:
        pass


def _hilo_textos(prueba_pk, asignatura, curso, n_textos):
    from django.db import connection
    try:
        textos_obj = generar_lote_textos_biblioteca(asignatura, curso, n=n_textos)
        prueba = Prueba.objects.get(pk=prueba_pk)
        for i, texto in enumerate(textos_obj, 1):
            PruebaTexto.objects.get_or_create(
                prueba=prueba, texto=texto,
                defaults={'orden': i, 'n_nivel1': 1, 'n_nivel2': 2, 'n_nivel3': 3},
            )
        prueba.estado = 'borrador'
        prueba.save()
    except Exception as e:
        _set_error(prueba_pk, str(e), traceback.format_exc())
    finally:
        connection.close()


def _hilo_preguntas(prueba_pk):
    from django.db import connection
    try:
        prueba = Prueba.objects.get(pk=prueba_pk)
        for pt in prueba.prueba_textos.all():
            poblar_preguntas_prueba_texto(pt)

        rubrica = validar_rubrica_prueba(prueba)
        prueba.rubrica_ok  = rubrica['aprobado']
        prueba.rubrica_log = rubrica
        prueba.estado      = 'revision'
        prueba.save()
    except Exception as e:
        _set_error(prueba_pk, str(e), traceback.format_exc())
    finally:
        connection.close()


# ── Admin: Dashboard ──────────────────────────────────────────────

@login_required
@user_passes_test(is_staff)
def admin_dashboard(request):
    pruebas = Prueba.objects.all().annotate(
        n_sesiones=Count('sesiones', filter=Q(sesiones__completada=True))
    )
    ctx = {
        'pruebas':     pruebas,
        'asignaturas': ASIGNATURA_CHOICES,
        'cursos':      CURSOS_SIMCE,
    }
    return render(request, 'simce/admin_dashboard.html', ctx)


# ── Admin: Generar prueba (textos + preguntas) ────────────────────

@login_required
@user_passes_test(is_staff)
@require_POST
def admin_generar(request):
    asignatura = request.POST.get('asignatura')
    curso      = request.POST.get('curso')
    titulo     = request.POST.get('titulo', '').strip() or None
    try:
        n_textos = max(1, min(8, int(request.POST.get('n_textos', 3))))
    except (TypeError, ValueError):
        n_textos = 3

    if not asignatura or not curso:
        messages.error(request, 'Selecciona asignatura y curso.')
        return redirect('simce:admin_dashboard')

    prueba = Prueba.objects.create(
        titulo     = titulo or f'SIMCE {asignatura.title()} {curso} {timezone.now().year}',
        asignatura = asignatura,
        curso      = curso,
        estado     = 'generando_textos',
        creada_por = request.user,
    )

    threading.Thread(
        target=_hilo_textos,
        args=(prueba.pk, asignatura, curso, n_textos),
        daemon=True,
    ).start()

    return redirect('simce:prueba_generando', pk=prueba.pk)


# ── Admin: Página de espera ───────────────────────────────────────

@login_required
@user_passes_test(is_staff)
def prueba_generando(request, pk):
    prueba = get_object_or_404(Prueba, pk=pk)
    return render(request, 'simce/generando.html', {'prueba': prueba})


@login_required
@user_passes_test(is_staff)
def api_estado_prueba(request, pk):
    prueba = get_object_or_404(Prueba, pk=pk)
    log = prueba.rubrica_log if isinstance(prueba.rubrica_log, dict) else {}
    return JsonResponse({
        'estado':    prueba.estado,
        'titulo':    prueba.titulo,
        'error':     log.get('error', ''),
        'traceback': log.get('traceback', ''),
    })


# ── Admin: Revisar textos + configurar preguntas ──────────────────

@login_required
@user_passes_test(is_staff)
def admin_revisar_textos(request, pk):
    prueba = get_object_or_404(Prueba, pk=pk)
    prueba_textos = prueba.prueba_textos.select_related('texto').order_by('orden')

    items = []
    for pt in prueba_textos:
        texto   = pt.texto
        checklist = CHECKLIST_POR_TIPO.get(texto.tipo_textual, [])
        items.append({'pt': pt, 'texto': texto, 'checklist': checklist})

    n_aprobados = prueba_textos.filter(texto__estado='aprobado').count()
    ctx = {
        'prueba':      prueba,
        'items':       items,
        'n_aprobados': n_aprobados,
        'n_total':     prueba_textos.count(),
    }
    return render(request, 'simce/admin_revisar_textos.html', ctx)


# ── AJAX: Ajustar texto de la biblioteca ─────────────────────────

@login_required
@user_passes_test(is_staff)
@require_POST
def api_ajustar_texto(request, pk):
    texto  = get_object_or_404(TextoBiblioteca, pk=pk)
    accion = request.POST.get('accion', '')
    curso  = request.POST.get('curso', '6B')
    if accion not in ('aumentar_largo', 'disminuir_largo',
                      'aumentar_dificultad', 'disminuir_dificultad'):
        return JsonResponse({'error': 'accion_invalida'}, status=400)

    try:
        resultado = ajustar_texto(texto, accion, curso=curso)
        texto.titulo    = resultado['titulo']
        texto.contenido = resultado['contenido']
        texto.dificultad = resultado['dificultad']
        texto.estado     = 'pendiente'
        texto.save()
        return JsonResponse({
            'ok':               True,
            'titulo':           texto.titulo,
            'contenido':        texto.contenido,
            'char_count':       texto.char_count,
            'word_count':       texto.word_count,
            'dificultad':       texto.dificultad,
            'dificultad_display': texto.get_dificultad_display(),
            'cumple':           texto.cumple_extension(),
        })
    except Exception as e:
        return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)


# ── AJAX: Aprobar / rechazar texto ────────────────────────────────

@login_required
@user_passes_test(is_staff)
@require_POST
def api_estado_texto(request, pk):
    texto  = get_object_or_404(TextoBiblioteca, pk=pk)
    estado = request.POST.get('estado', '')
    if estado not in ('aprobado', 'rechazado', 'pendiente'):
        return JsonResponse({'error': 'estado_invalido'}, status=400)

    texto.estado = estado
    texto.save(update_fields=['estado'])

    # Cuenta aprobados para la prueba si viene con prueba_pk
    prueba_pk = request.POST.get('prueba_pk')
    n_aprobados = None
    n_total = None
    if prueba_pk:
        try:
            prueba = Prueba.objects.get(pk=prueba_pk)
            pts = prueba.prueba_textos.select_related('texto')
            n_aprobados = pts.filter(texto__estado='aprobado').count()
            n_total = pts.count()
        except Prueba.DoesNotExist:
            pass

    return JsonResponse({
        'ok':          True,
        'estado':      estado,
        'n_aprobados': n_aprobados,
        'n_total':     n_total,
    })


# ── Admin: Lanzar generación de preguntas ─────────────────────────

@login_required
@user_passes_test(is_staff)
@require_POST
def admin_lanzar_preguntas(request, pk):
    prueba = get_object_or_404(Prueba, pk=pk)

    # Actualizar configuración per-texto desde el form
    for pt in prueba.prueba_textos.all():
        try:
            n1 = max(0, int(request.POST.get(f'n1_{pt.pk}', pt.n_nivel1)))
            n2 = max(0, int(request.POST.get(f'n2_{pt.pk}', pt.n_nivel2)))
            n3 = max(0, int(request.POST.get(f'n3_{pt.pk}', pt.n_nivel3)))
        except (ValueError, TypeError):
            n1, n2, n3 = pt.n_nivel1, pt.n_nivel2, pt.n_nivel3
        PruebaTexto.objects.filter(pk=pt.pk).update(n_nivel1=n1, n_nivel2=n2, n_nivel3=n3)

    # Limpiar preguntas existentes
    Pregunta.objects.filter(prueba_texto__prueba=prueba).delete()

    prueba.estado = 'generando_preguntas'
    prueba.save(update_fields=['estado'])

    threading.Thread(
        target=_hilo_preguntas,
        args=(prueba.pk,),
        daemon=True,
    ).start()

    return redirect('simce:prueba_generando', pk=prueba.pk)


# ── Admin: Revisar prueba (preguntas) ─────────────────────────────

@login_required
@user_passes_test(is_staff)
def admin_revisar(request, pk):
    prueba = get_object_or_404(Prueba, pk=pk)
    prueba_textos = prueba.prueba_textos.select_related('texto').prefetch_related(
        'preguntas__alternativas'
    ).order_by('orden')
    ctx = {
        'prueba':       prueba,
        'prueba_textos': prueba_textos,
        'rubrica':      prueba.rubrica_log,
        'tipos_textuales': TIPO_TEXTUAL_CHOICES,
    }
    return render(request, 'simce/admin_revisar.html', ctx)


@login_required
@user_passes_test(is_staff)
@require_POST
def admin_aprobar(request, pk):
    prueba = get_object_or_404(Prueba, pk=pk)
    prueba.estado       = 'aprobada'
    prueba.aprobada_por = request.user
    prueba.aprobada_en  = timezone.now()
    prueba.save()
    messages.success(request, f'Prueba aprobada: {prueba.titulo}')
    return redirect('simce:admin_dashboard')


@login_required
@user_passes_test(is_staff)
@require_POST
def admin_publicar(request, pk):
    prueba = get_object_or_404(Prueba, pk=pk)
    prueba.estado = 'publicada'
    prueba.save()
    messages.success(request, 'Prueba publicada. Los estudiantes ya pueden acceder.')
    return redirect('simce:admin_dashboard')


@login_required
@user_passes_test(is_staff)
@require_POST
def admin_eliminar(request, pk):
    prueba = get_object_or_404(Prueba, pk=pk)
    titulo = prueba.titulo
    prueba.delete()
    messages.success(request, f'Prueba eliminada: {titulo}')
    return redirect('simce:admin_dashboard')


# ── Biblioteca de Textos (CRUD independiente) ─────────────────────

@login_required
@user_passes_test(is_staff)
def biblioteca_list(request):
    asignatura_f = request.GET.get('asignatura', '')
    textos = TextoBiblioteca.objects.all()
    if asignatura_f:
        textos = textos.filter(asignatura=asignatura_f)

    ctx = {
        'textos':      textos.annotate(n_banco=Count('preguntas_banco')),
        'asignaturas': ASIGNATURA_CHOICES,
        'cursos':      CURSOS_SIMCE,
        'filtro_asignatura': asignatura_f,
    }
    return render(request, 'simce/biblioteca_list.html', ctx)


@login_required
@user_passes_test(is_staff)
@require_POST
def biblioteca_generar(request):
    asignatura = request.POST.get('asignatura')
    curso      = request.POST.get('curso')
    try:
        n_textos = max(1, min(8, int(request.POST.get('n_textos', 3))))
    except (TypeError, ValueError):
        n_textos = 3
    if not asignatura or not curso:
        messages.error(request, 'Selecciona asignatura y curso.')
        return redirect('simce:biblioteca_list')

    def _hilo(asig, cur, n):
        from django.db import connection
        try:
            generar_lote_textos_biblioteca(asig, cur, n=n)
        except Exception as e:
            print(f'[biblioteca_generar] error: {e}')
        finally:
            connection.close()

    threading.Thread(target=_hilo, args=(asignatura, curso, n_textos), daemon=True).start()
    messages.success(request, f'Generando {n_textos} textos para {asignatura}/{curso}. Aparecerán en esta página en breve.')
    return redirect('simce:biblioteca_list')


@login_required
@user_passes_test(is_staff)
def biblioteca_texto_detalle(request, pk):
    import json as _json
    texto = get_object_or_404(TextoBiblioteca, pk=pk)
    preguntas_banco = texto.preguntas_banco.prefetch_related('alternativas').order_by('nivel', 'creada_en')
    checklist = CHECKLIST_POR_TIPO.get(texto.tipo_textual, [])
    preguntas_json = _json.dumps([
        {
            'pk':   p.pk,
            'enunciado': p.enunciado,
            'nivel': p.nivel,
            'habilidad': p.habilidad,
            'alternativa_correcta': p.alternativa_correcta,
            'alts': {a.letra: a.texto for a in p.alternativas.all()},
        }
        for p in preguntas_banco
    ], ensure_ascii=False)
    ctx = {
        'texto':           texto,
        'preguntas_banco': preguntas_banco,
        'preguntas_json':  preguntas_json,
        'checklist':       checklist,
        'cursos':          CURSOS_SIMCE,
    }
    return render(request, 'simce/biblioteca_texto_detalle.html', ctx)


@login_required
@user_passes_test(is_staff)
@require_POST
def api_generar_preguntas_banco(request, pk):
    texto = get_object_or_404(TextoBiblioteca, pk=pk)
    try:
        n1 = max(0, int(request.POST.get('n_nivel1', 1)))
        n2 = max(0, int(request.POST.get('n_nivel2', 2)))
        n3 = max(0, int(request.POST.get('n_nivel3', 3)))
    except (TypeError, ValueError):
        n1, n2, n3 = 1, 2, 3

    try:
        creadas = generar_preguntas_banco(texto, n1, n2, n3)
        return JsonResponse({'ok': True, 'n_creadas': len(creadas)})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_staff)
@require_POST
def api_pregunta_banco_estado(request, pk):
    pregunta = get_object_or_404(PreguntaBanco, pk=pk)
    estado   = request.POST.get('estado', '')
    if estado not in ('aprobado', 'rechazado', 'pendiente'):
        return JsonResponse({'error': 'estado_invalido'}, status=400)
    pregunta.estado = estado
    pregunta.save(update_fields=['estado'])
    return JsonResponse({'ok': True, 'estado': estado})


# ── Biblioteca: CRUD TextoBiblioteca ─────────────────────────────

@login_required
@user_passes_test(is_staff)
def biblioteca_texto_crear(request):
    if request.method == 'POST':
        asignatura   = request.POST.get('asignatura', '').strip()
        tipo_textual = request.POST.get('tipo_textual', '').strip()
        titulo       = request.POST.get('titulo', '').strip()
        contenido    = request.POST.get('contenido', '').strip()
        try:
            dificultad = int(request.POST.get('dificultad', 2))
        except (TypeError, ValueError):
            dificultad = 2
        if asignatura and tipo_textual and titulo and contenido:
            texto = TextoBiblioteca.objects.create(
                asignatura=asignatura,
                tipo_textual=tipo_textual,
                titulo=titulo,
                contenido=contenido,
                dificultad=dificultad,
                word_count=len(contenido.split()),
                char_count=len(contenido),
                creada_por=request.user,
            )
            return redirect('simce:biblioteca_texto_detalle', pk=texto.pk)
    ctx = {
        'asignaturas':    ASIGNATURA_CHOICES,
        'tipos_textuales': TIPO_TEXTUAL_CHOICES,
        'dificultades':   DIFICULTAD_TEXTO,
        'editando': False,
    }
    return render(request, 'simce/biblioteca_texto_form.html', ctx)


@login_required
@user_passes_test(is_staff)
def biblioteca_texto_editar(request, pk):
    texto = get_object_or_404(TextoBiblioteca, pk=pk)
    if request.method == 'POST':
        texto.asignatura   = request.POST.get('asignatura', texto.asignatura)
        texto.tipo_textual = request.POST.get('tipo_textual', texto.tipo_textual)
        texto.titulo       = request.POST.get('titulo', texto.titulo).strip()
        texto.contenido    = request.POST.get('contenido', texto.contenido).strip()
        try:
            texto.dificultad = int(request.POST.get('dificultad', texto.dificultad))
        except (TypeError, ValueError):
            pass
        texto.word_count = len(texto.contenido.split())
        texto.char_count = len(texto.contenido)
        texto.save()
        return redirect('simce:biblioteca_texto_detalle', pk=texto.pk)
    ctx = {
        'texto':           texto,
        'asignaturas':    ASIGNATURA_CHOICES,
        'tipos_textuales': TIPO_TEXTUAL_CHOICES,
        'dificultades':   DIFICULTAD_TEXTO,
        'editando': True,
    }
    return render(request, 'simce/biblioteca_texto_form.html', ctx)


@login_required
@user_passes_test(is_staff)
@require_POST
def biblioteca_texto_eliminar(request, pk):
    texto = get_object_or_404(TextoBiblioteca, pk=pk)
    texto.delete()
    return redirect('simce:biblioteca_list')


# ── Biblioteca: CRUD PreguntaBanco ───────────────────────────────

@login_required
@user_passes_test(is_staff)
@require_POST
def pregunta_banco_crear(request, texto_pk):
    texto      = get_object_or_404(TextoBiblioteca, pk=texto_pk)
    enunciado  = request.POST.get('enunciado', '').strip()
    habilidad  = request.POST.get('habilidad', '').strip()
    try:
        nivel = int(request.POST.get('nivel', 1))
    except (TypeError, ValueError):
        nivel = 1
    alternativa_correcta = request.POST.get('alternativa_correcta', 'A')
    if not enunciado:
        return JsonResponse({'ok': False, 'error': 'Enunciado requerido'}, status=400)
    pregunta = PreguntaBanco.objects.create(
        texto=texto,
        enunciado=enunciado,
        nivel=nivel,
        habilidad=habilidad,
        alternativa_correcta=alternativa_correcta,
        estado='pendiente',
    )
    for letra in ['A', 'B', 'C', 'D']:
        alt_texto = request.POST.get(f'alt_{letra}', '').strip()
        AlternativaBanco.objects.create(
            pregunta=pregunta,
            letra=letra,
            texto=alt_texto,
            es_correcta=(letra == alternativa_correcta),
        )
    return JsonResponse({'ok': True, 'pk': pregunta.pk})


@login_required
@user_passes_test(is_staff)
@require_POST
def api_pregunta_banco(request, pk):
    pregunta = get_object_or_404(PreguntaBanco, pk=pk)
    accion   = request.POST.get('accion', '')
    if accion == 'eliminar':
        pregunta.delete()
        return JsonResponse({'ok': True})
    # editar
    pregunta.enunciado  = request.POST.get('enunciado', pregunta.enunciado).strip()
    pregunta.habilidad  = request.POST.get('habilidad', pregunta.habilidad).strip()
    try:
        pregunta.nivel = int(request.POST.get('nivel', pregunta.nivel))
    except (TypeError, ValueError):
        pass
    alt_correcta = request.POST.get('alternativa_correcta', pregunta.alternativa_correcta)
    pregunta.alternativa_correcta = alt_correcta
    pregunta.save()
    for letra in ['A', 'B', 'C', 'D']:
        alt_texto = request.POST.get(f'alt_{letra}', '').strip()
        if alt_texto:
            AlternativaBanco.objects.filter(pregunta=pregunta, letra=letra).update(
                texto=alt_texto,
                es_correcta=(letra == alt_correcta),
            )
    return JsonResponse({'ok': True})


# ── Admin: Crear test desde biblioteca ───────────────────────────

@login_required
@user_passes_test(is_staff)
def admin_crear_test(request):
    if request.method == 'GET':
        asignatura_f = request.GET.get('asignatura', '')
        textos_aprobados = TextoBiblioteca.objects.filter(estado='aprobado')
        if asignatura_f:
            textos_aprobados = textos_aprobados.filter(asignatura=asignatura_f)
        ctx = {
            'textos':      textos_aprobados.annotate(n_banco_aprobado=Count(
                'preguntas_banco', filter=Q(preguntas_banco__estado='aprobado')
            )),
            'asignaturas': ASIGNATURA_CHOICES,
            'cursos':      CURSOS_SIMCE,
            'filtro_asignatura': asignatura_f,
        }
        return render(request, 'simce/admin_crear_test.html', ctx)

    # POST: crear prueba con textos seleccionados
    asignatura = request.POST.get('asignatura')
    curso      = request.POST.get('curso')
    titulo     = request.POST.get('titulo', '').strip()
    textos_ids = [int(x) for x in request.POST.getlist('textos_ids') if x.isdigit()]

    if not asignatura or not curso or not textos_ids:
        messages.error(request, 'Selecciona asignatura, curso y al menos un texto.')
        return redirect('simce:admin_crear_test')

    prueba = Prueba.objects.create(
        titulo     = titulo or f'SIMCE {asignatura.title()} {curso} {timezone.now().year}',
        asignatura = asignatura,
        curso      = curso,
        estado     = 'generando_preguntas',
        creada_por = request.user,
    )

    textos_qs = TextoBiblioteca.objects.filter(pk__in=textos_ids, asignatura=asignatura)
    for i, texto in enumerate(textos_qs, 1):
        key = f'texto_{texto.pk}'
        try:
            n1 = max(0, int(request.POST.get(f'{key}_n1', 1)))
            n2 = max(0, int(request.POST.get(f'{key}_n2', 2)))
            n3 = max(0, int(request.POST.get(f'{key}_n3', 3)))
        except (TypeError, ValueError):
            n1, n2, n3 = 1, 2, 3
        PruebaTexto.objects.create(
            prueba=prueba, texto=texto, orden=i,
            n_nivel1=n1, n_nivel2=n2, n_nivel3=n3,
        )

    threading.Thread(target=_hilo_preguntas, args=(prueba.pk,), daemon=True).start()
    return redirect('simce:prueba_generando', pk=prueba.pk)


# ── Estudiante: Identificación ────────────────────────────────────

def prueba_identificacion(request, pk, modo='simce'):
    # `Prueba.todos` y no `Prueba.objects`: el estudiante rinde sin cuenta, así que
    # es anónimo y no tiene organización. Con el manager filtrado, toda prueba le
    # daría 404 aunque el link sea correcto y esté publicada. Lo que autoriza el
    # acceso acá es `estado='publicada'`, no la pertenencia a una organización.
    prueba = get_object_or_404(Prueba.todos, pk=pk, estado='publicada')
    if modo not in ('simce', 'pistas'):
        modo = 'simce'

    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        rut    = request.POST.get('rut', '').strip()
        curso  = request.POST.get('curso')
        letra  = request.POST.get('letra')
        estab  = request.POST.get('establecimiento', '').strip()
        rbd    = request.POST.get('rbd', '').strip()
        if not all([nombre, rut, curso, letra, estab]):
            messages.error(request, 'Completa todos los campos obligatorios.')
        else:
            sesion = SesionEstudiante.objects.create(
                prueba=prueba, nombre=nombre, rut=rut,
                curso=curso, letra_curso=letra,
                establecimiento=estab, rbd=rbd, modo=modo,
                sede=_resolver_sede(prueba, estab),
            )
            return redirect('simce:prueba_rendir', sesion_pk=sesion.pk)

    ctx = {
        'prueba': prueba,
        'cursos': CURSO_CHOICES,
        'modo': modo,
        'sedes': _sedes_de_la_prueba(prueba),
    }
    return render(request, 'simce/prueba_identificacion.html', ctx)


def _sedes_de_la_prueba(prueba):
    """Sedes entre las que puede elegir quien rinde: las de la organización dueña."""
    from users.models import Establecimiento

    if not prueba.organizacion_id:
        return []
    return list(
        Establecimiento.objects
        .filter(organizacion_id=prueba.organizacion_id, activo=True)
        .values_list('codigo', 'nombre')
    )


def _resolver_sede(prueba, declarado):
    """Traduce lo que escribió el estudiante a una sede real, si coincide.

    Nunca inventa: si no hay coincidencia queda `None` y el reporte lo agrupa
    aparte, en vez de asignarle un colegio que el estudiante no dijo.
    """
    from users.models import Establecimiento

    if not (prueba.organizacion_id and declarado):
        return None
    return Establecimiento.objects.filter(
        organizacion_id=prueba.organizacion_id,
        codigo=declarado.strip().upper(),
    ).first()


# ── Estudiante: Rendir prueba ─────────────────────────────────────

def prueba_rendir(request, sesion_pk):
    sesion = get_object_or_404(SesionEstudiante, pk=sesion_pk, completada=False)
    prueba = sesion.prueba
    prueba_textos = prueba.prueba_textos.select_related('texto').prefetch_related(
        'preguntas__alternativas'
    ).order_by('orden')

    respondidas = {
        r.pregunta_id: {
            'puntaje': r.puntaje_obtenido,
            'intentos': r.intentos,
            'correcta': r.alternativa_elegida.es_correcta if r.alternativa_elegida else False,
            'letra_elegida': r.alternativa_elegida.letra if r.alternativa_elegida else None,
        }
        for r in sesion.respuestas.select_related('alternativa_elegida').all()
    }

    total_preguntas = Pregunta.objects.filter(prueba_texto__prueba=prueba).count()

    ctx = {
        'sesion':         sesion,
        'prueba':         prueba,
        'prueba_textos':  prueba_textos,
        'respondidas_json': json.dumps(respondidas),
        'total_preguntas': total_preguntas,
        'modo':           sesion.modo,
    }
    return render(request, 'simce/prueba_rendir.html', ctx)


# ── AJAX: Verificar respuesta ─────────────────────────────────────

@require_POST
def verificar_respuesta(request, sesion_pk, pregunta_pk):
    sesion   = get_object_or_404(SesionEstudiante, pk=sesion_pk, completada=False)
    pregunta = get_object_or_404(Pregunta, pk=pregunta_pk, prueba_texto__prueba=sesion.prueba)

    if sesion.respuestas.filter(pregunta=pregunta).exists():
        return JsonResponse({'error': 'ya_respondida'}, status=400)

    letra = request.POST.get('letra', '').upper()
    if letra not in ['A', 'B', 'C', 'D']:
        return JsonResponse({'error': 'letra_invalida'}, status=400)

    sesion_key    = f'simce_{sesion_pk}_{pregunta_pk}_intentos'
    intento_actual = request.session.get(sesion_key, 0) + 1
    request.session[sesion_key] = intento_actual

    alternativa = pregunta.alternativas.filter(letra=letra).first()
    es_correcta = alternativa and alternativa.es_correcta
    puntaje_map = {1: 4, 2: 3, 3: 2}

    if es_correcta:
        puntaje = puntaje_map.get(intento_actual, 2)
        RespuestaEstudiante.objects.create(
            sesion=sesion, pregunta=pregunta,
            alternativa_elegida=alternativa,
            intentos=intento_actual, puntaje_obtenido=puntaje,
        )
        del request.session[sesion_key]
        return JsonResponse({'resultado': 'correcto', 'puntaje': puntaje, 'intentos': intento_actual})

    if intento_actual >= 3:
        correcta_alt = pregunta.alternativas.filter(es_correcta=True).first()
        RespuestaEstudiante.objects.create(
            sesion=sesion, pregunta=pregunta,
            alternativa_elegida=alternativa,
            intentos=3, puntaje_obtenido=0,
        )
        del request.session[sesion_key]
        return JsonResponse({
            'resultado': 'fallido', 'puntaje': 0, 'intentos': 3,
            'letra_correcta': correcta_alt.letra if correcta_alt else pregunta.alternativa_correcta,
        })

    pista = pregunta.pista_1 if intento_actual == 1 else pregunta.pista_2
    return JsonResponse({
        'resultado': 'incorrecto',
        'intento': intento_actual,
        'pista': pista or '💡 Vuelve a leer el texto con atención.',
        'intentos_restantes': 3 - intento_actual,
    })


# ── Estudiante: Finalizar ─────────────────────────────────────────

@require_POST
def finalizar_prueba(request, sesion_pk):
    sesion    = get_object_or_404(SesionEstudiante, pk=sesion_pk, completada=False)
    preguntas = Pregunta.objects.filter(prueba_texto__prueba=sesion.prueba)

    respondidas_ids = set(sesion.respuestas.values_list('pregunta_id', flat=True))
    for p in preguntas:
        if p.pk not in respondidas_ids:
            RespuestaEstudiante.objects.create(
                sesion=sesion, pregunta=p,
                alternativa_elegida=None, intentos=0, puntaje_obtenido=0,
            )

    sesion.calcular_puntajes()
    return JsonResponse({'redirect': f'/simce/resultado/{sesion.pk}/'}, status=200)


@require_POST
def entregar_simce(request, sesion_pk):
    sesion    = get_object_or_404(SesionEstudiante, pk=sesion_pk, completada=False)
    preguntas = Pregunta.objects.filter(prueba_texto__prueba=sesion.prueba)

    for pregunta in preguntas:
        letra       = request.POST.get(f'p_{pregunta.pk}')
        alternativa = pregunta.alternativas.filter(letra=letra).first() if letra else None
        es_correcta = alternativa.es_correcta if alternativa else False
        RespuestaEstudiante.objects.update_or_create(
            sesion=sesion, pregunta=pregunta,
            defaults={
                'alternativa_elegida': alternativa,
                'intentos': 1,
                'puntaje_obtenido': 1 if es_correcta else 0,
            }
        )

    sesion.calcular_puntajes()
    return redirect('simce:prueba_resultado', sesion_pk=sesion.pk)


# ── Estudiante: Resultado ─────────────────────────────────────────

def prueba_resultado(request, sesion_pk):
    sesion     = get_object_or_404(SesionEstudiante, pk=sesion_pk, completada=True)
    respuestas = sesion.respuestas.select_related(
        'pregunta', 'pregunta__prueba_texto__texto', 'alternativa_elegida'
    ).order_by('pregunta__orden')
    ctx = {'sesion': sesion, 'respuestas': respuestas}
    return render(request, 'simce/prueba_resultado.html', ctx)


# ── CRUD API ──────────────────────────────────────────────────────

@login_required
@user_passes_test(is_staff)
@require_http_methods(['GET', 'POST', 'DELETE'])
def api_texto(request, pk):
    texto = get_object_or_404(TextoBiblioteca, pk=pk)

    if request.method == 'GET':
        return JsonResponse({
            'pk': texto.pk, 'titulo': texto.titulo,
            'tipo_textual': texto.tipo_textual,
            'contenido': texto.contenido,
            'char_count': texto.char_count,
        })

    if request.method == 'POST':
        texto.titulo       = request.POST.get('titulo', texto.titulo).strip()
        texto.tipo_textual = request.POST.get('tipo_textual', texto.tipo_textual)
        texto.contenido    = request.POST.get('contenido', texto.contenido).strip()
        texto.save()
        return JsonResponse({
            'ok': True, 'titulo': texto.titulo,
            'tipo_textual_display': texto.get_tipo_textual_display(),
            'char_count': texto.char_count,
            'cumple': texto.cumple_extension(),
        })

    # DELETE — solo si no está en ninguna prueba publicada
    if texto.usos_en_pruebas.filter(prueba__estado='publicada').exists():
        return JsonResponse({'error': 'texto_en_prueba_publicada'}, status=403)
    texto.delete()
    return JsonResponse({'ok': True})


@login_required
@user_passes_test(is_staff)
@require_http_methods(['GET', 'POST', 'DELETE'])
def api_pregunta(request, pk):
    pregunta = get_object_or_404(Pregunta, pk=pk)

    if request.method == 'GET':
        alts = {a.letra: {'texto': a.texto, 'justificacion': a.justificacion}
                for a in pregunta.alternativas.all()}
        return JsonResponse({
            'pk': pregunta.pk, 'enunciado': pregunta.enunciado,
            'nivel': pregunta.nivel, 'habilidad': pregunta.habilidad,
            'alternativa_correcta': pregunta.alternativa_correcta,
            'pista_1': pregunta.pista_1, 'pista_2': pregunta.pista_2,
            'alternativas': alts,
        })

    if request.method == 'POST':
        pregunta.enunciado            = request.POST.get('enunciado', pregunta.enunciado).strip()
        pregunta.nivel                = int(request.POST.get('nivel', pregunta.nivel))
        pregunta.habilidad            = request.POST.get('habilidad', pregunta.habilidad).strip()
        pregunta.alternativa_correcta = request.POST.get('alternativa_correcta', pregunta.alternativa_correcta)
        pregunta.pista_1              = request.POST.get('pista_1', pregunta.pista_1).strip()
        pregunta.pista_2              = request.POST.get('pista_2', pregunta.pista_2).strip()
        pregunta.save()

        for letra in ['A', 'B', 'C', 'D']:
            texto_alt = request.POST.get(f'alt_{letra}', '').strip()
            if texto_alt:
                alt = pregunta.alternativas.filter(letra=letra).first()
                if alt:
                    alt.texto      = texto_alt
                    alt.es_correcta = (letra == pregunta.alternativa_correcta)
                    alt.save()
        pregunta.alternativas.exclude(letra=pregunta.alternativa_correcta).update(es_correcta=False)
        pregunta.alternativas.filter(letra=pregunta.alternativa_correcta).update(es_correcta=True)

        return JsonResponse({'ok': True, 'nivel': pregunta.nivel,
                             'nivel_estrellas': pregunta.nivel_estrellas(),
                             'alternativa_correcta': pregunta.alternativa_correcta})

    # DELETE
    if pregunta.prueba_texto.prueba.estado != 'revision':
        return JsonResponse({'error': 'solo_en_revision'}, status=403)
    if pregunta.prueba_texto.preguntas.count() <= 1:
        return JsonResponse({'error': 'minimo_una_pregunta'}, status=400)
    pregunta.delete()
    return JsonResponse({'ok': True})


@login_required
@user_passes_test(is_staff)
@require_http_methods(['DELETE', 'POST'])
def api_sesion(request, pk):
    sesion = get_object_or_404(SesionEstudiante, pk=pk)
    prueba_pk = sesion.prueba.pk
    sesion.delete()
    return JsonResponse({'ok': True, 'prueba_pk': prueba_pk})


# ── Reportes ──────────────────────────────────────────────────────

@login_required
def reportes_dashboard(request):
    pruebas = Prueba.objects.filter(estado__in=['publicada', 'cerrada']).annotate(
        n_sesiones=Count('sesiones', filter=Q(sesiones__completada=True)),
        promedio_logro=Avg('sesiones__porcentaje_logro', filter=Q(sesiones__completada=True)),
        promedio_simce=Avg('sesiones__puntaje_simce', filter=Q(sesiones__completada=True)),
    )
    asignatura_f = request.GET.get('asignatura', '')
    curso_f      = request.GET.get('curso', '')
    if asignatura_f:
        pruebas = pruebas.filter(asignatura=asignatura_f)
    if curso_f:
        pruebas = pruebas.filter(curso=curso_f)

    ctx = {
        'pruebas': pruebas, 'asignaturas': ASIGNATURA_CHOICES, 'cursos': CURSO_CHOICES,
        'filtros': {'asignatura': asignatura_f, 'curso': curso_f},
    }
    return render(request, 'simce/reportes_dashboard.html', ctx)


@login_required
def reporte_prueba(request, pk):
    prueba   = get_object_or_404(Prueba, pk=pk)
    sesiones = SesionEstudiante.objects.filter(prueba=prueba, completada=True)

    estab_f = request.GET.get('establecimiento', '')
    curso_f = request.GET.get('curso', '')
    letra_f = request.GET.get('letra', '')
    if estab_f: sesiones = sesiones.filter(establecimiento=estab_f)
    if curso_f: sesiones = sesiones.filter(curso=curso_f)
    if letra_f: sesiones = sesiones.filter(letra_curso=letra_f)

    preguntas = Pregunta.objects.filter(prueba_texto__prueba=prueba).order_by('orden')
    analisis  = []
    for p in preguntas:
        resp_p = RespuestaEstudiante.objects.filter(sesion__in=sesiones, pregunta=p)
        total  = resp_p.count()
        correctas = resp_p.filter(alternativa_elegida__es_correcta=True).count()
        dist = {l: resp_p.filter(alternativa_elegida__letra=l).count() for l in 'ABCD'}
        analisis.append({
            'pregunta': p, 'total': total, 'correctas': correctas,
            'pct_logro': round(correctas / total * 100, 1) if total else 0,
            'dist': dist,
        })

    ctx = {
        'prueba': prueba, 'sesiones': sesiones, 'analisis': analisis,
        'establecimientos': sesiones.values_list('establecimiento', flat=True).distinct(),
        'cursos': CURSO_CHOICES,
        'filtros': {'establecimiento': estab_f, 'curso': curso_f, 'letra': letra_f},
        'promedio_logro': sesiones.aggregate(p=Avg('porcentaje_logro'))['p'] or 0,
        'promedio_simce': sesiones.aggregate(p=Avg('puntaje_simce'))['p'] or 0,
    }
    return render(request, 'simce/reporte_prueba.html', ctx)


@login_required
def reporte_estudiante(request, sesion_pk):
    sesion     = get_object_or_404(SesionEstudiante, pk=sesion_pk, completada=True)
    respuestas = sesion.respuestas.select_related(
        'pregunta', 'pregunta__prueba_texto__texto',
        'alternativa_elegida',
    ).prefetch_related('pregunta__alternativas').order_by('pregunta__orden')
    ctx = {'sesion': sesion, 'respuestas': respuestas}
    return render(request, 'simce/reporte_estudiante.html', ctx)
