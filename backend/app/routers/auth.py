from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.services.auth import create_access_token, get_current_user, hash_password, verify_password
from app.services.matching import create_account_for_user

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginPayload(BaseModel):
    username: str = Field(min_length=3, max_length=30)
    password: str = Field(min_length=6, max_length=100)


class RegisterPayload(LoginPayload):
    nickname: str = Field(min_length=1, max_length=50)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    nickname: str


@router.post("/register", response_model=TokenOut, status_code=201)
def register(payload: RegisterPayload, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="帳號已被使用")

    nickname = payload.nickname.strip()
    if not nickname:
        raise HTTPException(status_code=422, detail="暱稱不可為空白")

    user = User(username=payload.username, nickname=nickname, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    create_account_for_user(db, user.id)

    token = create_access_token(user.id)
    return TokenOut(access_token=token, username=user.username, nickname=user.nickname)


@router.post("/login", response_model=TokenOut)
def login(payload: LoginPayload, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")

    token = create_access_token(user.id)
    return TokenOut(access_token=token, username=user.username, nickname=user.nickname)


class MeOut(BaseModel):
    id: int
    username: str
    nickname: str


@router.get("/me", response_model=MeOut)
def me(current_user: User = Depends(get_current_user)):
    return MeOut(id=current_user.id, username=current_user.username, nickname=current_user.nickname)
