from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import ImprovementGoal, RiskAlert, ImprovementAction
from users.models import User
from django.db.models import Count
from django.contrib import messages
from .utils import generate_cycle_content_ai
from meetings.models import MeetingRoom, MeetingBooking
from users.scoping import establecimientos_de


@login_required
def dashboard_ee(request):
    """Dashboard universal para ver todas las metas de mejora."""
    goals = ImprovementGoal.objects.all()
    all_alerts = RiskAlert.objects.filter(is_active=True)
    # Por ahora mostramos todas las alertas
    alerts = all_alerts
    return render(request, 'improvement_cycle/dashboard_ee.html', {
        'goals': goals,
        'alerts': alerts,
        'establishment': 'Todos los Establecimientos',
    })


# dashboard_red eliminado según requerimiento


@login_required
def alertas_activas(request):
    alerts = RiskAlert.objects.filter(is_active=True).order_by('-triggered_at')
    return render(request, 'improvement_cycle/alertas.html', {'alerts': alerts})


@login_required
def meta_crear(request):
    if not request.user.is_staff:
        messages.error(request, "Solo el administrador puede realizar esta acción.")
        return redirect('improvement_cycle:dashboard_ee')
    
    ee_initial = request.user.establishment or 'RED'

    if request.method == 'POST':
        ee = request.user.establishment or 'RED'
        target_val = 100.0  # Default value as we removed it from UI
        
        objectives = request.POST.getlist('strategic_objectives[]')
        # Limpiar objetivos vacíos
        objectives = [obj.strip() for obj in objectives if obj.strip()]

        has_objectives = bool(objectives)
        goal = ImprovementGoal.objects.create(
            establishment=ee,
            profile_role=request.user.role or '',
            subvention_type='SEP',  # Default since we removed it
            title=request.POST.get('title', ''),
            description=request.POST.get('description', ''),
            strategic_objectives=objectives,
            is_meeting_cycle=request.POST.get('is_meeting_cycle') == 'on',
            target_value=target_val,
            measurement_unit='%',
            deadline=request.POST.get('deadline'),
            created_by=request.user,
            is_generating=has_objectives,  # Solo True si hay objetivos que generar
        )

        # Generar contenido IA sincrónicamente — Gunicorn tiene timeout 300s, DeepSeek tarda ~10s
        if has_objectives:
            generate_cycle_content_ai(goal)  # Incluye create_meeting_default_actions si is_meeting_cycle
            messages.success(request, "Ciclo de mejora creado con plan de acción generado por IA.")
        elif goal.is_meeting_cycle:
            # Sin objetivos estratégicos, pero es un ciclo de reunión: crear acciones de seguimiento
            from improvement_cycle.utils import create_meeting_default_actions
            create_meeting_default_actions(goal)
            messages.success(request, "Ciclo de reunión creado. Agenda la videollamada para activar el seguimiento.")
        
        # Sincronizar con Calendario
        try:
            from calendar_red.models import CalendarEvent
            CalendarEvent.objects.create(
                title=f"Meta: {goal.title}",
                description=f"Plazo para cumplir meta de mejora: {goal.description}",
                event_date=goal.deadline,
                event_type='interno',
                applies_to_roles=[goal.profile_role] if goal.profile_role else [],
                applies_to_establishments=[goal.establishment] if goal.establishment else [],
                created_by=request.user
            )
        except Exception as e:
            print(f"Error sincronizando calendario: {e}")

        if goal.is_meeting_cycle:
            return redirect('improvement_cycle:goal_agendar_reunion', pk=goal.pk)
        return redirect(f'/mejora/?ee={ee or "RED"}')


    return render(request, 'improvement_cycle/meta_form.html', {
        'establishments': establecimientos_de(request.user),
        'roles': User.ROLE_CHOICES,
        'ee_initial': ee_initial,
        'initial_title': request.GET.get('title', ''),
        'initial_description': request.GET.get('description', ''),
    })


@login_required
def goal_detail(request, pk):
    try:
        goal = get_object_or_404(ImprovementGoal, pk=pk)
        actions = goal.actions.all()
        can_edit = True # Habilitado para todos los usuarios según requerimiento

        
        return render(request, 'improvement_cycle/goal_detail.html', {
            'goal': goal,
            'actions': actions,
            'can_edit': request.user.is_staff,
        })
    except Exception as e:
        messages.error(request, f"Error al cargar el detalle: {str(e)}")
        return redirect('improvement_cycle:dashboard_ee')


@login_required
def goal_edit(request, pk):
    if not request.user.is_staff:
        messages.error(request, "Solo el administrador puede realizar esta acción.")
        return redirect('improvement_cycle:dashboard_ee')
    goal = get_object_or_404(ImprovementGoal, pk=pk)


    if request.method == 'POST':
        from django.utils import timezone
        import json
        
        changes = []
        old_title = goal.title
        old_desc = goal.description
        
        # Procesar Título y Descripción
        new_title = request.POST.get('title')
        new_desc = request.POST.get('description')
        if new_title != old_title:
            changes.append(f"Título: '{old_title}' → '{new_title}'")
            goal.title = new_title
        if new_desc != old_desc:
            changes.append("Descripción general modificada")
            goal.description = new_desc
            
        if request.POST.get('deadline'):
            goal.deadline = request.POST.get('deadline')

        # Procesar Etapas (Ruta de Proceso)
        etapas_titulos = request.POST.getlist('etapa_titulo[]')
        etapas_descripciones = request.POST.getlist('etapa_descripcion[]')
        new_route = []
        for t, d in zip(etapas_titulos, etapas_descripciones):
            if t.strip():
                new_route.append({'etapa': t, 'descripcion': d})
        
        if json.dumps(new_route) != json.dumps(goal.process_route):
            changes.append("Estrategia del Ciclo (etapas) modificada")
            goal.process_route = new_route

        # Procesar Indicadores
        ind_names = request.POST.getlist('indicator_name[]')
        ind_targets = request.POST.getlist('indicator_target[]')
        new_indicators = []
        for n, t in zip(ind_names, ind_targets):
            if n.strip():
                new_indicators.append({'name': n, 'target': t})
        
        if json.dumps(new_indicators) != json.dumps(goal.indicators):
            changes.append("Indicadores de logro modificados")
            goal.indicators = new_indicators

        if changes:
            history_entry = {
                'user': request.user.get_full_name() or request.user.username,
                'date': timezone.now().strftime("%d/%m/%Y %H:%M"),
                'changes': changes
            }
            if not goal.edit_history:
                goal.edit_history = []
            goal.edit_history.append(history_entry)
            
        goal.save()
        messages.success(request, "Meta de mejora y estrategia actualizadas correctamente.")
        return redirect('improvement_cycle:goal_detail', pk=goal.pk)

    return render(request, 'improvement_cycle/meta_edit.html', {
        'goal': goal,
    })


@login_required
def action_create(request, goal_pk):
    if not request.user.is_staff:
        messages.error(request, "Solo el administrador puede realizar esta acción.")
        return redirect('improvement_cycle:dashboard_ee')
    goal = get_object_or_404(ImprovementGoal, pk=goal_pk)


    if request.method == 'POST':
        responsible_id = request.POST.get('responsible')
        responsible = User.objects.get(id=responsible_id) if responsible_id else None
        
        ImprovementAction.objects.create(
            goal=goal,
            responsible=responsible,
            title=request.POST.get('title'),
            description=request.POST.get('description', ''),
            evidence=request.POST.get('evidence', ''),
            deadline=request.POST.get('deadline'),
            weight=float(request.POST.get('weight', 1)),
            status='pendiente'
        )
        messages.success(request, "Acción creada correctamente.")
        return redirect('improvement_cycle:goal_detail', pk=goal.pk)

    users = User.objects.filter(establishment=goal.establishment, is_active=True)
    return render(request, 'improvement_cycle/action_form.html', {
        'goal': goal,
        'users': users,
    })


@login_required
def action_toggle(request, pk):
    action = get_object_or_404(ImprovementAction, pk=pk)

    if action.status == 'completado':
        action.status = 'pendiente'
        action.completed_by = None
        action.completed_at = None
    else:
        action.status = 'completado'
        action.completed_by = request.user
        action.completed_at = timezone.now()
    action.save()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        from django.http import JsonResponse
        completed_label = ''
        if action.completed_by:
            name = action.completed_by.get_full_name() or action.completed_by.username
            date = action.completed_at.strftime('%d/%m/%Y %H:%M')
            completed_label = f'{name} · {date}'
        return JsonResponse({
            'status': action.status,
            'new_progress': action.goal.progress_pct,
            'summary': action.goal.actions_summary,
            'completed_label': completed_label,
        })

    messages.success(request, f"Estado de '{action.title}' actualizado.")
    return redirect('improvement_cycle:goal_detail', pk=action.goal.pk)

@login_required
def goal_delete(request, pk):
    """Elimina una meta de mejora (solo admin)."""
    if not request.user.is_staff:
        messages.error(request, "Solo el administrador puede realizar esta acción.")
        return redirect('improvement_cycle:dashboard_ee')
    goal = get_object_or_404(ImprovementGoal, pk=pk)


    if request.method == 'POST':
        ee = goal.establishment
        goal.delete()
        messages.success(request, "Meta de mejora eliminada correctamente.")
        return redirect(f'/mejora/?ee={ee or "RED"}')
    
    return render(request, 'improvement_cycle/goal_confirm_delete.html', {'goal': goal})


@login_required
def goal_agendar_reunion(request, pk):
    """Crea una reserva de videollamada y la vincula al ciclo de mejora."""
    if not (request.user.is_staff or request.user.is_red_team):
        messages.error(request, "Sin permiso.")
        return redirect('improvement_cycle:goal_detail', pk=pk)

    goal = get_object_or_404(ImprovementGoal, pk=pk)
    rooms = MeetingRoom.objects.filter(room_type='daily').order_by('name')

    if request.method == 'POST':
        room_pk = request.POST.get('room')
        scheduled_str = request.POST.get('scheduled_at')
        agenda = request.POST.get('agenda', '').strip() or goal.title

        room = get_object_or_404(MeetingRoom, pk=room_pk)
        from datetime import datetime
        try:
            scheduled_at = timezone.make_aware(datetime.fromisoformat(scheduled_str))
        except (ValueError, TypeError):
            messages.error(request, "Fecha y hora inválidas.")
            return render(request, 'improvement_cycle/goal_agendar_reunion.html',
                          {'goal': goal, 'rooms': rooms})

        from calendar_red.models import CalendarEvent
        event = CalendarEvent.objects.create(
            title=f"Videollamada: {room.name}",
            description=f"Agenda: {agenda}",
            event_date=scheduled_at.date(),
            event_time=scheduled_at.time(),
            event_type='interno',
            applies_to_roles=[request.user.role],
            applies_to_establishments=[request.user.establishment],
            created_by=request.user,
        )
        booking = MeetingBooking.objects.create(
            room=room,
            booked_by=request.user,
            scheduled_at=scheduled_at,
            agenda=agenda,
            calendar_event=event,
            processing_status='sin_grabacion',
        )
        goal.associated_booking = booking
        goal.is_meeting_cycle = True
        goal.save(update_fields=['associated_booking', 'is_meeting_cycle'])

        messages.success(request, "Videollamada agendada correctamente.")
        return redirect('improvement_cycle:goal_detail', pk=goal.pk)

    return render(request, 'improvement_cycle/goal_agendar_reunion.html',
                  {'goal': goal, 'rooms': rooms})
