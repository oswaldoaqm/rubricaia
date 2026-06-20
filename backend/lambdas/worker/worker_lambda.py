"""
RúbricaIA - Worker Lambda
=========================
Disparador : SQS (event source mapping) desde la cola principal `rubricaia-jobs`.
Funcion    : por cada mensaje (un entregable) llama a Groq, parsea el JSON de
             salida y guarda el resultado/estado en DynamoDB.

Resiliencia (rúbrica criterio 3):
  - Idempotencia: si el item ya está DONE, no se reprocesa.
  - 429 / 5xx / JSON inválido  -> excepcion -> el mensaje se reporta como fallido
    -> SQS lo reentrega tras el visibility timeout (reintento automatico).
  - Tras `MAX_ATTEMPTS` recepciones, se marca FAILED y SQS lo manda a la DLQ.
  - Se usa ReportBatchItemFailures: solo se reintenta el mensaje que falla,
    no todo el lote.

Despliegue (AWS Learner Lab):
  - Runtime  : python3.12
  - Handler  : worker_lambda.handler
  - Role     : LabRole
  - Sin dependencias externas: solo stdlib + boto3 (ya incluido en el runtime).
    => se sube como un .zip con solo este archivo.
  - Reserved concurrency: 3-5  (controla cuantas llamadas simultaneas a Groq -> evita rate limit)
  - Trigger SQS: batchSize 5, "Report batch item failures" ACTIVADO.

Variables de entorno:
  TABLE_NAME      = rubricaia
  GROQ_API_KEY    = gsk_...            (tu key de https://console.groq.com/keys)
  GROQ_MODEL      = llama-3.3-70b-versatile   (opcional)
  MAX_ATTEMPTS    = 3                  (opcional)
"""

import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from decimal import Decimal

import boto3

TABLE_NAME = os.environ["TABLE_NAME"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "3"))
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

ddb = boto3.resource("dynamodb")
table = ddb.Table(TABLE_NAME)


# --- errores que SI ameritan reintento -------------------------------------
class RetryableError(Exception):
    pass


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# --- llamada a Groq (stdlib, sin librerias externas) -----------------------
def call_groq(texto, rubrica):
    system_prompt = (
        "Eres un evaluador academico estricto. Recibes la RUBRICA y el TEXTO de "
        "un entregable de un estudiante. Evalua que tan bien el texto cumple la "
        "rubrica. Responde UNICAMENTE un objeto JSON valido con EXACTAMENTE estas "
        "claves:\n"
        '  "cumplimiento": entero 0-100 (porcentaje global de cumplimiento),\n'
        '  "criterios_ok": lista de strings (lo que SI cumple),\n'
        '  "faltantes": lista de strings (lo que falta),\n'
        '  "sugerencias": lista de strings accionables y concretas.\n'
        "No agregues texto fuera del JSON."
    )
    user_prompt = f"RUBRICA:\n{rubrica}\n\nTEXTO DEL ENTREGABLE:\n{texto}"

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        GROQ_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            # Groq esta detras de Cloudflare; el User-Agent por defecto de urllib
            # ("Python-urllib/x.y") es bloqueado con error 1010. Mandamos uno normal.
            "User-Agent": "Mozilla/5.0 (RubricaIA)",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 429 = rate limit ; 5xx = error temporal del proveedor -> reintentar
        if e.code == 429 or e.code >= 500:
            raise RetryableError(f"Groq HTTP {e.code} (reintentar)")
        # 4xx (ej. 401 key mala, 400 payload) -> error permanente, no reintentar util,
        # pero lo tratamos como reintentable para no perder el dato; quedara en DLQ.
        raise RetryableError(f"Groq HTTP {e.code}: {e.read().decode('utf-8')[:200]}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise RetryableError(f"Groq red/timeout: {e}")

    try:
        content = body["choices"][0]["message"]["content"]
        result = json.loads(content)
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise RetryableError(f"Respuesta de Groq no parseable: {e}")

    return {
        "cumplimiento": int(result.get("cumplimiento", 0)),
        "criterios_ok": [str(x) for x in result.get("criterios_ok", [])],
        "faltantes": [str(x) for x in result.get("faltantes", [])],
        "sugerencias": [str(x) for x in result.get("sugerencias", [])],
    }


# --- DynamoDB helpers ------------------------------------------------------
def get_status(pk, sk):
    item = table.get_item(Key={"PK": pk, "SK": sk}).get("Item")
    return item.get("status") if item else None


def set_processing(pk, sk):
    table.update_item(
        Key={"PK": pk, "SK": sk},
        UpdateExpression="SET #s = :s, updatedAt = :t",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "PROCESSING", ":t": now_iso()},
    )


def set_done(pk, sk, result):
    table.update_item(
        Key={"PK": pk, "SK": sk},
        UpdateExpression=(
            "SET #s = :s, cumplimiento = :c, criterios_ok = :ok, "
            "faltantes = :f, sugerencias = :g, updatedAt = :t"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "DONE",
            ":c": Decimal(str(result["cumplimiento"])),
            ":ok": result["criterios_ok"],
            ":f": result["faltantes"],
            ":g": result["sugerencias"],
            ":t": now_iso(),
        },
    )


def set_attempt_status(pk, sk, recv_count, error_msg):
    status = "FAILED" if recv_count >= MAX_ATTEMPTS else "RETRYING"
    table.update_item(
        Key={"PK": pk, "SK": sk},
        UpdateExpression="SET #s = :s, attempts = :a, last_error = :e, updatedAt = :t",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": status,
            ":a": Decimal(str(recv_count)),
            ":e": error_msg[:500],
            ":t": now_iso(),
        },
    )


# --- procesamiento de un mensaje ------------------------------------------
def process_record(record):
    msg = json.loads(record["body"])
    job_id = msg["jobId"]
    sid = msg["idEstudiante"]
    pk = f"JOB#{job_id}"
    sk = f"ITEM#{sid}"

    # Idempotencia: si ya quedo DONE (reentrega duplicada de SQS), no reprocesar.
    if get_status(pk, sk) == "DONE":
        return

    set_processing(pk, sk)
    result = call_groq(msg["texto"], msg["rubrica"])  # puede lanzar RetryableError
    set_done(pk, sk, result)


# --- handler ---------------------------------------------------------------
def handler(event, context):
    batch_item_failures = []

    for record in event.get("Records", []):
        recv_count = int(record.get("attributes", {}).get("ApproximateReceiveCount", "1"))
        try:
            process_record(record)
        except Exception as e:  # noqa: BLE001 - cualquier fallo -> reintentar via SQS
            try:
                msg = json.loads(record["body"])
                pk = f"JOB#{msg['jobId']}"
                sk = f"ITEM#{msg['idEstudiante']}"
                set_attempt_status(pk, sk, recv_count, str(e))
            except Exception:
                pass  # si ni el body se puede leer, igual reportamos el fallo abajo
            # Reportar este mensaje como fallido => SQS lo reentrega (o lo manda a DLQ
            # cuando se supera maxReceiveCount). El resto del lote NO se reintenta.
            batch_item_failures.append({"itemIdentifier": record["messageId"]})

    return {"batchItemFailures": batch_item_failures}
