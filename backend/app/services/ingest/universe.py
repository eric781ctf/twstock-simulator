"""股票池的共用判斷：哪些代號算普通股、哪些股票已經下市。

回補、研究面板、訓練管線都要回答同樣的問題，放在一處才不會各寫一套、慢慢
長得不一樣。
"""

from sqlalchemy.orm import Session

from app.models import LISTING_DELISTED, Stock


def is_ordinary_stock(code: str) -> bool:
    """4 碼且不是 00 開頭。00 開頭是 ETF，5／6 碼是特別股、ETF、TDR 之類。"""
    return len(code) == 4 and code.isdigit() and not code.startswith("00")


def load_delisted_codes(db: Session) -> set[str]:
    """所有已標記下市的股票代號（不分市場）。"""
    return {c for (c,) in db.query(Stock.code).filter(Stock.listing_status == LISTING_DELISTED).all()}
