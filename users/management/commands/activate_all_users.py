import traceback
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()

ESTABLISHMENTS = [
    'TEMUCO', 'LAUTARO', 'RENAICO', 'SANTIAGO',
    'IMPERIAL', 'ERCILLA', 'ARAUCO', 'ANGOL',
]

ROLES = [
    'DIRECTOR',
    'UTP',
    'INSPECTOR',
    'CONVIVENCIA',
    'REPRESENTANTE',
]

USER_PASSWORD = '123456'


class Command(BaseCommand):
    help = 'Crea/activa todos los usuarios de un proyecto LiderA+. Seguro para correr en cada deploy.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant', default='sfa',
            help='Slug del proyecto (default: sfa)',
        )

    def handle(self, *args, **options):
        self.tenant = options['tenant']
        try:
            self._run()
        except Exception:
            self.stderr.write('=== ERROR CRÍTICO en activate_all_users ===')
            self.stderr.write(traceback.format_exc())
            self.stderr.write('El deploy continúa, pero los usuarios pueden no haberse creado.')

    def _run(self):
        # Detectar si la columna must_change_password ya existe en el esquema real
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='users_user' AND column_name='must_change_password'")
            has_mcp = cursor.fetchone() is not None

        self.stdout.write(f'=== activate_all_users | tenant: {self.tenant} | must_change_password en DB: {has_mcp} ===')

        all_combos = [(role, ee) for ee in ESTABLISHMENTS for role in ROLES]
        all_combos.append(('RED', 'RED'))

        created = updated = errors = 0

        for role, ee in all_combos:
            username = f"{role.lower()}.{ee.lower()}"
            try:
                result = self._process(username, role, ee, has_mcp)
                if result == 'created':
                    created += 1
                elif result == 'updated':
                    updated += 1
            except Exception:
                errors += 1
                self.stderr.write(f'  ERROR {username}: {traceback.format_exc()}')

        self.stdout.write(f'=== Listo: {created} creados | {updated} actualizados | {errors} errores ===')

    def _process(self, username, role, ee, has_mcp):
        # director.angol pertenece al equipo RED, no al establecimiento Angol
        if username == 'director.angol':
            role, ee = 'RED', 'RED'

        try:
            user = User.objects.get(username=username, tenant=self.tenant)
            created = False
        except User.DoesNotExist:
            user = User(
                username=username,
                tenant=self.tenant,
                role=role,
                establishment=ee,
                email=f'{username}@{self.tenant}.lideramas.cl',
                is_active=True,
                first_name='',
                last_name='',
            )
            user.set_password(USER_PASSWORD)
            if has_mcp:
                user.must_change_password = True
            user.save()
            self.stdout.write(f'  CREADO      {username}')
            return 'created'

        # Usuario existente — solo tocar lo mínimo necesario
        changed = False

        if not user.is_active:
            user.is_active = True
            changed = True

        from django.contrib.auth.hashers import check_password as chk

        has_correct_pwd = chk(USER_PASSWORD, user.password)
        must_change     = has_mcp and getattr(user, 'must_change_password', False)
        # Claves conocidas de deploys anteriores que quedaron con must_change_password=False
        LEGACY_PWDS = ['Admin1234!', 'SanFrancisco2026!']
        has_legacy = any(chk(p, user.password) for p in LEGACY_PWDS)

        if has_legacy or (must_change and not has_correct_pwd):
            user.set_password(USER_PASSWORD)
            if has_mcp:
                user.must_change_password = True
            changed = True

        # Determinar si el usuario aún no completó el primer ingreso
        pending = has_legacy or must_change

        # Corregir rol/establecimiento de director.angol → RED
        if user.role != role or user.establishment != ee:
            user.role = role
            user.establishment = ee
            changed = True

        if username == 'utp.temuco':
            if user.first_name != 'Luis Humberto' or user.last_name != 'Jeria Castro':
                user.first_name = 'Luis Humberto'
                user.last_name = 'Jeria Castro'
                changed = True
        elif pending and (user.first_name or user.last_name):
            user.first_name = ''
            user.last_name = ''
            changed = True

        if changed:
            user.save()
            self.stdout.write(f'  ACTUALIZADO {username}')
            return 'updated'

        self.stdout.write(self.style.SUCCESS(f'  OK          {username}'))
        return 'ok'
