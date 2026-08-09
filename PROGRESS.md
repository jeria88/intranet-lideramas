# PROGRESS.md — Guía de continuación para cualquier IA

> **Actualizado:** 2026-08-09 · Rama `refactor/multi-tenant` · Últimos commits: `883b60e`, `cc7ca13`, `c0d2d7a` (SIMCE), `c1b33f0` (listo para contactar), `c05093f` (CRM)
> Leer esto ANTES de hacer cualquier cambio al código.
>
> **El nombre de la carpeta miente: ya no se despliega en Railway.** Corre en Oracle con systemd. Ver §Despliegue.

---

## Qué es esto hoy

**LíderA+** — plataforma educacional multi-tenant, **producto**, no la intranet de un cliente. Un solo cliente la usó (contrato terminado en mayo de 2026) y su marca se retiró del código el 2026-08-08.

- Stack: **Django 6.0 / Python 3.12 / PostgreSQL 16 nativa (Oracle) / Cloudflare R2 / Daily.co / OpenAI / DeepSeek**
- Restricción crítica: servidor sin holgura → sin numpy, sin pgvector; embeddings como JSONField
- **En vivo:** https://lidera.146.181.39.4.sslip.io — dominio propio todavía no (ver §Pendientes)
- **Estado de la base:** limpia desde el 2026-08-08. Una organización `demo`. Sin datos de clientes.

### Comando de tests — memorizarlo

```bash
cd ~/Intranet/intranet_railway && KNOWLEDGE_BASE_URL= .venv/bin/python manage.py test
# 2026-08-09: Ran 205 tests in 164.367s / OK
```

⚠️ **El `KNOWLEDGE_BASE_URL=` vacío no es opcional.** Sin él, `config/settings.py:104-115` arma un segundo alias de base contra el **Supabase de producción** y el runner intenta crear una base de test ahí. `load_dotenv` no sobrescribe el entorno del shell, así que la variable vacía gana.

---

## Multi-tenancy — cómo funciona de verdad

Hasta agosto de 2026 el aislamiento era **de credenciales, no de datos**: `User.tenant` era un CharField y ningún otro modelo tenía dueño. Hoy hay tres capas.

### 1. Las tablas

```python
Organizacion(slug, nombre, activa, modulos, creada_en)   # slug == el viejo User.tenant
Establecimiento(organizacion, codigo, nombre, rbd, es_equipo_central, activo)
User.organizacion / User.establecimiento                 # FK; los CharFields viejos siguen como espejo
```

### 2. El aislamiento — automático por request (`users/scoping.py`)

**19 modelos** heredan `ModeloDeOrganizacion`. El filtro NO está en las vistas: está en el manager, alimentado por un `contextvar` que fija `TenantMiddleware`.

| Estado del contextvar | Comportamiento |
|---|---|
| `FUERA_DE_REQUEST` (default) | **No filtra.** Comandos, migraciones y shell funcionan igual que antes |
| `TODAS` | Superusuario |
| `Organizacion` \| `None` | Filtra. `None` devuelve **cero filas**, no la tabla |

- `objects` filtra · **`todos` nunca filtra** y es el `base_manager_name` (Django lo usa para resolver FK; una relación válida no puede levantar `DoesNotExist` a mitad de un request).
- `save()` asigna la organización del alcance activo cuando la fila no la trae. Sin esto, un `objects.create()` en una vista produce una fila que el propio filtro vuelve invisible para todos.
- El campo va solo en **raíces de agregado**. Los hijos (`Pregunta` dentro de `Prueba`) se filtran por su padre.
- 🛡️ **Meta-test de cobertura** (`users/tests_aislamiento.py`): recorre las FK **transitivamente** y falla si aparece un modelo de negocio sin aislar y sin ancestro aislado. Ya encontró tres.

**Verificado en producción 2026-08-09:** dos organizaciones, dos logins reales por HTTP → 0 de 6 asistentes de B visibles para A; A pidiendo un asistente de B por URL directa → 404.

### 3. Módulos contratables (`users/middleware.py`)

`Organizacion.modulos` = lista JSON. **Lista vacía = todo contratado** (el campo se agregó sobre organizaciones que ya usaban todo; restringir es un acto explícito).

| Prefijo | Módulo |
|---|---|
| `/ia/` | asistentes |
| `/simce/` | simce |
| `/salas/` | reuniones |
| `/mejora/` | mejora |
| `/biblioteca/` | biblioteca |

El corte es **por prefijo de URL, no por decorador**: cada módulo tiene decenas de vistas y la que se olvide del decorador queda abierta. Denegar es `messages.error` + `redirect`, nunca 403 crudo — y el middleware va **después** de `MessageMiddleware`, o `request._messages` no existe todavía y el mensaje se pierde.

### Alta y baja de una organización

```bash
python manage.py crear_organizacion --slug colegio-andes --nombre "Colegio Los Andes" \
    --establecimientos "Sede Centro,Sede Norte" [--modulos "simce,reuniones"]
# → crea sedes + equipo central + 5 asistentes por sede, con los prompts de rol ya montados

python manage.py purgar_organizacion --slug colegio-andes --confirmar colegio-andes
```

🕳️ **`purgar_organizacion` NO funciona en la instancia de Oracle.** Al cascadear, `AIAssistant` arrastra `AIKnowledgeChunk`, que el router manda a la base `knowledge_base`, y esa tabla no existe ahí: `ProgrammingError: relation "ai_modules_aiknowledgechunk" does not exist`. La baja de un cliente está rota en producción. Sin arreglar.

---

## Asistentes IA (`ai_modules/`) — 🔴 NO SE VENDEN TODAVÍA

**La alucinación de citas normativas sigue abierta y medida:** `eval_2026-05-20_01-15.md:9`, TX004 con artículos inventados, ~13 de 19 casos en WARN o FAIL. Es la pieza de mayor diferencial del producto y por eso mismo no sale rota.

### El motor ya no se elige por el nombre

`AIAssistant.motor` (default `v3`) + `ai_modules/motores.py` como único punto de despacho.

🕳️ El dispatch viejo (`slug.endswith('-v3')`) **ya estaba roto y nadie lo sabía**: al prefijar los slugs por organización (`<org>-<rol>-<sede>`) ningún asistente termina en `-v3`, así que todos habrían respondido con **v1** en silencio.

v1 y v2 siguen disponibles vía el campo `motor`. **No se eliminan** hasta correr el eval comparativo (gasta API real).

### Arquitectura de prompts (orden de inyección)

```
_REGLA_URGENCIA          ← primero siempre (gate 🚨 denuncia obligatoria)
prompt_rol(est_name)     ← ai_modules/plantillas_roles.py
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

⚠️ **Envenenamiento por ejemplo negativo:** poner artículos específicos dentro de una prohibición **se los enseña al modelo**. Las prohibiciones nunca deben nombrar los artefactos exactos que prohíben. Costó varias rondas de eval descubrirlo.

Los 5 prompts de rol (~500 líneas de dominio educacional chileno) viven en `ai_modules/plantillas_roles.py`, extraídos tal cual y sin el nombre del colegio, que estaba **dentro** de cada uno.

---

## SIMCE (`simce/`) — la primera pieza que sale a vender

Generador de ensayos con IA. Comprador: el **UTP** de un colegio.

### Modelos
`TextoBiblioteca` · `PreguntaBanco` + `AlternativaBanco` · `PruebaTexto` (junction) · `SimceDocumento` + `SimceChunk` (RAG) · `SesionEstudiante` (con `sede` como FK real desde `d825d64`)

### Dos modos de rendición
- **Modo SIMCE**: formulario clásico, entrega al final, campos `p_<pk>`
- **Modo Pistas**: AJAX por pregunta (`verificar_respuesta`), puntaje 4-3-2-0 según intentos

⚠️ Son flujos distintos: mezclarlos al probar da un 0% que no es real.

### Tres defectos que impedían generar un ensayo publicable (arreglados 2026-08-08)

1. **El UTP no podía entrar al panel.** `is_staff = lambda u: u.is_staff or u.is_superuser` — y un colegio cliente no tiene usuarios `is_staff`, los crea el proveedor. La demo del producto no funcionaba para su comprador.
2. **La generación reventaba con JSON casi válido.** Una coma de más antes de un `}` → `JSONDecodeError`, prueba en estado `error` sin explicación. Ahora tolera comas finales, vallas de código y prosa alrededor.
3. **La respuesta correcta caía siempre en D** (6 de 6). La rúbrica lo detectaba y no aprobaba ninguna prueba: el control de calidad estaba bien, el generador nunca entregaba.

---

## Videollamadas (`meetings/`)

```
Booking creado → CalendarEvent + ImprovementGoal (IA)
Usuario entra → Daily "meeting-started" → Django inicia grabación (async thread)
Reunión termina → "recording.ready-to-download" → processing_status = 'pendiente'
GitHub Actions (cron 15min) → descarga → chunks 10min + detección silencio
→ Whisper → DeepSeek (acta + acuerdos) → Daily (participantes)
→ /api/update/ → processing_status = 'completado' → ImprovementGoal actualizado
```

⚠️ El webhook de Daily y el worker de actas **no tienen usuario**. El aislamiento por request los rompió en silencio una vez; hay tests que lo vigilan.

---

## CRM comercial (`crm/`) — a quién le vendemos

**Ojo con la dirección:** no son datos de un cliente, son los datos con los que se consigue un cliente. Por eso `crm/` **NO** hereda `ModeloDeOrganizacion` — si se aislara, Franco vería cero leads por no pertenecer a ninguna organización. El acceso va por `is_staff`. Hay un test que lo vigila.

`Vertical` · `Ciudad` · `Target` · `Etapa` · `Lead` · `Contacto`. Kanban con arrastre, ficha con historial, importador CSV agnóstico de la fuente.

```bash
python manage.py importar_leads --csv archivo.csv --vertical educacion --ciudad Temuco [--simular]
```

Decisiones copiadas de `acme-leads` y ARQlead, que ya pagaron el aprendizaje:
- `hash_dedupe` sobre el **nombre normalizado y nada más**. Incluir el teléfono parece más preciso y es peor: dos fuentes del mismo colegio, una con teléfono y otra sin él, dejarían de colisionar.
- Etapa inicial por `MIN(orden)`, **no por nombre**. En ARQlead eso dejó 20 leads invisibles con `stage_id` NULL.
- La normalización borra los puntos pero convierte el resto de la puntuación en espacio: `Colegio S.A.` debe colapsar con `Colegio SA`, pero `Colegio-San José` debe separarse.

**Estado: 0 leads.** Es lo único que bloquea empezar a vender.

---

## Despliegue — Oracle, no Railway

| Qué | Dónde |
|---|---|
| Host | `146.181.39.4`, `/home/ubuntu/lideramas` |
| Proceso | `systemctl {status,restart} lideramas` — gunicorn, 2 workers, timeout 300s |
| Log | `/home/ubuntu/logs/lideramas.log` |
| Base | PostgreSQL 16 **nativa**, base `lideramas` (no un contenedor más) |
| Entrada | Traefik → `lideramas-proxy` (nginx:alpine) → `host.docker.internal:8010` |
| Puerto | 8010, solo acepta tráfico de `10.0.2.0/24` (iptables) |

**Nunca escribir una IP fija en la configuración de ruteo.** Causa raíz ya pagada: un YAML con `10.0.2.12` hizo que `michicosas.store` sirviera públicamente el CRM de ARQlead durante ~6 semanas, porque Docker reasignó esa IP al morir el otro contenedor.

🕳️ **Bucle de redirección al montar el proxy:** nginx ponía `X-Forwarded-Proto: $scheme` y, como escucha en el puerto 80, ese valor es `http` — pisaba el `https` de Traefik y Django (`SECURE_SSL_REDIRECT`) redirigía sin fin. Fix: un `map` que propaga el valor original y solo cae a `$scheme` si nadie lo mandó.

⚠️ Con `SECURE_PROXY_SSL_HEADER` configurado, Django mira **solo** ese header: cualquier prueba con el test client debe mandar `HTTP_X_FORWARDED_PROTO=https` o todo responde 301. Y el host debe estar en `ALLOWED_HOSTS`: `testserver` no lo está y devuelve 400.

---

## Pendientes

### Bloquea vender
- [ ] **Cargar leads en el CRM.** El importador está probado; falta la lista. El directorio del MINEDUC **no está verificado** como descargable — por eso el importador no depende de él.

### Bloqueado por algo externo
- [ ] **Dominio propio.** `lideramas.cl` e `intranet.lideramas.cl` resuelven a Cloudflare y devuelven **404**: no hay nada publicado. El `.env` y `ALLOWED_HOSTS` del servidor ya lo contemplan. Requiere tocar Cloudflare.
- [ ] **Landing** (`~/Proyectos/lideramas/lideramas-web`): alineada y commiteada, **sin deployar**. El push a GitHub no publica solo.
- [ ] **Eval de asistentes** (`manage.py eval_assistants`): gasta API real y los datos de evaluación se fueron con la purga. Sin eso, v1 y v2 no se eliminan y los asesores no se venden.

### Higiene
- [ ] 🔒 `director.admin` lo crea `ai_modules/migrations/0017` y la `0021` le fija una **contraseña escrita en el repo**. Estaba activo en la instancia pública sin haber entrado nunca; **desactivado el 2026-08-09** por SQL (`is_active = false`). La migración sigue ahí: cualquier instancia nueva lo vuelve a crear activo.
- [ ] Restos de la marca del cliente fuera del alcance del guardia: `ai_modules/management/commands/eval_assistants.py` (slugs `utp-temuco`, `inspector-temuco`… en los casos de prueba) y `scripts/test_pipeline_dev.py` (nombre del colegio en prosa).
- [ ] `ai_modules/knowledge_base/` (43 MB) son documentos institucionales de una sede concreta. El corpus fuente vive intacto en `~/Intranet/ia-trainning/` (5,8 GB).
- [ ] Deriva de migraciones: `makemigrations` propone migraciones no relacionadas en 5 apps. Deuda preexistente, no del refactor.
- [ ] `~/Intranet/CLAUDE.md` sigue describiendo Railway, Supabase y "Red SFA". Sus prohibiciones apuntan a infraestructura que ya no es la de este proyecto.

### Conocido, no se arregla ahora
- `threading.Thread` daemon con gunicorn (`simce/views.py:117-121`): aguanta usuarios de a uno. Se vuelve cuando haya concurrencia real.
- Llamada LLM síncrona en request (`improvement_cycle/views.py:67`): el timeout de 300s la cubre.
- Oracle tiene 2 vCPU y **sin swap**: un pico de RAM mata procesos sin aviso. No lanzar nada CPU-intensivo junto con los renders de reels de content-studio.

---

## Trampas que ya costaron tiempo

| Síntoma | Causa |
|---|---|
| Los tests no corren, `OperationalError: near "SET"` | `simce/migrations/0005` ejecutaba `SET CONSTRAINTS` (PostgreSQL puro) como RunSQL crudo. Arreglado con guarda por vendor |
| El runner no descubre tests | Un script en la raíz que hacía `django.setup()` al importarse. Movido a `scratch/` |
| La base de test no nace vacía | `ai_modules/0017` y `0021` **crean usuarios durante las migraciones**. Cualquier test que asuma tablas vacías es frágil |
| `auth.W004` en cada `manage.py check` | Intencional: la unicidad es `unique_together('username','tenant')` |
| Todo responde 301 o 400 al probar | Falta `HTTP_X_FORWARDED_PROTO=https` o el host no está en `ALLOWED_HOSTS` |

---

## Secretos de entorno

| Variable | Descripción |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL en Oracle (nativa) |
| `KNOWLEDGE_BASE_URL` | Supabase del RAG. **Vaciar al correr tests** |
| `DAILY_API_KEY` | API Daily.co |
| `OPENAI_API_KEY` | Embeddings text-embedding-3-small |
| `DEEPSEEK_API_KEY` | Motor IA (`api.deepseek.com`, modelo `deepseek-chat`) |
| `AWS_*` | Cloudflare R2 (bucket, endpoint, credenciales) |
| `INTERNAL_API_KEY` | Seguridad webhooks/API interna |
