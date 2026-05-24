from django.contrib.auth import get_user_model
from django.db.models import Q

User = get_user_model()


class TenantAuthBackend:
    """
    Autentica usuarios dentro de un tenant (proyecto).
    También maneja el login de staff/superusuarios para /admin/.
    """

    def authenticate(self, request, username=None, password=None, tenant=None, **kwargs):
        if not username:
            return None

        if tenant:
            qs = User.objects.filter(username=username, tenant=tenant)
        else:
            # Login sin tenant → solo staff/superusuarios (Django admin)
            qs = User.objects.filter(username=username).filter(
                Q(is_staff=True) | Q(is_superuser=True)
            )

        try:
            user = qs.get()
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            # Ejecutar hash igualmente para mitigar timing attacks
            User().set_password(password)
            return None

        if user.check_password(password) and user.is_active:
            return user
        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
