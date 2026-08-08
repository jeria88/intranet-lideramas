from django.shortcuts import render, redirect, get_object_or_404, reverse
from django.db.models import Q
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, JsonResponse
import json
from collections import defaultdict
from django.utils import timezone
from django.conf import settings
import requests
from .models import MeetingRoom, MeetingBooking, MeetingAttendance, MeetingDocument, MeetingAgreement, MeetingParticipant, GuestInvite
from improvement_cycle.models import ImprovementGoal
from users.scoping import establecimientos_de

MONTHLY_QUOTA = 4  # Reuniones máximas por usuario por mes (salvo RED)


def _check_quota(user, room):
    """Retorna True si el usuario puede reservar (dentro del cupo)."""
    if user.is_red_team or room.is_unlimited:
        return True
    month_year = timezone.now().strftime('%Y-%m')
    count = MeetingBooking.objects.filter(
        booked_by=user, month_year=month_year
    ).exclude(status='cancelada').count()
    return count < MONTHLY_QUOTA


def _generate_daily_token(room_name, user_name, is_owner=False):
    """
    Solicita un token de acceso a la API de Daily.co.
    """
    api_key = (settings.DAILY_API_KEY or "").strip()
    if not api_key:
        return None

    url = "https://api.daily.co/v1/meeting-tokens"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "properties": {
            "room_name": room_name,
            "user_name": user_name,
            "is_owner": is_owner,
            "start_cloud_recording": True,
        }
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=5)
        if response.status_code == 200:
            return response.json().get('token')
        else:
            print(f"Daily API Error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Daily Connection Error: {e}")

    return None


@login_required
def meeting_list(request):
    user = request.user
    now = timezone.now()

    # ── Salas visibles ────────────────────────────────────────────────────────
    if user.is_staff:
        rooms_role = list(MeetingRoom.objects.filter(room_type='daily').exclude(target_role=''))
        rooms_global = list(MeetingRoom.objects.filter(target_establishment='', target_role='', room_type='daily'))
    else:
        # Solo ve salas de su rol y salas globales
        rooms_role = list(MeetingRoom.objects.filter(target_role=user.role, room_type='daily'))
        rooms_global = list(MeetingRoom.objects.filter(target_establishment='', target_role='', room_type='daily'))

    all_rooms = rooms_role + rooms_global
    room_ids = [r.id for r in all_rooms]


    # ── Pre-load TODOS los bookings relevantes en UNA SOLA QUERY (fix N+1) ───
    since = now - timezone.timedelta(hours=8)  # Margen para reuniones en curso
    bookings_qs = list(
        MeetingBooking.objects.filter(
            room_id__in=room_ids,
            scheduled_at__gte=since,
            status__in=['programada', 'activa']
        ).select_related('booked_by').order_by('scheduled_at')
    )

    bookings_by_room = defaultdict(list)
    for b in bookings_qs:
        bookings_by_room[b.room_id].append(b)

    def _process_room_status(room):
        """Determina el estado de la sala sin nuevas queries a la BD."""
        room_bookings = bookings_by_room.get(room.id, [])

        # ¿Reunión en curso ahora mismo?
        current = next(
            (b for b in sorted(room_bookings, key=lambda x: x.scheduled_at, reverse=True)
             if b.scheduled_at <= now < b.end_time),
            None
        )
        if current:
            room.status_label = 'EN_CURSO'
            room.active_booking = current
            return

        # ¿Próxima reunión hoy?
        next_b = next(
            (b for b in sorted(room_bookings, key=lambda x: x.scheduled_at)
             if b.scheduled_at > now and b.scheduled_at.date() == now.date()
             and b.status == 'programada'),
            None
        )
        if next_b:
            room.status_label = 'PROXIMA'
            room.next_booking = next_b
        else:
            room.status_label = 'LIBRE'

    for r in all_rooms:
        _process_room_status(r)

    # ── Próximas reuniones para el widget de calendario (datos reales) ────────
    upcoming_bookings = MeetingBooking.objects.filter(
        room_id__in=room_ids,
        scheduled_at__gte=now,
        status='programada'
    ).select_related('room', 'booked_by').order_by('scheduled_at')[:8]

    month_year = now.strftime('%Y-%m')
    user_count = MeetingBooking.objects.filter(
        booked_by=user, month_year=month_year
    ).exclude(status='cancelada').count()
    quota_remaining = None if user.is_red_team else max(0, MONTHLY_QUOTA - user_count)

    return render(request, 'meetings/meeting_list.html', {
        'rooms_role': rooms_role,
        'rooms_global': rooms_global,
        'upcoming_bookings': upcoming_bookings,
        'quota_remaining': quota_remaining,
    })



@login_required
def meeting_room(request, slug):
    room = get_object_or_404(MeetingRoom, slug=slug)
    now = timezone.now()

    # 1. Buscar si hay una reserva formal en curso
    booking = MeetingBooking.objects.filter(
        room=room,
        scheduled_at__lte=now,
        status__in=['programada', 'activa']
    ).order_by('-scheduled_at').first()

    # Si la reserva ya terminó (según duración), no es la "actual"
    if booking and now >= booking.end_time:
        booking = None

    # 2. Si no hay reserva y no es staff, validamos si la sala está libre para entrada ad-hoc
    if not booking:
        # Verificar si hay alguna reserva que empiece MUY pronto (margen de 5 min)
        conflict = MeetingBooking.objects.filter(
            room=room,
            scheduled_at__range=(now, now + timezone.timedelta(minutes=5)),
            status='programada'
        ).exists()

        if conflict and not request.user.is_staff:
            messages.warning(request, "La sala estará ocupada en breve por una reunión agendada.")
            return redirect('meetings:meeting_list')

        # Entrada Libre: Creamos una reserva "al vuelo" para auditoría y acuerdos
        # Staff omite la validación de cuota pero sí necesita booking para el pipeline de grabación
        if not request.user.is_staff and not _check_quota(request.user, room):
            messages.error(request, "No tienes cupo para iniciar una reunión ahora.")
            return redirect('meetings:meeting_list')

        booking = MeetingBooking.objects.create(
            room=room,
            booked_by=request.user,
            scheduled_at=now,
            duration_minutes=60,
            status='activa',
            agenda='Reunión espontánea (Sin agenda previa)',
            processing_status='sin_grabacion'  # Solo cambia a 'pendiente' al llegar el webhook
        )

    # Redirección a Daily.co
    daily_url = f"{settings.DAILY_BASE_URL}{room.daily_identifier}"
    token = _generate_daily_token(
        room.daily_identifier,
        request.user.get_full_name() or request.user.username,
        is_owner=(request.user.is_staff or (booking and booking.booked_by == request.user))
    )
    if token:
        daily_url = f"{daily_url}?t={token}"
    if booking:
        MeetingAttendance.objects.get_or_create(booking=booking, user=request.user)
    return redirect(daily_url)


@login_required
def booking_crear(request, slug):
    room = get_object_or_404(MeetingRoom, slug=slug)
    error = None

    if request.method == 'POST':
        if not _check_quota(request.user, room):
            error = f'Has alcanzado el límite de {MONTHLY_QUOTA} reuniones para este mes.'
        else:
            from datetime import datetime
            scheduled_str = request.POST.get('scheduled_at')
            agenda = request.POST.get('agenda', '')
            try:
                scheduled_at = datetime.fromisoformat(scheduled_str)
                scheduled_at = timezone.make_aware(scheduled_at)

                # Sincronización con Calendario
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
                    room=room, booked_by=request.user,
                    scheduled_at=scheduled_at, agenda=agenda,
                    calendar_event=event,
                    processing_status='sin_grabacion'
                )

                # Crear Ciclo de Mejora Automático para la Reunión
                ImprovementGoal.objects.create(
                    establishment=request.user.establishment,
                    profile_role=request.user.role,
                    title=f"Mejora: {room.name} ({scheduled_at.date()})",
                    description=f"Seguimiento de entregables para la reunión: {agenda}",
                    strategic_objectives=f"Optimizar la gestión de la reunión {room.name} y asegurar el cumplimiento de acuerdos.",
                    is_meeting_cycle=True,
                    associated_booking=booking,
                    target_value=100,
                    measurement_unit='%',
                    deadline=scheduled_at.date(),
                    created_by=request.user,
                )
                from improvement_cycle.utils import generate_cycle_content_ai
                goal = ImprovementGoal.objects.filter(associated_booking=booking).first()
                if goal:
                    generate_cycle_content_ai(goal)

                return redirect('meetings:booking_detalle', pk=booking.pk)
            except (ValueError, TypeError):
                error = 'Fecha y hora inválidas.'

    return render(request, 'meetings/booking_form.html', {'room': room, 'error': error})


@login_required
def booking_detalle(request, pk):
    booking = get_object_or_404(MeetingBooking, pk=pk)
    agreements = booking.agreements.all()
    documents = booking.documents.all()
    attendances = booking.attendances.select_related('user')

    if request.method == 'POST':
        form_type = request.POST.get('form_type')
        if form_type == 'agreement':
            desc = request.POST.get('description', '').strip()
            deadline = request.POST.get('deadline') or None
            if desc:
                MeetingAgreement.objects.create(
                    booking=booking, description=desc,
                    responsible=request.user, deadline=deadline,
                )
        elif form_type == 'document':
            title = request.POST.get('title', '').strip()
            f = request.FILES.get('file')
            if title and f:
                MeetingDocument.objects.create(
                    booking=booking, title=title,
                    file=f, uploaded_by=request.user,
                )
    goal = booking.improvement_cycles.first()
    return render(request, 'meetings/booking_detalle.html', {
        'booking': booking,
        'agreements': agreements,
        'documents': documents,
        'attendances': attendances,
        'goal': goal,
    })




@login_required
def recording_list(request):
    """
    Repositorio de grabaciones. Filtrado por perfil de usuario.
    """
    # 1. Base del QuerySet: solo aquello que tiene video
    bookings = MeetingBooking.objects.filter(
        Q(recording_url__isnull=False)
    ).exclude(recording_url='').select_related('room', 'booked_by')

    # 2. Filtro de SEGURIDAD (Segmentación por Perfil)
    if not request.user.is_red_team and not request.user.is_staff:
        # El usuario solo ve videos de: Su establecimiento O Su Rol
        bookings = bookings.filter(
            Q(room__target_establishment=request.user.establishment) |
            Q(room__target_role=request.user.role)
        )

    # 3. Filtros Manuales de Búsqueda (GET params)
    est = request.GET.get('establishment')
    role = request.GET.get('role')
    month = request.GET.get('month')

    if est:
        bookings = bookings.filter(booked_by__establishment=est)
    if role:
        bookings = bookings.filter(booked_by__role=role)
    if month:
        bookings = bookings.filter(scheduled_at__month=month)

    return render(request, 'meetings/recording_list.html', {
        'bookings': bookings,
        'establishments': establecimientos_de(request.user),
        'roles': request.user.ROLE_CHOICES,
    })


@csrf_exempt
def recording_webhook(request):
    """
    Recibe notificaciones de Daily.co cuando una grabación está lista o una reunión empieza.
    """
    if request.method not in ['POST', 'GET']:
        return HttpResponse(status=405)

    if request.method == 'GET':
        return HttpResponse("Webhook is active", status=200)

    # Cuerpo vacío → validación inicial de Daily
    if not request.body:
        print("🔍 Webhook: Recibido cuerpo vacío (posible validación)")
        return HttpResponse(status=200)

    try:
        data = json.loads(request.body)

        # Manejar prueba de validación de Daily
        if data.get('test') == 'test' or data.get('type') == 'test':
            print("🔍 Webhook: Recibida prueba de validación de Daily.co")
            return JsonResponse({"status": "verified"})

        event_type = data.get('type')
        payload = data.get('payload', {})

        # Catch-all log para depuración — registra TODOS los tipos de evento que llegan
        print(f"📥 Webhook recibido de Daily: tipo={event_type!r} | payload_keys={list(payload.keys()) if payload else []}")

        if event_type == 'recording.ready-to-download':
            room_id = payload.get('room_name')
            recording_id = payload.get('recording_id')

            # Daily NO envía download_url en el webhook — solo room_name + recording_id
            # El pipeline resuelve el link real via GET /recordings/{id}/access-link
            if room_id and recording_id:
                room = MeetingRoom.todos.filter(daily_identifier=room_id).first()
                if not room:
                    print(f"⚠️ Webhook: Sala '{room_id}' no encontrada en la base de datos.")
                    return JsonResponse({"status": "ignored", "reason": "room_not_found"})

                now = timezone.now()
                booking = MeetingBooking.todos.filter(
                    room=room,
                    scheduled_at__lte=now + timezone.timedelta(hours=1)
                ).order_by('-scheduled_at').first()

                if booking:
                    booking.recording_url = f"daily_id:{recording_id}"
                    booking.recording_id = recording_id
                    booking.processing_status = 'pendiente'
                    booking.save(update_fields=['recording_url', 'recording_id', 'processing_status'])
                    print(f"✅ Grabación vinculada a Booking ID: {booking.id} (recording_id={recording_id})")
                    return JsonResponse({"status": "linked", "booking_id": booking.id})
                else:
                    print(f"⚠️ Webhook: No se encontró reserva reciente para sala '{room_id}'.")
                    return JsonResponse({"status": "ignored", "reason": "no_recent_booking"})

        elif event_type == 'meeting-started':
            # La grabación la inicia Daily automáticamente (enable_recording='cloud' en la sala).
            # Este evento solo se loguea para trazabilidad.
            room_id = payload.get('room') or payload.get('room_name')
            print(f"🟢 Reunión iniciada: sala={room_id} (grabación cloud automática activa)")
            return JsonResponse({"status": "received", "event": "meeting-started"})

        elif event_type == 'meeting-ended':
            room_id = payload.get('room')
            session_id = payload.get('session_id')
            print(f"🔴 Reunión terminada: sala={room_id}, session={session_id}")
            return JsonResponse({"status": "received", "event": "meeting-ended"})

        return JsonResponse({"status": "received", "event": event_type})

    except Exception as e:
        print(f"❌ Webhook Error: {e}")
        # Siempre 200 para no bloquear la validación de Daily
        return HttpResponse("Error handled", status=200)


@login_required
def sync_daily_recordings(request):
    """
    Sincroniza manualmente las grabaciones desde la API de Daily.co.
    """
    if not request.user.is_staff and not request.user.is_red_team:
        messages.error(request, "No tienes permiso para realizar esta acción.")
        return redirect('meetings:recording_list')

    api_key = settings.DAILY_API_KEY
    if not api_key:
        messages.error(request, "Error de configuración: DAILY_API_KEY no encontrada.")
        return redirect('meetings:recording_list')

    url = "https://api.daily.co/v1/recordings"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"❌ Daily API Sync Error: {response.status_code} - {response.text}")
            messages.error(request, f"Error API Daily: {response.status_code} - {response.text}")
            return redirect('meetings:recording_list')

        data = response.json()
        recordings = data.get('data', [])
        total_found = len(recordings)
        synced_count = 0
        matches_room_but_not_time = 0

        for rec in recordings:
            recording_id = rec.get('id')
            room_name = (rec.get('room_name') or "").lower().strip()

            if room_name and recording_id:
                room = MeetingRoom.todos.filter(daily_identifier__iexact=room_name).first()
                if room:
                    booking = MeetingBooking.todos.filter(
                        Q(recording_url__isnull=True) | Q(recording_url=''),
                        room=room
                    ).order_by('-scheduled_at').first()

                    if booking:
                        # ── FIX #6: guardar también recording_id, no solo recording_url ──
                        booking.recording_url = f"daily_id:{recording_id}"
                        booking.recording_id = recording_id
                        booking.processing_status = 'pendiente'
                        booking.save(update_fields=['recording_url', 'recording_id', 'processing_status'])
                        synced_count += 1
                    else:
                        matches_room_but_not_time += 1

        if synced_count > 0:
            messages.success(request, f"✅ Sincronización exitosa: {synced_count} grabaciones nuevas vinculadas.")
        elif matches_room_but_not_time > 0:
            messages.warning(request, f"ℹ️ Se encontraron {matches_room_but_not_time} grabaciones en la sala correcta, pero sin reserva sin video disponible.")
        elif total_found > 0:
            messages.info(request, f"🔎 Se encontraron {total_found} grabaciones en Daily.co, pero no coinciden con las salas de la intranet.")
        else:
            messages.info(request, "📭 No se encontraron grabaciones nuevas.")

    except Exception as e:
        messages.error(request, f"❌ Error: {str(e)}")

    return redirect('meetings:recording_list')


@login_required
def download_recording(request, pk):
    """
    Genera un enlace de descarga fresco desde Daily.co y redirige al usuario.
    Esto evita problemas con los enlaces firmados de S3 que expiran.
    """
    booking = get_object_or_404(MeetingBooking, pk=pk)

    if not booking.recording_url or not booking.recording_url.startswith('daily_id:'):
        if booking.recording_url:
            return redirect(booking.recording_url)
        messages.error(request, "No se encontró el ID de grabación para esta sesión.")
        return redirect('meetings:recording_list')

    daily_id = booking.recording_url.replace('daily_id:', '')
    api_key = (settings.DAILY_API_KEY or "").strip()
    headers = {"Authorization": f"Bearer {api_key}"}
    access_url = f"https://api.daily.co/v1/recordings/{daily_id}/access-link"

    try:
        response = requests.get(access_url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            download_link = data.get('download_link')
            if download_link:
                return redirect(download_link)

        messages.warning(request, "No se pudo obtener el enlace de descarga directa. Redirigiendo al panel de Daily.co.")
        return redirect(f"https://dashboard.daily.co/recordings/{daily_id}")

    except Exception as e:
        messages.error(request, f"Error al conectar con Daily.co: {str(e)}")
        return redirect('meetings:recording_list')


@login_required
def register_daily_webhook(request):
    """
    Ejecuta el management command que registra el webhook de Daily.co.
    """
    if not request.user.is_staff and not request.user.is_red_team:
        messages.error(request, "No tienes permiso para realizar esta acción.")
        return redirect('meetings:recording_list')

    if request.method != 'POST':
        return HttpResponse(status=405)

    from django.core.management import call_command
    from io import StringIO

    out = StringIO()
    try:
        call_command('register_daily_webhook', stdout=out)
        output = out.getvalue()
        if '✅' in output:
            messages.success(request, "✅ Webhook de Daily.co registrado y activo.")
        elif 'DAILY_API_KEY' in output:
            messages.error(request, "❌ DAILY_API_KEY no configurada.")
        else:
            messages.info(request, f"ℹ️ {output.strip()}")
    except Exception as e:
        messages.error(request, f"❌ Error al ejecutar el registro: {str(e)}")

    return redirect('meetings:recording_list')


# ── API para Procesamiento Externo (GitHub Actions) ───────────────────────────

def _check_api_key(request):
    """Valida la clave API interna."""
    key = request.headers.get('X-Internal-API-Key')
    return key == settings.INTERNAL_API_KEY


@csrf_exempt
def api_pending_meetings(request):
    """Retorna las reuniones que necesitan ser procesadas (máx. 10 a la vez)."""
    if not _check_api_key(request):
        return JsonResponse({"error": "Unauthorized"}, status=401)

    # `.todos` y no `.objects`: estas llamadas no traen usuario — el webhook lo
    # dispara Daily.co y la API interna la llama el worker con X-Internal-API-Key.
    # Sin usuario no hay organización, y el manager filtrado devolvería cero filas:
    # la grabación nunca se procesaría y el acta nunca llegaría.
    pending = MeetingBooking.todos.filter(
        processing_status__in=['pendiente', 'fallido'],
        recording_url__isnull=False
    ).exclude(recording_url='').select_related('room').prefetch_related('attendances__user')[:10]

    data = []
    for p in pending:
        attendees = [
            a.user.get_full_name() or a.user.username
            for a in p.attendances.all()
        ]
        data.append({
            "id": p.id,
            "recording_url": p.recording_url,
            "room_name": p.room.daily_identifier,
            "recording_id": p.recording_id,
            "attendees": attendees,
        })

    return JsonResponse({"meetings": data})


@csrf_exempt
def api_update_meeting(request, pk):
    """Recibe los resultados del procesamiento IA."""
    if not _check_api_key(request):
        return JsonResponse({"error": "Unauthorized"}, status=401)

    if request.method != 'POST':
        return JsonResponse({"error": "Method not allowed"}, status=405)

    booking = get_object_or_404(MeetingBooking.todos, pk=pk)

    try:
        body = json.loads(request.body)

        if body.get('status') == 'failed':
            booking.processing_status = 'fallido'
            booking.save(update_fields=['processing_status'])
            return JsonResponse({"status": "updated_to_failed"})

        booking.transcript = body.get('transcript', '')
        booking.acta = body.get('acta', '')
        booking.acuerdos_text = body.get('acuerdos_text', '')
        booking.processing_status = 'completado'

        if body.get('recording_id'):
            booking.recording_id = body.get('recording_id')

        if body.get('r2_url'):
            booking.recording_r2_url = body.get('r2_url')

        update_fields = [
            'transcript', 'acta', 'acuerdos_text', 'processing_status',
            'recording_id', 'recording_r2_url',
        ]
        booking.save(update_fields=update_fields)

        # --- REPOSITORY INTEGRATION: Save deliverables as documents ---
        from django.core.files.base import ContentFile
        if booking.acta:
            MeetingDocument.objects.get_or_create(
                booking=booking,
                title=f"Acta de Reunión - {booking.scheduled_at.date()}",
                defaults={
                    "uploaded_by": booking.booked_by,
                    "file": ContentFile(booking.acta.encode('utf-8'), name=f"acta_{booking.id}.txt")
                }
            )
        
        if booking.acuerdos_text:
            MeetingDocument.objects.get_or_create(
                booking=booking,
                title=f"Acuerdos y Compromisos - {booking.scheduled_at.date()}",
                defaults={
                    "uploaded_by": booking.booked_by,
                    "file": ContentFile(booking.acuerdos_text.encode('utf-8'), name=f"acuerdos_{booking.id}.txt")
                }
            )
        # -------------------------------------------------------------

        # Guardar participantes si vienen en el body
        participants = body.get('participants', [])
        for p in participants:
            MeetingParticipant.objects.update_or_create(
                booking=booking,
                name=p.get('name'),
                defaults={
                    "joined_at": p.get('joined_at'),
                    "left_at": p.get('left_at'),
                    "duration_seconds": p.get('duration_seconds', 0)
                }
            )

        # Sincronizar con el Ciclo de Mejora si existe
        from improvement_cycle.models import ImprovementAction
        goal = booking.improvement_cycles.first()
        if goal:
            actions_to_complete = [
                "Grabación de Video",
                "Lista de Participantes",
                "Acta de Reunión",
                "Acuerdos Redactados"
            ]
            ImprovementAction.objects.filter(
                goal=goal,
                title__in=actions_to_complete
            ).update(status='completado')

        return JsonResponse({"status": "success"})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@csrf_exempt
def api_start_processing(request, pk):
    """Marca una reunión como 'en proceso' para evitar duplicados."""
    if not _check_api_key(request):
        return JsonResponse({"error": "Unauthorized"}, status=401)

    booking = get_object_or_404(MeetingBooking.todos, pk=pk)
    booking.processing_status = 'procesando'
    booking.save(update_fields=['processing_status'])
    return JsonResponse({"status": "processing_started"})


@login_required
def participants_report_print(request, pk):
    """Vista optimizada para impresión (PDF) de los participantes detectados."""
    booking = get_object_or_404(MeetingBooking, pk=pk)
    
    # Seguridad: solo creador o staff (o RED)
    if not request.user.is_staff and not getattr(request.user, 'is_red_team', False):
        if booking.booked_by != request.user:
            return render(request, 'ai_modules/no_access.html')  # Usa template existente de acceso denegado
            
    participants = booking.detected_participants.all().order_by('joined_at')
    
    return render(request, 'meetings/participants_report_print.html', {
        'booking': booking,
        'participants': participants
    })


@login_required
def acta_report_print(request, pk):
    """Vista optimizada para impresión (PDF) del Acta de la Reunión."""
    booking = get_object_or_404(MeetingBooking, pk=pk)
    
    # Seguridad: solo creador o staff (o RED)
    if not request.user.is_staff and not getattr(request.user, 'is_red_team', False):
        if booking.booked_by != request.user:
            return render(request, 'ai_modules/no_access.html')
            
    return render(request, 'meetings/acta_report_print.html', {
        'booking': booking
    })


@login_required
def acuerdos_report_print(request, pk):
    """Vista optimizada para impresión (PDF) de los Acuerdos de la Reunión."""
    booking = get_object_or_404(MeetingBooking, pk=pk)
    
    # Seguridad: solo creador o staff (o RED)
    if not request.user.is_staff and not getattr(request.user, 'is_red_team', False):
        if booking.booked_by != request.user:
            return render(request, 'ai_modules/no_access.html')
            
    return render(request, 'meetings/acuerdos_report_print.html', {
        'booking': booking
    })

@login_required
def meeting_edit(request, pk):
    """Edita una reunión existente (Solo Admin/Staff)."""
    if not request.user.is_staff and not getattr(request.user, 'is_red_team', False):
        messages.error(request, "No tienes permiso para editar reuniones.")
        return redirect('meetings:recording_list')

    booking = get_object_or_404(MeetingBooking, pk=pk)
    if request.method == 'POST':
        booking.agenda = request.POST.get('agenda', booking.agenda)
        booking.status = request.POST.get('status', booking.status)
        booking.recording_url = request.POST.get('recording_url', booking.recording_url)
        booking.save()
        messages.success(request, "Reunión actualizada correctamente.")
        return redirect('meetings:recording_list')
    
    return render(request, 'meetings/meeting_form_edit.html', {'booking': booking})


@login_required
def meeting_delete(request, pk):
    """Elimina una reunión y sus entregables (Solo Admin/Staff)."""
    if not request.user.is_staff and not getattr(request.user, 'is_red_team', False):
        messages.error(request, "No tienes permiso para eliminar reuniones.")
        return redirect('meetings:recording_list')

    booking = get_object_or_404(MeetingBooking, pk=pk)
    if request.method == 'POST':
        booking.delete()
        messages.success(request, "Reunión eliminada correctamente.")
        return redirect('meetings:recording_list')
    
    return render(request, 'meetings/meeting_confirm_delete.html', {'booking': booking})


@login_required
def meeting_create_manual(request):
    """Crea una reunión manualmente sin pasar por Daily (Solo Admin/Staff)."""
    if not request.user.is_staff and not getattr(request.user, 'is_red_team', False):
        messages.error(request, "No tienes permiso para crear reuniones manuales.")
        return redirect('meetings:recording_list')

    if request.method == 'POST':
        room_id = request.POST.get('room')
        room = get_object_or_404(MeetingRoom, id=room_id)
        
        try:
            from datetime import datetime
            scheduled_at = datetime.fromisoformat(request.POST.get('scheduled_at'))
            scheduled_at = timezone.make_aware(scheduled_at)
        except (ValueError, TypeError) as e:
            messages.error(request, f"Fecha inválida: {e}")
            return redirect('meetings:recording_list')

        booking = MeetingBooking.objects.create(
            room=room,
            booked_by=request.user,
            scheduled_at=scheduled_at,
            agenda=request.POST.get('agenda', ''),
            recording_url=request.POST.get('recording_url', ''),
            status='cerrada',
            processing_status='completado'
        )
        # Sincronizar con Calendario
        try:
            from calendar_red.models import CalendarEvent
            CalendarEvent.objects.create(
                title=f"Reunión: {booking.room.name}",
                description=f"Agenda: {booking.agenda}",
                event_date=booking.scheduled_at.date(),
                event_time=booking.scheduled_at.time(),
                event_type='interno',
                applies_to_roles=[request.user.role],
                applies_to_establishments=[request.user.establishment],
                created_by=request.user
            )
        except Exception as e:
            print(f"Error sincronizando calendario (reunión): {e}")

        messages.success(request, "Reunión manual registrada correctamente.")

        return redirect('meetings:recording_list')

    rooms = MeetingRoom.objects.all()
    return render(request, 'meetings/meeting_form_manual.html', {'rooms': rooms})


# ── Links de invitación para externos ─────────────────────────────────────

@login_required
def generate_guest_invite(request, pk):
    """Genera un link de invitación para un externo sin cuenta. Solo staff / RED."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    booking = get_object_or_404(MeetingBooking, pk=pk)
    can_invite = (
        request.user.is_staff or
        request.user.is_red_team or
        request.user == booking.booked_by or
        request.user.role == booking.room.target_role
    )
    if not can_invite:
        return JsonResponse({'error': 'Sin permiso'}, status=403)
    label = request.POST.get('label', '').strip()
    invite = GuestInvite.objects.create(booking=booking, created_by=request.user, label=label)
    invite_url = request.build_absolute_uri(
        reverse('meetings:guest_join', kwargs={'token': str(invite.token)})
    )
    return JsonResponse({'url': invite_url, 'token': str(invite.token), 'label': invite.label})


def guest_join(request, token):
    """Vista pública para externos. No requiere login.
    Valida el token, pide nombre al invitado y redirige a Daily.co.
    """
    invite = get_object_or_404(GuestInvite, token=token, is_active=True)
    booking = invite.booking
    room = booking.room

    if booking.status == 'cancelada':
        return render(request, 'meetings/guest_join.html', {
            'cancelled': True, 'booking': booking,
        })

    if request.method == 'POST':
        guest_name = request.POST.get('guest_name', '').strip() or 'Invitado externo'
        daily_url = f"{settings.DAILY_BASE_URL}{room.daily_identifier}"
        daily_token = _generate_daily_token(room.daily_identifier, guest_name, is_owner=False)
        if daily_token:
            daily_url = f"{daily_url}?t={daily_token}"
        return redirect(daily_url)

    return render(request, 'meetings/guest_join.html', {
        'invite': invite,
        'booking': booking,
        'room': room,
        'cancelled': False,
    })
