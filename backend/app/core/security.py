from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode(), salt).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def create_access_token(
    subject: str,
    token_version: int = 0,
    extra: dict[str, Any] | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": subject, "exp": expire, "type": "access", "tv": token_version}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_refresh_token(subject: str, token_version: int = 0) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    payload = {"sub": subject, "exp": expire, "type": "refresh", "tv": token_version}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_password_reset_token(subject: str, token_version: int) -> str:
    """1-hour reset token. tv 機制保證單次使用：重設後 tv +1 → 舊 token 自動失效。"""
    expire = datetime.now(timezone.utc) + timedelta(hours=1)
    payload = {"sub": subject, "exp": expire, "type": "reset", "tv": token_version}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])


def verify_token_payload(token: str, token_type: str = "access") -> dict[str, Any] | None:
    """驗證簽章 + type，回傳完整 payload 供呼叫端做 tv 比對。"""
    try:
        payload = decode_token(token)
        if payload.get("type") != token_type:
            return None
        return payload
    except JWTError:
        return None


def verify_token(token: str, token_type: str = "access") -> str | None:
    """Legacy thin wrapper：只回傳 sub。新程式請改用 verify_token_payload。"""
    payload = verify_token_payload(token, token_type)
    return payload.get("sub") if payload else None
