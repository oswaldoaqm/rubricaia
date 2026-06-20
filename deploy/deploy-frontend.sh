#!/usr/bin/env bash
###############################################################################
# RúbricaIA - Despliegue del frontend en AWS Amplify Hosting (manual deploy CLI)
#
# Compila la app React con la API_URL del backend y la publica en Amplify.
# Uso:
#   echo "API_URL=<endpoint de 'serverless info'>" > deploy/outputs.env
#   source deploy/env.sh
#   bash deploy/deploy-frontend.sh
###############################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# API_URL viene de outputs.env (lo creas con el endpoint de 'serverless info')
source "${ROOT}/deploy/outputs.env"
: "${API_URL:?No encuentro API_URL. Crea deploy/outputs.env con API_URL=<endpoint de 'serverless info'>}"

APP_NAME="rubricaia-frontend"
BRANCH="main"
AWS_REGION="${AWS_REGION:-us-east-1}"

echo "== Frontend deploy (Amplify) =="
echo "  API_URL = ${API_URL}"

# --- 1. Build -----------------------------------------------------------------
cd "${ROOT}/frontend"
echo "[1/4] npm install + build..."
npm install --silent
VITE_API_URL="${API_URL}" npm run build
# empaquetar el contenido de dist/ (index.html debe quedar en la raiz del zip)
( cd dist && zip -r -q /tmp/rubricaia-site.zip . )

# --- 2. App + branch (crear si no existen) -----------------------------------
echo "[2/4] App Amplify..."
APP_ID="$(aws amplify list-apps --query "apps[?name=='${APP_NAME}'].appId" --output text 2>/dev/null || true)"
if [ -z "${APP_ID}" ] || [ "${APP_ID}" = "None" ]; then
  APP_ID="$(aws amplify create-app --name "${APP_NAME}" --query app.appId --output text)"
  aws amplify create-branch --app-id "${APP_ID}" --branch-name "${BRANCH}" >/dev/null
  echo "  app creada: ${APP_ID}"
else
  echo "  app existente: ${APP_ID}"
  aws amplify get-branch --app-id "${APP_ID}" --branch-name "${BRANCH}" >/dev/null 2>&1 \
    || aws amplify create-branch --app-id "${APP_ID}" --branch-name "${BRANCH}" >/dev/null
fi

# --- 3. Crear deployment + subir zip -----------------------------------------
echo "[3/4] Subiendo build..."
read -r JOB_ID UPLOAD_URL < <(aws amplify create-deployment \
  --app-id "${APP_ID}" --branch-name "${BRANCH}" \
  --query '[jobId,zipUploadUrl]' --output text)
curl -s -H "Content-Type: application/zip" --upload-file /tmp/rubricaia-site.zip "${UPLOAD_URL}"

# --- 4. Iniciar deployment ----------------------------------------------------
echo "[4/4] Activando deployment..."
aws amplify start-deployment --app-id "${APP_ID}" --branch-name "${BRANCH}" --job-id "${JOB_ID}" >/dev/null

FRONT_URL="https://${BRANCH}.${APP_ID}.amplifyapp.com"
echo
echo "============================================================"
echo " FRONTEND DESPLEGADO"
echo "   ${FRONT_URL}"
echo "============================================================"
echo "FRONT_URL=${FRONT_URL}" >> "${ROOT}/deploy/outputs.env"
echo "(la primera carga puede tardar ~1 min en propagar)"
