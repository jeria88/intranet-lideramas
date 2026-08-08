from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

app_name = 'evidencia'

urlpatterns = [
    path('', views.reuniones, name='reuniones'),
    path('formularios/', views.formularios, name='formularios'),
]
# `presencial/` y `virtual/` servían dos actas de eventos de un cliente concreto,
# con las imágenes alojadas en su propio dominio. Se retiraron con el resto de su
# marca; los documentos de evidencia siguen listándose en `reuniones`.
