from pydantic import BaseModel, EmailStr, field_validator


def _password_must_be_strong(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters")
    return v


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str | None = None

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        return _password_must_be_strong(v)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def new_password_strong(cls, v: str) -> str:
        return _password_must_be_strong(v)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def new_password_strong(cls, v: str) -> str:
        return _password_must_be_strong(v)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str | None
    avatar_url: str | None = None
    role: str = "user"
    search_enabled: bool = False
    # 給前端判斷「設定頁」是否要顯示「綁定 Google」按鈕用
    has_password: bool = False
    google_linked: bool = False

    model_config = {"from_attributes": True}


class GoogleAuthRequest(BaseModel):
    """前端 GIS 拿到 ID token 後 POST 過來。"""
    credential: str  # Google ID token (JWT)
