# Contrato de datos — RúbricaIA

Fuente única de verdad de los formatos que viajan por el sistema. Si algo cambia aquí,
cambia en Splitter, Worker, API, LMS y Frontend.

---

## 1. Entrada — qué se sube

El frontend extrae el texto de los archivos del alumno (**PDF / Word / TXT**, en el
navegador con pdf.js y mammoth) y arma un **CSV** con una fila por entregable:

```csv
id_estudiante,texto_entrega
E001,"El problema que abordo es la deserción estudiantil..."
E002,"Mi proyecto trata sobre reciclaje en el campus..."
```

- En una **entrega de tarea**, el alumno sube su(s) archivo(s) y se genera **una fila**
  (id = su nombre/correo, texto = sus archivos concatenados).
- En carga directa por CLI, el CSV puede traer 20–30 filas (lote masivo).
- Llega a S3 como `inputs/<jobId>/submissions.csv` y dispara al Splitter.

La **rúbrica y los pesos NO viajan por metadata de S3**: los fija la API en el item `META`
de DynamoDB (soporta texto largo, acentos y saltos de línea sin romper el presigned URL).
En una entrega de tarea, la API los toma de la **tarea** (fuente de verdad), no del cliente.

## 2. Mensaje SQS — un evento por entregable

```json
{
  "jobId": "job-20260620-...",
  "idEstudiante": "E001",
  "texto": "El problema que abordo es...",
  "rubrica": "1) Define un problema real. 2) ...",
  "pesos": [30, 20, 20, 15, 15]
}
```
`pesos` es opcional (`null` si el docente no los fijó).

## 3. Salida del LLM (Groq) — JSON estructurado

Se pide a Groq (modo `json_object`) la evaluación **criterio por criterio**:

```json
{
  "cumplimiento": 60,
  "criterios": [
    {"criterio": "Define un problema real y concreto", "cumple": true,  "evidencia": "...", "sugerencia": ""},
    {"criterio": "Justifica el impacto con métricas",   "cumple": false, "evidencia": "...", "sugerencia": "Agrega 2-3 métricas de éxito"}
  ]
}
```

El Worker deriva el **cumplimiento final desde los criterios** (consistente con las marcas):
ponderado si hay `pesos` válidos, equitativo en caso contrario. También arma las listas
de resumen `criterios_ok`, `faltantes` y `sugerencias` para el frontend.

## 4. DynamoDB

### Tabla `rubricaia-<stage>` (pipeline / jobs)

| Atributo | Job (META) | Entregable (ITEM) | Stats / fallos |
|---|---|---|---|
| `PK` | `JOB#<jobId>` | `JOB#<jobId>` | `JOB#<jobId>` |
| `SK` | `META` | `ITEM#<id>` | `STATS` / `FAIL#<criterio>` |
| `status` | `PENDING_UPLOAD`/`PROCESSING`/`DONE` | `PENDING`→`PROCESSING`→`DONE`/`RETRYING`/`FAILED` | — |
| `rubrica`, `pesos` | sí | — | — |
| `classId`,`taskId`,`studentEmail` | sí (si es de tarea) | — | — |
| `cumplimiento`,`criterios`,`criterios_ok`,`faltantes`,`sugerencias` | — | sí (al DONE) | — |
| `done_count`,`failed_count`,`cumplimiento_sum`,`dist_*`,`completed` | — | — | `STATS` |

El Aggregator mantiene `STATS` y `FAIL#` por DynamoDB Streams, y al completar el lote
escribe `completed` (una sola vez) y emite `JobCompleted`.

### Tabla `rubricaia-lms-<stage>` (plano de control)

| Entidad | PK | SK |
|---|---|---|
| Usuario | `USER#<email>` | `PROFILE` (rol, hash de contraseña) |
| Clase | `CLASS#<id>` | `META` (nombre, dueño) |
| Tarea | `CLASS#<id>` | `TASK#<taskId>` (rubrica, pesos, fecha) |
| Roster | `CLASS#<id>` | `MEMBER#<email>` (estado invited/active) |
| Mis clases (alumno) | `USER#<email>` | `MEMBERSHIP#<classId>` |
| Mis clases (profesor) | `USER#<email>` | `OWNS#<classId>` |
| Entrega (alumno) | `USER#<email>` | `SUBMISSION#<taskId>` (jobId) |
| Entregas por tarea | `CLASS#<id>` | `SUB#<taskId>#<email>` (jobId) |

## 5. Máquina de estados del entregable

```
PENDING ─(Worker toma)→ PROCESSING ─(Groq OK)→ DONE
                            │
                            ├─(error/429, intento<MAX)→ RETRYING ─(reencola con backoff)→ PROCESSING
                            └─(error, intento==MAX)──→ FAILED (+ mensaje a DLQ)
```

Ningún dato se pierde: un fallo solo cambia el `status`; `FAILED` queda visible y el
mensaje en la **DLQ**. Se puede **reprocesar** (`POST /jobs/{id}/retry`), que re-encola y
reabre la compuerta para regenerar reporte y notificación.

## 6. API (resumen de endpoints)

```
POST /auth/signup            POST /auth/login
POST /uploads                GET  /jobs/{id}        GET /jobs/{id}/report
POST /jobs/{id}/retry
POST /classes                GET  /classes          POST /classes/delete
POST /classes/invite         POST /classes/remove   POST /classes/accept
GET  /classes/detail         POST /tasks            POST /tasks/update
POST /tasks/delete           GET  /tasks/submissions
```
Las rutas del plano de control van autenticadas con `Authorization: Bearer <JWT>`.
