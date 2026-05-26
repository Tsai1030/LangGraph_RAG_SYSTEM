"""
google_oauth_service.py — Google ID token 驗證 + 帳號 lookup/建立/綁定。

GIS (Google Identity Services) flow：
1. 前端用 GoogleLogin 按鈕 → Google 回傳一個 ID token (JWT) 給前端
2. 前端把 ID token POST 給後端 /auth/google
3. 後端用 google-auth 套件驗 ID token 簽章 + audience (aud == 我們的 client_id)
4. 驗證通過 → 拿到 payload (sub, email, name, picture, hd, email_verified)
5. 依 sub / email lookup 既有 user，找不到就在公司網域允許下新建

我們不需要 client_secret — ID token flow 的驗證材料來自 Google 的公鑰，前端拿到的
token 本身就足以驗證使用者身份，不會有「需要 server 換 access token」的步驟。
"""
from __future__ import annotations

import logging

from fastapi import HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import create_access_token, create_refresh_token
from app.models.user import User

logger = logging.getLogger("app.auth.google")

# 模組級單例，避免每次驗證都建新的 transport
_request = google_requests.Request()


def _domain_of(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def _enforce_domain(email: str, hd: str | None) -> None:
    """強制 email 屬於公司網域。hd (hosted domain) 是 Workspace 帳號才有的 claim，
    對個人 Gmail 為 None — 所以以 email suffix 為主要判斷，hd 為輔助。"""
    allowed = settings.allowed_email_domain.strip().lower()
    if not allowed:
        return  # 未設定 = 不限制（dev 用）

    actual = _domain_of(email)
    if actual != allowed:
        logger.warning("Google login blocked: email domain %s != allowed %s", actual, allowed)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"僅允許 @{allowed} 的公司帳號登入",
        )
    # hd 若存在但不符合，視為 token 與設定不一致，拒絕
    if hd and hd.lower() != allowed:
        logger.warning("Google login blocked: hd claim %s != allowed %s", hd, allowed)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"僅允許 @{allowed} 的公司帳號登入",
        )


def verify_google_id_token(credential: str) -> dict:
    """驗證 Google ID token 並回傳 payload。失敗一律 401。

    google-auth 會檢：簽章、exp、iss (accounts.google.com)、aud (== client_id)
    """
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GOOGLE_CLIENT_ID 未設定",
        )
    try:
        payload = google_id_token.verify_oauth2_token(
            credential, _request, settings.google_client_id
        )
    except ValueError as e:
        # 簽章錯、過期、aud 不符都會落這
        logger.warning("Google ID token verify failed: %s", e)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google credential")

    if not payload.get("email_verified"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google email not verified")

    return payload


async def login_or_register_with_google(
    db: AsyncSession,
    credential: str,
) -> tuple[User, str, str, bool]:
    """
    主流程：驗 token → 查/建 User → 發 JWT。
    Returns: (user, access_token, refresh_token, is_new_user)

    查找順序：
    1. 先用 google_sub 找（最穩，不會被 email 改變影響）
    2. 找不到，用 email 找 — 找到代表是既有密碼帳號，自動把 google_sub 補上（首次登入即綁定）
    3. 還找不到 → 在公司網域允許下新建帳號
    """
    payload = verify_google_id_token(credential)

    sub: str = payload["sub"]
    email: str = payload["email"]
    name: str | None = payload.get("name")
    picture: str | None = payload.get("picture")
    hd: str | None = payload.get("hd")

    _enforce_domain(email, hd)

    # 1) google_sub lookup
    result = await db.execute(select(User).where(User.google_sub == sub))
    user = result.scalar_one_or_none()

    is_new_user = False

    if not user:
        # 2) email lookup — 既有密碼帳號首次用 Google 登入，自動綁
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            user.google_sub = sub
            if not user.avatar_url and picture:
                user.avatar_url = picture
            await db.commit()
            await db.refresh(user)
            logger.info("Auto-linked Google sub=%s to existing user email=%s", sub, email)
        else:
            # 3) 新建帳號（純 Google，無 password_hash）
            user = User(
                email=email,
                password_hash=None,
                display_name=name,
                google_sub=sub,
                avatar_url=picture,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            is_new_user = True
            logger.info("New user created via Google: email=%s sub=%s", email, sub)

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    access_token = create_access_token(str(user.id), token_version=user.token_version)
    refresh_token = create_refresh_token(str(user.id), token_version=user.token_version)
    return user, access_token, refresh_token, is_new_user


async def link_google_to_current_user(
    db: AsyncSession,
    user: User,
    credential: str,
) -> User:
    """已登入使用者綁定 Google 帳號（記下 google_sub）。

    規則：
    - Google email 必須跟當前 user.email 相同（否則就變成一個 Google 帳號可登入別人）
    - 且必須是公司網域
    - 該 Google sub 不能已綁在別的 user 上
    """
    payload = verify_google_id_token(credential)
    sub: str = payload["sub"]
    email: str = payload["email"]
    hd: str | None = payload.get("hd")

    _enforce_domain(email, hd)

    if email.lower() != user.email.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google 帳號 email ({email}) 必須與您的登入 email ({user.email}) 相同",
        )

    # 該 sub 不能已綁別人
    result = await db.execute(select(User).where(User.google_sub == sub))
    other = result.scalar_one_or_none()
    if other and other.id != user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="此 Google 帳號已被綁定到其他使用者",
        )

    user.google_sub = sub
    if not user.avatar_url and payload.get("picture"):
        user.avatar_url = payload["picture"]
    await db.commit()
    await db.refresh(user)
    return user


async def unlink_google_from_current_user(db: AsyncSession, user: User) -> User:
    """解除綁定。若使用者沒有密碼（純 Google 帳號）則禁止 — 否則會把自己鎖在外面。"""
    if not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="您的帳號沒有密碼，無法解除 Google 綁定（否則將無法登入）",
        )
    user.google_sub = None
    await db.commit()
    await db.refresh(user)
    return user
