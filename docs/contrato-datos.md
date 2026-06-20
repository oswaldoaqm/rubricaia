# Contrato de Datos — RúbricaIA (P0)

Este documento es la **fuente única de verdad** de los formatos que viajan por el sistema.
Si cambia algo aquí, cambia en Splitter, Worker, API y Frontend. No improvisar formatos.

---

## 1. Input — CSV que sube el docente

Un archivo CSV, **una fila por entregable**. UTF-8. Cabecera obligatoria.

```csv
id_estudiante,texto_entrega
E001,"El problema que abordo es la deserción estudiantil. Propongo un sistema de alertas tempranas..."
E002,"Mi proyecto trata sobre reciclaje en el campus. No incluí objetivos medibles..."
```

Reglas:
- `id_estudiante`: string único dentro del job (sirve de clave). Sin comas internas o va entre comillas.
- `texto_entrega`: el contenido a evaluar. Puede contener saltos de línea y comas si va entre comillas (estándar CSV).
- Tamaño objetivo de demo: **20–30 filas** (el lote masivo controlado que pide la rúbrica).

### Cómo llega a S3
- Key en S3: `inputs/<jobId>/submissions.csv`
- El `jobId` lo genera el frontend (ej. `job-20260619-153000`) y se usa como carpeta.
- La **rúbrica** viaja como *metadata* del objeto S3: `x-amz-meta-rubrica` (texto).
  Si no se envía, el Splitter usa `DEFAULT_RUBRICA` (variable de entorno).
  > Nota: metadata S3 tiene límite ~2KB. Suficiente para una rúbrica resumida en demo.
  > Para rúbricas largas, la versión P1-API guardará la rúbrica en DynamoDB al crear el job.

---

## 2. Mensaje SQS — un evento por entregable

El Splitter emite **un mensaje por fila**. Body = JSON:

```json
{
  "jobId": "job-20260619-153000",
  "idEstudiante": "E001",
  "texto": "El problema que abordo es la deserción estudiantil...",
  "rubrica": "1) Define problema real y profundo. 2) Casos de uso relevantes. 3) ..."
}
```

---

## 3. Output del LLM (Groq) — JSON estructurado

Se le pide a Groq que responda **solo** este objeto (modo `json_object`):

```json
{
  "cumplimiento": 72,
  "criterios_ok": [
    "Define un problema real y concreto",
    "Identifica al usuario afectado"
  ],
  "faltantes": [
    "No incluye objetivos medibles",
    "Falta justificar el impacto esperado"
  ],
  "sugerencias": [
    "Agrega 2-3 métricas de éxito concretas (ej. % de reducción de deserción)",
    "Cierra con un párrafo de impacto cuantificado"
  ]
}
```

Campos:
- `cumplimiento`: entero 0–100 (porcentaje global vs. rúbrica).
- `criterios_ok`: lista de strings (lo que sí cumple).
- `faltantes`: lista de strings (lo que falta).
- `sugerencias`: lista de strings accionables.

Si el LLM devuelve algo no parseable, el Worker lo trata como error transitorio y reintenta.

---

## 4. Esquema DynamoDB — tabla `rubricaia`

**Una sola tabla**, diseño PK/SK. Permite leer todo un job con un solo `Query`.

| Atributo | Tipo | Job (META) | Entregable (ITEM) |
|---|---|---|---|
| `PK` (Partition Key) | S | `JOB#<jobId>` | `JOB#<jobId>` |
| `SK` (Sort Key) | S | `META` | `ITEM#<idEstudiante>` |
| `status` | S | `PROCESSING` / `DONE` | `PENDING` / `PROCESSING` / `DONE` / `RETRYING` / `FAILED` |
| `total` | N | nº de entregables | — |
| `rubrica` | S | rúbrica usada | — |
| `id_estudiante` | S | — | id del alumno |
| `cumplimiento` | N | — | 0–100 (cuando DONE) |
| `criterios_ok` | L | — | lista strings |
| `faltantes` | L | — | lista strings |
| `sugerencias` | L | — | lista strings |
| `attempts` | N | — | nº de intentos |
| `last_error` | S | — | último error (si falló) |
| `createdAt` / `updatedAt` | S | ISO 8601 | ISO 8601 |

Creación (AWS CLI, Learner Lab):
```bash
aws dynamodb create-table \
  --table-name rubricaia \
  --attribute-definitions AttributeName=PK,AttributeType=S AttributeName=SK,AttributeType=S \
  --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST
```

### Lectura para el dashboard
```
Query  PK = "JOB#<jobId>"
```
Devuelve la fila META (total + status del job) y todas las filas ITEM (estado + resultado por alumno).
El frontend hace polling de esta query cada 2–3s.

---

## 5. Estados por entregable (máquina de estados)

```
PENDING ──(Worker toma el mensaje)──> PROCESSING ──(Groq OK)──> DONE
                                          │
                                          ├─(error/429, intento < MAX)──> RETRYING ──(reencola SQS)──> PROCESSING
                                          └─(error, intento == MAX)─────> FAILED  (+ mensaje va a DLQ)
```

- Ningún dato se pierde: un fallo nunca borra el ítem, solo cambia su `status`.
- `FAILED` queda **visible** en el dashboard y el mensaje original queda en la **DLQ** como evidencia.
