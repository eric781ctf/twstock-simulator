import logging
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="請先登入")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="登入已過期，請重新登入")

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="使用者不存在")
    if user.frozen_until is not None and user.frozen_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=403, detail=f"帳號已被凍結，將於 {user.frozen_until.isoformat()} 解除")
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="僅限管理員使用")
    return current_user


def ensure_admin_user(db: Session) -> None:
    """每次啟動都用 .env 裡的帳密同步管理員帳號。

    刻意不走註冊流程：這個系統只有管理員會登入，密碼改了 .env 重啟就生效，
    帳號不存在就自動建立，不需要額外的管理介面。

    先前還會順便建一個交易帳戶（Account），那是舊的多使用者模擬器留下的——
    當時每個頁面都預設使用者一定有 Account。那些頁面已經下線，所以不再建立。
    """
    user = db.query(User).filter(User.username == settings.admin_username).first()
    if user is None:
        user = User(
            username=settings.admin_username,
            nickname="管理員",
            password_hash=hash_password(settings.admin_password),
            is_admin=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info("ensure_admin_user: 已建立管理員帳號 %s", settings.admin_username)
    else:
        user.is_admin = True
        user.password_hash = hash_password(settings.admin_password)
        db.commit()
