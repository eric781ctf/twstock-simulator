"""特徵表的欄式表示。

取代原本的 `list[dict]`。一列 116 個 key 的 dict 大約 6KB，168 萬列就要 10GB，
而且產生它的過程還要先 `astype(object)` 把每個 float 變成 Python 物件（再多
約 6GB）。同樣的數字放 float32 矩陣只要 750MB——差了一個數量級以上，而那正是
六年歷史跑不動的原因。

省下來的不只是空間。原本 `rank_normalize` 之類的轉換每次都要重建整個 list of
dict（`dict(row)` 複製 168 萬次），改成欄式之後直接在矩陣上原地運算。

**缺值一律用 NaN，不用 None。** 舊表示法沒有 NaN 可用（object 欄位裡 NaN 跟
None 混在一起很容易出錯），所以當初選了 None；float32 矩陣天生就有 NaN，
判斷缺值用 `np.isnan` 比 `is None` 快也省。

少數地方（回測、每日選股、推論）本來就是逐列處理的，那些用 RowView——一個
照著原本 dict 介面的輕量視圖，讀的時候才去矩陣取值，所以呼叫端幾乎不用改，
也不會把資料複製出來。
"""

from __future__ import annotations

from datetime import date

import numpy as np

# 除了特徵以外還要隨身帶的欄位。close/volume 是成交與流動性判斷要用的，
# 但它們跨股票不可比，所以不是特徵；label 兩欄是 attach_labels 之後才有
EXTRA_KEYS = ("close", "volume", "future_return_percent", "label")


class RowView:
    """單一列的唯讀視圖，介面比照原本的 row dict。

    刻意不做成 dataclass 或 namedtuple——那些都會把值複製出來，而這裡的重點
    就是不要複製。`__slots__` 讓每個視圖只有兩個欄位的大小。
    """

    __slots__ = ("_frame", "_i")

    def __init__(self, frame: FeatureFrame, i: int):
        self._frame = frame
        self._i = i

    def __getitem__(self, key: str):
        value = self.get(key, _MISSING)
        if value is _MISSING:
            raise KeyError(key)
        return value

    def get(self, key: str, default=None):
        f = self._frame
        i = self._i
        if key == "stock_code":
            return f.code_names[f.codes[i]]
        if key == "as_of_date":
            return date.fromordinal(int(f.dates[i]))
        column = f.extras.get(key)
        if column is not None:
            value = column[i]
            return None if isinstance(value, float) and np.isnan(value) else value.item()
        j = f.key_index.get(key)
        if j is None:
            return default
        value = float(f.values[i, j])
        # 下游用 `is None` 判斷缺值，所以邊界上還是把 NaN 翻譯回 None
        return None if np.isnan(value) else value

    def __contains__(self, key: str) -> bool:
        return self.get(key, _MISSING) is not _MISSING

    def __repr__(self) -> str:
        return f"<RowView {self['stock_code']} {self['as_of_date']}>"


_MISSING = object()


class FeatureFrame:
    """特徵矩陣加上「這一列是哪一檔、哪一天」的索引。"""

    __slots__ = (
        "codes", "code_names", "dates", "values", "feature_keys", "key_index", "extras",
        # 序列模型用：每檔股票一份連續的特徵矩陣，加上每一列在自己那檔裡的位置。
        # 視窗不複製到每一列上——相鄰兩天的視窗有 T-1 天是重疊的，複製會多吃好幾百 MB
        "seq_matrices", "seq_pos",
    )

    def __init__(
        self,
        codes: np.ndarray,
        code_names: np.ndarray,
        dates: np.ndarray,
        values: np.ndarray,
        feature_keys: list[str],
        extras: dict[str, np.ndarray],
    ):
        self.codes = codes
        self.code_names = code_names
        self.dates = dates
        self.values = values
        self.feature_keys = feature_keys
        self.key_index = {key: i for i, key in enumerate(feature_keys)}
        self.extras = extras
        self.seq_matrices: dict | None = None
        self.seq_pos: np.ndarray | None = None

    # ── 基本 ────────────────────────────────────────────────────────────
    def __len__(self) -> int:
        return len(self.dates)

    def __bool__(self) -> bool:
        return len(self.dates) > 0

    def __iter__(self):
        for i in range(len(self.dates)):
            yield RowView(self, i)

    def row(self, i: int) -> RowView:
        return RowView(self, i)

    def __getitem__(self, item):
        """切片得到子表（給分批推論用），單一整數得到 RowView。

        切片走 numpy 的 basic indexing，拿到的是**視圖不是複製**——分批預測
        十萬列時這個差別就是幾百 MB。
        """
        if isinstance(item, slice):
            return self._take(item)
        return RowView(self, item)

    def _take(self, indexer) -> FeatureFrame:
        out = FeatureFrame(
            codes=self.codes[indexer],
            code_names=self.code_names,
            dates=self.dates[indexer],
            values=self.values[indexer],
            feature_keys=self.feature_keys,
            extras={k: v[indexer] for k, v in self.extras.items()},
        )
        # 序列矩陣照參照共用：位置索引指向「該股票自己的矩陣」，不是指向這張表，
        # 所以篩選之後仍然有效，也不需要重算
        if self.seq_pos is not None:
            out.seq_matrices = self.seq_matrices
            out.seq_pos = self.seq_pos[indexer]
        return out

    @classmethod
    def empty(cls, feature_keys: list[str]) -> FeatureFrame:
        return cls(
            codes=np.zeros(0, dtype=np.int32),
            code_names=np.array([], dtype=object),
            dates=np.zeros(0, dtype=np.int32),
            values=np.zeros((0, len(feature_keys)), dtype=np.float64),
            feature_keys=list(feature_keys),
            extras={k: np.zeros(0, dtype=np.float64) for k in EXTRA_KEYS},
        )

    # ── 取值 ────────────────────────────────────────────────────────────
    def column(self, key: str) -> np.ndarray:
        if key in self.extras:
            return self.extras[key]
        j = self.key_index.get(key)
        if j is None:
            raise KeyError(key)
        return self.values[:, j]

    def set_column(self, key: str, values: np.ndarray) -> None:
        self.extras[key] = values

    def stock_codes(self) -> np.ndarray:
        """每一列的股票代碼（字串陣列）。會實體化，只在需要時呼叫。"""
        return self.code_names[self.codes]

    def dates_as_objects(self) -> np.ndarray:
        return np.array([date.fromordinal(int(d)) for d in self.dates], dtype=object)

    def unique_dates(self) -> list[date]:
        return [date.fromordinal(int(d)) for d in np.unique(self.dates)]

    def feature_matrix(self, keys: list[str]) -> np.ndarray:
        """依指定順序取出特徵欄，轉成 float64 給模型用。

        訓練端一律 float64：儲存省記憶體用 float32 就夠，但 LightGBM 與 sklearn
        內部本來就會轉成 float64，在這裡轉一次比讓它們各自轉乾淨。
        """
        missing = [k for k in keys if k not in self.key_index]
        if missing:
            raise KeyError(f"特徵表裡沒有這些欄位：{missing}")
        idx = [self.key_index[k] for k in keys]
        out = self.values[:, idx].astype(np.float64)
        # 舊的 to_matrix 是 `np.isfinite(...) else np.nan`——inf 會被當成缺值。
        # 但它只在組矩陣時這樣做，排名階段 inf 仍然參與（被排成最大值），
        # 所以這個轉換要留在這裡而不是在建表時做，語意才跟原本一致
        out[~np.isfinite(out)] = np.nan
        return out

    # ── 篩選 ────────────────────────────────────────────────────────────
    def mask(self, keep: np.ndarray) -> FeatureFrame:
        """依布林遮罩取子集。code_names 共用不複製——它只有一千多個字串。"""
        return self._take(keep)

    def between(self, start: date, end: date) -> FeatureFrame:
        keep = (self.dates >= start.toordinal()) & (self.dates <= end.toordinal())
        return self.mask(keep)

    def on_date(self, day: date) -> FeatureFrame:
        return self.mask(self.dates == day.toordinal())

    def before(self, day: date) -> FeatureFrame:
        return self.mask(self.dates < day.toordinal())
