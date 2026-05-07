"""
auth_service.py — 帳號與 JWT 業務邏輯

功能：
- 建立新帳號（email 唯一性檢查 + bcrypt 密碼）
- 驗證帳號密碼
- 發放 access token + refresh token
- 改密碼（bump token_version 強制踢出所有舊 session）
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token


async def register_user(
    db: AsyncSession,
    email: str,
    password: str,
    display_name: str | None = None,
) -> tuple[User, str, str]:
    """
    建立新帳號。
    Returns: (user, access_token, refresh_token)
    Raises: HTTPException 400 if email already exists.
    """
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    access_token = create_access_token(str(user.id), token_version=user.token_version)
    refresh_token = create_refresh_token(str(user.id), token_version=user.token_version)
    return user, access_token, refresh_token


async def change_user_password(
    db: AsyncSession,
    user: User,
    current_password: str,
    new_password: str,
) -> tuple[str, str]:
    """改密碼 + bump token_version。回傳新的 (access, refresh) token。"""
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password incorrect",
        )

    user.password_hash = hash_password(new_password)
    user.token_version = (user.token_version or 0) + 1
    await db.commit()
    await db.refresh(user)

    access_token = create_access_token(str(user.id), token_version=user.token_version)
    refresh_token = create_refresh_token(str(user.id), token_version=user.token_version)
    return access_token, refresh_token


async def reset_password_with_token(
    db: AsyncSession,
    user: User,
    new_password: str,
) -> None:
    """重設密碼（已驗證 token 後呼叫）。bump token_version 讓 reset token 一次性失效。"""
    user.password_hash = hash_password(new_password)
    user.token_version = (user.token_version or 0) + 1
    await db.commit()


async def authenticate_user(
    db: AsyncSession,
    email: str,
    password: str,
) -> tuple[User, str, str]:
    """
    驗證帳號密碼。
    Returns: (user, access_token, refresh_token)
    Raises: HTTPException 401 if credentials invalid or account disabled.
    """
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    access_token = create_access_token(str(user.id), token_version=user.token_version)
    refresh_token = create_refresh_token(str(user.id), token_version=user.token_version)
    return user, access_token, refresh_token
