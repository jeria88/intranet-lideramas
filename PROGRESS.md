# PROGRESS.md — Guía de continuación para cualquier IA

> **Actualizado:** 2026-05-17 · Últimos commits: `cab9684` (_REGLA_TOPICO) → `187e73d` (feedback pilotaje) → `2e8a93f` (nav dashboard) → `22bcfc8` (fixes prompts art+inspector)
> Leer esto ANTES de hacer cualquier cambio al código.

---

## 🏗️ Arquitectura General

Intranet escolar chilena (Red SFA — 8 establecimientos) desplegada en **Railway** + **GitHub Actions**.
- Stack: **Django / Python 3.12 / PostgreSQL (Railway) / Cloudflare R2 / Daily.co / OpenAI / DeepSeek**
- Restricción crítica: servidor <4 GB RAM → sin numpy, sin pgvector; embeddings como JSONField
- Roles de usuario: `DIRECTOR`, `UTP`, `INSPECTOR`, `CONVIVENCIA`, `REPRESENTANTE`, `RED`
- Establecimientos: `TEMUCO`, `ANGOL`, `ARAUCO`, `IMPERIAL`, `LAUTARO`, `ERCILLA`, `SANTIAGO`, `RENAICO`
- Deploy: push a `main` → Railway corre Procfile automáticamente (migrate + setup_all_establishments + collectstatic)

---

## ✅ MÓDULO COMPLETADO: Asistentes IA (`ai_modules/`)

### Estado actual
- **41 asistentes** activos: 5 roles × 8 establecimientos + 1 RED
- **Sistema de conversaciones** estilo ChatGPT: sidebar con historial + panel de chat unificado (`chat_app.html`)
- **Prompts gestionados** por `setup_all_establishments.py` — fuente única de verdad, actualiza en cada deploy con `--update-prompts`

### Arquitectura de prompts (orden de inyección)
```
_REGLA_URGENCIA          ← primero siempre (gate 🚨 denuncia obligatoria)
prompt_rol(est_name)     ← tabla PASO 1 + competencias del estamento
_PASOS                   ← IF NO → para / IF SÍ → continúa PASO 2-4
_META_REGLA
_REGLA_TOPICO            ← rechaza consultas fuera del dominio escolar
_REGLA_DIAGNOSTICOS
_REGLA_CONFLICTOS
_REGLA_INTEGRIDAD        ← prohíbe citar artículos con contenido sin RAG
_REGLA_RICE
_REGLA_OPD_OLN
_ORGANIGRAMA_DERIVACION
_RECORDATORIO_FORMATO
_DISCLAIMER
```

### Vulnerabilidades resueltas (resultado test piloto UTP)
| Vulnerabilidad | Fix aplicado |
|---|---|
| Urgencia no disparaba | `_REGLA_URGENCIA` inyectada al inicio (primacy) |
| Rol incorrecto continuaba PASO 2-4 | `_PASOS` con IF/ELSE explícito |
| Inspector tomaba casos de UTP | `prompt_inspector` con sección NO COMPETENCIA explícita |
| Artículos laborales inventados (CT, ED) | `_REGLA_INTEGRIDAD` item 4 con lista de artículos prohibidos |
| Consultas off-topic (recetas, etc.) | `_REGLA_TOPICO` con mensaje de rechazo fijo |
| Contaminación de historial | No ocurrió en test (sistema ok) |

### Modelos de conversación
```python
ChatConversation: user, assistant, title, created_at, updated_at, case(FK)
ConversationMessage: conversation, role (user/assistant), content, timestamp
PilotFeedback: user, origin (banner/respuesta_ia), message(FK nullable), feedback_text, created_at
```

### Vistas de conversación
| Vista | URL | Descripción |
|-------|-----|-------------|
| `conversation_list` | `/<slug>/conversaciones/` | Redirige a última conv o muestra empty state |
| `conversation_new` | `/<slug>/conversaciones/nueva/` | Crea nueva conv y redirige |
| `conversation_detail` | `/<slug>/conversaciones/<id>/` | GET: carga chat; POST: envía mensaje, retorna `response + message_id + new_title` |
| `submit_pilot_feedback` | `/feedback/piloto/` | POST — guarda PilotFeedback |

### Navegación
- Botón "Volver" en chat → `portal:index` (dashboard)
- URL `/<slug>/` redirige a `conversation_list` (vista detalle eliminada)
- `ai_list` redirige a `conversation_list` del asistente

### Sistema de feedback de pilotaje
- **Banner amarillo** en cabecera del chat → modal feedback general (`origin='banner'`)
- **👎 por burbuja IA** → modal con contexto pre-cargado + `origin='respuesta_ia'` + FK al mensaje
- Input obligatorio en ambos; si vacío → borde rojo sin enviar
- Al enviar: toast ✓, botón 👎 se convierte en ✓ deshabilitado

---

## ✅ MÓDULO COMPLETADO: Videollamadas (`meetings/`)

Pipeline 100% automático.

```
Booking creado → CalendarEvent + ImprovementGoal (IA)
Usuario entra → Daily "meeting-started" → Django inicia grabación (async thread)
Reunión termina → "recording.ready-to-download" → processing_status = 'pendiente'
GitHub Actions (cron 15min) → descarga → chunks 10min + detección silencio
→ Whisper → DeepSeek (acta + acuerdos) → Daily (participantes)
→ /api/update/ → processing_status = 'completado' → ImprovementGoal actualizado
```

---

## ✅ MÓDULO COMPLETADO: SIMCE (`simce/`)

Generador de pruebas con IA. Arquitectura nueva desde migración 0005.

### Modelos
`TextoBiblioteca` · `PreguntaBanco` + `AlternativaBanco` · `PruebaTexto` (junction) · `SimceDocumento` + `SimceChunk` (RAG)

### Flujo admin
```
Biblioteca → generar/crear textos → revisar/aprobar
→ "Crear test desde biblioteca" → selecciona textos → configura preguntas por nivel
→ lanzar generación IA → revisión final → aprobar → publicar
```

### Dos modos para estudiantes
- **Modo SIMCE**: formulario clásico, entrega al final
- **Modo Pistas**: AJAX por pregunta, puntaje 4-3-2-0 según intentos

---

## 🎯 PRÓXIMOS PASOS

- [ ] **Analizar feedbacks piloto** — revisar `PilotFeedback` en admin Django después de la semana de pilotaje
- [ ] Indexar PDFs MINEDUC para RAG (`python manage.py index_simce_docs`)
- [ ] Notificaciones push cuando procesamiento de reunión termine
- [ ] Badges de estado en lista de grabaciones
- [ ] Indexar PME faltante en Knowledge Base

---

## Commits Recientes

| Hash | Descripción |
|------|-------------|
| `cab9684` | fix(prompts): agrega _REGLA_TOPICO — rechaza consultas fuera del dominio escolar |
| `187e73d` | feat(chat): sistema de feedback de pilotaje (banner + 👎 por respuesta) |
| `2e8a93f` | feat(nav): volver desde chat va al dashboard, elimina vista detalle |
| `22bcfc8` | fix(prompts): refuerza prohibición de artículos laborales y delimita rol Inspector |
| `e2e45de` | feat(chat): interfaz ChatGPT — sidebar conversaciones + panel unificado |
| `b94ad21` | feat(simce): CRUD completo TextoBiblioteca y PreguntaBanco |

---

## Secretos de Entorno

| Variable | Descripción |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL Railway |
| `DAILY_API_KEY` | API Daily.co |
| `OPENAI_API_KEY` | Embeddings text-embedding-3-small |
| `DEEPSEEK_API_KEY` | Motor IA (base_url: api.deepseek.com, modelo: deepseek-chat) |
| `AWS_ACCESS_KEY_ID` | Cloudflare R2 |
| `AWS_SECRET_ACCESS_KEY` | Cloudflare R2 |
| `AWS_STORAGE_BUCKET_NAME` | `intranet-sfa-storage` |
| `AWS_S3_ENDPOINT_URL` | Endpoint R2 |
| `INTERNAL_API_KEY` | Seguridad webhooks/API interna |
