from django.urls import path, include
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from users import views as user_views

urlpatterns = [
    path('admin/', admin.site.urls),

    # Acceso genérico (para bookmarks rotos o @login_required redirects)
    path('acceso/', user_views.acceso, name='acceso'),

    # Login/logout por organización: /<slug>/login/
    # IMPORTANTE: va antes de los includes para que <str:tenant>/ no capture rutas del sistema
    path('<str:tenant>/login/', user_views.tenant_login, name='tenant-login'),
    path('<str:tenant>/logout/', user_views.tenant_logout, name='tenant-logout'),

    path('', include('portal.urls')),
    path('mensajes/', include('messaging.urls')),
    path('calendario/', include('calendar_red.urls')),
    path('salas/', include('meetings.urls')),
    path('biblioteca/', include('library.urls')),
    path('ia/', include('ai_modules.urls')),
    path('evidencia/', include('evidencia.urls')),
    path('mejora/', include('improvement_cycle.urls')),
    path('notificaciones/', include('notifications.urls')),
    path('usuarios/', include('users.urls')),
    path('simce/', include('simce.urls')),
    path('eventos/', include('eventos.urls')),
    path('encuesta/', include('encuesta.urls')),
    # CRM comercial: a quién le vendemos el producto. Solo staff.
    path('crm/', include('crm.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
