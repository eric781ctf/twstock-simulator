"""籌碼面資料的同步與回補：三大法人買賣超與信用交易餘額。

跟日K回補走同一種請求形狀——TWSE 的 T86 與 MI_MARGN 都是「一次一天、拿全
市場」，所以補 N 個交易日就是 N 次請求，不會因為股票數量而爆增。

一天要打兩支端點（法人一支、信用交易一支），兩支之間也要節流。所以請求數是
交易日數 × 2，補兩年約 1000 次——比逐檔抓的數量級還是小得多，但仍然要慢慢來。

已經補過的日期會跳過，重跑不浪費請求。
"""

import logging
from datetime import date, timedelta

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import ChipDaily, Market, Stock
from app.services import backfill_status
from app.services.stock_sync import _HEADERS, _throttled_sleep
from app.services.twse_client import (
    RateLimitedError,
    fetch_twse_foreign_holding_for_date,
    fetch_twse_institutional_for_date,
    fetch_twse_margin_for_date,
)

logger = logging.getLogger(__name__)

# 各端點之間、以及每個交易日之間的間隔。一天要打三支（法人、信用交易、
# 外資持股），所以比日K保守
REQUEST_DELAY_SECONDS = 3.5
# 一天至少要有這麼多檔才算補過。法人買賣超只有「當天有法人交易」的股票會出現，
# 所以門檻不能設得像日K那麼高
MIN_ROWS_PER_DAY = 200


def _upsert(db: Session, day: date, rows: dict[str, dict]) -> int:
    """把某一天的籌碼資料寫進去。同一天同一檔已存在就更新，不重複插入。"""
    if not rows:
        return 0

    existing = {
        chip.stock_code: chip
        for chip in db.query(ChipDaily).filter(ChipDaily.trade_date == day).all()
    }
    written = 0
    for code, values in rows.items():
        chip = existing.get(code)
        if chip is None:
            db.add(ChipDaily(stock_code=code, trade_date=day, **values))
            written += 1
        else:
            for key, value in values.items():
                # 只補上沒有的部分：法人與信用交易是分兩支端點抓的，
                # 其中一支失敗時不該把另一支已經寫好的值蓋成 None
                if value is not None:
                    setattr(chip, key, value)
            written += 1
    db.commit()
    return written


async def sync_chip_for_date(
    db: Session,
    day: date,
    known_codes: set[str],
    client: httpx.AsyncClient,
) -> int:
    """抓某一天的法人與信用交易資料並寫入。回傳寫了幾檔。

    兩支端點各自可能失敗或該日無資料，任一支有資料就寫入——法人資料拿到了
    但信用交易沒拿到，仍然比整天都不寫好。
    """
    combined: dict[str, dict] = {}
    stamp = day.strftime("%Y%m%d")

    institutional = await fetch_twse_institutional_for_date(stamp, client=client)
    for item in institutional or []:
        code = item.pop("stock_code")
        if code in known_codes:
            combined[code] = dict(item)

    await _throttled_sleep(REQUEST_DELAY_SECONDS, "籌碼面各端點之間")

    margin = await fetch_twse_margin_for_date(stamp, client=client)
    for item in margin or []:
        code = item.pop("stock_code")
        if code in known_codes:
            combined.setdefault(code, {}).update(item)

    await _throttled_sleep(REQUEST_DELAY_SECONDS, "籌碼面各端點之間")

    holding = await fetch_twse_foreign_holding_for_date(stamp, client=client)
    for item in holding or []:
        code = item.pop("stock_code")
        if code in known_codes:
            combined.setdefault(code, {}).update(item)

    return _upsert(db, day, combined)


async def backfill_chip_data(db: Session, start: date, end: date) -> int:
    """逐日回補 [start, end] 的籌碼面資料。回傳寫入的筆數。"""
    known_codes = {c for (c,) in db.query(Stock.code).filter(Stock.market == Market.TWSE).all()}
    if not known_codes:
        backfill_status.finish(backfill_status.PHASE_COMPLETED, "本地還沒有上市股票清單")
        return 0

    # 「補過了」的判斷刻意看**最新加入的欄位**而不是總筆數：加了新欄位之後，
    # 先前補好的日期在「有幾列」這個舊定義下會被跳過，永遠拿不到新資料。
    # _upsert 只覆寫非 None 的值，所以重抓既有日期是安全的，只是多花時間。
    existing_counts = dict(
        db.query(ChipDaily.trade_date, func.count(ChipDaily.id))
        .filter(
            ChipDaily.trade_date >= start,
            ChipDaily.trade_date <= end,
            ChipDaily.foreign_holding_ratio.isnot(None),
        )
        .group_by(ChipDaily.trade_date)
        .all()
    )

    all_days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    candidate_days = [d for d in all_days if d.weekday() < 5]
    pending_days = [d for d in candidate_days if existing_counts.get(d, 0) < MIN_ROWS_PER_DAY]

    backfill_status.begin(len(pending_days), backfill_status.JOB_CHIP)
    if not pending_days:
        backfill_status.finish(backfill_status.PHASE_COMPLETED, f"{start} ~ {end} 的籌碼面資料都補齊了")
        return 0

    backfill_status.set_batch(len(pending_days), len(pending_days))
    logger.info(
        "backfill_chip_data: %s ~ %s 共 %d 個待補日期（已跳過 %d 個補過的與週末）",
        start,
        end,
        len(pending_days),
        len(candidate_days) - len(pending_days),
    )

    written = 0
    processed = 0
    # 新的日期先補：越近期的資料對模型越有用，被限流中斷時手上留下的也是有用的那段
    pending_days.sort(reverse=True)
    try:
        async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
            for i, day in enumerate(pending_days):
                if i > 0:
                    await _throttled_sleep(REQUEST_DELAY_SECONDS, "每個交易日之間的間隔")

                backfill_status.set_running(day.isoformat(), processed, written)
                try:
                    written += await sync_chip_for_date(db, day, known_codes, client)
                except RateLimitedError:
                    logger.warning("backfill_chip_data: 被 TWSE 限流，在 %s 中止", day)
                    backfill_status.finish(
                        backfill_status.PHASE_RATE_LIMITED,
                        f"被 TWSE 限流，本輪補到 {day} 為止（已寫入 {written} 筆），剩下的留給下次",
                    )
                    return written
                processed += 1

        backfill_status.finish(
            backfill_status.PHASE_COMPLETED,
            f"籌碼面回補完成，處理 {processed} 個日期、寫入 {written} 筆",
        )
    except Exception as e:
        logger.exception("backfill_chip_data 失敗")
        backfill_status.finish(backfill_status.PHASE_FAILED, str(e)[:200])
        raise

    logger.info("backfill_chip_data: 完成，寫入 %d 筆", written)
    return written


def earliest_chip_date(db: Session) -> date | None:
    return db.query(func.min(ChipDaily.trade_date)).scalar()


def latest_chip_date(db: Session) -> date | None:
    return db.query(func.max(ChipDaily.trade_date)).scalar()
