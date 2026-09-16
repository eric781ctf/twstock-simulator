"""選股母體：哪些證券算「普通股」，以及哪些價格變動不是真的行情。

daily_bars 裡的上市證券不只普通股，還有兩百多檔 ETF（含 00631L 這類槓桿／
反向型）、ETN（02 開頭）、特別股（2881A 這類 5 碼）、TDR（91 開頭）。它們
混進來會出三種問題：

1. 合成大盤是全市場等權平均，ETF 一檔一票，會把「大盤」拉成一籃子 ETF 的走勢
2. 槓桿型 ETF 反分割一天 -96%，這種 label 對迴歸頭是極端離群值
3. 模型真的會挑到槓桿 ETF 進前 10 名——那不是這個系統要做的選股

所以特徵、大盤、label、選股、每日推論全部用同一個母體，定義只放這裡一份。

**只看代號，不看產業別欄位。** 產業別是另一條同步管線寫的，沒同步到就是
NULL；代號規則是 TWSE 編碼本身的約定，不依賴任何額外資料。
"""

import re

# 4 碼、第一碼不是 0（00 開頭是 ETF）、不是 91 開頭（91xx 是 TDR 存託憑證）。
# 5／6 碼一律排除：特別股、ETF、ETN、TDR。
#
# 同一個 pattern 同時給 Python re 跟 PostgreSQL 的 ~ 用。兩邊都支援
# (?!…) 否定前瞻，寫法完全一樣，所以 SQL 端的篩選跟這裡的判斷不會分岔。
ORDINARY_STOCK_CODE_PATTERN = r"^(?!91)[1-9][0-9]{3}$"
_ORDINARY_STOCK_CODE = re.compile(ORDINARY_STOCK_CODE_PATTERN)

# TWSE 單日漲跌幅上限是 ±10%。收盤相對前一根 K 棒超過這個幅度，就不是市場
# 行情能產生的變動，而是價格基準變了：減資、反分割、除權息、停牌後復牌，
# 或長時間缺資料後接上的那一根。多留 0.5 個百分點給跳動檔位的進位誤差。
#
# 已知的誤判：新股上市前五日沒有漲跌幅限制，那幾天的大漲大跌是真的；除息日
# 跌停（-10% 再疊上息值）也會超過門檻。前者落在暖身期內，幾乎不會進到 label
# 視窗；後者的 label 本來就被未還原的息值污染，丟掉不算損失。
PRICE_JUMP_PERCENT = 10.5


def is_ordinary_stock(code: str) -> bool:
    return _ORDINARY_STOCK_CODE.match(code) is not None


def is_price_jump(previous_close: float, close: float) -> bool:
    """這一根收盤相對前一根收盤的變動，是否超出漲跌幅限制能產生的範圍。"""
    if not previous_close:
        return False
    return abs(close - previous_close) / previous_close * 100 > PRICE_JUMP_PERCENT
