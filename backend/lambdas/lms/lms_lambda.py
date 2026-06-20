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
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "common"))
from authlib import auth_from_event  # noqa: E402

LMS_TABLE = os.environ["LMS_TABLE"]
JOBS_TABLE = os.environ.get("TABLE_NAME", "")  # P2: leer resultados del pipeline
ALLOWED_DOMAIN = os.environ.get("ALLOWED_DOMAIN", "utec.edu.pe").lower().lstrip("@")
ddb = boto3.resource("dynamodb")
table = ddb.Table(LMS_TABLE)
jobs_table = ddb.Table(JOBS_TABLE) if JOBS_TABLE else None

CORS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
}


def _num(o):
    if isinstance(o, Decimal):
        return int(o) if o % 1 == 0 else float(o)
    raise TypeError


def _resp(code, body):
    return {
        "statusCode": code,
        "headers": CORS,
        "body": json.dumps(body, ensure_ascii=False, default=_num),
    }


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
        if method == "POST" and path.endswith("/classes/invite"):
            return invite_member(email, role, event)
        if method == "POST" and path.endswith("/classes/remove"):
            return remove_member(email, role, event)
        if method == "POST" and path.endswith("/classes/accept"):
            return accept_invite(email, event)
        if method == "GET" and path.endswith("/classes/detail"):
            return get_detail(email, role, event)
        if method == "GET" and path.endswith("/tasks/submissions"):
            return get_task_submissions(email, role, event)
        if method == "GET" and path.endswith("/tasks/attempts"):
            return get_task_attempts(email, event)
        if method == "POST" and path.endswith("/tasks/update"):
            return update_task(email, role, event)
        if method == "POST" and path.endswith("/tasks/delete"):
            return delete_task(email, role, event)
        if method == "POST" and path.endswith("/tasks"):
            return create_task(email, role, event)
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
    if role == "profesor":
        resp = table.query(
            KeyConditionExpression=Key("PK").eq(f"USER#{email}") & Key("SK").begins_with("OWNS#")
        )
        classes = [
            {"classId": i.get("classId"), "name": i.get("name"), "createdAt": i.get("createdAt")}
            for i in resp.get("Items", [])
        ]
        classes.sort(key=lambda c: c.get("createdAt") or "", reverse=True)
        return _resp(200, {"classes": classes, "role": role})

    # Estudiante: separa clases ACTIVAS (ya aceptadas) de INVITACIONES pendientes.
    resp = table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{email}") & Key("SK").begins_with("MEMBERSHIP#")
    )
    active, invitations = [], []
    for i in resp.get("Items", []):
        entry = {
            "classId": i.get("classId"),
            "name": i.get("name"),
            "ownerEmail": i.get("ownerEmail"),
            "status": i.get("status"),
            "invitedAt": i.get("invitedAt"),
        }
        (active if i.get("status") == "active" else invitations).append(entry)
    active.sort(key=lambda c: c.get("name") or "")
    return _resp(200, {"classes": active, "invitations": invitations, "role": role})


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


# --- helper: cargar META y verificar que 'email' es el dueño ----------------
def _owned_class(class_id, email):
    meta = table.get_item(Key={"PK": f"CLASS#{class_id}", "SK": "META"}).get("Item")
    if not meta:
        return None, _resp(404, {"error": "Clase no encontrada"})
    if meta.get("ownerEmail") != email:
        return None, _resp(403, {"error": "No eres el dueño de esta clase"})
    return meta, None


# --- POST /classes/invite --------------------------------------------------
def invite_member(email, role, event):
    if role != "profesor":
        return _resp(403, {"error": "Solo un profesor puede invitar"})
    body = json.loads(event.get("body") or "{}")
    class_id = (body.get("classId") or "").strip()
    invitee = (body.get("email") or "").strip().lower()

    if "@" not in invitee or not invitee.endswith("@" + ALLOWED_DOMAIN):
        return _resp(400, {"error": f"El correo debe ser @{ALLOWED_DOMAIN}"})
    if invitee == email:
        return _resp(400, {"error": "No puedes invitarte a ti mismo"})

    meta, err = _owned_class(class_id, email)
    if err:
        return err

    existing = table.get_item(Key={"PK": f"CLASS#{class_id}", "SK": f"MEMBER#{invitee}"}).get("Item")
    if existing:
        return _resp(200, {"invited": invitee, "status": existing.get("status"), "already": True})

    now = now_iso()
    table.put_item(
        Item={
            "PK": f"CLASS#{class_id}",
            "SK": f"MEMBER#{invitee}",
            "email": invitee,
            "status": "invited",
            "role": "estudiante",
            "invitedAt": now,
        }
    )
    table.put_item(
        Item={
            "PK": f"USER#{invitee}",
            "SK": f"MEMBERSHIP#{class_id}",
            "classId": class_id,
            "name": meta.get("name"),
            "ownerEmail": email,
            "status": "invited",
            "invitedAt": now,
        }
    )
    return _resp(200, {"invited": invitee, "status": "invited"})


# --- POST /classes/remove --------------------------------------------------
def remove_member(email, role, event):
    if role != "profesor":
        return _resp(403, {"error": "Solo un profesor puede quitar miembros"})
    body = json.loads(event.get("body") or "{}")
    class_id = (body.get("classId") or "").strip()
    target = (body.get("email") or "").strip().lower()

    _, err = _owned_class(class_id, email)
    if err:
        return err

    table.delete_item(Key={"PK": f"CLASS#{class_id}", "SK": f"MEMBER#{target}"})
    table.delete_item(Key={"PK": f"USER#{target}", "SK": f"MEMBERSHIP#{class_id}"})
    return _resp(200, {"removed": target})


# --- POST /classes/accept (estudiante) -------------------------------------
def accept_invite(email, event):
    body = json.loads(event.get("body") or "{}")
    class_id = (body.get("classId") or "").strip()

    mem = table.get_item(Key={"PK": f"USER#{email}", "SK": f"MEMBERSHIP#{class_id}"}).get("Item")
    if not mem:
        return _resp(404, {"error": "No tienes una invitación a esta clase"})

    now = now_iso()
    # Activa la membresia en ambos lados (espejo del alumno y roster de la clase).
    table.update_item(
        Key={"PK": f"USER#{email}", "SK": f"MEMBERSHIP#{class_id}"},
        UpdateExpression="SET #s = :a, acceptedAt = :t",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":a": "active", ":t": now},
    )
    table.update_item(
        Key={"PK": f"CLASS#{class_id}", "SK": f"MEMBER#{email}"},
        UpdateExpression="SET #s = :a, acceptedAt = :t",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":a": "active", ":t": now},
    )
    return _resp(200, {"accepted": class_id, "name": mem.get("name")})


# --- GET /classes/detail?classId=... ---------------------------------------
def get_detail(email, role, event):
    qs = event.get("queryStringParameters") or {}
    class_id = (qs.get("classId") or "").strip()

    meta = table.get_item(Key={"PK": f"CLASS#{class_id}", "SK": "META"}).get("Item")
    if not meta:
        return _resp(404, {"error": "Clase no encontrada"})

    items = table.query(KeyConditionExpression=Key("PK").eq(f"CLASS#{class_id}")).get("Items", [])
    members = [
        {"email": i.get("email"), "status": i.get("status"), "invitedAt": i.get("invitedAt")}
        for i in items
        if i["SK"].startswith("MEMBER#")
    ]
    members.sort(key=lambda m: m.get("email") or "")
    tasks = [
        {
            "taskId": i.get("taskId"),
            "title": i.get("title"),
            "dueDate": i.get("dueDate"),
            "rubrica": i.get("rubrica"),
            "pesos": [float(p) for p in i.get("pesos", [])] if i.get("pesos") else None,
        }
        for i in items
        if i["SK"].startswith("TASK#")
    ]
    tasks.sort(key=lambda t: t.get("dueDate") or "")

    is_owner = meta.get("ownerEmail") == email
    if not is_owner:
        me = next(
            (m for m in members if m["email"] == email and m["status"] == "active"), None
        )
        if not me:
            return _resp(403, {"error": "No perteneces a esta clase"})
        # F5: adjunta a cada tarea el jobId de la entrega del alumno (si ya entregó).
        subs = table.query(
            KeyConditionExpression=Key("PK").eq(f"USER#{email}")
            & Key("SK").begins_with("SUBMISSION#")
        ).get("Items", [])
        submap = {s.get("taskId"): s.get("jobId") for s in subs}
        for t in tasks:
            t["submissionJobId"] = submap.get(t["taskId"])

    return _resp(
        200,
        {
            "classId": class_id,
            "name": meta.get("name"),
            "ownerEmail": meta.get("ownerEmail"),
            "isOwner": is_owner,
            "members": members,
            "tasks": tasks,
        },
    )


# --- Tareas (F4) -----------------------------------------------------------
def _to_decimal_list(raw):
    """Pesos -> lista de Decimal (acepta lista o string '30,20,...'). None si vacío/invalido."""
    if not raw:
        return None
    if isinstance(raw, str):
        raw = [p for p in raw.replace(";", ",").split(",") if p.strip()]
    if not isinstance(raw, (list, tuple)):
        return None
    out = []
    for p in raw:
        try:
            out.append(Decimal(str(float(p))))
        except (TypeError, ValueError):
            return None
    return out or None


def create_task(email, role, event):
    if role != "profesor":
        return _resp(403, {"error": "Solo un profesor puede crear tareas"})
    body = json.loads(event.get("body") or "{}")
    class_id = (body.get("classId") or "").strip()
    _, err = _owned_class(class_id, email)
    if err:
        return err

    title = (body.get("title") or "").strip()
    if not title:
        return _resp(400, {"error": "El título de la tarea es obligatorio"})

    task_id = "task-" + uuid.uuid4().hex[:8]
    item = {
        "PK": f"CLASS#{class_id}",
        "SK": f"TASK#{task_id}",
        "taskId": task_id,
        "title": title,
        "rubrica": (body.get("rubrica") or "").strip(),
        "dueDate": (body.get("dueDate") or "").strip(),
        "createdAt": now_iso(),
    }
    pesos = _to_decimal_list(body.get("pesos"))
    if pesos:
        item["pesos"] = pesos
    table.put_item(Item=item)
    return _resp(200, {"taskId": task_id, "title": title})


def update_task(email, role, event):
    if role != "profesor":
        return _resp(403, {"error": "Solo un profesor puede editar tareas"})
    body = json.loads(event.get("body") or "{}")
    class_id = (body.get("classId") or "").strip()
    task_id = (body.get("taskId") or "").strip()
    _, err = _owned_class(class_id, email)
    if err:
        return err

    existing = table.get_item(Key={"PK": f"CLASS#{class_id}", "SK": f"TASK#{task_id}"}).get("Item")
    if not existing:
        return _resp(404, {"error": "Tarea no encontrada"})

    title = (body.get("title") or existing.get("title") or "").strip()
    if not title:
        return _resp(400, {"error": "El título de la tarea es obligatorio"})

    item = {
        "PK": f"CLASS#{class_id}",
        "SK": f"TASK#{task_id}",
        "taskId": task_id,
        "title": title,
        "rubrica": body.get("rubrica", existing.get("rubrica", "")),
        "dueDate": body.get("dueDate", existing.get("dueDate", "")),
        "createdAt": existing.get("createdAt", now_iso()),
        "updatedAt": now_iso(),
    }
    pesos = _to_decimal_list(body.get("pesos")) if "pesos" in body else existing.get("pesos")
    if pesos:
        item["pesos"] = pesos
    table.put_item(Item=item)
    return _resp(200, {"updated": task_id})


def delete_task(email, role, event):
    if role != "profesor":
        return _resp(403, {"error": "Solo un profesor puede eliminar tareas"})
    body = json.loads(event.get("body") or "{}")
    class_id = (body.get("classId") or "").strip()
    task_id = (body.get("taskId") or "").strip()
    _, err = _owned_class(class_id, email)
    if err:
        return err
    table.delete_item(Key={"PK": f"CLASS#{class_id}", "SK": f"TASK#{task_id}"})
    return _resp(200, {"deleted": task_id})


# --- GET /tasks/submissions?classId=&taskId= (P2: vista del profesor) -------
def get_task_submissions(email, role, event):
    if role != "profesor":
        return _resp(403, {"error": "Solo el profesor ve las entregas"})
    qs = event.get("queryStringParameters") or {}
    class_id = (qs.get("classId") or "").strip()
    task_id = (qs.get("taskId") or "").strip()
    _, err = _owned_class(class_id, email)
    if err:
        return err

    subs = table.query(
        KeyConditionExpression=Key("PK").eq(f"CLASS#{class_id}")
        & Key("SK").begins_with(f"SUB#{task_id}#")
    ).get("Items", [])

    results = []
    for s in subs:
        job_id = s.get("jobId")
        item = {}
        if job_id and jobs_table is not None:
            jitems = jobs_table.query(
                KeyConditionExpression=Key("PK").eq(f"JOB#{job_id}")
            ).get("Items", [])
            ent = [i for i in jitems if i.get("SK", "").startswith("ITEM#")]
            item = ent[0] if ent else {}
        results.append({
            "studentEmail": s.get("studentEmail"),
            "jobId": job_id,
            "status": item.get("status", "PENDING"),
            "cumplimiento": item.get("cumplimiento"),
            "criterios": item.get("criterios", []),
            "criterios_ok": item.get("criterios_ok", []),
            "faltantes": item.get("faltantes", []),
            "sugerencias": item.get("sugerencias", []),
            "submittedAt": s.get("submittedAt"),
        })
    results.sort(key=lambda r: r.get("studentEmail") or "")

    done = [r for r in results if r["status"] == "DONE" and r["cumplimiento"] is not None]
    cumpls = [int(r["cumplimiento"]) for r in done]
    promedio = round(sum(cumpls) / len(cumpls)) if cumpls else 0
    dist = {"low": 0, "mid": 0, "high": 0}
    for c in cumpls:
        dist["high" if c >= 70 else "mid" if c >= 40 else "low"] += 1
    failc = {}
    for r in done:
        for c in r["criterios"]:
            if isinstance(c, dict) and not c.get("cumple"):
                n = str(c.get("criterio", "")).strip()
                if n:
                    failc[n] = failc.get(n, 0) + 1
    criterios_fallados = sorted(
        [{"criterio": k, "count": v} for k, v in failc.items()], key=lambda x: -x["count"]
    )
    stats = {
        "total": len(results),
        "evaluados": len(done),
        "promedio": promedio,
        "distribucion": dist,
        "criterios_fallados": criterios_fallados,
    }
    return _resp(200, {"submissions": results, "stats": stats})


# --- GET /tasks/attempts?taskId=... (G1: historial del propio alumno) -------
def get_task_attempts(email, event):
    qs = event.get("queryStringParameters") or {}
    task_id = (qs.get("taskId") or "").strip()
    items = table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{email}")
        & Key("SK").begins_with(f"SUBVER#{task_id}#")
    ).get("Items", [])

    attempts = []
    for it in items:
        job_id = it.get("jobId")
        cumplimiento, status = None, "PENDING"
        if job_id and jobs_table is not None:
            jit = jobs_table.query(
                KeyConditionExpression=Key("PK").eq(f"JOB#{job_id}")
            ).get("Items", [])
            ent = [i for i in jit if i.get("SK", "").startswith("ITEM#")]
            if ent:
                status = ent[0].get("status", "PENDING")
                cumplimiento = ent[0].get("cumplimiento")
        attempts.append(
            {
                "jobId": job_id,
                "submittedAt": it.get("submittedAt"),
                "status": status,
                "cumplimiento": cumplimiento,
            }
        )
    attempts.sort(key=lambda a: a.get("submittedAt") or "")
    return _resp(200, {"attempts": attempts})
