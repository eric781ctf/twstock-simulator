"""Combinatorial Purged Cross-Validation（CPCV）。

walk-forward 的根本限制是**只產生一條路徑**：36 個測試段串起來，就是「這段
歷史如果這樣跑會怎樣」的一次實現。歷史只有一條，所以沒辦法分辨「這個 edge
是真的」還是「這條路徑剛好幸運」。

CPCV 的做法是把時間軸切成 N 組，每次抽 k 組當測試、其餘當訓練，窮舉
C(N, k) 種組合。每一組會在不同組合裡被測到 C(N-1, k-1) 次，所以測試結果可以
重新拼成 **φ = C(N-1, k-1) 條完整覆蓋整段歷史的路徑**——於是有了績效的分布，
而不是單一數字。

**這不比 walk-forward「更真實」，反而更不真實**：測試組在中間時，訓練資料
同時來自它的前面和後面，模型看過「未來」。它的用途是統計上的——估計績效的
分布、判斷 edge 是否可能只是運氣。要模擬實際部署的樣子，walk-forward 才是
對的形狀。兩者互補，不是取代。

正因為訓練資料會出現在測試組的**兩側**，purging 必須是雙側的，embargo 也要
加在測試組之後（報酬有序列相關，緊接在後面的訓練樣本仍然帶著測試期的資訊）。
這是它跟前向 walk-forward 最大的實作差異。

參考：López de Prado, *Advances in Financial Machine Learning*, ch.12；
Bailey, Borwein, López de Prado & Zhu, *The Probability of Backtest Overfitting*。
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from itertools import combinations

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_GROUPS = 6          # N：時間軸切成幾組
DEFAULT_TEST_GROUPS = 2     # k：每次抽幾組當測試
MAX_COMBINATIONS = 60       # 護欄：C(N,k) 會爆炸，每個組合都要訓練一次


@dataclass
class Group:
    """時間軸上的一段。用交易日切而不是日曆日——資料密度不均勻時，
    等長的日曆區間會含有差很多的樣本數。"""

    index: int
    start: date
    end: date

    def as_dict(self) -> dict:
        return {"index": self.index, "start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass
class CpcvSplit:
    """一個組合：哪幾組當測試、哪幾組當訓練。"""

    index: int
    test_groups: tuple[int, ...]
    train_groups: tuple[int, ...]
    validation_group: int
    groups: list[Group] = field(repr=False, default_factory=list)

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "test_groups": list(self.test_groups),
            "train_groups": list(self.train_groups),
            "validation_group": self.validation_group,
        }


def make_groups(days: list[date], n_groups: int) -> list[Group]:
    """把交易日等分成 N 組（依樣本數而不是日曆長度）。"""
    if n_groups < 2:
        raise ValueError("CPCV 至少要切 2 組")
    if len(days) < n_groups:
        raise ValueError(f"只有 {len(days)} 個交易日，切不出 {n_groups} 組")
    bounds = np.linspace(0, len(days), n_groups + 1).astype(int)
    return [
        Group(index=i, start=days[bounds[i]], end=days[bounds[i + 1] - 1])
        for i in range(n_groups)
    ]


def generate_splits(
    n_groups: int = DEFAULT_GROUPS, test_groups: int = DEFAULT_TEST_GROUPS
) -> list[CpcvSplit]:
    """窮舉 C(N, k) 種「哪 k 組當測試」的組合。

    驗證組取訓練組裡**時間上最後的那一組**：訓練與驗證必須互斥，而 CPCV 原本
    只分 train/test 兩段。挑最後一組是因為它離測試組最近，選出來的模型比較
    不會是「對很久以前的市況最合身」的那個。
    """
    if test_groups < 1 or test_groups >= n_groups:
        raise ValueError("測試組數必須介於 1 與 N-1 之間")

    splits: list[CpcvSplit] = []
    for i, test in enumerate(combinations(range(n_groups), test_groups)):
        train = tuple(g for g in range(n_groups) if g not in test)
        if len(train) < 2:
            raise ValueError("訓練組至少要 2 組（其中一組要當驗證）")
        splits.append(
            CpcvSplit(
                index=i + 1,
                test_groups=test,
                train_groups=train[:-1],      # 最後一組留給驗證
                validation_group=train[-1],
            )
        )
    if len(splits) > MAX_COMBINATIONS:
        raise ValueError(
            f"C({n_groups},{test_groups}) = {len(splits)} 種組合，每種都要訓練一次，"
            f"超過上限 {MAX_COMBINATIONS}。請調小組數或測試組數"
        )
    return splits


def path_count(n_groups: int, test_groups: int) -> int:
    """能拼出幾條完整路徑：φ = C(N-1, k-1)。"""
    from math import comb

    return comb(n_groups - 1, test_groups - 1)


def assign_paths(splits: list[CpcvSplit], n_groups: int) -> list[dict[int, int]]:
    """把「組合 × 測試組」的結果重新拼成多條完整路徑。

    每一組都被測到 φ 次（由 φ 個不同的模型），所以第 j 條路徑的做法是：
    對每一組，取「第 j 個測到它的組合」。這樣每條路徑都完整覆蓋整段歷史，
    而且是由一批不同的模型拼出來的。

    回傳 [ {組別: 組合編號}, ... ]，長度就是路徑數。
    """
    testers: dict[int, list[int]] = {g: [] for g in range(n_groups)}
    for split in splits:
        for g in split.test_groups:
            testers[g].append(split.index)

    phi = min(len(v) for v in testers.values())
    return [{g: testers[g][j] for g in range(n_groups)} for j in range(phi)]


def purged_train_mask(
    dates: np.ndarray,
    groups: list[Group],
    train_groups: tuple[int, ...],
    test_groups: tuple[int, ...],
    unique_days: np.ndarray,
    purge_days: int,
    embargo_days: int,
) -> np.ndarray:
    """訓練樣本的遮罩：屬於訓練組、且不落在任何測試組的淨化區間裡。

    淨化區間是 **[測試組起 − purge, 測試組迄 + embargo]**，兩側都要：

    - 往前 purge：label 是未來 n 天的報酬，測試組開始前 n 天的訓練樣本，
      它們的答案落在測試期裡。
    - 往後 embargo：訓練資料就緊接在測試期後面，而報酬有序列相關；不空一段
      的話，模型等於學過「測試期結束時市場長什麼樣」。

    前向的 walk-forward 只需要往前那一側（訓練永遠在測試之前），CPCV 兩側都要。
    """
    keep = np.zeros(len(dates), dtype=bool)
    for g in train_groups:
        keep |= (dates >= groups[g].start.toordinal()) & (dates <= groups[g].end.toordinal())

    for g in test_groups:
        lo_idx = int(np.searchsorted(unique_days, groups[g].start.toordinal()))
        hi_idx = int(np.searchsorted(unique_days, groups[g].end.toordinal()))
        lo = unique_days[max(lo_idx - purge_days, 0)]
        hi = unique_days[min(hi_idx + embargo_days, len(unique_days) - 1)]
        keep &= ~((dates >= lo) & (dates <= hi))

    return keep


def group_mask(dates: np.ndarray, groups: list[Group], indices) -> np.ndarray:
    out = np.zeros(len(dates), dtype=bool)
    for g in (indices if isinstance(indices, (tuple, list)) else (indices,)):
        out |= (dates >= groups[g].start.toordinal()) & (dates <= groups[g].end.toordinal())
    return out


def summarize_paths(path_scores: list[float]) -> dict:
    """多條路徑的績效分布。

    重點不是平均值，是**有幾條路徑是正的**、以及分散程度——那才回答
    「這個 edge 是不是只在某一條歷史上成立」。
    """
    if not path_scores:
        return {}
    arr = np.array(path_scores, dtype=float)
    return {
        "count": len(arr),
        "mean": float(arr.mean()),
        "std": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
        "min": float(arr.min()),
        "max": float(arr.max()),
        "positive_paths": int((arr > 0).sum()),
    }
