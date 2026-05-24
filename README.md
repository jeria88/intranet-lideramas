# LiderA+ — Plataforma de Gestión Educacional

Plataforma multi-tenant de gobernanza digital para redes de establecimientos educativos.  
Desarrollada en Django, desplegada en Railway.

**Stack:** Django 5.x · PostgreSQL (Railway) · Cloudflare R2 · Daily.co · DeepSeek · OpenAI Whisper  
**Dominio:** `intranet.lideramas.cl`

---

## 🚀 Deploy en Railway

El deploy es automático al hacer push a `main`. Railway ejecuta el Procfile:

```
web: python manage.py migrate
     && python manage.py archive_sfa_users
     && python manage.py setup_all_establishments --update-prompts
     && python manage.py seed_simce_curriculum
     && python manage.py collectstatic --noinput
     && python manage.py ensure_webhook
     && python manage.py enable_room_recording
     && gunicorn config.wsgi --workers 1 --timeout 300 --log-file -
```

### Variables de entorno requeridas

| Variable | Descripción |
|----------|-------------|
| `SECRET_KEY` | Django secret key |
| `DATABASE_URL` | PostgreSQL Railway (auto-provisto) |
| `ALLOWED_HOSTS` | `intranet.lideramas.cl` |
| `DEEPSEEK_API_KEY` | Motor principal IA (api.deepseek.com, modelo: deepseek-chat) |
| `OPENAI_API_KEY` | Embeddings text-embedding-3-small |
| `DAILY_API_KEY` | Videollamadas Daily.co |
| `AWS_ACCESS_KEY_ID` | Cloudflare R2 |
| `AWS_SECRET_ACCESS_KEY` | Cloudflare R2 |
| `AWS_STORAGE_BUCKET_NAME` | Bucket R2 |
| `AWS_S3_ENDPOINT_URL` | Endpoint R2 |
| `INTERNAL_API_KEY` | Seguridad webhooks/API interna |

---

## 🏗️ Estructura del Proyecto

```
intranet_railway/
├── config/               # Settings · urls.py · wsgi.py
├── users/                # Modelo User multi-tenant (6 roles, unique per tenant)
│   ├── backends.py       # TenantAuthBackend
│   └── middleware.py     # TenantMiddleware + ForcePasswordChangeMiddleware
├── portal/               # Dashboard principal
├── meetings/             # Videollamadas Daily.co + grabaciones + actas IA
├── ai_modules/           # Asistentes IA + sistema de conversaciones
├── simce/                # Generador de pruebas SIMCE con IA
├── library/              # Biblioteca documental
├── improvement_cycle/    # Ciclo de mejora + metas estratégicas
├── notifications/        # Notificaciones internas
├── messaging/            # Mensajería interna
├── calendar_red/         # Calendario estratégico
├── encuesta/             # Encuesta semanal de bienestar
│
├── Procfile              # Arranque Railway
├── requirements.txt
└── .env                  # Variables locales (no versionado)
```

---

## 🔑 Roles del Sistema

| Rol | Descripción |
|-----|-------------|
| `REPRESENTANTE` | Representante Legal del establecimiento |
| `DIRECTOR` | Director/a |
| `UTP` | Unidad Técnica Pedagógica |
| `INSPECTOR` | Inspector/a General |
| `CONVIVENCIA` | Encargado/a Convivencia Escolar |
| `RED` | Equipo Red (acceso total) |

---

## 🌐 Multi-tenancy

Los proyectos (clientes) están aislados por `tenant` en el modelo de usuario.

- **Login:** `intranet.lideramas.cl/{tenant}/login/`
- **Logout:** `intranet.lideramas.cl/{tenant}/logout/`
- **Landing genérico:** `intranet.lideramas.cl/acceso/`

Para crear un nuevo tenant:
```bash
python manage.py activate_all_users --tenant slug-del-proyecto
```

### Tenants activos

| Slug | Estado | Descripción |
|------|--------|-------------|
| `sfa` | ⚠️ Archivado | Red SFA — contrato pausado 2026-05-24 |

---

## 🧠 Módulo Asistentes IA (`ai_modules/`)

- Asistentes configurados por `setup_all_establishments.py` (fuente única de verdad)
- Sistema de conversaciones estilo ChatGPT con sidebar + historial
- Protocolo de 13 capas de prompt por orden de inyección
- Feedback de pilotaje: banner general + 👎 por respuesta IA

---

## 🎥 Módulo Videollamadas (`meetings/`)

Pipeline automático: booking → grabación Daily.co → transcripción Whisper → acta DeepSeek → ImprovementGoal.

---

## 📝 Módulo SIMCE (`simce/`)

Generador de pruebas en dos modos: Modo SIMCE (formulario clásico) y Modo Pistas (AJAX por pregunta, puntaje 4-3-2-0).

---

## 💰 Costos Mensuales Estimados

| Componente | Costo USD/mes |
|-----------|--------------|
| Railway app + PostgreSQL | ~$7 |
| Daily.co videollamadas | $0–5 |
| Cloudflare R2 (videos 90 días) | ~$3 |
| DeepSeek (asesores + SIMCE) | ~$1–2 |
| OpenAI Whisper (transcripciones) | ~$3–5 |
| **Total** | **~$14–22 USD** |
