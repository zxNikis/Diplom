import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_site_token(
    *,
    telegram_user_id: int,
    username: str | None,
    secret: str,
    ttl_days: int,
) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)
    payload = {
        "telegram_user_id": int(telegram_user_id),
        "username": username,
        "exp": int(expires_at.timestamp()),
    }
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload_part = _b64encode(payload_json)
    signature = hmac.new(secret.encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_part}.{_b64encode(signature)}"


def verify_site_token(token: str, *, secret: str) -> dict[str, Any]:
    if not token or "." not in token:
        raise HTTPException(status_code=401, detail="Некорректная ссылка сайта")

    payload_part, signature_part = token.split(".", 1)
    expected_signature = hmac.new(secret.encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256).digest()
    try:
        incoming_signature = _b64decode(signature_part)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Некорректная подпись ссылки сайта") from exc

    if not hmac.compare_digest(incoming_signature, expected_signature):
        raise HTTPException(status_code=401, detail="Подпись ссылки сайта не совпадает")

    try:
        payload = json.loads(_b64decode(payload_part).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Некорректные данные ссылки сайта") from exc

    expires_at = int(payload.get("exp") or 0)
    if expires_at < int(datetime.now(timezone.utc).timestamp()):
        raise HTTPException(status_code=401, detail="Срок действия ссылки сайта истек")

    telegram_user_id = payload.get("telegram_user_id")
    if not telegram_user_id:
        raise HTTPException(status_code=401, detail="В ссылке сайта нет пользователя")

    return payload
