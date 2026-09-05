from pydantic import BaseModel, EmailStr
from app.models.user import UserRole


class UserRegister(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    role: UserRole = UserRole.PMU_INSPECTOR
    organization: str | None = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: str | None = None  # user id
    role: str | None = None
