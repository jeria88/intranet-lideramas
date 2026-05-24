from django.shortcuts import redirect


def _is_auth_path(path):
    """Retorna True si la ruta es un login/logout/acceso de cualquier tenant."""
    if path in ('/acceso/', '/usuarios/logout/', '/usuarios/cambiar-contrasena/'):
        return True
    if path.startswith('/admin/') or path.startswith('/static/') or path.startswith('/media/'):
        return True
    # /{tenant}/login/ y /{tenant}/logout/
    parts = path.strip('/').split('/')
    return len(parts) == 2 and parts[1] in ('login', 'logout')


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = request.session.get('tenant', '')
        return self.get_response(request)


class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.user.is_authenticated
            and getattr(request.user, 'must_change_password', False)
            and not _is_auth_path(request.path)
        ):
            return redirect('users:change_password')
        return self.get_response(request)
