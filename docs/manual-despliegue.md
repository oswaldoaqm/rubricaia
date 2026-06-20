# Manual de despliegue — RúbricaIA

Despliegue 100% **serverless** con **Serverless Framework v4** sobre AWS (probado en
**AWS Academy Learner Lab** con `LabRole`). Una sola fuente de infraestructura:
[`../serverless.yml`](../serverless.yml). No hay Docker ni máquinas virtuales.

Diagrama de arquitectura: [`arquitectura.svg`](arquitectura.svg).

---

## 1. Requisitos

- `aws` CLI configurado (credenciales del Learner Lab en `~/.aws/credentials`).
- **Serverless Framework v4**, **Node 18+**, **Python 3.12**, `zip`.
- **GROQ_API_KEY** (https://console.groq.com/keys).
- **SERVERLESS_ACCESS_KEY** (https://app.serverless.com → Access Keys) — v4 exige
  autenticación y la VM es headless (no usar `serverless login`).

## 2. Variables de entorno

```bash
cp deploy/env.example.sh deploy/env.sh   # luego edita deploy/env.sh
source deploy/env.sh
```

| Variable | Para qué | Ejemplo |
|---|---|---|
| `GROQ_API_KEY` | LLM (Worker y resumen del Report) | `gsk_...` |
| `SERVERLESS_ACCESS_KEY` | autenticar Serverless v4 | `...` |
| `JWT_SECRET` | firmar los JWT | `openssl rand -hex 32` |
| `TEACHER_EMAILS` | correos que entran como profesor (coma) | `prof@utec.edu.pe` |
| `TEACHER_EMAIL` | correo que recibe el aviso SNS | `prof@utec.edu.pe` |

> `deploy/env.sh` **no se commitea** (lleva secretos). El dominio permitido
> (`ALLOWED_DOMAIN=utec.edu.pe`) está en `serverless.yml`.

## 3. Desplegar el backend

```bash
source deploy/env.sh
serverless deploy
serverless info        # endpoint del API + recursos
```

Un `serverless deploy` crea/actualiza de cero, en orden y con dependencias resueltas:

- **DynamoDB** `rubricaia-dev` (jobs, con Streams) y `rubricaia-lms-dev` (usuarios,
  clases, tareas, membresías).
- **S3** `rubricaia-inputs-<acct>-dev` con CORS y notificación `ObjectCreated` → Splitter.
- **SQS** `rubricaia-jobs-dev` + DLQ `rubricaia-dlq-dev` (redrive, maxReceiveCount 3).
- **EventBridge** bus `rubricaia-events-dev`, **SNS** `rubricaia-notify-dev` (+ suscripción
  al `TEACHER_EMAIL`) y la regla `JobCompleted` con fan-out a SNS + Report.
- **API Gateway** HTTP API y las **7 Lambdas** (todas con `LabRole`).

> **Confirma la suscripción SNS:** tras el primer deploy AWS manda un correo a
> `TEACHER_EMAIL` con "Confirm subscription". Haz clic una vez (queda confirmado).

## 4. Desplegar el frontend

```bash
echo "API_URL=$(serverless info --verbose | grep -m1 'ANY ' | awk '{print $3}')" > deploy/outputs.env
# (o pega manualmente el endpoint de 'serverless info')
source deploy/env.sh
bash deploy/deploy-frontend.sh
```

Hace `npm install`, `vite build` con `VITE_API_URL` y publica en Amplify. La URL de
Amplify se mantiene entre despliegues; el endpoint del API **sí cambia** en un deploy
fresco (remove+deploy), por eso hay que reconstruir el frontend con la nueva `API_URL`.

## 5. Prueba por la interfaz (flujo completo)

1. Abre la URL de Amplify. Regístrate con un correo `@utec.edu.pe`. Si está en
   `TEACHER_EMAILS` entras como **profesor**; si no, como **estudiante**.
2. Como **profesor**: crea una **clase**, entra a "Gestionar", crea una **tarea** (título,
   rúbrica, pesos opcionales, fecha) e **invita** el correo de un alumno.
3. Como **estudiante** (ese correo): acepta la invitación, abre la tarea y sube un
   **PDF o Word**. Verás "Evaluando…" y luego tu cumplimiento criterio por criterio.
4. Como **profesor**: en la tarea pulsa **"Entregas"** para ver el cumplimiento de cada
   alumno, el promedio y los criterios más fallados de la clase.

## 6. Prueba del pipeline por CLI (sin frontend)

Valida la tubería S3 → Splitter → SQS → Worker → Groq → DynamoDB → Aggregator. Si no se
fija rúbrica, el Splitter usa `DEFAULT_RUBRICA` (variable de entorno en `serverless.yml`).

```bash
source deploy/env.sh
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BUCKET="rubricaia-inputs-${ACCOUNT_ID}-dev"
API_URL="<endpoint de 'serverless info'>"
JOB="job-test-$(date +%s)"

aws s3 cp samples/submissions.csv "s3://${BUCKET}/inputs/${JOB}/submissions.csv"
sleep 25
curl -s "${API_URL}/jobs/${JOB}" | python3 -m json.tool
```

Esperado: los entregables pasan `PENDING → PROCESSING → DONE` con `cumplimiento`,
`criterios`, `criterios_ok`, `faltantes` y `sugerencias`.

## 7. Verificación de recursos

```bash
aws dynamodb describe-table --table-name rubricaia-dev      --query 'Table.TableStatus'
aws dynamodb describe-table --table-name rubricaia-lms-dev  --query 'Table.TableStatus'
aws sqs get-queue-attributes --queue-url "$(aws sqs get-queue-url --queue-name rubricaia-jobs-dev --query QueueUrl --output text)" --attribute-names RedrivePolicy
aws lambda list-functions --query "Functions[?starts_with(FunctionName,'rubricaia')].FunctionName"
aws events list-rules --event-bus-name rubricaia-events-dev --query 'Rules[].Name'
```

## 8. Demostrar resiliencia (reintentos + DLQ)

Para forzar el camino de error en la demo: pon temporalmente una `GROQ_API_KEY` inválida
en el Worker, sube un lote y observa cómo los ítems pasan a `RETRYING` y, tras 3 intentos,
a `FAILED`, con los mensajes acumulándose en la **DLQ** (ningún dato se pierde). Restaura
la key y usa el botón **"Reprocesar fallidos"** (o `POST /jobs/{id}/retry`) para
re-encolarlos.

```bash
aws sqs get-queue-attributes \
  --queue-url "$(aws sqs get-queue-url --queue-name rubricaia-dlq-dev --query QueueUrl --output text)" \
  --attribute-names ApproximateNumberOfMessages
```

## 9. Troubleshooting

| Síntoma | Causa probable | Solución |
|---|---|---|
| Deploy falla por crear roles | Learner Lab no permite IAM roles | ya se usa `LabRole`; no cambiar `provider.iam.role` |
| `Cannot resolve '${env:GROQ_API_KEY}'` | variable no exportada | `source deploy/env.sh` antes de `serverless deploy` |
| Login pide navegador | falta `SERVERLESS_ACCESS_KEY` | expórtala (VM headless) |
| Worker: todos `FAILED` | `GROQ_API_KEY` mala o modelo inválido | revisa env del worker + CloudWatch |
| Subida del navegador "Failed to fetch" | CORS del bucket | ya está en IaC (`InputsBucket`); re-deploy |
| El alumno no ve su clase | no aceptó la invitación | debe pulsar "Aceptar" (compuerta de F3) |
| El profesor sale como estudiante | correo no está en `TEACHER_EMAILS` | añádelo y vuelve a iniciar sesión |
| No llega el email de SNS | suscripción sin confirmar | confirma el correo de "Confirm subscription" |
| runtime python3.12 no disponible | lab sin esa versión | cambia `provider.runtime` a `python3.11` |

## 10. Limpieza

```bash
serverless remove        # borra toda la infraestructura del stack
```
