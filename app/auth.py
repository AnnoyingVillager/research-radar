from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

PASSWORD_ITERATIONS = 310_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return (
        f"pbkdf2_sha256${PASSWORD_ITERATIONS}$"
        f"{base64.urlsafe_b64encode(salt).decode()}$"
        f"{base64.urlsafe_b64encode(digest).decode()}"
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text)
        expected = base64.urlsafe_b64decode(digest_text)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def create_session(username: str, secret: str, max_age_seconds: int) -> str:
    payload = json.dumps(
        {"username": username, "expires": int(time.time()) + max_age_seconds},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = _b64encode(payload)
    signature = _sign(encoded, secret)
    return f"{encoded}.{signature}"


def verify_session(token: str, secret: str) -> str | None:
    try:
        encoded, signature = token.split(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(signature, _sign(encoded, secret)):
        return None
    try:
        payload: dict[str, Any] = json.loads(_b64decode(encoded))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("expires", 0)) < int(time.time()):
        return None
    username = str(payload.get("username", "")).strip()
    return username or None


def csrf_token(username: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        f"csrf:{username}".encode(),
        hashlib.sha256,
    ).hexdigest()


def valid_csrf(username: str, secret: str, value: str) -> bool:
    return hmac.compare_digest(csrf_token(username, secret), value)


def safe_next_url(value: str) -> str:
    if value.startswith("/") and not value.startswith("//"):
        return value
    return "/settings"


def _sign(encoded: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding).decode("utf-8")
