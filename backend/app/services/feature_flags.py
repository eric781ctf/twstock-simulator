"""功能模組開關：管理員可以不重新部署就暫停某個功能。每個 key 對應一列
`feature_flags`，預設全部是 True（開發這個機制之前，這些功能本來就是一直
開著跑的，不能讓它一上線就把大家的功能關掉）。"""

from sqlalchemy.orm import Session

from app.models import FeatureFlag

STRATEGY = "strategy"
SCHEDULER_MATCHING_POLL = "scheduler_matching_poll"
SCHEDULER_STRATEGY_POLL = "scheduler_strategy_poll"
SCHEDULER_DAILY_STOCK_SYNC = "scheduler_daily_stock_sync"
SCHEDULER_DAILY_BAR_BACKFILL = "scheduler_daily_bar_backfill"
SCHEDULER_EQUITY_SNAPSHOT = "scheduler_equity_snapshot"
SCHEDULER_MODEL_SCORING = "scheduler_model_scoring"

FLAG_LABELS: dict[str, str] = {
    STRATEGY: "策略功能",
    SCHEDULER_MATCHING_POLL: "撮合輪詢排程",
    SCHEDULER_STRATEGY_POLL: "策略輪詢排程",
    SCHEDULER_DAILY_STOCK_SYNC: "每日股票同步排程",
    SCHEDULER_DAILY_BAR_BACKFILL: "每日日K回補排程",
    SCHEDULER_EQUITY_SNAPSHOT: "每日績效快照排程",
    SCHEDULER_MODEL_SCORING: "每日模型選股排程",
}

FLAG_KEYS = list(FLAG_LABELS.keys())

# 只有這三個排程跟預測模型系統有關，管理後台只顯示這些——其餘的（撮合輪詢、
# 策略輪詢、績效快照）都是舊模擬器留下來的，對這個系統沒有意義。
MODEL_SYSTEM_FLAGS = [
    SCHEDULER_DAILY_STOCK_SYNC,
    SCHEDULER_DAILY_BAR_BACKFILL,
    SCHEDULER_MODEL_SCORING,
]

# 關掉一個排程會發生什麼事，要講清楚——不然沒人敢動，或動了才發現後果
FLAG_DESCRIPTIONS: dict[str, str] = {
    SCHEDULER_DAILY_STOCK_SYNC: "每天 08:30 更新股票清單並寫入最新一筆日K。關掉的話模型會拿不到當天的收盤資料。",
    SCHEDULER_DAILY_BAR_BACKFILL: "每天 07:00 往前補歷史日K，補到設定的目標月數為止。關掉不影響既有資料，只是不再往前補。",
    SCHEDULER_MODEL_SCORING: "每個交易日 15:00 讓所有啟用中的模型選股與判斷出場。關掉的話模型不會再開新部位，手上的部位也不會出場。",
}


def get_model_system_flags(db: Session) -> list[dict]:
    rows = {f.key: f.enabled for f in db.query(FeatureFlag).all()}
    return [
        {
            "key": key,
            "label": FLAG_LABELS[key],
            "description": FLAG_DESCRIPTIONS.get(key, ""),
            "enabled": rows.get(key, True),
        }
        for key in MODEL_SYSTEM_FLAGS
    ]


def ensure_feature_flags(db: Session) -> None:
    existing = {f.key for f in db.query(FeatureFlag).all()}
    for key in FLAG_KEYS:
        if key not in existing:
            db.add(FeatureFlag(key=key, enabled=True))
    db.commit()


def is_enabled(db: Session, key: str) -> bool:
    flag = db.get(FeatureFlag, key)
    return flag.enabled if flag else True


def get_all_flags(db: Session) -> list[dict]:
    rows = {f.key: f.enabled for f in db.query(FeatureFlag).all()}
    return [{"key": key, "label": FLAG_LABELS[key], "enabled": rows.get(key, True)} for key in FLAG_KEYS]


def set_flag(db: Session, key: str, enabled: bool) -> bool:
    if key not in FLAG_LABELS:
        raise ValueError(f"未知的功能代碼：{key}")
    flag = db.get(FeatureFlag, key)
    if flag is None:
        flag = FeatureFlag(key=key, enabled=enabled)
        db.add(flag)
    else:
        flag.enabled = enabled
    db.commit()
    return flag.enabled
