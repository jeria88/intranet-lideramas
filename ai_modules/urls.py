from django.urls import path
from . import views

app_name = 'ai_modules'

urlpatterns = [
    path('', views.ai_list, name='ai_list'),
    path('mis-consultas/', views.mis_consultas, name='mis_consultas'),
    path('mis-consultas/<int:pk>/', views.consulta_detalle, name='consulta_detalle'),
    path('admin/cola/', views.cola_consultas, name='cola_consultas'),
    path('admin/consulta/<int:pk>/', views.responder_consulta, name='responder_consulta'),
    
    # Repositorio de Casos (Debe ir antes de <slug:slug>/ para evitar colisiones)
    path('repositorio/', views.case_repository, name='case_repository_general'),
    path('casos/guardar/', views.save_as_case, name='save_as_case'),
    path('casos/<int:pk>/cambiar-estado/', views.toggle_case_status, name='toggle_case_status'),
    path('casos/<int:pk>/actualizar/', views.update_case, name='update_case'),
    path('casos/<int:pk>/eliminar/', views.soft_delete_case, name='soft_delete_case'),
    path('casos/<int:pk>/observacion/', views.add_case_observation, name='add_case_observation'),
    path('casos/<int:pk>/reporte/', views.case_report_print, name='case_report_print'),
    path('casos/<int:pk>/reporte-defensa/', views.case_defense_print, name='case_defense_print'),
    path('casos/<int:pk>/generar-descargos/', views.generate_case_defense, name='generate_case_defense'),

    path('<slug:slug>/', views.conversation_list, name='ai_detail'),
    path('<slug:slug>/consultar/', views.nueva_consulta, name='nueva_consulta'),
    path('<slug:slug>/chat/', views.ai_chat, name='ai_chat'),
    path('<slug:slug>/repositorio/', views.case_repository, name='case_repository'),

    # Gestión de conversaciones (nueva interfaz)
    path('<slug:slug>/conversaciones/', views.conversation_list, name='conversation_list'),
    path('<slug:slug>/conversaciones/nueva/', views.conversation_new, name='conversation_new'),
    path('<slug:slug>/conversaciones/<int:conv_id>/', views.conversation_detail, name='conversation_detail'),
    path('<slug:slug>/conversaciones/<int:conv_id>/guardar-caso/', views.conversation_save_case, name='conversation_save_case'),
]
