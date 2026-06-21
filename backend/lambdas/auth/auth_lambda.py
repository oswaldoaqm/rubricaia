import os
import sys
import json
from datetime import datetime, timezone

import boto3

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "common"))
from authlib import jwt_encode, hash_password, verify_password  # noqa: E402

LMS_TABLE = os.environ["LMS_TABLE"]
ALLOWED_DOMAIN = os.environ.get("ALLOWED_DOMAIN", "utec.edu.pe").lower().lstrip("@")
TEACHER_EMAILS = {
    e.strip().lower() for e in os.environ.get("TEACHER_EMAILS", "").split(",") if e.strip()
}

ddb = boto3.resource("dynamodb")
table = ddb.Table(LMS_TABLE)

CORS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
}


def _resp(code, body):
    return {"statusCode": code, "headers": CORS, "body": json.dumps(body, ensure_ascii=False)}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def role_for(email):
    return "profesor" if email in TEACHER_EMAILS else "estudiante"


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "POST")
    path = event.get("rawPath", "")
    try:
        if method == "OPTIONS":
            return _resp(200, {"ok": True})
        if path.endswith("/signup"):
            return signup(event)
        if path.endswith("/login"):
            return login(event)
        return _resp(404, {"error": "ruta no encontrada"})
    except Exception as e:  # noqa: BLE001
        return _resp(500, {"error": str(e)})


def _profile_response(item):
    user = {"email": item["email"], "role": item["role"], "name": item.get("name", "")}
    token = jwt_encode(user)
    return _resp(200, {"token": token, "user": user})


def signup(event):
    body = json.loads(event.get("body") or "{}")
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    name = (body.get("name") or "").strip()

    if "@" not in email or not email.endswith("@" + ALLOWED_DOMAIN):
        return _resp(400, {"error": f"Solo se permiten correos @{ALLOWED_DOMAIN}"})
    if len(password) < 6:
        return _resp(400, {"error": "La contraseña debe tener al menos 6 caracteres"})

    existing = table.get_item(Key={"PK": f"USER#{email}", "SK": "PROFILE"}).get("Item")
    if existing:
        return _resp(409, {"error": "Ya existe una cuenta con ese correo"})

    salt, pw_hash = hash_password(password)
    role = role_for(email)
    item = {
        "PK": f"USER#{email}",
        "SK": "PROFILE",
        "email": email,
        "name": name,
        "role": role,
        "salt": salt,
        "pw_hash": pw_hash,
        "createdAt": now_iso(),
    }
    table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
    return _profile_response(item)


def login(event):
    body = json.loads(event.get("body") or "{}")
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    item = table.get_item(Key={"PK": f"USER#{email}", "SK": "PROFILE"}).get("Item")
    if not item or not verify_password(password, item.get("salt", ""), item.get("pw_hash", "")):
        return _resp(401, {"error": "Correo o contraseña incorrectos"})

    role = role_for(email)
    if role != item.get("role"):
        table.update_item(
            Key={"PK": f"USER#{email}", "SK": "PROFILE"},
            UpdateExpression="SET #r = :r",
            ExpressionAttributeNames={"#r": "role"},
            ExpressionAttributeValues={":r": role},
        )
        item["role"] = role
    return _profile_response(item)
