import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Account, Order, Position, Trade, User, WatchlistItem
from app.services.auth import hash_password
from app.services.matching import TAIPEI_TZ, create_account_for_user

logger = logging.getLogger(__name__)


def ensure_admin_user(db: Session) -> None:
    """管理員帳號不走一般註冊流程，而是每次啟動都用 .env 裡的帳密同步一次——
    密碼改了 .env 重啟後端就會生效，帳號不存在就自動建立，不需要額外的管理介面。
    也順便給一個一般交易帳戶：其他頁面（首頁、交易…）都預設每個使用者一定有
    Account，沒有的話一進去就會噴 500，讓管理員一樣有帳戶最簡單，之後 admin
    專屬的加值/歸零操作已經用 is_admin 過濾掉管理員自己這筆了。"""
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

    if db.query(Account).filter(Account.user_id == user.id).first() is None:
        create_account_for_user(db, user.id)


def list_all_accounts(db: Session) -> list[tuple[User, Account | None]]:
    users = db.query(User).order_by(User.created_at.asc()).all()
    return [(u, db.query(Account).filter(Account.user_id == u.id).first()) for u in users]


class AdminActionError(Exception):
    pass


def reset_all_cash(db: Session, amount: float) -> int:
    accounts = db.query(Account).join(User, Account.user_id == User.id).filter(User.is_admin.is_(False)).all()
    for account in accounts:
        account.cash_balance = amount
    db.commit()
    return len(accounts)


def add_cash_to_all(db: Session, amount: float) -> int:
    accounts = db.query(Account).join(User, Account.user_id == User.id).filter(User.is_admin.is_(False)).all()
    for account in accounts:
        account.cash_balance = float(account.cash_balance) + amount
    db.commit()
    return len(accounts)


def delete_account(db: Session, user_id: int) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise AdminActionError("使用者不存在")
    if user.is_admin:
        raise AdminActionError("無法刪除管理員帳號")

    account = db.query(Account).filter(Account.user_id == user_id).first()
    if account is not None:
        db.query(Trade).filter(Trade.account_id == account.id).delete(synchronize_session=False)
        db.query(Order).filter(Order.account_id == account.id).delete(synchronize_session=False)
        db.query(Position).filter(Position.account_id == account.id).delete(synchronize_session=False)
        db.query(WatchlistItem).filter(WatchlistItem.account_id == account.id).delete(synchronize_session=False)
        db.delete(account)
    db.delete(user)
    db.commit()


def freeze_account(db: Session, user_id: int, hours: int = 24) -> datetime:
    user = db.get(User, user_id)
    if user is None:
        raise AdminActionError("使用者不存在")
    if user.is_admin:
        raise AdminActionError("無法凍結管理員帳號")

    frozen_until = datetime.now(TAIPEI_TZ) + timedelta(hours=hours)
    user.frozen_until = frozen_until
    db.commit()
    return frozen_until
