#!/usr/bin/env bash
###############################################################################
# RúbricaIA - Borra todos los recursos creados por deploy.sh.
# Uso: source env.sh && bash teardown.sh
# Util si necesitas re-desplegar limpio o liberar la cuenta del Learner Lab.
###############################################################################
set -uo pipefail

PROJECT="${PROJECT:-rubricaia}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

BUCKET="${PROJECT}-inputs-${ACCOUNT_ID}"
TABLE="${PROJECT}"
QUEUE="${PROJECT}-jobs"
DLQ="${PROJECT}-dlq"

echo "Borrando recursos de ${PROJECT}..."

# Lambdas
for FN in "${PROJECT}-splitter" "${PROJECT}-worker" "${PROJECT}-api"; do
  # borrar event source mappings asociados
  for UUID in $(aws lambda list-event-source-mappings --function-name "${FN}" \
      --query 'EventSourceMappings[].UUID' --output text 2>/dev/null); do
    aws lambda delete-event-source-mapping --uuid "${UUID}" >/dev/null 2>&1 || true
  done
  aws lambda delete-function --function-name "${FN}" >/dev/null 2>&1 && echo "  lambda ${FN} borrada" || true
done

# API Gateway
for API_ID in $(aws apigatewayv2 get-apis --query "Items[?Name=='${PROJECT}-api'].ApiId" --output text 2>/dev/null); do
  aws apigatewayv2 delete-api --api-id "${API_ID}" >/dev/null 2>&1 && echo "  api ${API_ID} borrada" || true
done

# SQS
for Q in "${QUEUE}" "${DLQ}"; do
  URL="$(aws sqs get-queue-url --queue-name "${Q}" --query QueueUrl --output text 2>/dev/null || true)"
  [ -n "${URL:-}" ] && aws sqs delete-queue --queue-url "${URL}" >/dev/null 2>&1 && echo "  cola ${Q} borrada" || true
done

# DynamoDB
aws dynamodb delete-table --table-name "${TABLE}" >/dev/null 2>&1 && echo "  tabla ${TABLE} borrada" || true

# S3 (vaciar y borrar)
aws s3 rb "s3://${BUCKET}" --force >/dev/null 2>&1 && echo "  bucket ${BUCKET} borrado" || true

echo "Listo."
