from fastapi import APIRouter, Depends, HTTPException, Request, Response, Cookie, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.dependencies import get_current_user
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    verify_token_payload,
)
from app.database import get_db
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
)
from app.services.auth_service import (
    authenticate_user,
    change_user_password,
    register_user,
    reset_password_with_token,
)
from app.services.email_service import send_password_reset_email
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_KEY = "refresh_token"
COOKIE_MAX_AGE = settings.refresh_token_expire_days * 24 * 60 * 60


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_KEY,
        value=token,
        httponly=True,
        secure=settings.app_env != "development",
        samesite="strict",
        max_age=COOKIE_MAX_AGE,
        path="/api/auth",
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    _, access_token, refresh_token = await register_user(
        db, body.email, body.password, body.display_name
    )
    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(access_token=access_token)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    _, access_token, refresh_token = await authenticate_user(db, body.email, body.password)
    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_KEY),
    db: AsyncSession = Depends(get_db),
):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")

    payload = verify_token_payload(refresh_token, token_type="refresh")
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user_id = payload.get("sub")
    token_tv = payload.get("tv", 0)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    if token_tv != user.token_version:
        raise HTTPException(status_code=401, detail="Token revoked, please login again")

    access_token = create_access_token(user_id, token_version=user.token_version)
    new_refresh = create_refresh_token(user_id, token_version=user.token_version)
    _set_refresh_cookie(response, new_refresh)
    return TokenResponse(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(response: Response):
    response.delete_cookie(key=REFRESH_COOKIE_KEY, path="/api/auth")
    return {"message": "Logged out"}


@router.post("/change-password", response_model=TokenResponse)
async def change_password(
    body: ChangePasswordRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """改密碼。成功後 token_version +1 → 所有舊 token（含本次發出的）失效，並回傳新的 access token + 重設 refresh cookie。"""
    access_token, refresh_token = await change_user_password(
        db, current_user, body.current_password, body.new_password
    )
    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(access_token=access_token)


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """寄重設連結到使用者 email。為避免帳號 enumeration，無論 email 是否存在都回 200。"""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user and user.is_active:
        token = create_password_reset_token(str(user.id), token_version=user.token_version)
        reset_link = f"{settings.frontend_url.rstrip('/')}/reset-password?token={token}"
        try:
            await send_password_reset_email(user.email, reset_link, user.display_name)
        except Exception as e:
            # 寄信失敗不對外洩漏，但 log 出來
            import logging
            logging.getLogger("app.auth").error("send reset email failed: %s", e)

    return {"message": "If the email exists, a reset link has been sent."}


@router.post("/reset-password", response_model=TokenResponse)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """用 reset token 重設密碼。token 為一小時內有效的單次使用 JWT（透過 token_version 機制保證單次使用）。"""
    payload = verify_token_payload(body.token, token_type="reset")
    if not payload:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user_id = payload.get("sub")
    token_tv = payload.get("tv", 0)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    if token_tv != user.token_version:
        # token 已被使用過或使用者已改過密碼
        raise HTTPException(status_code=400, detail="Reset token already used or invalidated")

    await reset_password_with_token(db, user, body.new_password)

    # 重設後直接登入：發新 token + cookie
    access_token = create_access_token(str(user.id), token_version=user.token_version)
    new_refresh = create_refresh_token(str(user.id), token_version=user.token_version)
    _set_refresh_cookie(response, new_refresh)
    return TokenResponse(access_token=access_token)


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)
