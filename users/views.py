from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import (
    logout as django_logout,
    authenticate,
    login as auth_login,
    update_session_auth_hash,
)
from django.contrib import messages
from .forms import UserProfileForm


def tenant_login(request, tenant):
    if request.user.is_authenticated:
        return redirect('portal:index')

    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password, tenant=tenant)
        if user is not None:
            auth_login(request, user)
            request.session['tenant'] = tenant
            next_url = request.POST.get('next') or request.GET.get('next') or '/'
            return redirect(next_url)
        error = 'Usuario o contraseña incorrectos. Intente nuevamente.'

    return render(request, 'users/login.html', {'tenant': tenant, 'error': error})


def tenant_logout(request, tenant):
    if request.user.is_authenticated:
        django_logout(request)
    return render(request, 'users/logout_success.html', {'tenant': tenant})


def acceso(request):
    return render(request, 'users/acceso.html')


@login_required
def profile(request):
    if request.method == 'POST':
        form = UserProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            return redirect('users:profile')
    else:
        form = UserProfileForm(instance=request.user)
    return render(request, 'users/profile.html', {'form': form})


@login_required
def change_password(request):
    error = None
    if request.method == 'POST':
        nueva = request.POST.get('new_password', '').strip()
        confirmar = request.POST.get('confirm_password', '').strip()

        if len(nueva) < 6:
            error = 'La contraseña debe tener al menos 6 caracteres.'
        elif nueva != confirmar:
            error = 'Las contraseñas no coinciden.'
        else:
            request.user.set_password(nueva)
            request.user.must_change_password = False
            request.user.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, 'Contraseña actualizada. Bienvenido/a.')
            return redirect('portal:index')

    return render(request, 'users/change_password.html', {'error': error})


def custom_logout(request):
    tenant = request.session.get('tenant', '') if request.user.is_authenticated else ''
    if request.user.is_authenticated:
        django_logout(request)
    if tenant:
        return redirect(f'/{tenant}/login/')
    return redirect('acceso')
