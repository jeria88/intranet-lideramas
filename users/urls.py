from django.urls import path
from django.views.generic import RedirectView
from . import views

app_name = 'users'

urlpatterns = [
    # Ruta legacy → redirige a la página de acceso
    path('login/', RedirectView.as_view(url='/acceso/', permanent=False), name='login'),
    path('logout/', views.custom_logout, name='logout'),
    path('profile/', views.profile, name='profile'),
    path('cambiar-contrasena/', views.change_password, name='change_password'),
]
