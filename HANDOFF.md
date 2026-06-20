# HANDOFF — RúbricaIA (estado para continuar)

> Documento de traspaso. Si eres un nuevo asistente retomando este proyecto:
> **lee esto completo y luego revisa el repo a fondo** antes de tocar nada. Actúa como
> **mentor técnico, arquitecto cloud y estratega de hackatón**, con criterio fuerte,
> crítico y orientado a GANAR según la rúbrica (no a hacer cosas bonitas). Sé
> incremental, no sobre-ingenieres, una sola ruta recomendada, señala riesgos y
> mitígalos. Trabaja por fases testeables: construyes → el usuario despliega y prueba →
> sigues.

---

## 0. Dónde retomar (LO PRIMERO)

El usuario **acaba de pushear el código** y va a continuar con **G2 (multinube OCI + RAG)**,
que ya está **codificado pero no desplegado en OCI**. El siguiente paso es del usuario, en
OCI:

1. Levantar/usar la VM de OCI (compartment `lab-oci`, VCN `vcn-lab`, Oracle Linux **ARM**).
2. Abrir el puerto **8000** (Security List de OCI + `firewall-cmd` del SO).
3. En la VM: `git clone` del repo → `cd oci-rag` → `docker compose up -d --build`
   (o el modo manual con podman; ver `oci-rag/README.md`).
4. Probar el servicio RAG **desde internet**: `curl http://<IP-PUBLICA>:8000/health`.
5. **Solo si responde**, poner `export RAG_URL="http://<IP-PUBLICA>:8000"` en `deploy/env.sh`
   y hacer `serverless deploy` en la VM de AWS → el Worker empieza a usar RAG.
6. Probar una entrega end-to-end y, al final, **actualizar README + diagrama** para
   reflejar la multinube (coherencia criterio 5).

Riesgo de G2: el build de `fastembed`/onnxruntime en ARM y la red de OCI. **G2 es aditivo
con degradación elegante**: si `RAG_URL` está vacío o OCI falla, el Worker evalúa igual.
No puede romper lo ya logrado.

Después de G2, lo único pendiente del entregable obligatorio es el **video** (≤5 min).

---

## 1. Qué es el proyecto (estado actual)

**RúbricaIA** ya **no es solo** el lote batch original: es una **plataforma multi-tenant**
donde un docente crea **clases** y **tareas** (cada una con su rúbrica, pesos opcionales y
fecha límite), invita estudiantes, y cada alumno sube su entregable en **PDF/Word**; un
**LLM (Groq)** lo evalúa **criterio por criterio** (cumple/evidencia/sugerencia, % derivado
de los criterios). El docente ve las entregas y estadísticas de la clase.

Reto: **arquitectura basada en eventos, asíncrona y serverless**, lotes 20–30, resiliencia
ante límites del LLM. Equipo de 3 (en la práctica lo construyó uno). Curso Cloud Computing.

---

## 2. Rúbrica — estado (≈19-20/20)

| # | Criterio | Estado |
|---|----------|--------|
| 1 | Contexto e impacto | ✅ `docs/contexto.md` |
| 2 | Diseño y diagrama | ✅ `docs/arquitectura.svg` + arquitectura event-driven |
| 3 | Resiliencia/LLM | ✅ lotes, SQS/DLQ, backoff+Retry-After, idempotencia, retry |
| 4 | Frontend/UX | ✅ URL pública, multi-tenant, PDF/Word, diseño propio |
| 5 | Repo/código/manual | ✅ README + manual + contrato + código limpio |

**Pendiente obligatorio: el video de YouTube** (no es criterio numerado pero lo piden).
G2 (multinube) es bonus: es lo único que puede sumar algo nuevo (la rúbrica menciona
"no se limita a una sola nube"), pero es lo más frágil.

---

## 3. Arquitectura actual (desplegada y funcionando)

Dos planos:

- **Plano de control (síncrono):** Frontend (React/Vite en Amplify) → API Gateway (HTTP API)
  → Lambdas `auth` (JWT, dominio `@utec.edu.pe`, rol por allowlist) y `lms` (clases, tareas,
  membresías, entregas del profesor) → DynamoDB `rubricaia-lms-dev`.
- **Plano de datos (event-driven, asíncrono):** entrega → API λ (presigned) → **S3** →
  evento → **Splitter** → **SQS (+DLQ)** → **Worker** → **Groq** → DynamoDB `rubricaia-dev`
  → **Streams** → **Aggregator** (STATS en vivo) → al completar el lote emite `JobCompleted`
  en **EventBridge** → fan-out a **SNS** (email al docente) y **Report λ** (reporte de clase
  CSV/JSON/HTML a S3).

**7 Lambdas:** auth, lms, api, splitter, worker, aggregator, report.
**Diagrama:** `docs/arquitectura.svg`. **Contrato de datos:** `docs/contrato-datos.md`.
Todo es IaC en `serverless.yml` (un `serverless deploy` levanta todo).

---

## 4. Qué se construyó (resumen de lo hecho desde el handoff original)

Sobre la base original (4 Lambdas, batch CSV) se añadió, en este orden:

1. **Fase 3B** — EventBridge (`JobCompleted`) + SNS (email docente) + Report Lambda
   (reporte de clase CSV/JSON/HTML a S3). El Aggregator detecta el cierre del lote y emite
   una sola vez (escritura condicional `attribute_not_exists(completed)`).
2. **5 features de backend:** F1 reprocesar fallidos (`POST /jobs/{id}/retry`), F2 resumen
   ejecutivo de clase por LLM (en Report), F3 backoff exponencial + `Retry-After` con jitter
   (Worker), F4 detección de similitud anti-copia (TF-IDF coseno, stdlib), F5 ponderación de
   criterios por el docente.
3. **Subida PDF/Word/TXT:** extracción de texto en el navegador (pdf.js + mammoth por CDN,
   ver `index.html` y `frontend/src/extract.js`). El backend sigue recibiendo el mismo CSV.
4. **Plataforma multi-tenant (F1–F5):** auth JWT con `backend/common/authlib.py` (HS256 +
   PBKDF2, stdlib), gestión de clases, invitación con **compuerta de aceptación**, tareas con
   rúbrica/pesos/fecha, y entrega del alumno ligada a la tarea (la rúbrica/pesos la fija la
   tarea, no el alumno). Tabla `rubricaia-lms-dev` (diseño PK/SK con ítems espejo, sin GSI).
5. **Rediseño editorial + logo propio** (P1): tema papel claro, Fraunces + Inter, acento
   verde pino. P2: vista del profesor con entregas/resultados por tarea + insights. P3: vista
   de resultado del alumno limpia (anillo + criterios). P4: fechas límite con chips, auto-logout
   en 401, refrescar entregas, responsive.
6. **G1 — historial de intentos** del alumno (versiones `SUBVER#`, `GET /tasks/attempts`,
   tendencia de cumplimiento entre intentos).
7. **F7 — documentación:** `docs/contexto.md`, `docs/arquitectura.svg`, README raíz,
   `docs/manual-despliegue.md` reescrito, `docs/contrato-datos.md` actualizado. Limpieza de
   código muerto (se quitaron `UploadView`, `Dashboard`, `ReportBar` del frontend y exports
   sin uso de `api.js`) y de archivos legacy (`deploy/deploy.sh`, `teardown.sh`,
   `deploy-frontend-s3.sh`).
8. **G2 (en curso) — multinube OCI + RAG:** `oci-rag/` (FastAPI + FastEmbed + Qdrant, con
   `docker-compose.yml`); el Worker llama al servicio RAG en OCI si `RAG_URL` está definido
   (degradación elegante si no). **Código pushed; falta levantarlo en OCI** (ver sección 0).

---

## 5. Recursos desplegados (AWS Learner Lab)

- **Cuenta:** `334461248248` · **Región:** `us-east-1` · **Stack:** `rubricaia-dev`
- **API endpoint:** `https://m0mx1jdgna.execute-api.us-east-1.amazonaws.com`
  (se mantiene en deploys de actualización; CAMBIA solo en un deploy fresco remove+deploy)
- **Frontend Amplify:** `https://main.d2aurxjj1g5f03.amplifyapp.com` (appId `d2aurxjj1g5f03`)
- **DynamoDB:** `rubricaia-dev` (jobs, Streams) y `rubricaia-lms-dev` (usuarios/clases/tareas)
- **S3:** `rubricaia-inputs-334461248248-dev` (inputs/ y reports/)
- **SQS:** `rubricaia-jobs-dev` + `rubricaia-dlq-dev`
- **EventBridge:** bus `rubricaia-events-dev` · **SNS:** `rubricaia-notify-dev`
- **Serverless Framework:** org `oswaldoaqm`, app `rubricaia`, v4
- **Repo:** https://github.com/oswaldoaqm/rubricaia
- **OCI (G2):** compartment `lab-oci`, VCN `vcn-lab`, VM Oracle Linux ARM (A2.Flex);
  acceso por OCI Cloud Shell + SSH (`opc@<ip>`). Puertos 80/8000 ya abiertos en el lab.

---

## 6. Variables de entorno (en `deploy/env.sh`, NO se commitea)

| Variable | Para qué |
|---|---|
| `GROQ_API_KEY` | LLM (Worker y resumen del Report) |
| `SERVERLESS_ACCESS_KEY` | autenticar Serverless v4 (VM headless) |
| `JWT_SECRET` | firmar los JWT (`openssl rand -hex 32`) |
| `TEACHER_EMAILS` | **plural** → correos que entran como profesor (rol) |
| `TEACHER_EMAIL` | **singular** → correo que recibe el aviso SNS (obligatorio para el deploy) |
| `RAG_URL` | G2: URL del servicio RAG en OCI; vacío = sin RAG |

> Correo usado en demo (profesor): `oswaldo.quispe@utec.edu.pe` (va en ambas TEACHER_*).

---

## 7. Flujo de trabajo y comandos

El código vive en el repo. Se edita en local, se hace `git push`, y en la **VM de AWS** se
hace `git pull` + deploy. La **VM de OCI** corre el servicio RAG de G2.

```bash
# --- Backend (en la VM de AWS) ---
cd ~/rubricaia && git pull
python3 -m py_compile backend/lambdas/*/*.py backend/common/*.py   # sanity check
source deploy/env.sh
serverless deploy
serverless info        # ver endpoint + recursos

# --- Frontend (en la VM de AWS) ---
echo "API_URL=https://m0mx1jdgna.execute-api.us-east-1.amazonaws.com" > deploy/outputs.env
source deploy/env.sh
bash deploy/deploy-frontend.sh
```

Tras un deploy de backend que toque CORS/SNS por primera vez, confirmar la suscripción SNS
(email a `TEACHER_EMAIL`). Tras un deploy fresco, reconstruir el frontend con la nueva
`API_URL`.

---

## 8. Gotchas (lecciones aprendidas — no repetir)

1. **Learner Lab NO permite crear roles IAM** → todas las Lambdas usan `LabRole`
   (`provider.iam.role`). No cambiarlo.
2. **Serverless v4 exige `SERVERLESS_ACCESS_KEY`** (VM headless; no usar `serverless login`).
3. **`TEACHER_EMAIL` (singular) es obligatorio** para el deploy (suscripción SNS). Es
   distinto de `TEACHER_EMAILS` (plural, rol profesor). Confundirlos rompe el deploy o el rol.
4. **Groq tras Cloudflare:** el Worker manda `User-Agent: Mozilla/...`. No quitarlo (error 1010).
5. **La rúbrica/pesos viajan por DynamoDB (item META), no por metadata de S3.** En entregas de
   tarea, la API los toma de la tarea (fuente de verdad), no del cliente.
6. **El endpoint del API cambia en un deploy fresco** (remove+deploy); reconstruir el frontend.
   La URL de Amplify se mantiene.
7. **CORS del bucket vive en `serverless.yml`** (recurso `InputsBucket`).
8. **El cumplimiento se DERIVA de los criterios** (ponderado o equitativo), no del número
   holístico del LLM — así el % siempre coincide con las marcas ✓/✗.
9. **Backend sin dependencias:** solo stdlib + boto3. Groq y el RAG se llaman con `urllib`.
   `authlib` se comparte vía `backend/common/authlib.py` (incluido en el package de cada
   Lambda y cargado con `sys.path.append`, no por import de paquete).
10. **`.pyc` y `deploy/env.sh`/`outputs.env` están en `.gitignore`.** Si el `git pull` en la VM
    se queja de `.pyc` locales: `git checkout -- backend/lambdas/*/__pycache__/*.pyc` y reintentar.
11. **OCI:** `docker` = **podman** en Oracle Linux. Dos capas de firewall (Security List + SO).
    Shape **ARM** (imágenes multi-arch). Qdrant interno; solo se expone el RAG en :8000.
12. **G2 degradación elegante:** si `RAG_URL` está vacío o OCI no responde, el Worker evalúa
    sin RAG (timeout corto). No bloquea.

---

## 9. Estructura del repo

```
rubricaia/
├── serverless.yml                 # IaC: toda la infra AWS
├── README.md                      # qué es, arquitectura, despliegue
├── HANDOFF.md                     # este archivo
├── backend/
│   ├── common/authlib.py          # JWT + hashing (compartido)
│   └── lambdas/{auth,lms,api,splitter,worker,aggregator,report}/*.py
├── frontend/                      # React + Vite (Amplify)
│   ├── index.html                 # + pdf.js/mammoth por CDN
│   └── src/{App.jsx, api.js, auth.js, lms.js, extract.js, styles.css}
├── oci-rag/                       # G2: servicio RAG para OCI (Docker)
│   ├── app.py, requirements.txt, Dockerfile, docker-compose.yml, README.md
├── deploy/
│   ├── env.example.sh             # plantilla (copiar a env.sh)
│   └── deploy-frontend.sh         # build + deploy a Amplify
├── docs/
│   ├── contexto.md                # criterio 1
│   ├── arquitectura.svg           # criterio 2 (diagrama)
│   ├── manual-despliegue.md       # criterio 5
│   └── contrato-datos.md          # formatos y esquema
└── samples/submissions.csv        # datos de prueba (CLI)
```

---

## 10. Roadmap pendiente (prioridad)

1. **G2 — terminar multinube** (sección 0): levantar OCI, probar `/health` desde internet,
   `RAG_URL` + `serverless deploy`, probar end-to-end, actualizar README + diagrama.
2. **Video de YouTube (≤5 min)** — entregable obligatorio. Guion sugerido:
   problema → diagrama (2 planos) → demo profesor (crea clase/tarea, invita) → demo alumno
   (sube PDF, recibe feedback por criterio, ve historial de intentos) → vista del profesor con
   insights → forzar 429 para mostrar RETRYING/DLQ y "reprocesar" → (si G2 listo) mostrar la
   VM de OCI con Qdrant+RAG y logs del Worker → recap por rúbrica.
3. **Opcional:** F6 email SES de invitación; descargar reporte desde la vista del profesor;
   restringir el puerto 8000 de OCI a la IP de salida de AWS.
4. **Antes de entregar:** regenerar las keys expuestas en el chat (`GROQ_API_KEY`,
   `SERVERLESS_ACCESS_KEY`).

---

## 11. Prompt de arranque para el nuevo chat

> Hola. Retomo un proyecto de hackatón de Cloud Computing llamado **RúbricaIA**. Actúa como
> mi mentor técnico, arquitecto cloud y estratega de hackatón, con criterio fuerte y
> orientado a ganar según la rúbrica. **Antes de proponer nada, lee `HANDOFF.md` y revisa el
> repo a fondo** (`serverless.yml`, `backend/lambdas/*`, `backend/common/authlib.py`,
> `frontend/src/*`, `oci-rag/*`, `docs/*`). La plataforma multi-tenant ya funciona end-to-end
> y la documentación está hecha (rúbrica ≈19-20/20). Acabo de pushear el código. Lo que sigue
> es **G2 (multinube OCI + RAG)**: el código del servicio RAG está en `oci-rag/` y el Worker
> ya lo usa si defino `RAG_URL`, pero **aún no lo he levantado en OCI**. Guíame desde crear/
> usar la VM de OCI, levantar el `docker-compose` de `oci-rag`, probar `/health` desde
> internet, conectar `RAG_URL` y desplegar. Trabajemos por fases testeables, sin
> sobre-ingenierizar. Confirma que entendiste el estado y proponme el siguiente paso.
