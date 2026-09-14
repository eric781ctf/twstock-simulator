"""集保戶股權分散表（TDCC）的匯入與同步。

這份資料回答的是「這檔股票的籌碼集中在誰手上」——散戶（不到 10 張）有多少人、
握多少股，大戶（超過 1000 張）又有多少。台股散戶佔比高，籌碼從散戶手上流向
大戶（俗稱籌碼集中）長期被視為看多訊號。

**只能從現在開始累積。** TDCC 的開放資料端點只提供最新一週，沒有歷史查詢；
所以歷史部分靠的是先前另一個專案每週六自動下載留下來的 CSV，這裡把它們匯入，
之後再由排程每週接上去。這也是為什麼要留一個「從資料夾匯入」的路徑，而不是
只寫一個線上抓取。

資料是週頻（每週五的快照），特徵那邊要用「日期嚴格早於特徵日」的最後一筆——
週五的快照要到週六才發布，用 <= 會在週五當天看到還沒公布的資料。
"""

import csv
import logging
from datetime import date, datetime
from pathlib import Path

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Market, ShareholdingWeekly, Stock

logger = logging.getLogger(__name__)

TDCC_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
DATA_DIR = Path(__file__).resolve().parents[2] / "tdcc_data"

# 持股分級的分組。級距定義來自 TDCC：
#   1~3   不到 10 張（1~10,000 股）           → 散戶
#   12~13 400~800 張                          → 中實戶
#   15    超過 1000 張（1,000,001 股以上）    → 大戶
#   16    差異數調整
#   17    合計 ← 這一列是總計，聚合時一定要排除，不然每個比例都會變成兩倍
RETAIL_TIERS = {1, 2, 3}
MID_TIERS = {12, 13}
BIG_TIERS = {15}
TOTAL_TIER = 17


def _parse_rows(reader) -> dict[str, dict[int, dict]]:
    """把 CSV 攤成 {證券代號: {分級: {人數, 股數, 佔比}}}。"""
    by_code: dict[str, dict[int, dict]] = {}
    for row in reader:
        code = (row.get("證券代號") or "").strip()
        if not code:
            continue
        try:
            tier = int(row["持股分級"])
            holders = int(row["人數"])
            percent = float(row["占集保庫存數比例%"])
        except (KeyError, TypeError, ValueError):
            continue
        by_code.setdefault(code, {})[tier] = {"holders": holders, "percent": percent}
    return by_code


def _aggregate(tiers: dict[int, dict]) -> dict | None:
    """把 17 個分級收斂成散戶／中實戶／大戶三組。"""
    total = tiers.get(TOTAL_TIER)
    if not total or not total["holders"]:
        return None

    def group(keys: set[int]) -> tuple[int, float]:
        holders = sum(tiers.get(t, {}).get("holders", 0) for t in keys)
        percent = sum(tiers.get(t, {}).get("percent", 0.0) for t in keys)
        return holders, percent

    retail_holders, retail_percent = group(RETAIL_TIERS)
    mid_holders, mid_percent = group(MID_TIERS)
    big_holders, big_percent = group(BIG_TIERS)

    return {
        "total_holders": total["holders"],
        "retail_holders": retail_holders,
        "retail_share_percent": retail_percent,
        "mid_holders": mid_holders,
        "mid_share_percent": mid_percent,
        "big_holders": big_holders,
        "big_share_percent": big_percent,
    }


def _store(db: Session, snapshot_date: date, by_code: dict[str, dict], known_codes: set[str]) -> int:
    existing = {
        row.stock_code
        for row in db.query(ShareholdingWeekly.stock_code)
        .filter(ShareholdingWeekly.as_of_date == snapshot_date)
        .all()
    }
    written = 0
    for code, tiers in by_code.items():
        if code not in known_codes or code in existing:
            continue
        values = _aggregate(tiers)
        if values is None:
            continue
        db.add(ShareholdingWeekly(stock_code=code, as_of_date=snapshot_date, **values))
        written += 1
    db.commit()
    return written


def import_directory(db: Session, directory: Path | None = None) -> dict:
    """把資料夾裡的 TDCC CSV 全部匯入。已經有的日期會跳過。"""
    directory = directory or DATA_DIR
    if not directory.exists():
        return {"files": 0, "written": 0, "message": f"找不到資料夾 {directory}"}

    known_codes = {c for (c,) in db.query(Stock.code).filter(Stock.market == Market.TWSE).all()}
    files = sorted(directory.glob("TDCC_OD_1-5_*.csv"))
    total_written = 0
    imported = 0

    for path in files:
        stamp = path.stem.split("_")[-1]
        try:
            snapshot_date = datetime.strptime(stamp, "%Y%m%d").date()
        except ValueError:
            logger.warning("import_directory: 檔名 %s 解不出日期，跳過", path.name)
            continue

        # utf-8-sig：TDCC 的 CSV 帶 BOM，用 utf-8 讀第一個欄名會多一個
        with path.open(encoding="utf-8-sig", newline="") as f:
            by_code = _parse_rows(csv.DictReader(f))

        written = _store(db, snapshot_date, by_code, known_codes)
        total_written += written
        imported += 1
        logger.info("import_directory: %s 寫入 %d 檔（檔內共 %d 檔證券）", snapshot_date, written, len(by_code))

    return {"files": imported, "written": total_written, "message": f"匯入 {imported} 個檔案、{total_written} 筆"}


async def fetch_latest(db: Session) -> dict:
    """從 TDCC 抓最新一週並寫入。

    這支端點只給最新一週，所以它的用途是「持續累積」而不是「回補歷史」——
    歷史只能靠先前存下來的檔案。
    """
    known_codes = {c for (c,) in db.query(Stock.code).filter(Stock.market == Market.TWSE).all()}
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        response = await client.get(TDCC_URL)
        response.raise_for_status()
        text = response.content.decode("utf-8-sig")

    by_code = _parse_rows(csv.DictReader(text.splitlines()))
    if not by_code:
        return {"written": 0, "message": "TDCC 回傳的內容解不出資料"}

    # 資料日期寫在每一列裡，直接從第一列取
    first = csv.DictReader(text.splitlines()).__next__()
    snapshot_date = datetime.strptime(first["資料日期"].strip(), "%Y%m%d").date()

    written = _store(db, snapshot_date, by_code, known_codes)
    logger.info("fetch_latest: %s 寫入 %d 檔", snapshot_date, written)
    return {"written": written, "as_of_date": snapshot_date.isoformat(), "message": f"{snapshot_date} 寫入 {written} 筆"}


def coverage(db: Session) -> dict:
    earliest, latest, total, weeks = (
        db.query(
            func.min(ShareholdingWeekly.as_of_date),
            func.max(ShareholdingWeekly.as_of_date),
            func.count(ShareholdingWeekly.id),
            func.count(func.distinct(ShareholdingWeekly.as_of_date)),
        ).one()
    )
    return {
        "earliest_date": earliest,
        "latest_date": latest,
        "total_rows": total or 0,
        "week_count": weeks or 0,
    }
