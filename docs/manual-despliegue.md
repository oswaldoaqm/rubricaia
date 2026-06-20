# Manual de Despliegue — RúbricaIA (Backend + API)

Backend 100% serverless en **AWS Learner Lab** con **LabRole**. Sin Docker, sin VM,
sin roles IAM custom. Compatible con el Worker y el Splitter ya creados.

---

## 0. Arquitectura de infraestructura

```
                         ┌────────────────────────────────────────────┐
   (frontend, luego)     │                  AWS                        │
        │                │                                            │
        │  POST /uploads │   ┌──────────────┐                         │
        ├───────────────────▶│  API Gateway │──▶ rubricaia-api (λ)    │
        │  GET /jobs(/id)│   │   HTTP API   │      │   │   │           │
        │◀───────────────────┤  ($default)  │      │   │   └─▶ S3 presigned URL
        │                │   └──────────────┘      │   └─────▶ DynamoDB (lectura)
        ▼                │                          ▼                  │
   sube CSV  ─PUT─────────────────────────────▶  S3  inputs/<jobId>/submissions.csv
                         │                          │ (ObjectCreated)  │
                         │                          ▼                  │
                         │                  rubricaia-splitter (λ)     │
                         │                    │            │           │
                         │       1 item PENDING│            │ 1 msg/fila│
                         │                     ▼            ▼           │
                         │                 DynamoDB      SQS rubricaia-jobs
                         │                 (rubricaia)       │          │
                         │                     ▲             ▼          │
                         │           estado/result│   rubricaia-worker (λ)
                         │                        └────────┤  └─▶ Groq API
                         │                                 │ (429/err)  │
                         │                                 ▼            │
                         │                          SQS rubricaia-dlq   │
                         └────────────────────────────────────────────┘
```

Componentes y por qué cada uno (sin sobra):
- **S3** `rubricaia-inputs-<acct>`: recibe el CSV y dispara el flujo (evento `ObjectCreated`).
- **Splitter (λ)**: parte el CSV en N eventos SQS + crea items `PENDING`.
- **SQS `rubricaia-jobs` + DLQ `rubricaia-dlq`**: bus de eventos + reintentos sin pérdida.
- **Worker (λ)**: llama a Groq, guarda resultado/estado. Reserved concurrency = 3 (anti rate-limit).
- **DynamoDB `rubricaia`**: estado y resultados por entregable.
- **API (λ) + API Gateway HTTP API**: presigned URL + lectura para el frontend.
- **LabRole**: rol de ejecución de las 3 Lambdas (Learner Lab no permite crear roles).

---

## 1. Estructura exacta del proyecto

```
rubricaia/                      (monorepo)
├── README.md
├── docs/
│   ├── contrato-datos.md        # formatos input/output + esquema DynamoDB
│   └── manual-despliegue.md     # este archivo
├── deploy/
│   ├── env.example.sh           # plantilla de variables (copiar a env.sh)
│   ├── deploy.sh                # despliegue completo con AWS CLI
│   ├── teardown.sh              # borrar todo
│   └── outputs.env              # (lo genera deploy.sh: BUCKET, API_URL, etc.)
├── backend/
│   └── lambdas/
│       ├── splitter/splitter_lambda.py   # handler: splitter_lambda.handler
│       ├── worker/worker_lambda.py        # handler: worker_lambda.handler
│       └── api/api_lambda.py              # handler: api_lambda.handler
├── samples/
│   └── submissions.csv          # datos de prueba
└── frontend/                    # (vacío por ahora — siguiente bloque)
```

### Variables de entorno por Lambda

| Lambda | Variable | Valor |
|---|---|---|
| splitter | `TABLE_NAME` | `rubricaia` |
| splitter | `QUEUE_URL` | URL de la cola principal |
| splitter | `DEFAULT_RUBRICA` | rúbrica por defecto (texto) |
| worker | `TABLE_NAME` | `rubricaia` |
| worker | `GROQ_API_KEY` | tu key `gsk_...` |
| worker | `GROQ_MODEL` | `llama-3.3-70b-versatile` |
| worker | `MAX_ATTEMPTS` | `3` |
| api | `TABLE_NAME` | `rubricaia` |
| api | `BUCKET` | `rubricaia-inputs-<acct>` |
| api | `URL_EXPIRES` | `300` |

### Dependencias
Ninguna externa. Solo **stdlib de Python + boto3** (ya incluido en el runtime Lambda).
Cada Lambda se empaqueta como un `.zip` con un único `.py`. Groq se llama con `urllib`.

---

## 2. Orden exacto de despliegue

> El script `deploy.sh` ya hace todo esto en el orden correcto. Esta es la lógica.

1. **S3** (bucket + CORS) — primero, porque es el origen del flujo.
2. **DynamoDB** — antes que las Lambdas, que la usan al ejecutar.
3. **SQS DLQ**, luego **cola principal** con RedrivePolicy apuntando a la DLQ.
4. **Lambdas** (splitter, worker, api) con `LabRole` y sus variables de entorno.
   Reserved concurrency del worker = 3.
5. **Trigger S3 → Splitter** (primero `add-permission`, luego la notificación del bucket).
6. **Trigger SQS → Worker** (event source mapping, batchSize 5, ReportBatchItemFailures).
7. **API Gateway HTTP API → API Lambda** (+ permiso de invocación).

### Comandos

```bash
cd rubricaia/deploy
cp env.example.sh env.sh
# edita env.sh: pon tu GROQ_API_KEY (y revisa AWS_REGION)
source env.sh
bash deploy.sh
```

Al terminar, el script imprime y guarda en `deploy/outputs.env`:
`BUCKET`, `TABLE`, `QUEUE_URL`, `DLQ_URL`, `API_URL`.

> **Recordatorio Learner Lab:** cada vez que reinicias el lab, las credenciales
> cambian. S3/DynamoDB/SQS/Lambda **persisten** (no se borran), solo necesitas
> volver a configurar el AWS CLI con las credenciales nuevas. No tienes que re-desplegar.

---

## 3. Prueba rápida con 2–3 filas (antes del lote completo)

**Objetivo:** validar la tubería S3→Splitter→SQS→Worker→DynamoDB **sin quemar cuota de Groq**.

```bash
source deploy/env.sh
source deploy/outputs.env   # trae BUCKET, TABLE, API_URL...

# 1) CSV mini de 3 filas
cat > /tmp/mini.csv <<'CSV'
id_estudiante,texto_entrega
T01,"Mi proyecto aborda la desercion estudiantil. Propongo alertas tempranas. Impacto: reducir 15% la desercion."
T02,"Hice una app de reciclaje. Esta buena."
T03,"El problema es la falta de feedback temprano en trabajos. Caso de uso: revision automatica con IA. Impacto medible por mejora de nota."
CSV

# 2) Subir al bucket con un jobId de prueba (dispara el Splitter)
JOB="job-test-001"
aws s3 cp /tmp/mini.csv "s3://${BUCKET}/inputs/${JOB}/submissions.csv" \
  --metadata rubrica="1) Problema real. 2) Usuario afectado. 3) Caso de uso. 4) Impacto con metricas."

# 3) Esperar ~15-30s y consultar el estado por API
curl -s "${API_URL}/jobs/${JOB}" | python -m json.tool
```

Resultado esperado: los 3 entregables pasan de `PENDING` → `PROCESSING` → `DONE`,
con `cumplimiento`, `criterios_ok`, `faltantes` y `sugerencias`.
Cuando funcione, repite con `samples/submissions.csv` (8 filas) o tu lote de 20–30.

---

## 4. Checklist de verificación de conexiones

Marca cada uno. Si alguno falla, revisa el componente indicado.

- [ ] **S3 creado y con CORS**
  `aws s3api get-bucket-cors --bucket "$BUCKET"`
- [ ] **DynamoDB ACTIVE**
  `aws dynamodb describe-table --table-name "$TABLE" --query 'Table.TableStatus'` → `ACTIVE`
- [ ] **Cola principal con RedrivePolicy a la DLQ**
  `aws sqs get-queue-attributes --queue-url "$QUEUE_URL" --attribute-names RedrivePolicy`
- [ ] **3 Lambdas activas**
  `aws lambda list-functions --query "Functions[?starts_with(FunctionName,'rubricaia')].FunctionName"`
- [ ] **Notificación S3 → Splitter configurada**
  `aws s3api get-bucket-notification-configuration --bucket "$BUCKET"`
- [ ] **Event source mapping SQS → Worker habilitado**
  `aws lambda list-event-source-mappings --function-name rubricaia-worker --query 'EventSourceMappings[].State'` → `Enabled`
- [ ] **Splitter corrió** (tras subir el CSV): hay item META en DynamoDB
  `aws dynamodb get-item --table-name "$TABLE" --key '{"PK":{"S":"JOB#job-test-001"},"SK":{"S":"META"}}'`
- [ ] **Worker procesó**: items en estado `DONE`
  `curl -s "$API_URL/jobs/job-test-001"` → `done` > 0
- [ ] **API responde**: `curl -s "$API_URL/jobs"` lista el job de prueba
- [ ] **Logs sin errores**: CloudWatch → `/aws/lambda/rubricaia-worker` y `.../rubricaia-splitter`

### Verificación del reintento / resiliencia (para la demo)
Para forzar el camino de error y ver la DLQ:
- Pon temporalmente una `GROQ_API_KEY` inválida en el Worker
  (`aws lambda update-function-configuration --function-name rubricaia-worker --environment ...`),
  sube un CSV, y observa: los items pasan a `RETRYING` y tras 3 intentos a `FAILED`;
  los mensajes aparecen en la **DLQ** (`aws sqs get-queue-attributes --queue-url "$DLQ_URL" --attribute-names ApproximateNumberOfMessages`).
  Restaura la key buena al terminar. **Ningún dato se pierde** (queda en DLQ + estado FAILED visible).

---

## 5. Troubleshooting rápido

| Síntoma | Causa probable | Solución |
|---|---|---|
| Splitter no se dispara | falta permiso/notificación S3 | re-aplica paso 5; verifica prefijo `inputs/` y sufijo `.csv` |
| Worker no consume | event source mapping deshabilitado | `aws lambda list-event-source-mappings ...` → debe estar `Enabled` |
| Todos los items en FAILED | `GROQ_API_KEY` mala o modelo inválido | revisa env del worker y CloudWatch |
| `create-function` falla por runtime | Learner Lab sin python3.12 | `export PY_RUNTIME=python3.11` y re-deploy |
| reserved concurrency falla | límite de cuenta del lab | coméntalo; no es crítico para la demo |
| API 500 en /jobs | tabla vacía o permisos | sube primero un CSV; revisa CloudWatch de `rubricaia-api` |
