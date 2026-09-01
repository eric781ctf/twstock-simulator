from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppConfig

_ROW_ID = 1


def ensure_app_config(db: Session) -> None:
    """`app_config` 只會有這一列，沒有就用 .env 裡的 TWSTOCK_INITIAL_CASH 當第一次的預設值。
    之後管理員在後台改的值都存在這裡，不會被 .env 或重開機蓋掉。"""
    if db.get(AppConfig, _ROW_ID) is None:
        db.add(AppConfig(id=_ROW_ID, default_initial_cash=settings.initial_cash))
        db.commit()


def get_default_initial_cash(db: Session) -> float:
    row = db.get(AppConfig, _ROW_ID)
    return float(row.default_initial_cash) if row else settings.initial_cash


def set_default_initial_cash(db: Session, amount: float) -> float:
    row = db.get(AppConfig, _ROW_ID)
    if row is None:
        row = AppConfig(id=_ROW_ID, default_initial_cash=amount)
        db.add(row)
    else:
        row.default_initial_cash = amount
    db.commit()
    return float(row.default_initial_cash)
