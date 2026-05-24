import os
import traceback
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = 'Inhabilita todos los usuarios del tenant SFA (excepto superusuarios) y les asigna la contraseña de archivo.'

    def handle(self, *args, **options):
        try:
            self._run()
        except Exception:
            self.stderr.write('=== ERROR en archive_sfa_users ===')
            self.stderr.write(traceback.format_exc())

    def _run(self):
        password = os.environ.get('SFA_ARCHIVED_PASSWORD', '')
        if not password:
            self.stderr.write('SFA_ARCHIVED_PASSWORD no definida en el entorno — abortando.')
            return

        qs = User.objects.filter(tenant='sfa', is_superuser=False, is_staff=False)
        total = qs.count()
        updated = 0

        for user in qs:
            changed = False
            if user.is_active:
                user.is_active = False
                changed = True
            # Siempre asigna la contraseña de archivo para invalidar credenciales anteriores
            user.set_password(password)
            user.save()
            updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'=== archive_sfa_users: {updated}/{total} usuarios SFA inhabilitados ==='
            )
        )
