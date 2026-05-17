from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.utils import timezone
from .models import AIAssistant, AIQuery, AIChatMessage, AICase, CaseObservation, ChatConversation, ConversationMessage
from notifications.models import Notification
from .forms import AIQueryForm
from .services import call_deepseek_ai
from .utils import extract_text_from_file
from django.http import JsonResponse
import re
from django.db.models import Count


def _extract_case_components(text):
    """Extrae las secciones A, B y C de la respuesta de la IA."""
    sustento = ""
    ruta = ""
    checklist = ""
    
    # Buscar secciones usando Regex — compatible con formato actual del prompt
    a_match = re.search(r'(?:#### A\)|PASO 2[^*\n]*A[\.\-]+)\s*SUSTENTO NORMATIVO(.*?)(?=(?:#### B\)|PASO 3)|$)', text, re.DOTALL | re.IGNORECASE)
    b_match = re.search(r'(?:#### B\)|PASO 3[^*\n]*B[\.\-]+)\s*PLAN DE ACCIÓN(.*?)(?=(?:#### C\)|PASO 4)|$)', text, re.DOTALL | re.IGNORECASE)
    c_match = re.search(r'(?:#### C\)|PASO 4[^*\n]*C[\.\-]+)\s*CHECKLIST(.*?)$', text, re.DOTALL | re.IGNORECASE)
    
    if a_match: sustento = a_match.group(1).strip()
    if b_match: ruta = b_match.group(1).strip()
    if c_match: checklist = c_match.group(1).strip()
    
    return sustento, ruta, checklist


@login_required
def ai_list(request):
    """Redirige automáticamente según el rol y establecimiento del usuario."""
    # Admins ven la lista completa
    if request.user.is_staff:
        assistants = AIAssistant.objects.filter(is_active=True).order_by('name')
        return render(request, 'ai_modules/ai_list.html', {'assistants': assistants})
    
    # 3. Redirección dinámica para otros roles con agente (UTP, Representante, etc.)
    from django.db import models
    assistant = AIAssistant.objects.filter(
        profile_role=request.user.role, 
        is_active=True
    ).filter(
        models.Q(establishment=request.user.establishment) | models.Q(establishment='')
    ).order_by('-establishment').first() # Priorizar el que tiene establecimiento definido
    
    if assistant:
        return redirect('ai_modules:ai_chat', slug=assistant.slug)

    # 4. Si no tiene asistente asignado, no mostrar nada más por seguridad
    return render(request, 'ai_modules/no_access.html')



@login_required
def ai_detail(request, slug):
    assistant = get_object_or_404(AIAssistant, slug=slug, is_active=True)
    
    # 3. Verificación de seguridad estricta
    if not request.user.is_staff:
        # Si es director, tiene acceso al director-general
        if request.user.role == 'DIRECTOR' and slug == 'director-general':
            pass
        else:
            # Solo puede ver su propio asistente asignado
            role_match = (assistant.profile_role == request.user.role)
            establishment_match = (not assistant.establishment or assistant.establishment == request.user.establishment)
            
            if not (role_match and establishment_match):
                return render(request, 'ai_modules/no_access.html')

    user_queries = AIQuery.objects.filter(
        user=request.user, assistant=assistant
    ).order_by('-submitted_at')[:5]
    return render(request, 'ai_modules/ai_detail.html', {
        'assistant': assistant,
        'user_queries': user_queries,
    })


@login_required
def nueva_consulta(request, slug):
    assistant = get_object_or_404(AIAssistant, slug=slug, is_active=True)
    if request.method == 'POST':
        form = AIQueryForm(request.POST, request.FILES)
        if form.is_valid():
            query = form.save(commit=False)
            query.user = request.user
            query.assistant = assistant
            query.save()
            
            # Generar sugerencia automática de la IA (RAG)
            if assistant.system_instruction or assistant.context_text:
                # Extraer texto del adjunto si existe
                attached_text = ""
                if query.attachment:
                    attached_text = extract_text_from_file(query.attachment)

                # El historial para una consulta única es solo la pregunta actual
                history = [{"role": "user", "content": query.question}]
                suggestion = call_deepseek_ai(
                    assistant,
                    history,
                    query.question,
                    attached_content=attached_text
                )
                query.ai_suggestion = suggestion
                query.save(update_fields=['ai_suggestion'])

                # --- AUTO-CASE GENERATION ---
                sustento, ruta, checklist = _extract_case_components(suggestion)
                if sustento or ruta:
                    AICase.objects.create(
                        user=request.user,
                        assistant=assistant,
                        title=f"Caso: {query.question[:50]}...",
                        user_query=query.question,
                        sustento=sustento,
                        ruta=ruta,
                        checklist=checklist,
                        status='abierto'
                    )
                # ----------------------------
            
            # Notificar a todos los admins (staff)
            from users.models import User
            for admin_user in User.objects.filter(is_staff=True):
                Notification.notify(
                    recipient=admin_user,
                    notification_type='alerta',
                    title=f'Nueva consulta IA de {request.user.get_full_name() or request.user.username}',
                    message=f'Asistente: {assistant.name} — Plazo: {query.deadline:%d/%m/%Y %H:%M}',
                    url=f'/ia/admin/consulta/{query.pk}/',
                )
            return redirect('ai_modules:mis_consultas')
    else:
        form = AIQueryForm()
        
    return render(request, 'ai_modules/nueva_consulta.html', {
        'assistant': assistant,
        'form': form
    })


@login_required
def mis_consultas(request):
    queries = AIQuery.objects.filter(user=request.user).select_related('assistant').order_by('-submitted_at')
    return render(request, 'ai_modules/mis_consultas.html', {'queries': queries})


@login_required
def consulta_detalle(request, pk):
    query = get_object_or_404(AIQuery, pk=pk, user=request.user)
    return render(request, 'ai_modules/consulta_detalle.html', {'query': query})


# ── Admin area ──────────────────────────────────────────────────────────
@staff_member_required
def cola_consultas(request):
    """Panel del admin: cola de consultas ordenadas por deadline."""
    queries = AIQuery.objects.filter(
        status__in=['pendiente', 'en_proceso']
    ).select_related('user', 'assistant').order_by('deadline')
    return render(request, 'ai_modules/cola_consultas.html', {'queries': queries})


@staff_member_required
def responder_consulta(request, pk):
    query = get_object_or_404(AIQuery, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'tomar' and query.status == 'pendiente':
            query.status = 'en_proceso'
            query.save(update_fields=['status'])
        elif action == 'responder':
            answer = request.POST.get('answer', '').strip()
            if answer:
                query.answer = answer
                query.status = 'respondida'
                query.answered_at = timezone.now()
                query.answered_by = request.user
                query.save()
                # Notificar al usuario que su consulta fue respondida
                Notification.notify(
                    recipient=query.user,
                    notification_type='ai_respuesta',
                    title=f'Tu consulta a {query.assistant.name} fue respondida',
                    message='Haz clic para ver la respuesta.',
                    url=f'/ia/mis-consultas/{query.pk}/',
                )
        return redirect('ai_modules:cola_consultas')

    return render(request, 'ai_modules/responder_consulta.html', {'query': query})


@login_required
def ai_chat(request, slug):
    """Vista de chat tipo ChatGPT para asistentes internos."""
    assistant = get_object_or_404(AIAssistant, slug=slug, is_active=True, is_chat_enabled=True)
    
    # Verificación de seguridad estricta
    has_access = request.user.is_staff
    if not has_access:
        role_match = (request.user.role == assistant.profile_role)
        establishment_match = (not assistant.establishment or assistant.establishment == request.user.establishment)
        if role_match and establishment_match:
            has_access = True

    if not has_access:
        return render(request, 'ai_modules/no_access.html')

    if request.method == 'POST':
        import traceback
        try:
            user_message = request.POST.get('message', '').strip()
            if not user_message:
                return JsonResponse({'error': 'Mensaje vacío'}, status=400)
            
            # 1. Guardar mensaje del usuario
            AIChatMessage.objects.create(
                user=request.user,
                assistant=assistant,
                role='user',
                content=user_message
            )
            
            # 2. Obtener historial reciente para el contexto
            history_objs = AIChatMessage.objects.filter(
                user=request.user, assistant=assistant
            ).order_by('timestamp')
            
            history = []
            for h in history_objs:
                history.append({'role': h.role, 'content': h.content})
            
            # 3. Llamar a la IA
            attached_files = request.FILES.getlist('attachment')
            attached_text = ""
            for attached_file in attached_files:
                attached_text += extract_text_from_file(attached_file) + "\n\n"
            
            ai_response = call_deepseek_ai(
                assistant,
                history,
                user_message,
                attached_content=attached_text
            )
            
            # 4. Guardar respuesta de la IA
            AIChatMessage.objects.create(
                user=request.user,
                assistant=assistant,
                role='assistant',
                content=ai_response
            )

            # 5. Registrar la consulta en AIQuery para trazabilidad en el admin
            AIQuery.objects.create(
                user=request.user,
                assistant=assistant,
                question=user_message,
                ai_suggestion=ai_response,
                status='respondida',
            )

            return JsonResponse({
                'response': ai_response,
                'status': 'success'
            })
        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"Error CRITICO en ai_chat: {error_trace}")
            return JsonResponse({
                'response': f'ERROR INTERNO: {str(e)}\n\nDetalle:\n{error_trace}',
                'status': 'success'
            })

    # Para GET: Cargar historial y renderizar template
    messages = AIChatMessage.objects.filter(
        user=request.user, assistant=assistant
    ).order_by('timestamp')
    
    # Obtener la última respuesta de la IA (para el Canvas)
    last_ai_response = messages.filter(role='assistant').last()
    
    repo_case_count = AICase.objects.filter(user=request.user, is_active=True).count()
    
    return render(request, 'ai_modules/chat.html', {
        'assistant': assistant,
        'chat_messages': messages,
        'last_ai_response': last_ai_response.content if last_ai_response else None,
        'repo_case_count': repo_case_count
    })

@login_required
def case_repository(request, slug=None):
    """Listado de casos guardados centrado en el usuario autenticado."""
    
    # 1. Determinar el asistente de contexto para la interfaz (Botón Volver, Títulos)
    if slug:
        assistant = get_object_or_404(AIAssistant, slug=slug, is_active=True)
    else:
        # Buscar el asistente primario del usuario (Lógica idéntica a ai_list)
        from django.db import models
        assistant = AIAssistant.objects.filter(
            profile_role=request.user.role, 
            is_active=True
        ).filter(
            models.Q(establishment=request.user.establishment) | models.Q(establishment='')
        ).order_by('-establishment').first()
        
        # Fallback para directores sin asistente específico
        if not assistant and request.user.role == 'DIRECTOR':
            assistant = AIAssistant.objects.filter(profile_role='DIRECTOR', is_active=True, establishment='').first()
            
        # Si aún no hay asistente (ej. Admin sin rol asignado), tomar el primero activo
        if not assistant:
            assistant = AIAssistant.objects.filter(is_active=True).first()

    # 2. Verificación de seguridad (Staff puede ver todo si hay slug, si no, solo lo suyo)
    if slug and request.user.is_staff:
        # Supervisión administrativa: Ver todos los casos de este asistente
        cases = AICase.objects.filter(assistant=assistant, is_active=True)
    else:
        # Repositorio Personal: Ver solo mis casos (de cualquier asistente)
        cases = AICase.objects.filter(user=request.user, is_active=True)

    cases = cases.select_related('assistant', 'user').prefetch_related('obs_log__user').order_by('-created_at')
    
    role = assistant.profile_role if assistant else 'GENERAL'
    if role == 'UTP': subtitle = 'Gestión y seguimiento de asesorías técnico-pedagógicas.'
    elif role == 'DIRECTOR': subtitle = 'Gestión y seguimiento de casos directivos y normativos.'
    elif role == 'CONVIVENCIA': subtitle = 'Gestión y seguimiento de casos de convivencia educativa.'
    elif role == 'INSPECTOR': subtitle = 'Gestión y seguimiento de disciplina e inspectoría general.'
    elif role == 'REPRESENTANTE': subtitle = 'Gestión y seguimiento legal y representación institucional.'
    else: subtitle = 'Gestión y seguimiento de casos normativos institucionales.'
    
    return render(request, 'ai_modules/repository.html', {
        'cases': cases,
        'assistant': assistant,
        'subtitle': subtitle
    })


@login_required
def save_as_case(request):
    """AJAX: Guarda contenido como un caso."""
    if request.method == 'POST':
        assistant_slug = request.POST.get('assistant_slug')
        title = request.POST.get('title', 'Caso sin título')
        sustento = request.POST.get('sustento', '')
        ruta = request.POST.get('ruta', '')
        checklist = request.POST.get('checklist', '')
        observations = request.POST.get('observations', '')
        
        # 1. Intentar obtener el asistente por slug enviado
        assistant = AIAssistant.objects.filter(slug=assistant_slug, is_active=True).first()
        
        # 2. Si falla, buscar el asistente que coincide con el perfil y establecimiento del usuario
        if not assistant:
            from django.db import models
            assistant = AIAssistant.objects.filter(
                profile_role=request.user.role, 
                is_active=True
            ).filter(
                models.Q(establishment=request.user.establishment) | models.Q(establishment='')
            ).order_by('-establishment').first()
            
        # 3. Último recurso: cualquier asistente activo del rol del usuario
        if not assistant:
            assistant = AIAssistant.objects.filter(profile_role=request.user.role, is_active=True).first()
            
        if not assistant:
            return JsonResponse({'status': 'error', 'message': 'No se encontró un asistente válido'}, status=404)
        
        # Priorizar query del POST, si no viene, usar lo que sea que ayude a la trazabilidad
        user_query = request.POST.get('query', '').strip()
        if not user_query:
            user_query = f"Consulta automática generada para el caso: {title}"

        case = AICase.objects.create(
            user=request.user,
            assistant=assistant,
            title=title,
            user_query=user_query,
            sustento=sustento,
            ruta=ruta,
            checklist=checklist,
            observations=observations
        )
        
        return JsonResponse({'status': 'success', 'case_id': case.id})
    return JsonResponse({'status': 'error'}, status=400)


@login_required
def toggle_case_status(request, pk):
    """Cambia el estado del caso."""
    case = get_object_or_404(AICase, pk=pk)
    if not request.user.is_staff and case.user != request.user:
        return JsonResponse({'status': 'error'}, status=403)
        
    case.status = 'cerrado' if case.status == 'abierto' else 'abierto'
    case.save()
    return JsonResponse({'status': 'success', 'new_status': case.get_status_display()})


@login_required
def generate_case_defense(request, pk):
    """Genera redacción de descargos para fiscalizadores externos."""
    case = get_object_or_404(AICase, pk=pk)

    user_prompt = f"""Redacta un documento formal de DESCARGOS para presentar ante entes fiscalizadores.

Usa un tono formal y técnico. No uses frases de plantilla genéricas.

ESTRUCTURA OBLIGATORIA:
1. Antecedentes (Hechos específicos del caso)
2. Fundamentación Técnico-Normativa (Citas legales precisas)
3. Acciones de Mitigación/Corrección (Pasos realizados)
4. Conclusión y petitorio

---
Título del Caso: {case.title}
Consulta Original (Hechos): {case.user_query}
Sustento Normativo: {case.sustento}
Ruta de Acción: {case.ruta}
---"""

    defense_text = call_deepseek_ai(
        case.assistant,
        [{'role': 'user', 'content': user_prompt}],
        user_prompt,
        temperature=1.3
    )

    case.descargos = defense_text
    case.save(update_fields=['descargos'])

    return JsonResponse({'status': 'success', 'defense': defense_text})

@login_required
def update_case(request, pk):
    """AJAX: Actualiza un caso existente."""
    case = get_object_or_404(AICase, pk=pk)
    if not request.user.is_staff and case.user != request.user:
        return JsonResponse({'status': 'error', 'message': 'No tienes permiso'}, status=403)
        
    if request.method == 'POST':
        case.title = request.POST.get('title', case.title)
        case.status = request.POST.get('status', case.status)
        case.save()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'}, status=400)


@login_required
def add_case_observation(request, pk):
    """AJAX: Añade una observación al log."""
    case = get_object_or_404(AICase, pk=pk)
    if not request.user.is_staff and case.user != request.user:
        return JsonResponse({'status': 'error'}, status=403)
        
    content = request.POST.get('content', '').strip()
    if content:
        obs = CaseObservation.objects.create(
            case=case,
            user=request.user,
            content=content
        )
        return JsonResponse({
            'status': 'success',
            'obs': {
                'user': obs.user.get_full_name() or obs.user.username,
                'content': obs.content,
                'created_at': obs.created_at.strftime('%d/%m/%Y %H:%M')
            }
        })
    return JsonResponse({'status': 'error', 'message': 'Contenido vacío'}, status=400)


@login_required
def case_report_print(request, pk):
    """Vista optimizada para impresión de un caso guardado."""
    case = get_object_or_404(AICase, pk=pk)
    if not request.user.is_staff and case.user != request.user:
        return render(request, 'ai_modules/no_access.html')
    
    return render(request, 'ai_modules/case_report_print.html', {
        'case': case
    })


@login_required
def case_defense_print(request, pk):
    """Vista optimizada para impresión de la DEFENSA (Descargos)."""
    case = get_object_or_404(AICase, pk=pk)
    # Si el caso está inactivo y el usuario no es staff, denegar acceso
    if not case.is_active and not request.user.is_staff:
        return render(request, 'ai_modules/no_access.html')
        
    if not request.user.is_staff and case.user != request.user:
        return render(request, 'ai_modules/no_access.html')
    
    return render(request, 'ai_modules/case_defense_print.html', {
        'case': case
    })


@login_required
def soft_delete_case(request, pk):
    """AJAX: Marca un caso como inactivo (Soft Delete)."""
    case = get_object_or_404(AICase, pk=pk)
    if not request.user.is_staff and case.user != request.user:
        return JsonResponse({'status': 'error', 'message': 'No tienes permiso'}, status=403)

    if request.method == 'POST':
        case.is_active = False
        case.save(update_fields=['is_active'])
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'}, status=400)


# ── Gestión de conversaciones ────────────────────────────────────────────────

def _check_assistant_access(request, assistant):
    if request.user.is_staff:
        return True
    return (
        request.user.role == assistant.profile_role
        and (not assistant.establishment or assistant.establishment == request.user.establishment)
    )


@login_required
def conversation_list(request, slug):
    assistant = get_object_or_404(AIAssistant, slug=slug, is_active=True, is_chat_enabled=True)
    if not _check_assistant_access(request, assistant):
        return render(request, 'ai_modules/no_access.html')

    latest = ChatConversation.objects.filter(
        user=request.user, assistant=assistant
    ).order_by('-updated_at').first()

    if latest:
        return redirect('ai_modules:conversation_detail', slug=slug, conv_id=latest.pk)

    return render(request, 'ai_modules/chat_app.html', {
        'assistant': assistant,
        'conversation': None,
        'chat_messages': [],
        'all_conversations': [],
    })


@login_required
def conversation_new(request, slug):
    assistant = get_object_or_404(AIAssistant, slug=slug, is_active=True, is_chat_enabled=True)
    if not _check_assistant_access(request, assistant):
        return render(request, 'ai_modules/no_access.html')

    if request.method != 'POST':
        return redirect('ai_modules:conversation_list', slug=slug)

    conv = ChatConversation.objects.create(user=request.user, assistant=assistant)
    return redirect('ai_modules:conversation_detail', slug=slug, conv_id=conv.pk)


@login_required
def conversation_save_case(request, slug, conv_id):
    """AJAX: guarda el último mensaje IA de la conversación como AICase."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error'}, status=400)

    assistant = get_object_or_404(AIAssistant, slug=slug, is_active=True)
    conversation = get_object_or_404(ChatConversation, pk=conv_id, user=request.user, assistant=assistant)

    if conversation.case:
        return JsonResponse({'status': 'success', 'case_id': conversation.case.pk, 'existing': True})

    last_ai = conversation.messages.filter(role='assistant').last()
    if not last_ai:
        return JsonResponse({'status': 'error', 'message': 'Sin respuesta IA para guardar'}, status=400)

    sustento, ruta, checklist = _extract_case_components(last_ai.content)
    first_user = conversation.messages.filter(role='user').first()
    title = conversation.title if conversation.title != 'Nueva conversación' else (first_user.content[:80] if first_user else 'Caso sin título')

    case = AICase.objects.create(
        user=request.user,
        assistant=assistant,
        title=title,
        user_query=first_user.content if first_user else '',
        sustento=sustento or last_ai.content,
        ruta=ruta,
        checklist=checklist,
        status='abierto',
    )
    conversation.case = case
    conversation.save(update_fields=['case'])

    return JsonResponse({'status': 'success', 'case_id': case.pk})


@login_required
def conversation_detail(request, slug, conv_id):
    assistant = get_object_or_404(AIAssistant, slug=slug, is_active=True, is_chat_enabled=True)
    if not _check_assistant_access(request, assistant):
        return render(request, 'ai_modules/no_access.html')

    conversation = get_object_or_404(ChatConversation, pk=conv_id, user=request.user, assistant=assistant)

    if request.method == 'POST':
        user_message = request.POST.get('message', '').strip()
        if not user_message:
            return JsonResponse({'error': 'Mensaje vacío'}, status=400)

        ConversationMessage.objects.create(conversation=conversation, role='user', content=user_message)

        new_title = None
        if conversation.title == 'Nueva conversación':
            new_title = user_message[:80]
            conversation.title = new_title
            conversation.save(update_fields=['title', 'updated_at'])

        history = [{'role': m.role, 'content': m.content} for m in conversation.messages.all()]

        attached_text = ""
        for f in request.FILES.getlist('attachment'):
            attached_text += extract_text_from_file(f) + "\n\n"

        ai_response = call_deepseek_ai(assistant, history, user_message, attached_content=attached_text)

        ConversationMessage.objects.create(conversation=conversation, role='assistant', content=ai_response)
        conversation.save(update_fields=['updated_at'])

        return JsonResponse({'response': ai_response, 'status': 'success', 'new_title': new_title})

    messages = list(conversation.messages.all())
    last_ai = next((m for m in reversed(messages) if m.role == 'assistant'), None)
    all_conversations = ChatConversation.objects.filter(
        user=request.user, assistant=assistant
    ).order_by('-updated_at')

    return render(request, 'ai_modules/chat_app.html', {
        'assistant': assistant,
        'conversation': conversation,
        'chat_messages': messages,
        'last_ai_response': last_ai.content if last_ai else None,
        'all_conversations': all_conversations,
    })
