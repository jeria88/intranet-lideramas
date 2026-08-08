"""
Django settings — LíderA+
Stack: Railway.app · Django 6.0.2 · PostgreSQL · WhiteNoise · Gunicorn
"""

import os
import dj_database_url
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
# Load environment variables from .env file
load_dotenv(os.path.join(BASE_DIR, '.env'))

# ── Seguridad ──────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-local-dev-only-override-via-env-in-production')
DEBUG = os.environ.get('DEBUG', 'True') == 'True'
ALLOWED_HOSTS = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')]

# ── Apps ───────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Apps locales
    'portal',
    'ai_modules',
    'meetings',
    'users',
    'library',
    'evidencia',
    'messaging',
    'calendar_red',
    'improvement_cycle',
    'notifications',
    'simce',
    'eventos',
    'encuesta',
]

# ── SLA ───────────────────────────────────────────────────────────────────
AI_QUERY_SLA_HOURS = 24

# ── Daily.co ─────────────────────────────────────────────────────────────
DAILY_BASE_URL = os.environ.get('DAILY_BASE_URL', '')
DAILY_API_KEY = os.environ.get('DAILY_API_KEY')

# ── DeepSeek ─────────────────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')
DEEPSEEK_BASE_URL = os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
INTERNAL_API_KEY = os.environ.get('INTERNAL_API_KEY', 'default-dev-key')



# ── Middleware ─────────────────────────────────────────────────────────────
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'users.middleware.TenantMiddleware',
    'users.middleware.ForcePasswordChangeMiddleware',
    'encuesta.middleware.EncuestaObligatoriaMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'portal.context_processors.track_visits',
                'notifications.context_processors.unread_notifications',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# ── Base de Datos — PostgreSQL (Railway) con fallback a SQLite ────────────────
DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=60
    )
}

# ── Base de Datos de Conocimiento (Supabase / Vector DB) ───────────────────
KNOWLEDGE_BASE_URL = os.environ.get('KNOWLEDGE_BASE_URL')
if KNOWLEDGE_BASE_URL:
    DATABASES['knowledge_base'] = dj_database_url.config(
        default=KNOWLEDGE_BASE_URL,
        conn_max_age=60
    )
else:
    # Fallback a la base por defecto si no hay URL dedicada
    DATABASES['knowledge_base'] = DATABASES['default']

DATABASE_ROUTERS = ['ai_modules.db_routers.KnowledgeBaseRouter']

# ── Validación de contraseñas ──────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ── Internacionalización ───────────────────────────────────────────────────
LANGUAGE_CODE = 'es-cl'
TIME_ZONE = 'America/Santiago'
USE_I18N = True
USE_TZ = True

# ── Archivos estáticos ─────────────────────────────────────────────────────
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# ── Media ──────────────────────────────────────────────────────────────────
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ── Cloudflare R2 Storage ─────────────────────────────────────────────────
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME')
AWS_S3_ENDPOINT_URL = os.environ.get('AWS_S3_ENDPOINT_URL')
AWS_S3_REGION_NAME = 'auto'  # Cloudflare R2 usa 'auto'
AWS_S3_SIGNATURE_VERSION = 's3v4'
AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = None

# Solo activar si todas las variables están configuradas (Railway environment)
if all([AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_STORAGE_BUCKET_NAME, AWS_S3_ENDPOINT_URL]):
    if 'storages' not in INSTALLED_APPS:
        INSTALLED_APPS.insert(0, 'storages')
    
    # Configuración específica para Cloudflare R2
    AWS_S3_ADDRESSING_STYLE = 'path'  # R2 prefiere path-style en muchos SDKs
    
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {
                "location": "media",
            }
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
        },
    }
    # No forzamos MEDIA_URL, dejamos que S3Boto3Storage genere las URLs firmadas
    # o usamos AWS_S3_CUSTOM_DOMAIN si se habilitara el acceso público.
else:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
        },
    }

# ── Modelo de usuario personalizado ───────────────────────────────────────
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'users.User'

AUTHENTICATION_BACKENDS = [
    'users.backends.TenantAuthBackend',
]

# ── Auth URLs ─────────────────────────────────────────────────────────────
LOGIN_URL = '/acceso/'
LOGIN_REDIRECT_URL = 'portal:index'
LOGOUT_REDIRECT_URL = 'acceso'

# ── Registro de Logs ───────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}

# ── CONFIGURACIÓN PARA RAILWAY (DETECTADA AUTOMÁTICAMENTE) ─────────────────
# Este bloque solo se activa si existe DATABASE_URL (solo en producción/Railway)
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    # 1. Base de datos PostgreSQL
    DATABASES['default'] = dj_database_url.config(
        default=DATABASE_URL,
        conn_max_age=60,
        conn_health_checks=True,
    )

    # 2. Seguridad (HTTPS)
    DEBUG = os.environ.get('DEBUG', 'False') == 'True'
    SECRET_KEY = os.environ.get('SECRET_KEY', SECRET_KEY)
    
    _hosts = os.environ.get('ALLOWED_HOSTS', '*.railway.app')
    ALLOWED_HOSTS = [h.strip() for h in _hosts.split(',')]
    
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    
    CSRF_TRUSTED_ORIGINS = [f'https://{h}' for h in ALLOWED_HOSTS if not h.startswith('*')] + [
        'https://*.railway.app',
        'https://*.up.railway.app'
    ]


    # 3. Logs de producción
    LOGGING['root']['level'] = 'WARNING'
