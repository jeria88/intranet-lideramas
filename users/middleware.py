from django.shortcuts import redirect

from users.scoping import alcance_de, fijar_alcance, restaurar_alcance


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
    """Fija el alcance de datos del request.

    Mientras dura el request, `Modelo.objects` solo devuelve filas de la
    organización del usuario. Sin esto habría que acordarse de filtrar en cada
    una de las consultas de cada vista, y la que se olvide es una fuga entre
    clientes.

    Va DESPUÉS de AuthenticationMiddleware: necesita `request.user` resuelto.
    El alcance se restaura siempre en `finally` — un contextvar que quedara
    fijado podría filtrarse al siguiente request atendido por el mismo worker.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = request.session.get('tenant', '')

        token = fijar_alcance(alcance_de(getattr(request, 'user', None)))
        try:
            return self.get_response(request)
        finally:
            restaurar_alcance(token)


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
