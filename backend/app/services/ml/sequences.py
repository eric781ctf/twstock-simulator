"""序列模型（GRU/LSTM）用的視窗組裝。

表格式模型跟 MLP 看的是「某一天的特徵」（一列 = 一個樣本）；GRU/LSTM 看的是
「這一天之前連續 T 天的特徵」（一個 T×F 的視窗 = 一個樣本）。差別在於同樣一天
的樣本，序列模型還要拿得到它前面那段歷史。

實作上刻意**不把視窗複製到每一列上**。訓練期動輒 30 萬列，每列複製一份
20×14 的視窗要吃掉好幾百 MB，而那些視窗彼此高度重疊（相鄰兩天的視窗有 19 天
是一樣的）。所以這裡替每檔股票建一份連續的特徵矩陣，每一列只記「我是這檔的
第幾個位置」，真正要餵給網路時才即時切出視窗。這樣下游的
`predict_rows(bundle, rows)` 介面完全不用改——列自己就知道去哪裡拿歷史。

視窗的「連續」是指**該股票連續的特徵列**，不是連續的日曆日。停牌的股票中間
會少幾天，視窗就會橫跨比較長的日曆區間；這是這類模型的標準處理方式。
"""

import logging
from collections import defaultdict

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_SEQUENCE_LENGTH = 20
MIN_SEQUENCE_LENGTH = 5
MAX_SEQUENCE_LENGTH = 120

# 每一列上掛的兩個私有欄位：所屬股票的特徵矩陣（共用參照，不複製）與自己的位置
SEQ_MATRIX_KEY = "_seq_matrix"
SEQ_POSITION_KEY = "_seq_pos"


def index_feature_rows(rows: list[dict], feature_keys: list[str]) -> None:
    """替每一列掛上它所屬股票的特徵矩陣與位置（原地修改）。

    rows 必須是同一次 build_feature_rows 的完整輸出（含暖身期那段還不會被當成
    訓練目標、但要當歷史用的列），否則早期的樣本會湊不出完整視窗。
    """
    by_code: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_code[row["stock_code"]].append(row)

    for code, code_rows in by_code.items():
        code_rows.sort(key=lambda r: r["as_of_date"])
        matrix = np.full((len(code_rows), len(feature_keys)), np.nan, dtype=np.float32)
        for i, row in enumerate(code_rows):
            for j, key in enumerate(feature_keys):
                value = row.get(key)
                if value is None:
                    continue
                value = float(value)
                if np.isfinite(value):
                    matrix[i, j] = value
            row[SEQ_MATRIX_KEY] = matrix
            row[SEQ_POSITION_KEY] = i

    logger.info("index_feature_rows: %d 檔股票、共 %d 列建立序列索引", len(by_code), len(rows))


def has_full_window(row: dict, sequence_length: int) -> bool:
    position = row.get(SEQ_POSITION_KEY)
    return position is not None and position + 1 >= sequence_length


def filter_rows_with_history(rows: list[dict], sequence_length: int) -> list[dict]:
    """丟掉前面歷史不足 T 天的列。

    這些列不是資料有問題，只是它前面沒有足夠長的歷史可以組成視窗（例如剛上市、
    或正好落在本地日K回補到的最前緣）。留著會變成用補零的假歷史去訓練。
    """
    kept = [row for row in rows if has_full_window(row, sequence_length)]
    dropped = len(rows) - len(kept)
    if dropped:
        logger.info("filter_rows_with_history: 丟掉 %d 列（歷史不足 %d 天），剩 %d 列", dropped, sequence_length, len(kept))
    return kept


def stack_sequences(rows: list[dict], sequence_length: int) -> np.ndarray:
    """把每一列的視窗切出來疊成 (N, T, F)。呼叫前請先過 filter_rows_with_history。"""
    if not rows:
        return np.zeros((0, sequence_length, 0), dtype=np.float32)

    n_features = rows[0][SEQ_MATRIX_KEY].shape[1]
    out = np.empty((len(rows), sequence_length, n_features), dtype=np.float32)
    for i, row in enumerate(rows):
        end = row[SEQ_POSITION_KEY] + 1
        out[i] = row[SEQ_MATRIX_KEY][end - sequence_length : end]
    return out


def strip_sequence_refs(rows: list[dict]) -> None:
    """把序列參照從列上拿掉。

    這些列會被丟進回測結果等地方，而參照指向的是整檔股票的特徵矩陣——留著會
    讓一大塊記憶體被單一列「拖住」而無法回收。
    """
    for row in rows:
        row.pop(SEQ_MATRIX_KEY, None)
        row.pop(SEQ_POSITION_KEY, None)
