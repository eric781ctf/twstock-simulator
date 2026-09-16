"""下市股票的共用查詢。

「哪些代號算普通股」的定義只有一份，在 features/universe.py——這裡轉出來用。
先前這個檔案自己寫了一份寬鬆的版本（沒有排除 91 開頭的 TDR），兩份定義遲早
會分岔，而分岔的後果是母體在不同階段不一致，很難發現。
"""

from sqlalchemy.orm import Session

from app.models import LISTING_DELISTED, Stock
from app.services.features.universe import is_ordinary_stock

__all__ = ["is_ordinary_stock", "load_delisted_codes"]


def load_delisted_codes(db: Session) -> set[str]:
    """所有已標記下市的股票代號（不分市場）。"""
    return {c for (c,) in db.query(Stock.code).filter(Stock.listing_status == LISTING_DELISTED).all()}
