from django.urls import path

from . import views

app_name = 'crm'

urlpatterns = [
    path('', views.tablero, name='tablero'),
    path('lead/<int:pk>/', views.lead_detalle, name='lead_detalle'),
    path('lead/<int:pk>/mover/', views.mover_lead, name='mover_lead'),
    path('lead/<int:pk>/contacto/', views.registrar_contacto, name='registrar_contacto'),
]
