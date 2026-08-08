from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Count
from datetime import timedelta
from users.models import User
from .models import Circular, UserActivity
from notifications.models import Notification
from users.scoping import establecimientos_de


ROLE_LABELS = dict(User.ROLE_CHOICES)


@login_required
def index(request):
    now = timezone.now()
    online_window = now - timedelta(minutes=5)

    stats = UserActivity.objects.filter(
        last_activity__gte=online_window
    ).values('user__role').annotate(total=Count('id')).order_by('-total')

    formatted_stats = [
        {'role': ROLE_LABELS.get(s['user__role'], s['user__role'] or 'Sin Rol'), 'total': s['total']}
        for s in stats
    ]

    # Circulares visibles para este usuario
    published = Circular.objects.filter(status='publicado')
    circulars = [c for c in published if c.is_visible_to(request.user)][:10]

    # Circulares pendientes de aprobación (solo para REPRESENTANTE)
    pending_approval = []
    if request.user.can_approve_circulars:
        pending_approval = Circular.objects.filter(status='pendiente_aprobacion')

    # Notificaciones no leídas del usuario
    notifications = Notification.objects.filter(recipient=request.user, is_read=False)[:5]

    return render(request, 'portal/index.html', {
        'stats': formatted_stats,
        'circulars': circulars,
        'pending_approval': pending_approval,
        'notifications': notifications,
    })


@login_required
def circular_crear(request):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        body = request.POST.get('body', '').strip()
        priority = request.POST.get('priority', 'normal')
        target_roles = request.POST.getlist('target_roles')
        target_establishments = request.POST.getlist('target_establishments')

        if title and body:
            c = Circular.objects.create(
                title=title, body=body, priority=priority,
                author=request.user,
                target_roles=target_roles,
                target_establishments=target_establishments,
                status='pendiente_aprobacion' if Circular().requires_approval else 'publicado',
            )
            return redirect('portal:index')
    return render(request, 'portal/circular_form.html', {
        'roles': User.ROLE_CHOICES,
        'establishments': establecimientos_de(request.user),
    })


@login_required
def circular_aprobar(request, pk):
    if not request.user.can_approve_circulars:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()
    circular = get_object_or_404(Circular, pk=pk, status='pendiente_aprobacion')
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'aprobar':
            circular.status = 'publicado'
            circular.approved_by = request.user
            circular.published_at = timezone.now()
            circular.save()
        elif action == 'rechazar':
            circular.status = 'borrador'
            circular.save()
    return redirect('portal:index')


@login_required
def circular_detalle(request, pk):
    circular = get_object_or_404(Circular, pk=pk)
    return render(request, 'portal/circular_detalle.html', {'circular': circular})
