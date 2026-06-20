#!/usr/bin/env bash
###############################################################################
# RúbricaIA - PLAN B: frontend como sitio estatico en S3 (si Amplify falla).
#
# Publica la app React en un bucket S3 con website hosting (URL publica HTTP).
# Uso:
#   source deploy/env.sh
#   bash deploy/deploy-frontend-s3.sh
###############################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${ROOT}/deploy/outputs.env"
: "${API_URL:?No encuentro API_URL. Corre primero deploy.sh}"

AWS_REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
WEB="rubricaia-web-${ACCOUNT_ID}"

echo "== Frontend deploy (S3 website) =="
echo "  bucket = ${WEB}"

# --- 1. Build -----------------------------------------------------------------
cd "${ROOT}/frontend"
npm install --silent
VITE_API_URL="${API_URL}" npm run build

# --- 2. Bucket publico + website ---------------------------------------------
if [ "${AWS_REGION}" = "us-east-1" ]; then
  aws s3api create-bucket --bucket "${WEB}" >/dev/null 2>&1 || true
else
  aws s3api create-bucket --bucket "${WEB}" \
    --create-bucket-configuration LocationConstraint="${AWS_REGION}" >/dev/null 2>&1 || true
fi
aws s3api delete-public-access-block --bucket "${WEB}" >/dev/null 2>&1 || true
cat > /tmp/web-policy.json <<JSON
{ "Version": "2012-10-17", "Statement": [ {
  "Sid": "PublicRead", "Effect": "Allow", "Principal": "*",
  "Action": "s3:GetObject", "Resource": "arn:aws:s3:::${WEB}/*"
} ] }
JSON
aws s3api put-bucket-policy --bucket "${WEB}" --policy file:///tmp/web-policy.json
aws s3 website "s3://${WEB}/" --index-document index.html --error-document index.html

# --- 3. Subir build -----------------------------------------------------------
aws s3 sync dist "s3://${WEB}/" --delete

FRONT_URL="http://${WEB}.s3-website-us-east-1.amazonaws.com"
echo
echo "============================================================"
echo " FRONTEND DESPLEGADO (S3)"
echo "   ${FRONT_URL}"
echo "============================================================"
echo "FRONT_URL=${FRONT_URL}" >> "${ROOT}/deploy/outputs.env"
