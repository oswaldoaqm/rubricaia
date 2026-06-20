"""
RúbricaIA - LMS Lambda (plano de control multi-tenant)
======================================================
Disparador : API Gateway HTTP API. Rutas protegidas por JWT (header Authorization).
Funcion    : gestion de clases (F2), membresias/invitaciones (F3) y tareas (F4).

Esta fase (F2) implementa CLASES:
  POST /classes          -> crear clase (solo profesor)
  GET  /classes          -> listar mis clases (profesor: las que posee;
                            estudiante: aquellas donde es miembro -> F3)
  POST /classes/delete   -> eliminar clase (solo el profesor dueño; cascada)

Modelo (tabla rubricaia-lms):
  CLASS#<id>   / META                 -> {classId, name, ownerEmail, createdAt}
  USER#<email> / OWNS#<id>            -> espejo: clases que posee el profesor
  USER#<email> / MEMBERSHIP#<id>     -> espejo: clases del estudiante (F3)
  CLASS#<id>   / MEMBER#<email>      -> roster (F3)
  CLASS#<id>   / TASK#<taskId>       -> tareas (F4)

Variables de entorno:
  LMS_TABLE  = rubricaia-lms-<stage>
  JWT_SECRET = (lo usa authlib para validar el token)
"""

import os
import sys
import json
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "common"))
from authlib import auth_from_event  # noqa: E402

LMS_TABLE = os.environ["LMS_TABLE"]
ddb = boto3.resource("dynamodb")
table = ddb.Table(LMS_TABLE)

CORS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
}


def _resp(code, body):
    return {"statusCode": code, "headers": CORS, "body": json.dumps(body, ensure_ascii=False)}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "")

    if method == "OPTIONS":
        return _resp(200, {"ok": True})

    claims = auth_from_event(event)
    if not claims:
        return _resp(401, {"error": "no autenticado"})
    email = claims["email"]
    role = claims.get("role", "estudiante")

    try:
        if method == "POST" and path.endswith("/classes/delete"):
            return delete_class(email, role, event)
        if method == "POST" and path.endswith("/classes"):
            return create_class(email, role, event)
        if method == "GET" and path.endswith("/classes"):
            return list_classes(email, role)
        return _resp(404, {"error": "ruta no encontrada", "path": path})
    except Exception as e:  # noqa: BLE001
        return _resp(500, {"error": str(e)})


# --- POST /classes ---------------------------------------------------------
def create_class(email, role, event):
    if role != "profesor":
        return _resp(403, {"error": "Solo un profesor puede crear clases"})
    body = json.loads(event.get("body") or "{}")
    name = (body.get("name") or "").strip()
    if not name:
        return _resp(400, {"error": "El nombre de la clase es obligatorio"})

    class_id = "cls-" + uuid.uuid4().hex[:8]
    now = now_iso()
    # Item canonico de la clase.
    table.put_item(
        Item={
            "PK": f"CLASS#{class_id}",
            "SK": "META",
            "classId": class_id,
            "name": name,
            "ownerEmail": email,
            "createdAt": now,
        }
    )
    # Espejo para listar "mis clases" sin GSI.
    table.put_item(
        Item={
            "PK": f"USER#{email}",
            "SK": f"OWNS#{class_id}",
            "classId": class_id,
            "name": name,
            "createdAt": now,
        }
    )
    return _resp(200, {"classId": class_id, "name": name})


# --- GET /classes ----------------------------------------------------------
def list_classes(email, role):
    # Profesor: clases que posee (OWNS#). Estudiante: donde es miembro (MEMBERSHIP#).
    prefix = "OWNS#" if role == "profesor" else "MEMBERSHIP#"
    resp = table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{email}") & Key("SK").begins_with(prefix)
    )
    classes = [
        {
            "classId": i.get("classId"),
            "name": i.get("name"),
            "createdAt": i.get("createdAt"),
            "status": i.get("status"),  # solo aplica a estudiante (invited/active)
        }
        for i in resp.get("Items", [])
    ]
    classes.sort(key=lambda c: c.get("createdAt") or "", reverse=True)
    return _resp(200, {"classes": classes, "role": role})


# --- POST /classes/delete --------------------------------------------------
def delete_class(email, role, event):
    if role != "profesor":
        return _resp(403, {"error": "Solo un profesor puede eliminar clases"})
    body = json.loads(event.get("body") or "{}")
    class_id = (body.get("classId") or "").strip()

    meta = table.get_item(Key={"PK": f"CLASS#{class_id}", "SK": "META"}).get("Item")
    if not meta:
        return _resp(404, {"error": "Clase no encontrada"})
    if meta.get("ownerEmail") != email:
        return _resp(403, {"error": "No eres el dueño de esta clase"})

    # Cascada: borra META, tareas, roster y los espejos de membresia de cada alumno.
    items = []
    resp = table.query(KeyConditionExpression=Key("PK").eq(f"CLASS#{class_id}"))
    items += resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = table.query(
            KeyConditionExpression=Key("PK").eq(f"CLASS#{class_id}"),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items += resp.get("Items", [])

    with table.batch_writer() as bw:
        for it in items:
            if it["SK"].startswith("MEMBER#"):
                member = it["SK"].split("MEMBER#", 1)[1]
                bw.delete_item(Key={"PK": f"USER#{member}", "SK": f"MEMBERSHIP#{class_id}"})
            bw.delete_item(Key={"PK": it["PK"], "SK": it["SK"]})
        bw.delete_item(Key={"PK": f"USER#{email}", "SK": f"OWNS#{class_id}"})

    return _resp(200, {"deleted": class_id})
