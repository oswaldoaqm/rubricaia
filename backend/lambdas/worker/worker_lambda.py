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

Sin dependencias externas: stdlib + boto3 (Groq se llama con urllib).
"""

import os
import json
import random
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

# F3: backoff adaptativo ante rate limit (segundos).
QUEUE_URL = os.environ.get("QUEUE_URL", "")
RETRY_BASE = float(os.environ.get("RETRY_BASE_SECONDS", "5"))
RETRY_CAP = int(os.environ.get("RETRY_CAP_SECONDS", "300"))

# G2: servicio RAG en OCI (multinube). Si RAG_URL está vacío, se evalúa sin RAG.
RAG_URL = os.environ.get("RAG_URL", "").rstrip("/")
RAG_TIMEOUT = float(os.environ.get("RAG_TIMEOUT", "5"))

ddb = boto3.resource("dynamodb")
table = ddb.Table(TABLE_NAME)
sqs = boto3.client("sqs")


# --- errores que SI ameritan reintento -------------------------------------
class RetryableError(Exception):
    def __init__(self, message, retry_after=None):
        super().__init__(message)
        # Si Groq mando 'Retry-After', lo respetamos al calcular el backoff.
        self.retry_after = retry_after


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# --- G2: recuperacion de contexto desde el servicio RAG en OCI (multinube) -
def _retrieve_context(texto):
    """Best-effort: si no hay RAG_URL o el servicio en OCI falla/responde lento,
    devuelve [] y la evaluacion sigue sin RAG (degradacion elegante)."""
    if not RAG_URL:
        return []
    try:
        data = json.dumps({"text": texto[:2000], "k": 3}).encode("utf-8")
        req = urllib.request.Request(
            f"{RAG_URL}/retrieve",
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "RubricaIA-Worker"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=RAG_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return [c for c in body.get("contexts", []) if c]
    except Exception as e:  # noqa: BLE001
        print(f"RAG no disponible, se evalua sin contexto: {e}")
        return []


# --- llamada a Groq (stdlib, sin librerias externas) -----------------------
def call_groq(texto, rubrica, contexts=None):
    system_prompt = (
        "Eres un evaluador academico estricto y consistente. Recibes una RUBRICA "
        "(lista numerada de criterios) y el TEXTO del entregable de un estudiante. "
        "Evalua el texto contra CADA criterio de la rubrica, devolviendo el MISMO "
        "NUMERO de criterios que la rubrica y EN EL MISMO ORDEN (ni mas ni menos). "
        "Marca cumple=true SOLO si el texto satisface el criterio de forma clara y "
        "explicita; si falta, es vago o ambiguo, marca cumple=false. "
        "Responde UNICAMENTE un objeto JSON valido con EXACTAMENTE estas claves:\n"
        '  "cumplimiento": entero 0-100 (porcentaje global; referencial),\n'
        '  "criterios": lista con UN objeto POR CADA criterio de la rubrica, EN ORDEN:\n'
        '      "criterio": el criterio evaluado (parafraseado breve),\n'
        '      "cumple": true o false,\n'
        '      "evidencia": cita breve del texto que justifica la decision (o por que falta),\n'
        '      "sugerencia": accion concreta para cumplirlo (cadena vacia si ya cumple).\n'
        "No incluyas explicaciones ni texto fuera del JSON."
    )
    # G2: material del curso recuperado por RAG (si lo hay) para calibrar el juicio.
    contexto_str = ""
    if contexts:
        contexto_str = (
            "MATERIAL DE REFERENCIA DEL CURSO (usalo para calibrar tu evaluacion):\n- "
            + "\n- ".join(contexts)
            + "\n\n"
        )
    user_prompt = f"{contexto_str}RUBRICA:\n{rubrica}\n\nTEXTO DEL ENTREGABLE:\n{texto}"

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
        # 429 = rate limit: leemos 'Retry-After' del proveedor para el backoff.
        if e.code == 429:
            ra = e.headers.get("Retry-After") if e.headers else None
            raise RetryableError("Groq HTTP 429 (rate limit)", retry_after=_parse_retry_after(ra))
        # 5xx = error temporal del proveedor -> reintentar.
        if e.code >= 500:
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

    # Normalizamos la evaluacion por criterio y derivamos las listas de resumen
    # (compatibilidad hacia atras con el frontend actual).
    criterios = []
    for c in result.get("criterios", []):
        if not isinstance(c, dict):
            continue
        criterios.append({
            "criterio": str(c.get("criterio", "")),
            "cumple": bool(c.get("cumple", False)),
            "evidencia": str(c.get("evidencia", "")),
            "sugerencia": str(c.get("sugerencia", "")),
        })

    return {
        "cumplimiento": int(result.get("cumplimiento", 0)),
        "criterios": criterios,
        "criterios_ok": [c["criterio"] for c in criterios if c["cumple"]],
        "faltantes": [c["criterio"] for c in criterios if not c["cumple"]],
        "sugerencias": [
            c["sugerencia"] for c in criterios if c["sugerencia"] and not c["cumple"]
        ],
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
            "SET #s = :s, cumplimiento = :c, criterios = :cr, criterios_ok = :ok, "
            "faltantes = :f, sugerencias = :g, metodo = :m, updatedAt = :t"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "DONE",
            ":c": Decimal(str(result["cumplimiento"])),
            ":cr": result["criterios"],
            ":ok": result["criterios_ok"],
            ":f": result["faltantes"],
            ":g": result["sugerencias"],
            ":m": result.get("cumplimiento_metodo", "llm"),
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
    contexts = _retrieve_context(msg["texto"])  # G2: RAG multinube (best-effort)
    result = call_groq(msg["texto"], msg["rubrica"], contexts)  # puede lanzar RetryableError
    # F5: si el docente fijo pesos por criterio, el cumplimiento es ponderado.
    cump, metodo = _apply_weights(result["criterios"], result["cumplimiento"], msg.get("pesos"))
    result["cumplimiento"] = cump
    result["cumplimiento_metodo"] = metodo
    set_done(pk, sk, result)


# --- F5: cumplimiento ponderado --------------------------------------------
def _apply_weights(criterios, llm_cumplimiento, pesos):
    """El cumplimiento se DERIVA de los criterios (consistente con las marcas
    cumple/no-cumple): ponderado si el docente fijo pesos, equitativo en caso
    contrario. Solo si no hubo criterios se cae al numero holistico del LLM."""
    if criterios:
        if pesos and len(pesos) == len(criterios):
            total = sum(float(p) for p in pesos)
            if total > 0:
                got = sum(float(p) for c, p in zip(criterios, pesos) if c.get("cumple"))
                return int(round(got / total * 100)), "ponderado"
        met = sum(1 for c in criterios if c.get("cumple"))
        return int(round(met / len(criterios) * 100)), "equitativo"
    return int(llm_cumplimiento), "llm"


# --- F3: backoff adaptativo ------------------------------------------------
def _parse_retry_after(value):
    """Retry-After de Groq: aceptamos segundos; ignoramos el formato fecha HTTP."""
    if not value:
        return None
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return None


def _compute_backoff(recv_count, retry_after):
    if retry_after is not None:
        base = float(retry_after)
    else:
        base = RETRY_BASE * (2 ** (recv_count - 1))  # 5, 10, 20, ...
    jitter = random.uniform(0, RETRY_BASE)            # desincroniza reintentos en paralelo
    return int(min(base + jitter, RETRY_CAP))


def _delay_message(record, recv_count, retry_after):
    """Reaparece el mensaje tras el backoff calculado (en vez del visibility fijo)."""
    if not QUEUE_URL:
        return
    delay = _compute_backoff(recv_count, retry_after)
    try:
        sqs.change_message_visibility(
            QueueUrl=QUEUE_URL,
            ReceiptHandle=record["receiptHandle"],
            VisibilityTimeout=delay,
        )
        print(f"Backoff: reintento {recv_count} reaparece en ~{delay}s (retry_after={retry_after})")
    except Exception as ex:  # noqa: BLE001 - si falla, queda el visibility por defecto
        print(f"No se pudo ajustar el visibility timeout: {ex}")


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
            # F3: si aun le quedan intentos (RETRYING), aplicamos backoff adaptativo
            # con jitter (respeta Retry-After si Groq lo mando). En el ultimo intento
            # no tiene sentido: el mensaje ira a la DLQ.
            if recv_count < MAX_ATTEMPTS:
                _delay_message(record, recv_count, getattr(e, "retry_after", None))
            # Reportar este mensaje como fallido => SQS lo reentrega (o lo manda a DLQ
            # cuando se supera maxReceiveCount). El resto del lote NO se reintenta.
            batch_item_failures.append({"itemIdentifier": record["messageId"]})

    return {"batchItemFailures": batch_item_failures}
