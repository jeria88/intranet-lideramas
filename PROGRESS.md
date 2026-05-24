# PROGRESS.md — Guía de continuación para cualquier IA

> **Actualizado:** 2026-05-24 · Últimos commits: `3c28a99` (archive SFA users) · `1b6839e` (multi-tenancy) · `c7ca386` (rebranding LiderA+)
> Leer esto ANTES de hacer cualquier cambio al código.

---

## 🏗️ Arquitectura General

**LiderA+** — Plataforma multi-tenant de gestión educacional desplegada en **Railway** + **GitHub Actions**.
- Stack: **Django / Python 3.12 / PostgreSQL (Railway) / Cloudflare R2 / Daily.co / OpenAI / DeepSeek**
- Restricción crítica: servidor <4 GB RAM → sin numpy, sin pgvector; embeddings como JSONField
- Dominio: `intranet.lideramas.cl`
- Deploy: push a `main` → Railway corre Procfile automáticamente

---

## 🌐 Multi-tenancy (implementado 2026-05-24)

Usuarios aislados por campo `tenant` en el modelo User.

```python
# User.tenant + unique_together(username, tenant)
# Login: intranet.lideramas.cl/{tenant}/login/
# Auth backend: users.backends.TenantAuthBackend
# Middleware: users.middleware.TenantMiddleware → inyecta request.tenant desde sesión
```

**Tenants:**
| Slug | Estado | Detalle |
|------|--------|---------|
| `sfa` | ⚠️ Archivado | Contrato pausado 2026-05-24. Usuarios desactivados, contraseña de archivo guardada en `.env`. Solo admin activo. |

**Para crear nuevo tenant:**
```bash
python manage.py activate_all_users --tenant slug-proyecto
```

**Para archivar un tenant:**
- Crear comando similar a `archive_sfa_users.py` con el slug correspondiente
- Remover su `activate_all_users --tenant X` del Procfile

---

## ⚠️ Estado Tenant SFA — ARCHIVADO

- `archive_sfa_users` corre en cada deploy: desactiva todos los no-superusers de tenant='sfa'
- Contraseña de archivo en `.env` (variable `SFA_ARCHIVED_PASSWORD`)
- Admin (`is_superuser=True`) permanece activo
- Establecimientos del piloto: TEMUCO, LAUTARO, RENAICO, SANTIAGO, IMPERIAL, ERCILLA, ARAUCO, ANGOL

---

## ✅ MÓDULO COMPLETADO: Asistentes IA (`ai_modules/`)

### Estado actual
- **41 asistentes** por tenant SFA: 5 roles × 8 establecimientos + 1 RED
- **Sistema de conversaciones** estilo ChatGPT: sidebar con historial + panel de chat unificado
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

### Modelos de conversación
```python
ChatConversation: user, assistant, title, created_at, updated_at, case(FK)
ConversationMessage: conversation, role (user/assistant), content, timestamp
PilotFeedback: user, origin (banner/respuesta_ia), message(FK nullable), feedback_text, created_at
```

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

Generador de pruebas con IA. Arquitectura desde migración 0005.

### Modelos
`TextoBiblioteca` · `PreguntaBanco` + `AlternativaBanco` · `PruebaTexto` (junction) · `SimceDocumento` + `SimceChunk` (RAG)

### Dos modos para estudiantes
- **Modo SIMCE**: formulario clásico, entrega al final
- **Modo Pistas**: AJAX por pregunta, puntaje 4-3-2-0 según intentos

---

## 🎯 PRÓXIMOS PASOS

### Pendiente técnico (cuando se reactive un tenant)
- [ ] Analizar feedbacks piloto SFA — revisar `PilotFeedback` en admin Django
- [ ] Indexar PDFs MINEDUC para RAG (`python manage.py index_simce_docs`)
- [ ] Notificaciones push cuando procesamiento de reunión termine
- [ ] Indexar PME faltante en Knowledge Base
- [ ] Indexar RICE/RIOHS para los otros 7 establecimientos SFA

### Pendiente producto (nuevo negocio Lideramas)
- [ ] Definir modelo de negocio con Franco y su hermano
- [ ] Onboardear primer tenant nuevo (configurar establecimientos, roles, prompts)
- [ ] Considerar si ESTABLISHMENT_CHOICES debe volverse dinámico por tenant

---

## ✅ Knowledge Base — Estado al 2026-05-18

### Supabase — documentos activos (tenant SFA)
- **Nacional** (~10.800 chunks): CT, Constitución, Estatuto Docente, Ley Inclusión, Ley Buen Trato, Ley TEA, Ley RNPA, Ley Asistentes Educación, Ley Transparencia, Ley Compras Públicas, Ley Protección Datos, Ley Aula Segura, Ley Convivencia Escolar, DFL-1, DFL-2, Decreto 67, MBDLE, IDPS, Plan Seguridad Escolar, Ley Indígena, entre otras
- **Congregacional**: Manual Cuentas 2026, Oficio CGR 60820, Normativa congregacional
- **Institucional/Temuco**: RICE 2025 (36 chunks), RIOHS 2025 (72 chunks), Reglamento Interno 2025, Reglamento Evaluación, PEI, Política Convivencia MINEDUC, Ley 21430, Ley 20845, Derechos del Niño

### Fix aplicado (ingest)
- `ingest_md_to_knowledge.py`: busca assistant en `knowledge_base` DB (no en `default`) — evita FK violation entre Supabase y Railway

---

## Commits Recientes

| Hash | Descripción |
|------|-------------|
| `3c28a99` | Simplifica archive_sfa_users: contraseña fija, sin variable de entorno |
| `fc86770` | Archiva tenant SFA: usuarios inhabilitados, contraseña en .env |
| `1b6839e` | Multi-tenancy por path: /{tenant}/login/, /{tenant}/logout/ |
| `e882ecb` | Ajuste logo LiderA+: tamaño proporcional y mix-blend-mode |
| `c7ca386` | Rebranding completo SFA → LiderA+ (50 archivos) |
| `a13820b` | restore: prompts de establecimientos a estado pre-v8 |
| `82562c8` | feat: v3.1 — pipeline 2 etapas con RAG preprocesado + postprocesado |

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
| `AWS_STORAGE_BUCKET_NAME` | Bucket R2 |
| `AWS_S3_ENDPOINT_URL` | Endpoint R2 |
| `INTERNAL_API_KEY` | Seguridad webhooks/API interna |
