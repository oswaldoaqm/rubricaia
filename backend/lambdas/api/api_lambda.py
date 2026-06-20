"""
RúbricaIA - API Lambda
======================
Disparador : API Gateway HTTP API (ruta $default, integracion AWS_PROXY).
             Una sola Lambda enruta internamente por metodo + path.
Funcion    : expone la API que consumira el frontend.

Endpoints:
  POST /uploads        -> genera presigned URL para subir el CSV a S3
  GET  /jobs           -> lista todos los jobs (item META)
  GET  /jobs/{jobId}   -> estado + resultados de un job (progreso por entregable)

Despliegue (AWS Learner Lab):
  - Runtime  : python3.12
  - Handler  : api_lambda.handler
  - Role     : LabRole
  - Sin dependencias externas (stdlib + boto3).
  - Integracion API Gateway HTTP API (proxy), CORS abierto (demo).

Variables de entorno:
  TABLE_NAME    = rubricaia
  BUCKET        = rubricaia-inputs-<accountId>
  URL_EXPIRES   = 300            (segundos de validez del presigned URL, opcional)
"""

import os
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key, Attr

TABLE_NAME = os.environ["TABLE_NAME"]
BUCKET = os.environ["BUCKET"]
URL_EXPIRES = int(os.environ.get("URL_EXPIRES", "300"))

s3 = boto3.client("s3")
ddb = boto3.resource("dynamodb")
table = ddb.Table(TABLE_NAME)

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
        if method == "GET" and path.startswith("/jobs/"):
            return get_job(path.split("/jobs/", 1)[1])
        return _resp(404, {"error": "ruta no encontrada", "path": path, "method": method})
    except Exception as e:  # noqa: BLE001
        return _resp(500, {"error": str(e)})


# --- POST /uploads ---------------------------------------------------------
def create_upload(event):
    body = json.loads(event.get("body") or "{}")

    job_id = body.get("jobId") or (
        "job-"
        + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        + "-"
        + uuid.uuid4().hex[:6]
    )
    rubrica = (body.get("rubrica") or "").strip()
    key = f"inputs/{job_id}/submissions.csv"

    # Guardamos la rubrica en DynamoDB (NO en metadata de S3). Asi soporta texto
    # largo, con acentos y saltos de linea sin romper la firma del presigned URL
    # ni los limites de los headers HTTP.
    now = datetime.now(timezone.utc).isoformat()
    table.put_item(Item={
        "PK": f"JOB#{job_id}",
        "SK": "META",
        "status": "PENDING_UPLOAD",
        "rubrica": rubrica,
        "createdAt": now,
        "updatedAt": now,
    })

    # Presigned URL simple: solo Content-Type, sin metadata.
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
    })
