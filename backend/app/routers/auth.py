from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.services.platform.auth import create_access_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# 只有登入與「我是誰」。註冊端點隨舊的多使用者模擬器一起下線——這個系統只有
# 管理員會登入，帳號由 ensure_admin_user 在啟動時建立。


class LoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=30)
    password: str = Field(min_length=1, max_length=100)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    nickname: str
    is_admin: bool


@router.post("/login", response_model=TokenOut)
def login(payload: LoginPayload, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")
    if user.frozen_until is not None and user.frozen_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=403, detail=f"帳號已被凍結，將於 {user.frozen_until.isoformat()} 解除")

    token = create_access_token(user.id)
    return TokenOut(access_token=token, username=user.username, nickname=user.nickname, is_admin=user.is_admin)


class MeOut(BaseModel):
    id: int
    username: str
    nickname: str
    is_admin: bool


@router.get("/me", response_model=MeOut)
def me(current_user: User = Depends(get_current_user)):
    return MeOut(id=current_user.id, username=current_user.username, nickname=current_user.nickname, is_admin=current_user.is_admin)
