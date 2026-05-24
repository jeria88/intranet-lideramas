from datetime import date
from django.shortcuts import redirect
from users.middleware import _is_auth_path

EXEMPT_PREFIXES = (
    '/encuesta/', '/admin/', '/static/', '/media/',
)


class EncuestaObligatoriaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (request.user.is_authenticated
                and not request.user.is_staff
                and not request.user.is_superuser
                and date.today().weekday() == 4  # viernes
                and not _is_auth_path(request.path)
                and not any(request.path.startswith(p) for p in EXEMPT_PREFIXES)):
            from encuesta.models import EncuestaSemana
            today = date.today()
            iso = today.isocalendar()
            if not EncuestaSemana.objects.filter(
                user=request.user, iso_year=iso[0], iso_week=iso[1]
            ).exists():
                return redirect('encuesta:responder')
        return self.get_response(request)
