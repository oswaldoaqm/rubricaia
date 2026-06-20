#!/usr/bin/env bash
# RúbricaIA - variables de entorno para el despliegue.
# Copia este archivo a env.sh, rellena tu GROQ_API_KEY y haz: source env.sh
# (NO subas env.sh al repo: contiene tu API key)

# --- AWS / Learner Lab ---
export AWS_REGION="us-east-1"                 # Learner Lab suele ser us-east-1
export PROJECT="rubricaia"

# --- Groq ---
export GROQ_API_KEY="gsk_PON_AQUI_TU_KEY"     # https://console.groq.com/keys
export GROQ_MODEL="llama-3.3-70b-versatile"

# --- Fase 3B: correo del docente para la notificacion SNS ---
# AWS enviara un correo de confirmacion: el docente debe hacer clic en
# "Confirm subscription" UNA vez (queda confirmado para siempre).
export TEACHER_EMAIL="docente@dominio.com"

# --- Plano multi-tenant: auth ---
# Secreto para firmar los JWT (cualquier cadena larga y aleatoria; NO lo compartas).
export JWT_SECRET="cambia-esto-por-una-cadena-larga-aleatoria"
# Correos que entran como PROFESOR (separados por coma). El resto = estudiante.
export TEACHER_EMAILS="oswaldo.quispe@utec.edu.pe"

# --- Runtime Lambda ---
export PY_RUNTIME="python3.12"                # si Learner Lab no lo tiene, usa python3.11

# --- Rúbrica por defecto (si el CSV no trae metadata 'rubrica') ---
export DEFAULT_RUBRICA="1) Define un problema real y concreto. 2) Identifica al usuario afectado. 3) Describe el caso de uso. 4) Justifica el impacto esperado con metricas. 5) Redaccion clara y estructurada."
