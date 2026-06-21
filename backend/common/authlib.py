import os
import json
import time
import hmac
import hashlib
import base64

JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_TTL = int(os.environ.get("JWT_TTL", str(12 * 3600)))


# --- base64url -------------------------------------------------------------
def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# --- JWT HS256 -------------------------------------------------------------
def jwt_encode(claims: dict, secret: str = None, ttl: int = None) -> str:
    secret = secret or JWT_SECRET
    ttl = JWT_TTL if ttl is None else ttl
    header = {"alg": "HS256", "typ": "JWT"}
    payload = dict(claims)
    now = int(time.time())
    payload.setdefault("iat", now)
    payload.setdefault("exp", now + ttl)
    h = _b64u(json.dumps(header, separators=(",", ":")).encode())
    p = _b64u(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{h}.{p}".encode()
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{h}.{p}.{_b64u(sig)}"


def jwt_decode(token: str, secret: str = None) -> dict:
    secret = secret or JWT_SECRET
    try:
        h, p, s = token.split(".")
    except (ValueError, AttributeError):
        raise ValueError("token malformado")
    signing_input = f"{h}.{p}".encode()
    expected = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(_b64u(expected), s):
        raise ValueError("firma invalida")
    payload = json.loads(_b64u_decode(p))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("token expirado")
    return payload


# --- contraseñas (PBKDF2-HMAC-SHA256) --------------------------------------
def hash_password(password: str, salt: str = None):
    if salt is None:
        salt = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000)
    return salt, dk.hex()


def verify_password(password: str, salt: str, expected_hex: str) -> bool:
    _, calc = hash_password(password, salt)
    return hmac.compare_digest(calc, expected_hex)


# --- extraer claims desde un evento de API Gateway -------------------------
def auth_from_event(event):
    headers = event.get("headers") or {}
    raw = headers.get("authorization") or headers.get("Authorization") or ""
    if not raw.lower().startswith("bearer "):
        return None
    try:
        return jwt_decode(raw[7:].strip())
    except Exception:
        return None
