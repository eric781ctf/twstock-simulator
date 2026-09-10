"""Walk-forward（滾動視窗）驗證的切分產生。

單一次固定切分的問題：測試期只有一段市況。同一個模型在 2026 年 7~9 月的
Rank IC 是 +0.06、在 5~6 月是 -0.04，這個差距完全可能只是「那兩個月剛好」，
而不是模型變好或變壞。實測也確實看到同一個架構跑兩次就能讓測試 Rank IC
翻正負號——那不是模型在變，是我們在量一個沒有統計意義的東西。

滾動視窗把同一組設定在多段不同時期各測一次，回報平均與標準差。這樣才分得出
「這個改動有效」跟「這次剛好」。Qlib 那些 benchmark 之所以可信，正是因為它們
報的是 20 次的平均與標準差，不是單次結果。

每一折的切分都維持「訓練 < 驗證 < 測試」的時間順序，折與折之間往前滾動，
永遠不會拿後面的資料去訓練前面的測試期。
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta

logger = logging.getLogger(__name__)

DEFAULT_TRAIN_MONTHS = 6
DEFAULT_VALIDATION_MONTHS = 2
DEFAULT_TEST_MONTHS = 2
DEFAULT_STEP_MONTHS = 2
# 折數上限。每一折都要重新訓練一次，太多折會讓一次執行拖到難以接受
MAX_FOLDS = 12


@dataclass
class Fold:
    """一折的六個日期界線，跟單次切分的形狀完全一樣。"""

    index: int
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "validation_start": self.validation_start.isoformat(),
            "validation_end": self.validation_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
        }


def add_months(day: date, months: int) -> date:
    """往後推 N 個月。落在不存在的日期（例如 1/31 + 1 個月）時退到當月最後一天。"""
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    # 從下個月的第一天往回退一天，就是這個月的最後一天
    next_month_first = date(year + (month // 12), month % 12 + 1, 1)
    last_day_of_month = (next_month_first - timedelta(days=1)).day
    return date(year, month, min(day.day, last_day_of_month))


def generate_folds(
    overall_start: date,
    overall_end: date,
    train_months: int = DEFAULT_TRAIN_MONTHS,
    validation_months: int = DEFAULT_VALIDATION_MONTHS,
    test_months: int = DEFAULT_TEST_MONTHS,
    step_months: int = DEFAULT_STEP_MONTHS,
    max_folds: int = MAX_FOLDS,
) -> list[Fold]:
    """在 [overall_start, overall_end] 之間切出一連串滾動視窗。

    每往前滾一步就產生一折，直到測試期的結尾超出可用資料為止。回傳空清單代表
    這段期間連一折都排不下——呼叫端要把它當成設定錯誤處理，而不是「沒有結果」。
    """
    folds: list[Fold] = []
    cursor = overall_start

    while len(folds) < max_folds:
        train_start = cursor
        train_end = add_months(train_start, train_months)
        validation_start = train_end + timedelta(days=1)
        validation_end = add_months(validation_start, validation_months)
        test_start = validation_end + timedelta(days=1)
        test_end = add_months(test_start, test_months)

        if test_end > overall_end:
            break

        folds.append(
            Fold(
                index=len(folds) + 1,
                train_start=train_start,
                train_end=train_end,
                validation_start=validation_start,
                validation_end=validation_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        cursor = add_months(cursor, step_months)

    logger.info(
        "generate_folds: %s~%s 切出 %d 折（訓練 %d / 驗證 %d / 測試 %d 個月，每次滾動 %d 個月）",
        overall_start,
        overall_end,
        len(folds),
        train_months,
        validation_months,
        test_months,
        step_months,
    )
    return folds


def summarize_folds(fold_metrics: list[dict]) -> dict:
    """把每折的成績整理成平均與標準差。

    標準差才是這件事的重點：平均 Rank IC +0.02 但標準差 0.06，代表這個數字
    根本站不住腳；平均 +0.02、標準差 0.01 才是一個可以拿來做決策的訊號。
    另外回報「幾折是正的」——對只想知道「這東西到底穩不穩」的人，那比平均更直觀。
    """
    if not fold_metrics:
        return {}

    def stats(getter) -> dict | None:
        values = [v for v in (getter(m) for m in fold_metrics) if v is not None]
        if not values:
            return None
        mean = sum(values) / len(values)
        # 母體標準差：這幾折就是我們手上的全部，不是從更大的母體抽樣
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return {
            "mean": mean,
            "std": variance**0.5,
            "min": min(values),
            "max": max(values),
            "positive_folds": sum(1 for v in values if v > 0),
            "count": len(values),
        }

    return {
        "fold_count": len(fold_metrics),
        "test_rank_ic": stats(lambda m: m["test"].get("rank_ic")),
        "test_auc": stats(lambda m: m["test"].get("auc")),
        "validation_rank_ic": stats(lambda m: m["validation"].get("rank_ic")),
    }
