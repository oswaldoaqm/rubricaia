#!/usr/bin/env bash
###############################################################################
# RúbricaIA - Despliegue completo en AWS Learner Lab (LabRole, 100% serverless)
#
# Crea y conecta: S3 -> Splitter Lambda -> SQS(+DLQ) -> Worker Lambda -> DynamoDB
# y la API Lambda detras de un API Gateway HTTP API.
#
# Uso:
#   1) cp env.example.sh env.sh && edita env.sh (pon tu GROQ_API_KEY)
#   2) source env.sh
#   3) bash deploy.sh
#
# Requisitos: AWS CLI v2 configurado con las credenciales del Learner Lab.
# Idempotencia: pensado para una corrida limpia. Si re-ejecutas, algunos
# 'create' daran error de "ya existe" (puedes ignorarlos o correr teardown.sh).
###############################################################################
set -euo pipefail

# --- chequeos previos --------------------------------------------------------
: "${AWS_REGION:?Define AWS_REGION (source env.sh)}"
: "${GROQ_API_KEY:?Define GROQ_API_KEY (source env.sh)}"
PROJECT="${PROJECT:-rubricaia}"
PY_RUNTIME="${PY_RUNTIME:-python3.12}"
GROQ_MODEL="${GROQ_MODEL:-llama-3.3-70b-versatile}"
DEFAULT_RUBRICA="${DEFAULT_RUBRICA:-Rubrica por defecto: define problema, usuario, caso de uso e impacto.}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
LAB_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/LabRole"

# nombres de recursos
BUCKET="${PROJECT}-inputs-${ACCOUNT_ID}"
TABLE="${PROJECT}"
QUEUE="${PROJECT}-jobs"
DLQ="${PROJECT}-dlq"
FN_SPLITTER="${PROJECT}-splitter"
FN_WORKER="${PROJECT}-worker"
FN_API="${PROJECT}-api"

# rutas (este script vive en deploy/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LAMBDAS="${ROOT}/backend/lambdas"
BUILD="$(mktemp -d)"

echo "== RúbricaIA deploy =="
echo "  Cuenta : ${ACCOUNT_ID}"
echo "  Region : ${AWS_REGION}"
echo "  Role   : ${LAB_ROLE_ARN}"
echo "  Bucket : ${BUCKET}"
echo "  Build  : ${BUILD}"
echo

aws configure set region "${AWS_REGION}" || true

# === 1. S3 ===================================================================
echo "[1/8] S3 bucket..."
if [ "${AWS_REGION}" = "us-east-1" ]; then
  aws s3api create-bucket --bucket "${BUCKET}" >/dev/null
else
  aws s3api create-bucket --bucket "${BUCKET}" \
    --create-bucket-configuration LocationConstraint="${AWS_REGION}" >/dev/null
fi
# CORS (necesario para subir con presigned URL desde el navegador, fase frontend)
cat > "${BUILD}/s3-cors.json" <<'JSON'
{ "CORSRules": [ {
  "AllowedOrigins": ["*"],
  "AllowedMethods": ["PUT","GET","HEAD"],
  "AllowedHeaders": ["*"],
  "ExposeHeaders": ["ETag"]
} ] }
JSON
aws s3api put-bucket-cors --bucket "${BUCKET}" --cors-configuration "file://${BUILD}/s3-cors.json"
echo "  ok: ${BUCKET}"

# === 2. DynamoDB =============================================================
echo "[2/8] DynamoDB tabla..."
aws dynamodb create-table \
  --table-name "${TABLE}" \
  --attribute-definitions AttributeName=PK,AttributeType=S AttributeName=SK,AttributeType=S \
  --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST >/dev/null
aws dynamodb wait table-exists --table-name "${TABLE}"
echo "  ok: ${TABLE}"

# === 3. SQS DLQ + cola principal ============================================
echo "[3/8] SQS DLQ + cola principal..."
DLQ_URL="$(aws sqs create-queue --queue-name "${DLQ}" --query QueueUrl --output text)"
DLQ_ARN="$(aws sqs get-queue-attributes --queue-url "${DLQ_URL}" \
  --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)"

# RedrivePolicy: tras 3 recepciones fallidas el mensaje va a la DLQ.
# VisibilityTimeout (120s) DEBE ser >= timeout del Worker (60s).
cat > "${BUILD}/main-queue-attrs.json" <<JSON
{
  "VisibilityTimeout": "120",
  "RedrivePolicy": "{\"deadLetterTargetArn\":\"${DLQ_ARN}\",\"maxReceiveCount\":\"3\"}"
}
JSON
QUEUE_URL="$(aws sqs create-queue --queue-name "${QUEUE}" \
  --attributes "file://${BUILD}/main-queue-attrs.json" --query QueueUrl --output text)"
QUEUE_ARN="$(aws sqs get-queue-attributes --queue-url "${QUEUE_URL}" \
  --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)"
echo "  ok: ${QUEUE_URL}"
echo "  dlq: ${DLQ_URL}"

# === 4. Empaquetar y crear Lambdas ==========================================
echo "[4/8] Empaquetando Lambdas..."
zip -j "${BUILD}/splitter.zip" "${LAMBDAS}/splitter/splitter_lambda.py" >/dev/null
zip -j "${BUILD}/worker.zip"   "${LAMBDAS}/worker/worker_lambda.py"     >/dev/null
zip -j "${BUILD}/api.zip"      "${LAMBDAS}/api/api_lambda.py"           >/dev/null

# --- env files (evitan problemas de escaping en CLI) ---
cat > "${BUILD}/env-splitter.json" <<JSON
{ "Variables": {
  "TABLE_NAME": "${TABLE}",
  "QUEUE_URL": "${QUEUE_URL}",
  "DEFAULT_RUBRICA": "${DEFAULT_RUBRICA}"
} }
JSON
cat > "${BUILD}/env-worker.json" <<JSON
{ "Variables": {
  "TABLE_NAME": "${TABLE}",
  "GROQ_API_KEY": "${GROQ_API_KEY}",
  "GROQ_MODEL": "${GROQ_MODEL}",
  "MAX_ATTEMPTS": "3"
} }
JSON
cat > "${BUILD}/env-api.json" <<JSON
{ "Variables": {
  "TABLE_NAME": "${TABLE}",
  "BUCKET": "${BUCKET}",
  "URL_EXPIRES": "300"
} }
JSON

echo "  creando ${FN_SPLITTER}..."
aws lambda create-function --function-name "${FN_SPLITTER}" \
  --runtime "${PY_RUNTIME}" --handler splitter_lambda.handler \
  --role "${LAB_ROLE_ARN}" --zip-file "fileb://${BUILD}/splitter.zip" \
  --timeout 60 --memory-size 256 \
  --environment "file://${BUILD}/env-splitter.json" >/dev/null
aws lambda wait function-active --function-name "${FN_SPLITTER}"

echo "  creando ${FN_WORKER}..."
aws lambda create-function --function-name "${FN_WORKER}" \
  --runtime "${PY_RUNTIME}" --handler worker_lambda.handler \
  --role "${LAB_ROLE_ARN}" --zip-file "fileb://${BUILD}/worker.zip" \
  --timeout 60 --memory-size 256 \
  --environment "file://${BUILD}/env-worker.json" >/dev/null
aws lambda wait function-active --function-name "${FN_WORKER}"

# Throttle anti rate-limit de Groq: max 3 ejecuciones simultaneas del Worker.
# (Si Learner Lab limita la concurrencia de cuenta, este comando puede fallar:
#  no es critico para la demo, puedes comentarlo.)
aws lambda put-function-concurrency --function-name "${FN_WORKER}" \
  --reserved-concurrent-executions 3 >/dev/null || \
  echo "  (aviso) no se pudo fijar reserved concurrency; continuo sin throttle."

echo "  creando ${FN_API}..."
aws lambda create-function --function-name "${FN_API}" \
  --runtime "${PY_RUNTIME}" --handler api_lambda.handler \
  --role "${LAB_ROLE_ARN}" --zip-file "fileb://${BUILD}/api.zip" \
  --timeout 30 --memory-size 256 \
  --environment "file://${BUILD}/env-api.json" >/dev/null
aws lambda wait function-active --function-name "${FN_API}"
echo "  ok: 3 Lambdas activas"

# === 5. Trigger S3 -> Splitter ==============================================
echo "[5/8] Conectando S3 -> ${FN_SPLITTER}..."
SPLITTER_ARN="$(aws lambda get-function --function-name "${FN_SPLITTER}" \
  --query 'Configuration.FunctionArn' --output text)"
# permiso para que S3 invoque la Lambda (antes de poner la notificacion)
aws lambda add-permission --function-name "${FN_SPLITTER}" \
  --statement-id s3invoke --action 'lambda:InvokeFunction' \
  --principal s3.amazonaws.com \
  --source-arn "arn:aws:s3:::${BUCKET}" \
  --source-account "${ACCOUNT_ID}" >/dev/null
cat > "${BUILD}/s3-notif.json" <<JSON
{ "LambdaFunctionConfigurations": [ {
  "LambdaFunctionArn": "${SPLITTER_ARN}",
  "Events": ["s3:ObjectCreated:*"],
  "Filter": { "Key": { "FilterRules": [
    { "Name": "prefix", "Value": "inputs/" },
    { "Name": "suffix", "Value": ".csv" }
  ] } }
} ] }
JSON
aws s3api put-bucket-notification-configuration --bucket "${BUCKET}" \
  --notification-configuration "file://${BUILD}/s3-notif.json"
echo "  ok: ObjectCreated inputs/*.csv -> ${FN_SPLITTER}"

# === 6. Trigger SQS -> Worker ===============================================
echo "[6/8] Conectando SQS -> ${FN_WORKER}..."
aws lambda create-event-source-mapping --function-name "${FN_WORKER}" \
  --event-source-arn "${QUEUE_ARN}" \
  --batch-size 5 \
  --function-response-types ReportBatchItemFailures >/dev/null
echo "  ok: ${QUEUE} -> ${FN_WORKER} (batchSize 5, ReportBatchItemFailures)"

# === 7. API Gateway HTTP API -> API Lambda ==================================
echo "[7/8] API Gateway HTTP API..."
API_ARN="$(aws lambda get-function --function-name "${FN_API}" \
  --query 'Configuration.FunctionArn' --output text)"
API_ID="$(aws apigatewayv2 create-api \
  --name "${PROJECT}-api" \
  --protocol-type HTTP \
  --target "${API_ARN}" \
  --cors-configuration AllowOrigins='*',AllowMethods='*',AllowHeaders='*' \
  --query ApiId --output text)"
# permiso para que API Gateway invoque la Lambda
aws lambda add-permission --function-name "${FN_API}" \
  --statement-id apigwinvoke --action 'lambda:InvokeFunction' \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:${AWS_REGION}:${ACCOUNT_ID}:${API_ID}/*" >/dev/null
API_URL="https://${API_ID}.execute-api.${AWS_REGION}.amazonaws.com"
echo "  ok: ${API_URL}"

# === 8. Resumen ==============================================================
echo
echo "============================================================"
echo " DESPLIEGUE COMPLETO"
echo "============================================================"
echo "  BUCKET     = ${BUCKET}"
echo "  TABLE      = ${TABLE}"
echo "  QUEUE_URL  = ${QUEUE_URL}"
echo "  DLQ_URL    = ${DLQ_URL}"
echo "  API_URL    = ${API_URL}"
echo
echo "  Guarda estos valores (los usara el frontend y las pruebas):"
cat > "${ROOT}/deploy/outputs.env" <<OUT
BUCKET=${BUCKET}
TABLE=${TABLE}
QUEUE_URL=${QUEUE_URL}
DLQ_URL=${DLQ_URL}
API_URL=${API_URL}
OUT
echo "  -> escritos en deploy/outputs.env"
echo
echo "  PRUEBA RAPIDA (3 filas) - ve el manual: docs/manual-despliegue.md"
echo "============================================================"
