from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.security import verify_token_payload
from app.database import get_db
from app.models.user import User

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    payload = verify_token_payload(token, token_type="access")

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    token_tv = payload.get("tv", 0)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # token_version 比對：改密碼或強制登出後 user.token_version 會 +1，舊 token 失效
    if token_tv != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token revoked, please login again",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_admin(
    user: User = Depends(get_current_user),
) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


async def require_search_permission(
    user: User = Depends(get_current_user),
) -> User:
    """守鋼筋盤價助理 (/api/search/*) 的所有 endpoint。

    Admin 不自動享有 search 權限——避免「admin 就有所有功能」這個假設；admin
    要用 search 也得在 admin/users 頁打開自己的 search_enabled。

    權限即時生效：get_current_user 每次 hit DB 重抓 User，不從 JWT payload 讀。
    """
    if not user.search_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="搜尋功能未開通，請聯絡管理員",
        )
    return user
