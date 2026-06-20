"""
RúbricaIA - API Lambda
======================
Disparador : API Gateway HTTP API (ruta $default, integracion AWS_PROXY).
             Una sola Lambda enruta internamente por metodo + path.
Funcion    : expone la API que consumira el frontend.

Endpoints:
  POST /uploads               -> genera presigned URL para subir el CSV a S3
  GET  /jobs                  -> lista todos los jobs (item META)
  GET  /jobs/{jobId}          -> estado + resultados de un job (progreso por entregable)
  GET  /jobs/{jobId}/report   -> presigned URL de descarga del reporte (Fase 3B)
                                 ?format=html|csv|json (default html)
  POST /jobs/{jobId}/retry    -> re-encola los entregables en FAILED (F1)
"""

import os
import sys
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key, Attr

# authlib comun (para validar el JWT en las entregas ligadas a una tarea, F5).
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "common"))
from authlib import auth_from_event  # noqa: E402

TABLE_NAME = os.environ["TABLE_NAME"]
BUCKET = os.environ["BUCKET"]
URL_EXPIRES = int(os.environ.get("URL_EXPIRES", "300"))
QUEUE_URL = os.environ.get("QUEUE_URL", "")  # F1: re-encolar fallidos
LMS_TABLE = os.environ.get("LMS_TABLE", "")  # F5: tabla del plano de control

s3 = boto3.client("s3")
sqs = boto3.client("sqs")
ddb = boto3.resource("dynamodb")
table = ddb.Table(TABLE_NAME)
lms_table = ddb.Table(LMS_TABLE) if LMS_TABLE else None

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


# --- helpers ---------------------------------------------------------------
def _dec(o):
    if isinstance(o, Decimal):
        return int(o) if o % 1 == 0 else float(o)
    raise TypeError


def _resp(code, body):
    return {
        "statusCode": code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body, default=_dec, ensure_ascii=False),
    }


# --- router ----------------------------------------------------------------
def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/")

    try:
        if method == "OPTIONS":
            return _resp(200, {"ok": True})
        if method == "POST" and path == "/uploads":
            return create_upload(event)
        if method == "GET" and path == "/jobs":
            return list_jobs()
        if method == "POST" and path.startswith("/jobs/") and path.endswith("/retry"):
            return retry_failed(path[len("/jobs/"):-len("/retry")])
        if method == "GET" and path.startswith("/jobs/") and path.endswith("/report"):
            return get_report(event, path[len("/jobs/"):-len("/report")])
        if method == "GET" and path.startswith("/jobs/"):
            return get_job(path.split("/jobs/", 1)[1])
        return _resp(404, {"error": "ruta no encontrada", "path": path, "method": method})
    except Exception as e:  # noqa: BLE001
        return _resp(500, {"error": str(e)})


# --- POST /uploads ---------------------------------------------------------
def create_upload(event):
    body = json.loads(event.get("body") or "{}")
    class_id = (body.get("classId") or "").strip()
    task_id = (body.get("taskId") or "").strip()

    rubrica = (body.get("rubrica") or "").strip()
    pesos = _parse_pesos(body.get("pesos"))  # ruta libre (sin tarea)
    scope = {}

    # F5: si la entrega va ligada a una tarea, la rubrica y los pesos son los de la
    # TAREA (fuente de verdad en el plano de control); el cliente no los decide.
    if class_id and task_id:
        claims = auth_from_event(event)
        if not claims:
            return _resp(401, {"error": "no autenticado"})
        student = claims["email"]
        if lms_table is None:
            return _resp(500, {"error": "LMS no configurado"})
        member = lms_table.get_item(
            Key={"PK": f"CLASS#{class_id}", "SK": f"MEMBER#{student}"}
        ).get("Item")
        if not member or member.get("status") != "active":
            return _resp(403, {"error": "No perteneces a esta clase"})
        task = lms_table.get_item(
            Key={"PK": f"CLASS#{class_id}", "SK": f"TASK#{task_id}"}
        ).get("Item")
        if not task:
            return _resp(404, {"error": "Tarea no encontrada"})
        rubrica = task.get("rubrica", "") or rubrica
        pesos = _plain_pesos(task.get("pesos"))
        scope = {
            "classId": class_id,
            "taskId": task_id,
            "studentEmail": student,
            "taskTitle": task.get("title", ""),
        }

    job_id = body.get("jobId") or (
        "job-"
        + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        + "-"
        + uuid.uuid4().hex[:6]
    )
    key = f"inputs/{job_id}/submissions.csv"

    now = datetime.now(timezone.utc).isoformat()
    meta = {
        "PK": f"JOB#{job_id}",
        "SK": "META",
        "status": "PENDING_UPLOAD",
        "rubrica": rubrica,
        "createdAt": now,
        "updatedAt": now,
    }
    meta.update(scope)
    if pesos:
        meta["pesos"] = [Decimal(str(p)) for p in pesos]
    table.put_item(Item=meta)

    # F5: puntero de entrega del alumno (para reabrir la tarea y ver su resultado).
    # P2: índice por clase/tarea (para que el profesor liste las entregas sin scan).
    if scope:
        lms_table.put_item(
            Item={
                "PK": f"USER#{scope['studentEmail']}",
                "SK": f"SUBMISSION#{task_id}",
                "jobId": job_id,
                "classId": class_id,
                "taskId": task_id,
                "submittedAt": now,
            }
        )
        lms_table.put_item(
            Item={
                "PK": f"CLASS#{class_id}",
                "SK": f"SUB#{task_id}#{scope['studentEmail']}",
                "jobId": job_id,
                "studentEmail": scope["studentEmail"],
                "taskId": task_id,
                "submittedAt": now,
            }
        )
        # G1: registro versionado por intento (no sobrescribe; ordena por timestamp).
        lms_table.put_item(
            Item={
                "PK": f"USER#{scope['studentEmail']}",
                "SK": f"SUBVER#{task_id}#{now}",
                "jobId": job_id,
                "taskId": task_id,
                "submittedAt": now,
            }
        )

    params = {"Bucket": BUCKET, "Key": key, "ContentType": "text/csv"}
    url = s3.generate_presigned_url("put_object", Params=params, ExpiresIn=URL_EXPIRES)
    return _resp(200, {
        "jobId": job_id,
        "uploadUrl": url,
        "method": "PUT",
        "headers": {"Content-Type": "text/csv"},  # el frontend replica esto en el PUT
        "key": key,
    })


# --- GET /jobs -------------------------------------------------------------
def list_jobs():
    # Scan de items META (suficiente para la escala de demo)
    resp = table.scan(FilterExpression=Attr("SK").eq("META"))
    jobs = [
        {
            "jobId": i["PK"].split("JOB#")[1],
            "status": i.get("status"),
            "total": i.get("total"),
            "createdAt": i.get("createdAt"),
        }
        for i in resp.get("Items", [])
    ]
    jobs.sort(key=lambda x: x.get("createdAt") or "", reverse=True)
    return _resp(200, {"jobs": jobs})


# --- GET /jobs/{jobId} -----------------------------------------------------
def get_job(job_id):
    resp = table.query(KeyConditionExpression=Key("PK").eq(f"JOB#{job_id}"))
    items = resp.get("Items", [])
    if not items:
        return _resp(404, {"error": "job no encontrado", "jobId": job_id})

    meta = next((i for i in items if i["SK"] == "META"), None)
    entregables = [i for i in items if i["SK"].startswith("ITEM#")]
    stats = next((i for i in items if i["SK"] == "STATS"), None)
    fails = [i for i in items if i["SK"].startswith("FAIL#")]

    counts = {}
    for e in entregables:
        st = e.get("status", "PENDING")
        counts[st] = counts.get(st, 0) + 1

    total = int(meta.get("total")) if meta and meta.get("total") is not None else len(entregables)
    done = counts.get("DONE", 0)
    failed = counts.get("FAILED", 0)
    # estado del job derivado en vivo (no depende de escribir META)
    job_status = "DONE" if total > 0 and (done + failed) >= total else "PROCESSING"

    results = [
        {
            "id_estudiante": e.get("id_estudiante"),
            "status": e.get("status"),
            "cumplimiento": e.get("cumplimiento"),
            "criterios": e.get("criterios", []),
            "criterios_ok": e.get("criterios_ok", []),
            "faltantes": e.get("faltantes", []),
            "sugerencias": e.get("sugerencias", []),
            "attempts": e.get("attempts"),
            "last_error": e.get("last_error"),
        }
        for e in entregables
    ]
    results.sort(key=lambda x: x.get("id_estudiante") or "")

    # Insights de la clase (los mantiene el Aggregator via DynamoDB Streams).
    insights = None
    if stats:
        dc = int(stats.get("done_count", 0) or 0)
        csum = int(stats.get("cumplimiento_sum", 0) or 0)
        insights = {
            "evaluados": dc,
            "promedio": round(csum / dc) if dc else 0,
            "distribucion": {
                "low": int(stats.get("dist_low", 0) or 0),
                "mid": int(stats.get("dist_mid", 0) or 0),
                "high": int(stats.get("dist_high", 0) or 0),
            },
            "criterios_fallados": sorted(
                [
                    {
                        "criterio": f.get("criterio", f["SK"][5:]),
                        "count": int(f.get("fail_count", 0) or 0),
                    }
                    for f in fails
                ],
                key=lambda x: -x["count"],
            ),
        }

    return _resp(200, {
        "jobId": job_id,
        "jobStatus": job_status,
        "total": total,
        "done": done,
        "failed": failed,
        "counts": counts,
        "insights": insights,
        "results": results,
        # Fase 3B: el evento JobCompleted disparo SNS (docente notificado) y la
        # generacion del reporte. El frontend usa estos flags para el badge y la
        # descarga.
        "completed": bool(stats.get("completed")) if stats else False,
        "reportReady": bool(meta.get("report_ready")) if meta else False,
        # F4: nº de pares de entregables sospechosamente similares (anti-copia).
        "similarCount": int(meta.get("similar_count", 0) or 0) if meta else 0,
    })


# --- POST /jobs/{jobId}/retry (F1) -----------------------------------------
def retry_failed(job_id):
    """Re-encola los entregables en FAILED del job (redrive controlado) y reabre
    la compuerta de completion para que se regenere el reporte y la notificacion."""
    resp = table.query(KeyConditionExpression=Key("PK").eq(f"JOB#{job_id}"))
    items = resp.get("Items", [])
    meta = next((i for i in items if i["SK"] == "META"), {}) or {}
    rubrica = meta.get("rubrica", "")
    pesos = _plain_pesos(meta.get("pesos"))
    failed = [
        i for i in items if i["SK"].startswith("ITEM#") and i.get("status") == "FAILED"
    ]

    now = datetime.now(timezone.utc).isoformat()
    requeued = 0
    for it in failed:
        sid = it.get("id_estudiante")
        body = json.dumps(
            {
                "jobId": job_id,
                "idEstudiante": sid,
                "texto": it.get("texto", ""),
                "rubrica": rubrica,
                "pesos": pesos,
            }
        )
        sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=body)
        table.update_item(
            Key={"PK": f"JOB#{job_id}", "SK": f"ITEM#{sid}"},
            UpdateExpression="SET #s = :s, updatedAt = :t REMOVE last_error",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "PENDING", ":t": now},
        )
        requeued += 1

    if requeued:
        # Ajusta el contador de fallidos y reabre la compuerta: al terminar de
        # nuevo, el Aggregator vuelve a emitir JobCompleted (reporte + email).
        table.update_item(
            Key={"PK": f"JOB#{job_id}", "SK": "STATS"},
            UpdateExpression="ADD failed_count :neg REMOVE completed, completed_at",
            ExpressionAttributeValues={":neg": Decimal(-requeued)},
        )
        table.update_item(
            Key={"PK": f"JOB#{job_id}", "SK": "META"},
            UpdateExpression="SET #s = :s, updatedAt = :t REMOVE report_ready, report_at",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "PROCESSING", ":t": now},
        )

    return _resp(200, {"requeued": requeued})


# --- helpers de pesos (F5) -------------------------------------------------
def _parse_pesos(raw):
    """Acepta lista [30,20,...] o string '30,20,...'. Devuelve lista de numeros > 0 o None."""
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = [p for p in raw.replace(";", ",").split(",") if p.strip()]
    if not isinstance(raw, (list, tuple)):
        return None
    out = []
    for p in raw:
        try:
            f = float(p)
        except (TypeError, ValueError):
            return None
        if f < 0:
            return None
        out.append(int(f) if float(f).is_integer() else f)
    return out or None


def _plain_pesos(pesos):
    """Convierte pesos (Decimals de DynamoDB) a numeros JSON-serializables."""
    if not pesos:
        return None
    out = []
    for p in pesos:
        try:
            f = float(p)
        except (TypeError, ValueError):
            return None
        out.append(int(f) if f.is_integer() else f)
    return out or None


# --- GET /jobs/{jobId}/report ----------------------------------------------
def get_report(event, job_id):
    """Devuelve una presigned URL para descargar el reporte de clase (Fase 3B)."""
    qs = event.get("queryStringParameters") or {}
    fmt = (qs.get("format") or "html").lower()
    if fmt not in ("html", "csv", "json"):
        fmt = "html"

    meta = table.get_item(Key={"PK": f"JOB#{job_id}", "SK": "META"}).get("Item") or {}
    if not meta.get("report_ready"):
        return _resp(200, {"ready": False})

    key = f"reports/{job_id}/report.{fmt}"
    url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": BUCKET, "Key": key}, ExpiresIn=URL_EXPIRES
    )
    return _resp(200, {"ready": True, "format": fmt, "url": url})
