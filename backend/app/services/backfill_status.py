"""回補任務的即時狀態。

回補是一個「等待遠多於工作」的流程：一次跑 100 檔，股票之間要隔 60 秒、每 20
檔再多休 20 分鐘，光是自我節流就超過三小時。沒有狀態顯示的話，使用者按下
「繼續回補」之後只會看到一片安靜，分不出來是正在抓資料、在我們自己的節流
睡眠中，還是已經被 TWSE 擋下來了——這三種情況該做的反應完全不同。

特別要分清楚兩種「等待」：
- throttling：**我們主動**放慢速度，是正常狀態，讓它跑完就好
- rate_limited：**TWSE 真的擋了我們**（428/429），本輪已中止，要等下次排程

狀態放記憶體不放資料庫：這是「現在如何」的即時資訊，程式重啟後任務本來就
中斷了，狀態跟著歸零才是正確的。回補跑在 uvicorn 同一個 event loop 裡，
模組層級變數就夠用，不需要鎖。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.services.matching import TAIPEI_TZ

logger = logging.getLogger(__name__)

PHASE_IDLE = "idle"
PHASE_PREPARING = "preparing"
PHASE_RUNNING = "running"
PHASE_THROTTLING = "throttling"
PHASE_RATE_LIMITED = "rate_limited"
PHASE_COMPLETED = "completed"
PHASE_FAILED = "failed"

PHASE_LABELS: dict[str, str] = {
    PHASE_IDLE: "閒置中",
    PHASE_PREPARING: "準備中",
    PHASE_RUNNING: "回補中",
    PHASE_THROTTLING: "節流等待中",
    PHASE_RATE_LIMITED: "已被 TWSE 限流，本輪中止",
    PHASE_COMPLETED: "本輪完成",
    PHASE_FAILED: "發生錯誤",
}


# 目前有兩種回補共用這個狀態（日K與籌碼面）。它們共用是刻意的——兩者都打
# TWSE，同時跑只會讓請求密度加倍，正是節流想避免的事。但畫面上要看得出來
# 現在跑的是哪一種，不然使用者會以為自己按的那個沒有反應。
JOB_DAILY_BARS = "daily_bars"
JOB_CHIP = "chip"

JOB_LABELS: dict[str, str] = {
    JOB_DAILY_BARS: "日K",
    JOB_CHIP: "籌碼面",
}


@dataclass
class BackfillState:
    job: str = JOB_DAILY_BARS
    phase: str = PHASE_IDLE
    current_target: str | None = None
    processed: int = 0
    total: int = 0
    remaining_targets: int = 0
    written_bars: int = 0
    wait_until: datetime | None = None
    wait_reason: str | None = None
    message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


_state = BackfillState()


def is_active() -> bool:
    """有沒有一輪回補正在進行中（含節流等待）。用來擋掉重複觸發——同時跑兩輪
    只會讓對 TWSE 的請求密度加倍，正好是節流想避免的事。"""
    return _state.phase in (PHASE_PREPARING, PHASE_RUNNING, PHASE_THROTTLING)


def snapshot() -> dict:
    remaining = None
    if _state.phase == PHASE_THROTTLING and _state.wait_until is not None:
        remaining = max(0, int((_state.wait_until - datetime.now(TAIPEI_TZ)).total_seconds()))

    return {
        "job": _state.job,
        "job_label": JOB_LABELS.get(_state.job, _state.job),
        "phase": _state.phase,
        "phase_label": PHASE_LABELS.get(_state.phase, _state.phase),
        "current_target": _state.current_target,
        "processed": _state.processed,
        "total": _state.total,
        "remaining_targets": _state.remaining_targets,
        "written_bars": _state.written_bars,
        "wait_seconds_remaining": remaining,
        "wait_reason": _state.wait_reason,
        "message": _state.message,
        "started_at": _state.started_at,
        "finished_at": _state.finished_at,
    }


def begin(remaining_targets: int, job: str = JOB_DAILY_BARS) -> None:
    global _state
    _state = BackfillState(
        job=job,
        phase=PHASE_PREPARING,
        remaining_targets=remaining_targets,
        started_at=datetime.now(TAIPEI_TZ),
    )


def set_batch(total: int, remaining_targets: int) -> None:
    _state.phase = PHASE_RUNNING
    _state.total = total
    _state.remaining_targets = remaining_targets


def set_running(target: str, processed: int, written_bars: int) -> None:
    _state.phase = PHASE_RUNNING
    _state.current_target = target
    _state.processed = processed
    _state.written_bars = written_bars
    _state.wait_until = None
    _state.wait_reason = None


def begin_wait(seconds: float, reason: str) -> None:
    _state.phase = PHASE_THROTTLING
    _state.wait_until = datetime.now(TAIPEI_TZ) + timedelta(seconds=seconds)
    _state.wait_reason = reason


def finish(phase: str, message: str | None = None) -> None:
    _state.phase = phase
    _state.message = message
    _state.current_target = None
    _state.wait_until = None
    _state.wait_reason = None
    _state.finished_at = datetime.now(TAIPEI_TZ)
