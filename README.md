# Intranet Congregacional — Red SFA

Sistema de gobernanza digital para 8 establecimientos educativos de la Congregación Hermanas Terceras Franciscanas.

**Stack:** Django 5.x · PostgreSQL (Railway) · Cloudflare R2 · Daily.co · DeepSeek · OpenAI Whisper  
**Establecimientos:** Temuco · Lautaro · Renaico · Santiago · Imperial · Ercilla · Arauco · Angol

---

## 🚀 Deploy en Railway

El deploy es automático al hacer push a `main`. Railway ejecuta el Procfile:

```
web: python manage.py migrate
     && python manage.py activate_all_users
     && python manage.py setup_all_establishments --update-prompts
     && python manage.py seed_simce_curriculum
     && python manage.py collectstatic --noinput
     && python manage.py ensure_webhook
     && python manage.py enable_room_recording
     && gunicorn config.wsgi --workers 1 --timeout 300 --log-file -
```

`setup_all_establishments --update-prompts` actualiza los 41 asistentes IA (5 roles × 8 establecimientos + 1 RED) automáticamente en cada deploy.

### Variables de entorno requeridas

| Variable | Descripción |
|----------|-------------|
| `SECRET_KEY` | Django secret key |
| `DATABASE_URL` | PostgreSQL Railway (auto-provisto) |
| `ALLOWED_HOSTS` | tu-proyecto.railway.app |
| `DEEPSEEK_API_KEY` | Motor principal IA (api.deepseek.com, modelo: deepseek-chat) |
| `OPENAI_API_KEY` | Embeddings text-embedding-3-small |
| `DAILY_API_KEY` | Videollamadas Daily.co |
| `AWS_ACCESS_KEY_ID` | Cloudflare R2 |
| `AWS_SECRET_ACCESS_KEY` | Cloudflare R2 |
| `AWS_STORAGE_BUCKET_NAME` | `intranet-sfa-storage` |
| `AWS_S3_ENDPOINT_URL` | Endpoint R2 |
| `INTERNAL_API_KEY` | Seguridad webhooks/API interna |

---

## 🏗️ Estructura del Proyecto

```
intranet_railway/
├── config/               # Settings · urls.py · wsgi.py
├── users/                # Modelo User (6 roles × 8 establecimientos)
├── portal/               # Dashboard principal
├── meetings/             # Videollamadas Daily.co + grabaciones + actas IA
├── ai_modules/           # 41 asistentes IA + sistema de conversaciones
├── simce/                # Generador de pruebas SIMCE con IA
├── library/              # Biblioteca documental
├── improvement_cycle/    # Ciclo de mejora + metas estratégicas
├── notifications/        # Notificaciones internas
├── messaging/            # Mensajería interna
├── calendar_red/         # Calendario estratégico congregacional
│
├── Procfile              # Arranque Railway (ver arriba)
├── requirements.txt
├── seed_railway.py       # Datos iniciales (usuarios, establecimientos)
└── .env.example
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
| `RED` | Equipo Red Congregacional (acceso total) |

---

## 🧠 Módulo Asistentes IA (`ai_modules/`)

### Escala
- **41 asistentes**: 5 roles × 8 establecimientos + 1 asistente RED
- Todos gestionados por `setup_all_establishments.py` — fuente única de verdad para prompts

### Arquitectura de conversaciones
Interfaz ChatGPT-style: panel lateral con historial + panel de chat. Modelos:
- `ChatConversation`: conversación con título, usuario y asistente
- `ConversationMessage`: mensajes con rol (user/assistant) y timestamp
- `PilotFeedback`: feedback de pilotaje (banner general o 👎 por respuesta)

### Protocolo de prompts (capas por orden de inyección)

| Capa | Constante | Propósito |
|------|-----------|-----------|
| 1 | `_REGLA_URGENCIA` | 🚨 Gate de denuncia obligatoria — se ejecuta ANTES de todo |
| 2 | Prompt de rol | Tabla PASO 1 + competencias específicas del estamento |
| 3 | `_PASOS` | Lógica condicional: SI NO → para; SI SÍ → continúa PASO 2-4 |
| 4 | `_META_REGLA` | Las reglas siguientes solo aplican si el caso corresponde al rol |
| 5 | `_REGLA_TOPICO` | Rechaza consultas fuera del dominio escolar |
| 6 | `_REGLA_DIAGNOSTICOS` | Exige documento oficial para activar apoyos NEE |
| 7 | `_REGLA_CONFLICTOS` | Orden: Salud Mental → Convivencia → Medidas normativas |
| 8 | `_REGLA_INTEGRIDAD` | Prohíbe inventar artículos de leyes (CT, ED, CP, LGE, etc.) |
| 9 | `_REGLA_RICE` | Prohíbe inventar artículos del RICE interno |
| 10 | `_REGLA_OPD_OLN` | Nomenclatura correcta OPD/OLN |
| 11 | `_ORGANIGRAMA_DERIVACION` | Competencias por estamento |
| 12 | `_RECORDATORIO_FORMATO` | Refuerzo final: NO → para; SÍ → continúa |
| 13 | `_DISCLAIMER` | Pie de legalidad Lideramas |

### Reglas críticas de integridad
- **Artículos prohibidos**: nunca citar con contenido art. 161/163/169 CT, art. 72 ED, art. 296 CP u otros sin RAG
- **Inspector ≠ UTP**: materias pedagógicas (notas, planificación) son de UTP aunque el RIOHS sea del Inspector
- **Urgencia siempre primero**: abuso sexual, violencia grave, arma → 🚨 antes de cualquier tabla

### Feedback de pilotaje
- **Banner amarillo** en cabecera del chat → reporta experiencia general
- **👎 por burbuja** de la IA → reporta esa respuesta específica con contexto pre-cargado
- Ambos requieren input obligatorio del usuario
- Guardado en `PilotFeedback` con `origin`, `user`, `message` (FK), `feedback_text`

---

## 🎥 Módulo Videollamadas (`meetings/`)

Pipeline 100% automático:

```
Booking creado → CalendarEvent + ImprovementGoal (IA)
Usuario entra → Daily dispara "meeting-started" → Django inicia grabación (async thread)
Reunión termina → "recording.ready-to-download" → booking.processing_status = 'pendiente'
GitHub Actions (cron 15 min) → descarga → chunks 10 min + detección silencio
→ Whisper → DeepSeek (acta + acuerdos) → Daily (participantes)
→ booking.processing_status = 'completado' → ImprovementGoal actualizado
```

---

## 📝 Módulo SIMCE (`simce/`)

Generador de pruebas con IA en dos modos:
- **Modo SIMCE**: formulario clásico, entrega al final
- **Modo Pistas**: AJAX por pregunta, puntaje 4-3-2-0 según intentos

Flujo: Biblioteca de textos → generar/revisar → crear prueba → generar preguntas por nivel → publicar → rendir

---

## 💰 Costos Mensuales Estimados

| Componente | Costo USD/mes |
|-----------|--------------|
| Railway app + PostgreSQL | ~$7 |
| Daily.co videollamadas | $0–5 |
| Cloudflare R2 (videos 90 días) | ~$3 |
| DeepSeek (41 asesores + SIMCE) | ~$1–2 |
| OpenAI Whisper (transcripciones) | ~$3–5 |
| **Total** | **~$14–22 USD** |
