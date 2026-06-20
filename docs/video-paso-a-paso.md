# Runbook del Video — RúbricaIA (paso a paso literal)

> Guía de grabación: **[DECIR]** = lo que narras, **[HACER]** = lo que ejecutas/clicas,
> **[VERÁS]** = lo que debe aparecer. Tenlo al lado mientras grabas. Objetivo ≤ 5 min
> (puedes grabar por escenas y unirlas; corta los tiempos de espera del LLM).
>
> Valores reales de tu despliegue (confírmalos en la preparación):
> - Frontend: `https://main.d2aurxjj1g5f03.amplifyapp.com`
> - API: `https://m0mx1jdgna.execute-api.us-east-1.amazonaws.com` (verifícalo con `serverless info`)
> - Cuenta AWS: `334461248248` · Región `us-east-1` · Stack `rubricaia-dev`
> - Bucket: `rubricaia-inputs-334461248248-dev`
> - Colas: `rubricaia-jobs-dev` + `rubricaia-dlq-dev`
> - Lambdas: `rubricaia-dev-{auth,lms,api,splitter,worker,aggregator,report}`
> - Tablas: `rubricaia-dev`, `rubricaia-lms-dev`
> - RAG en OCI: `http://163.192.116.108:8000`

---

# PARTE 0 — PREPARACIÓN (antes de apretar REC, ~10 min)

Haz TODO esto y déjalo abierto. Si algo falla aquí, NO grabes hasta arreglarlo.

### 0.1 Verifica que el backend está vivo (en la VM de AWS)
```bash
cd ~/rubricaia
source deploy/env.sh
aws sts get-caller-identity          # credenciales del lab vigentes
serverless info                      # copia el endpoint del API (debe listar 7 funciones + rutas)
```
**[VERÁS]** el stack `rubricaia-dev`, el endpoint del API y las rutas. Si el endpoint cambió,
úsalo en todos los comandos siguientes como `API_URL`.

### 0.2 Verifica el frontend
Abre `https://main.d2aurxjj1g5f03.amplifyapp.com` en el navegador. Debe cargar la pantalla
de login. (Si no carga o da error de API, reconstruye: `bash deploy/deploy-frontend.sh`.)

### 0.3 Verifica el RAG en OCI (multinube)
```bash
# desde tu PC:
curl -s http://163.192.116.108:8000/health
```
**[VERÁS]** `{"ok":true,"model":"intfloat/multilingual-e5-large","dim":1024,"count":5}`.
Si no responde, en la VM de OCI: `docker ps` y, si hace falta, recrea el contenedor `rag`.

### 0.4 Prepara las cuentas y archivos
- Ten **dos sesiones del frontend**: una de **profesor** (correo en `TEACHER_EMAILS`,
  p.ej. `oswaldo.quispe@utec.edu.pe`) y una de **estudiante** (otro correo `@utec.edu.pe`),
  en pestañas o ventanas separadas (una en incógnito).
- Ten **2 archivos de prueba** listos en el escritorio:
  - `bueno.pdf` — un trabajo que cumple varios criterios.
  - `flojo.pdf` — un trabajo pobre (para que el contraste se vea en cámara).
- Crea (o ten ya creada) una **clase** y una **tarea** con su rúbrica, para no gastar tiempo
  en cámara. (En la demo solo mostrarás "ya tengo esto" y harás UNA entrega nueva.)

### 0.5 Abre estas ventanas/pestañas y déjalas listas
1. Navegador: frontend (profesor) · frontend (alumno) · el diagrama `docs/arquitectura.svg`.
2. Consola AWS: **CloudWatch** y **SQS** (cola + DLQ) — opcional pero suma.
3. Terminal A (VM de AWS): para los `aws logs tail` del backend.
4. Terminal B (tu PC): para el `curl` al RAG de OCI.
5. Editor con `backend/lambdas/worker/worker_lambda.py` abierto (para mostrar el código).

---

# PARTE 1 — INTRO Y PROBLEMA  (0:00–0:30)  · Criterio 1

**[HACER]** Cámara a ti o a una slide con el logo.
**[DECIR]:**
> "Hola, somos el equipo de **RúbricaIA**. El problema: los estudiantes entregan trabajos
> sin saber si cumplen la rúbrica, y los docentes no alcanzan a dar retroalimentación
> temprana a toda su clase. Nuestra solución usa un **LLM** para revisar cada entrega
> **criterio por criterio** contra la rúbrica, y devolver qué cumple, qué falta y cómo
> mejorar — antes de la entrega final. Pero el foco del reto, y de esta demo, es la
> **arquitectura: basada en eventos, asíncrona y serverless.**"

---

# PARTE 2 — ARQUITECTURA  (0:30–1:20)  · Criterio 2

**[HACER]** Muestra `docs/arquitectura.svg` en pantalla completa. Ve señalando con el cursor.
**[DECIR]:**
> "La arquitectura tiene **dos planos**. Un **plano de control síncrono** —arriba— con
> autenticación JWT y la gestión de clases y tareas, en las Lambdas `auth` y `lms`.
>
> Y el **plano de datos, 100% event-driven** —que es el corazón—: la entrega entra a **S3**;
> el evento `ObjectCreated` dispara el **Splitter**, que parte el lote en **un mensaje SQS
> por entregable**; un **Worker** serverless consume la cola, llama al **LLM (Groq)** y guarda
> en **DynamoDB**; los **DynamoDB Streams** disparan un **Aggregator** que calcula estadísticas
> de la clase en vivo y, al terminar el lote, publica un evento en **EventBridge**, que hace
> fan-out a **SNS** (avisa al docente por correo) y a una **Report Lambda** que genera el
> reporte de clase en S3.
>
> Son **7 Lambdas**, sin un solo servidor, y **todo está declarado como código** en un
> `serverless.yml`: un solo `serverless deploy` levanta esta infraestructura completa."

**[HACER]** (opcional, 3s) muestra el `serverless.yml` haciendo scroll rápido.

---

# PARTE 3 — EL PROFESOR CREA Y ASIGNA  (1:20–2:00)  · Criterio 4

**[HACER]** En la sesión de **profesor**:
1. Muestra tu lista de **clases** → entra a una clase → **Gestionar**.
2. Muestra una **tarea** ya creada (título + rúbrica + pesos + fecha). Di una frase:
**[DECIR]:**
> "Como docente creo una clase y una tarea con su **rúbrica** y, opcionalmente, **pesos por
> criterio**. Invito a mis estudiantes por correo, con una **compuerta de aceptación**.
> Algo clave: la rúbrica la fija la **tarea**, no el alumno."
3. (Si no la creaste antes) crea una tarea rápida e **invita** el correo del alumno.

---

# PARTE 4 — EL ALUMNO ENTREGA + BACKEND EN VIVO  (2:00–3:10)  · Criterios 3 y 4

Esta es la escena clave: subes una entrega Y muestras el backend procesándola por eventos.

**[HACER]** Antes de subir, en **Terminal A** (VM de AWS) deja corriendo el log del Worker:
```bash
aws logs tail /aws/lambda/rubricaia-dev-worker --follow --format short
```
**[HACER]** En la sesión de **estudiante**:
1. Acepta la invitación (si no lo hiciste) → abre la tarea → **sube `flojo.pdf`** (o `bueno.pdf`).
**[DECIR]:**
> "Como estudiante subo mi trabajo en **PDF** — el texto se extrae en el navegador con pdf.js.
> Fíjense en la terminal: esto NO es síncrono."
2. Mientras aparece "Evaluando…", **cambia a Terminal A**.
**[VERÁS]** en el log del Worker líneas de la invocación (START / END / REPORT). Señala:
**[DECIR]:**
> "El frontend no esperó al backend: subió a S3, eso disparó el Splitter, encoló en SQS y el
> Worker —una función serverless— está procesando la entrega de forma asíncrona, llamando al
> LLM y guardando el resultado."

**[HACER]** (opcional, muy potente) muestra el dato real en DynamoDB. En **Terminal A**:
```bash
# usa el jobId que veas; o lista el último job:
aws dynamodb scan --table-name rubricaia-dev \
  --filter-expression "SK = :m" --expression-attribute-values '{":m":{"S":"META"}}' \
  --query 'Items[].PK.S' --output text
```
y luego:
```bash
JOB="<pega aquí el JOB#... sin el prefijo JOB#>"
curl -s "https://m0mx1jdgna.execute-api.us-east-1.amazonaws.com/jobs/${JOB}" | python3 -m json.tool
```
**[VERÁS]** el JSON con `status: DONE`, `cumplimiento`, y la lista `criterios` (cumple/evidencia/sugerencia).

**[HACER]** Vuelve al **frontend del alumno**: ya muestra el **resultado**.
**[DECIR]:**
> "Y aquí está el resultado para el alumno: su porcentaje de cumplimiento y la evaluación
> **criterio por criterio**, con la evidencia y una **sugerencia concreta** para cada criterio
> que no cumplió."
**[HACER]** Sube una **segunda versión** del mismo alumno (otro PDF) y muestra el
**historial de intentos** y cómo cambia el cumplimiento entre intentos.

---

# PARTE 5 — VISTA DEL PROFESOR + INSIGHTS  (3:10–3:40)  · Criterio 4

**[HACER]** Cambia a la sesión de **profesor** → entra a la tarea → **"Entregas"**.
**[DECIR]:**
> "El docente ve **todas las entregas** de la clase: quién entregó, su cumplimiento, el
> **promedio del grupo**, la **distribución** y los **criterios que más falla la clase** —
> calculados en tiempo real por el Aggregator vía DynamoDB Streams. Con esto sabe exactamente
> dónde reforzar."
**[HACER]** (opcional) descarga el **reporte de clase** (botón de reporte / `/jobs/{id}/report`).

---

# PARTE 6 — RESILIENCIA: REINTENTOS + DLQ  (3:40–4:20)  · Criterio 3  (EL MOMENTO FUERTE)

Demuestra el manejo de límites del LLM sin perder datos. **Hazlo con la versión segura** (guarda
y restaura el env del Worker). Si te pone nervioso hacerlo en vivo, usa la **Opción B**.

### Opción A — Forzar el fallo en vivo (recomendada)
**[HACER]** En **Terminal A**, rompe temporalmente la key del Worker:
```bash
# 1) Guarda el env actual del Worker
aws lambda get-function-configuration --function-name rubricaia-dev-worker \
  --query 'Environment' --output json > /tmp/wenv.json
# 2) Pon una key inválida (duplica el archivo cambiando solo GROQ_API_KEY):
python3 - <<'PY'
import json
e=json.load(open('/tmp/wenv.json')); e['Variables']['GROQ_API_KEY']='gsk_INVALIDA_DEMO'
json.dump(e,open('/tmp/wenv_bad.json','w'))
PY
aws lambda update-function-configuration --function-name rubricaia-dev-worker \
  --environment file:///tmp/wenv_bad.json >/dev/null && echo "Key rota (demo)"
```
**[HACER]** Sube otra entrega desde el frontend. En **Terminal A** mira el log:
```bash
aws logs tail /aws/lambda/rubricaia-dev-worker --since 2m --format short
```
**[VERÁS]** líneas de error y **reintentos**. En el frontend el entregable queda en
`RETRYING` y luego `FAILED`. **[DECIR]:**
> "Cuando el LLM rechaza una petición, el Worker **no pierde el dato**: captura el error,
> aplica **backoff exponencial** y reencola el mensaje en SQS. Tras 3 intentos, el mensaje va
> a la **Dead Letter Queue**."
**[HACER]** Muestra la DLQ con mensajes:
```bash
aws sqs get-queue-attributes \
  --queue-url "$(aws sqs get-queue-url --queue-name rubricaia-dlq-dev --query QueueUrl --output text)" \
  --attribute-names ApproximateNumberOfMessages
```
**[VERÁS]** `ApproximateNumberOfMessages` > 0. **[DECIR]:**
> "Aquí están los mensajes que fallaron, intactos en la DLQ. Cero pérdida de datos."
**[HACER]** Restaura la key buena y reprocesa:
```bash
aws lambda update-function-configuration --function-name rubricaia-dev-worker \
  --environment file:///tmp/wenv.json >/dev/null && echo "Key restaurada"
```
Luego en el frontend pulsa **"Reprocesar fallidos"** (o `POST /jobs/{id}/retry`).
**[DECIR]:** "Restauro el servicio y con un clic **reproceso los fallidos**: se re-encolan y
se evalúan correctamente. Resiliencia de extremo a extremo."

### Opción B — Sin romper nada (fallback seguro)
**[HACER]** Muestra el **código del Worker** (`worker_lambda.py`): señala `RetryableError`, el
manejo de `429` con `Retry-After`, `_compute_backoff` y el `batchItemFailures`. Luego muestra
la DLQ y el redrive:
```bash
aws sqs get-queue-attributes \
  --queue-url "$(aws sqs get-queue-url --queue-name rubricaia-jobs-dev --query QueueUrl --output text)" \
  --attribute-names RedrivePolicy
```
**[DECIR]:** explica el mecanismo con el código a la vista (backoff, DLQ tras 3 intentos,
ReportBatchItemFailures, idempotencia).

---

# PARTE 7 — MULTINUBE: RAG EN OCI  (4:20–4:45)  · Bonus

Validación **honesta y sólida**: el componente RAG corre en una **segunda nube (OCI)** y está
integrado al Worker.

**[HACER]** En **Terminal B** (tu PC), consulta el servicio RAG en OCI en vivo:
```bash
curl -X POST http://163.192.116.108:8000/retrieve \
  -H 'Content-Type: application/json' \
  -d '{"text":"mi proyecto reduce la desercion estudiantil en 15%","k":3}'
```
**[VERÁS]** un JSON con `contexts` (fragmentos de material del curso, en español).
**[DECIR]:**
> "Y vamos más allá de una sola nube. En una **VM de Oracle Cloud (OCI)** corre un servicio
> **RAG** —Qdrant más embeddings multilingües, en Docker— que estoy consultando aquí en vivo
> por internet. Devuelve material del curso relevante."
**[HACER]** Muestra en `worker_lambda.py` la función `_retrieve_context` y la variable `RAG_URL`.
**[DECIR]:**
> "El Worker en AWS consulta este servicio en OCI **antes** de llamar al LLM, para calibrar la
> evaluación con el material del curso. Y está diseñado con **degradación elegante**: si OCI no
> responde, evalúa igual. Multinube **AWS + OCI**, con resiliencia incluso ante la caída de una
> nube."

> Nota para ti (no lo digas): si un evaluador pregunta por el tráfico AWS→OCI, la respuesta
> honesta es que el **Learner Lab restringe el egress de Lambda**, por eso el diseño usa
> degradación elegante; el servicio OCI es real, público y está integrado.

---

# PARTE 8 — CIERRE  (4:45–5:00)  · Mapeo a la rúbrica

**[DECIR]:**
> "En resumen: **(1)** un problema real con impacto claro y un LLM justificado; **(2)** una
> arquitectura **100% basada en eventos, asíncrona y serverless**, declarada como código;
> **(3)** procesamiento por lotes **resiliente** con reintentos, backoff y DLQ **sin perder
> datos**; **(4)** un frontend público **multi-tenant** con evaluación criterio por criterio e
> insights de clase; y **(5)** un repositorio con README, manual de despliegue y diagrama,
> reproducible con un solo comando. Además, un componente **multinube** en OCI. Gracias."

---

# Checklist final antes de subir el video
- [ ] El video dura ≤ 5 min (corta esperas del LLM en edición).
- [ ] Se ve la **URL pública** del frontend funcionando.
- [ ] Se ve el **backend asíncrono** (logs del Worker / resultado por API).
- [ ] Se ve la **evaluación criterio por criterio** y los **insights** del profesor.
- [ ] Se ve la **resiliencia** (RETRYING/DLQ o el código + DLQ).
- [ ] Se ve la **multinube** (curl al RAG de OCI).
- [ ] Subido a **YouTube** (no listado vale) y el **link pegado en el README**.
- [ ] (Antes de entregar) **regeneradas** `GROQ_API_KEY` y `SERVERLESS_ACCESS_KEY`.

## Frases-gancho para el jurado (dilas literalmente, van tachando su checklist)
"basada en eventos" · "asíncrona" · "serverless" · "infraestructura como código" ·
"procesamiento por lotes" · "reintentos sin pérdida de datos" · "Dead Letter Queue" ·
"URL pública" · "multinube".
