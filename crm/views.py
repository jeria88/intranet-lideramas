"""Vistas del CRM comercial. Solo staff: es el motor de venta, no un módulo del producto."""
import json

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Contacto, Etapa, Lead, Target, Vertical


@staff_member_required
def tablero(request):
    """Kanban de un target. Sin target elegido, el primero activo."""
    targets = Target.objects.filter(activo=True).select_related('vertical', 'ciudad')

    target_id = request.GET.get('target')
    target = (
        get_object_or_404(Target, pk=target_id) if target_id else targets.first()
    )

    columnas = []
    if target:
        etapas = target.etapas.order_by('orden')
        leads_por_etapa = {}
        for lead in Lead.objects.filter(target=target).select_related('etapa'):
            leads_por_etapa.setdefault(lead.etapa_id, []).append(lead)
        columnas = [
            {'etapa': etapa, 'leads': leads_por_etapa.get(etapa.pk, [])}
            for etapa in etapas
        ]

    return render(request, 'crm/tablero.html', {
        'targets': targets,
        'target': target,
        'columnas': columnas,
        'metricas': _metricas(),
    })


def _metricas():
    """Los números que deciden el día. Conversaciones primero: es la única que no
    depende de un algoritmo ajeno."""
    hoy = timezone.now().date()
    contactos = Contacto.objects.all()
    return {
        'conversaciones_hoy': contactos.filter(fecha__date=hoy).count(),
        'conversaciones_total': contactos.count(),
        'respuestas': contactos.filter(respondio=True).count(),
        'leads': Lead.objects.count(),
        'ganados': Lead.objects.filter(etapa__es_terminal=True, etapa__nombre__icontains='ganado').count(),
        'sin_contactar': Lead.objects.filter(ultimo_contacto__isnull=True).count(),
    }


@staff_member_required
def lead_detalle(request, pk):
    lead = get_object_or_404(
        Lead.objects.select_related('target__vertical', 'target__ciudad', 'etapa'), pk=pk,
    )
    return render(request, 'crm/lead_detalle.html', {
        'lead': lead,
        'etapas': lead.target.etapas.order_by('orden'),
        'contactos': lead.contactos.select_related('enviado_por'),
        'canales': Contacto.CANAL_CHOICES,
    })


@staff_member_required
@require_POST
def mover_lead(request, pk):
    """Cambia la etapa de un lead. Responde JSON para el arrastre del kanban."""
    lead = get_object_or_404(Lead, pk=pk)
    etapa = get_object_or_404(Etapa, pk=request.POST.get('etapa'), target=lead.target)

    lead.etapa = etapa
    lead.save(update_fields=['etapa', 'actualizado_en'])

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'etapa': etapa.nombre})
    return redirect('crm:lead_detalle', pk=lead.pk)


@staff_member_required
@require_POST
def registrar_contacto(request, pk):
    """Deja constancia de un mensaje enviado. El envío es manual, el registro no."""
    lead = get_object_or_404(Lead, pk=pk)
    enviado = request.POST.get('enviado', '').strip()

    if not enviado:
        messages.error(request, 'No se registró: falta el texto del mensaje.')
        return redirect('crm:lead_detalle', pk=lead.pk)

    Contacto.objects.create(
        lead=lead,
        canal=request.POST.get('canal', 'whatsapp'),
        enviado=enviado,
        respuesta=request.POST.get('respuesta', ''),
        enviado_por=request.user,
    )
    messages.success(request, 'Contacto registrado.')
    return redirect('crm:lead_detalle', pk=lead.pk)
