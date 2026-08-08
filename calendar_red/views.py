from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import CalendarEvent
from users.models import User
from users.scoping import establecimientos_de


@login_required
def calendario(request):
    now = timezone.now().date()
    events = CalendarEvent.objects.filter(is_active=True)
    user = request.user
    
    # Filtros del tablero
    filter_ee = request.GET.get('ee', '')     # establecimiento
    filter_type = request.GET.get('type', '') # tipo de evento

    # Filtrar por rol/establecimiento del usuario primero
    visible = []
    for e in events:
        role_ok = not e.applies_to_roles or user.role in e.applies_to_roles
        ee_ok = not e.applies_to_establishments or user.establishment in e.applies_to_establishments
        if role_ok and ee_ok:
            visible.append(e)

    # Filtros adicionales de tablero
    if filter_ee:
        visible = [e for e in visible if not e.applies_to_establishments or
                   filter_ee in e.applies_to_establishments]
    if filter_type:
        visible = [e for e in visible if e.event_type == filter_type]

    # Próximos 30 días (destacados)
    upcoming = [e for e in visible if e.event_date >= now and (e.event_date - now).days <= 30]
    
    # Agrupar por mes
    from itertools import groupby
    from django.utils.dates import MONTHS
    
    def month_key(e):
        return e.event_date.strftime('%Y-%m')
    
    sorted_events = sorted(visible, key=lambda e: e.event_date)
    grouped = {}
    for k, group_items in groupby(sorted_events, key=month_key):
        grouped[k] = list(group_items)

    import calendar
    from datetime import date
    
    # Grid logic for the current/selected month
    today = date.today()
    try:
        month_int = int(request.GET.get('m', today.month))
        year_int = int(request.GET.get('y', today.year))
    except ValueError:
        month_int, year_int = today.month, today.year
    
    cal = calendar.Calendar(firstweekday=6) # Sunday starts
    month_days = cal.monthdays2calendar(year_int, month_int)
    # Prepare events for the grid (only for the selected month)
    grid_events = [e for e in visible if e.event_date.month == month_int and e.event_date.year == year_int]
    
    return render(request, 'calendar_red/calendario.html', {
        'events': visible,
        'upcoming': upcoming,
        'grouped': grouped,
        'filter_ee': filter_ee,
        'filter_type': filter_type,
        'establishments': establecimientos_de(request.user),
        'event_types': CalendarEvent.EVENT_TYPE_CHOICES,
        'month_days': month_days,
        'current_month': month_int,
        'current_year': year_int,
        'month_name': calendar.month_name[month_int].capitalize(),
        'grid_events': grid_events,
        'view_mode': request.GET.get('view', 'board'), # 'board' or 'grid'
        'today': today,
    })


@login_required
def evento_detalle(request, pk):
    event = get_object_or_404(CalendarEvent, pk=pk)
    return render(request, 'calendar_red/evento_detalle.html', {'event': event})


@login_required
def evento_crear(request):
    # Removed is_staff restriction per user request
    if request.method == 'POST':
        CalendarEvent.objects.create(
            title=request.POST.get('title', ''),
            description=request.POST.get('description', ''),
            event_date=request.POST.get('event_date'),
            event_type=request.POST.get('event_type', 'interno'),
            applies_to_roles=request.POST.getlist('applies_to_roles'),
            applies_to_establishments=request.POST.getlist('applies_to_establishments'),
            is_critical=bool(request.POST.get('is_critical')),
            created_by=request.user,
        )
        return redirect('calendar_red:calendario')
    return render(request, 'calendar_red/evento_form.html', {
        'roles': User.ROLE_CHOICES,
        'establishments': establecimientos_de(request.user),
        'event_types': CalendarEvent.EVENT_TYPE_CHOICES,
        'initial_title': request.GET.get('title', ''),
        'initial_description': request.GET.get('description', ''),
    })


@login_required
def evento_editar(request, pk):
    event = get_object_or_404(CalendarEvent, pk=pk, is_active=True)
    if request.method == 'POST':
        event.title = request.POST.get('title', '')
        event.description = request.POST.get('description', '')
        event.event_date = request.POST.get('event_date')
        event.event_type = request.POST.get('event_type', 'interno')
        event.applies_to_roles = request.POST.getlist('applies_to_roles')
        event.applies_to_establishments = request.POST.getlist('applies_to_establishments')
        event.is_critical = bool(request.POST.get('is_critical'))
        event.save()
        return redirect('calendar_red:calendario')
    
    return render(request, 'calendar_red/evento_form.html', {
        'event': event,
        'roles': User.ROLE_CHOICES,
        'establishments': establecimientos_de(request.user),
        'event_types': CalendarEvent.EVENT_TYPE_CHOICES,
    })


@login_required
def evento_eliminar(request, pk):
    event = get_object_or_404(CalendarEvent, pk=pk, is_active=True)
    if request.method == 'POST':
        event.is_active = False
        event.deleted_by = request.user
        event.deleted_at = timezone.now()
        event.save()
        return redirect('calendar_red:calendario')
    
    return render(request, 'calendar_red/evento_confirm_delete.html', {'event': event})
