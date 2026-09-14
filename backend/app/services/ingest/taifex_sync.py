"""台灣期貨交易所（TAIFEX）行情同步。

存在的理由只有一個：**夜盤**。期交所的盤後交易時段是 15:00 到隔日 05:00，
完整涵蓋美股盤中。台股現貨在那段時間休市，所以「美股隔夜怎麼走」要等到隔天
09:00 才會反映在現貨價格上——但台指期夜盤是即時的。

那段價差（夜盤收盤 vs 前一日日盤收盤）就是「台灣投資人用台灣的商品，對美股
隔夜走勢的完整定價」，而且在台股開盤前 4 小時就已經確定。

**日期歸屬**（這是最容易寫錯的地方）：期交所把「D−1 日 15:00 開始、D 日
05:00 結束」的那一節標成日期 **D**。驗證方式是比對盤後開盤價跟前後日的日盤
收盤價，2020 與 2024 抽樣都顯示它貼近前一日日盤收盤（差 0~16 點），而距同日
日盤收盤動輒 100~300 點。

資料來源是期交所的下載端點，回傳 Big5 編碼的 CSV。**一次最多查一個月**——
三個月的區間會回一頁空白（614 bytes），所以回補是逐月進行。
"""

import csv
import io
import logging
from datetime import date, timedelta

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import FuturesDaily
from app.services.ingest.stock_sync import _throttled_sleep

logger = logging.getLogger(__name__)

DOWNLOAD_URL = "https://www.taifex.com.tw/cht/3/futDataDown"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    # 不帶 Referer 會被擋
    "Referer": "https://www.taifex.com.tw/cht/3/futDataDown",
}

# TX=臺股期貨（大盤）、TE=電子期貨。電子期對「美股半導體隔夜走勢」的敏感度
# 比大盤高，兩個一起存才分得出「整體」與「電子」的差異
CONTRACTS = ("TX", "TE")

SESSION_DAY = "day"
SESSION_NIGHT = "night"
_SESSION_MAP = {"一般": SESSION_DAY, "盤後": SESSION_NIGHT}

# 每次請求之間的間隔。一個月一次請求，整段六年也才八十幾次，
# 沒有理由壓榨對方
REQUEST_DELAY_SECONDS = 4.0


def _month_ranges(start: date, end: date) -> list[tuple[date, date]]:
    """把區間切成逐月的 (起, 迄)。端點一次最多吃一個月。"""
    out: list[tuple[date, date]] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        nxt = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
        out.append((max(cursor, start), min(nxt - timedelta(days=1), end)))
        cursor = nxt
    return out


def _to_int(value: str) -> int | None:
    value = (value or "").strip().replace(",", "")
    if not value or value in {"-", "NULL"}:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _parse(text: str, contract: str) -> dict[tuple[date, str], dict]:
    """把 CSV 解析成 {(日期, 時段): 近月那一列}。

    同一天同一個時段會有多個到期月份（近月、次月、週選、價差），只留**近月**——
    遠月流動性低，價格代表性差；價差組合的「到期月份」不是純數字，順手濾掉。
    """
    best: dict[tuple[date, str], tuple[str, dict]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        if (row.get("契約") or "").strip() != contract:
            continue
        month = (row.get("到期月份(週別)") or "").strip()
        if not month.isdigit():
            continue  # 週選或價差組合
        session = _SESSION_MAP.get((row.get("交易時段") or "").strip())
        if session is None:
            continue
        try:
            trade_date = date(*(int(p) for p in row["交易日期"].split("/")))
        except (KeyError, ValueError):
            continue
        close = _to_int(row.get("收盤價"))
        if close is None:
            continue  # 該時段沒有成交

        key = (trade_date, session)
        if key in best and best[key][0] <= month:
            continue
        best[key] = (
            month,
            {
                "contract": contract,
                "trade_date": trade_date,
                "session": session,
                "open": float(_to_int(row.get("開盤價")) or close),
                "high": float(_to_int(row.get("最高價")) or close),
                "low": float(_to_int(row.get("最低價")) or close),
                "close": float(close),
                "volume": _to_int(row.get("成交量")) or 0,
                "open_interest": _to_int(row.get("未沖銷契約數")),
            },
        )
    return {k: v[1] for k, v in best.items()}


async def _fetch_month(client: httpx.AsyncClient, contract: str, start: date, end: date) -> dict:
    response = await client.post(
        DOWNLOAD_URL,
        data={
            "down_type": "1",
            "commodity_id": contract,
            "queryStartDate": start.strftime("%Y/%m/%d"),
            "queryEndDate": end.strftime("%Y/%m/%d"),
        },
    )
    response.raise_for_status()
    # 期交所回 Big5；errors="replace" 是因為偶爾夾雜壞字元，不該讓整個月失敗
    return _parse(response.content.decode("big5", errors="replace"), contract)


def _store(db: Session, parsed: dict) -> int:
    if not parsed:
        return 0
    existing = {
        (r.contract, r.trade_date, r.session)
        for r in db.query(FuturesDaily.contract, FuturesDaily.trade_date, FuturesDaily.session)
        .filter(FuturesDaily.trade_date.in_({d for d, _ in parsed}))
        .all()
    }
    written = 0
    for item in parsed.values():
        key = (item["contract"], item["trade_date"], item["session"])
        if key in existing:
            continue
        db.add(FuturesDaily(**item))
        written += 1
    db.commit()
    return written


async def backfill(db: Session, start: date, end: date) -> dict:
    """逐月回補 [start, end]。已經有的日期會跳過，重跑不浪費請求。"""
    total = 0
    months = _month_ranges(start, end)
    logger.info(
        "taifex backfill: %s ~ %s 共 %d 個月 × %d 種契約", start, end, len(months), len(CONTRACTS)
    )

    async with httpx.AsyncClient(timeout=60, follow_redirects=True, headers=HEADERS) as client:
        for i, (m_start, m_end) in enumerate(months):
            for contract in CONTRACTS:
                if i > 0 or contract != CONTRACTS[0]:
                    await _throttled_sleep(REQUEST_DELAY_SECONDS, "期交所每次下載之間的間隔")
                try:
                    parsed = await _fetch_month(client, contract, m_start, m_end)
                except Exception:
                    logger.exception("taifex backfill: %s %s 抓取失敗，跳過", contract, m_start)
                    continue
                written = _store(db, parsed)
                total += written
                logger.info(
                    "taifex %s %s：解析 %d 列、寫入 %d 列", contract, m_start.strftime("%Y-%m"),
                    len(parsed), written,
                )

    logger.info("taifex backfill 完成，共寫入 %d 列", total)
    return {"written": total, "months": len(months)}


def coverage(db: Session) -> dict:
    rows = (
        db.query(
            FuturesDaily.contract,
            FuturesDaily.session,
            func.min(FuturesDaily.trade_date),
            func.max(FuturesDaily.trade_date),
            func.count(FuturesDaily.id),
        )
        .group_by(FuturesDaily.contract, FuturesDaily.session)
        .all()
    )
    return {
        "segments": [
            {
                "contract": c,
                "session": s,
                "earliest_date": lo,
                "latest_date": hi,
                "row_count": n,
            }
            for c, s, lo, hi, n in rows
        ]
    }
