"""序列模型（GRU/LSTM）用的視窗組裝。

表格式模型跟 MLP 看的是「某一天的特徵」（一列 = 一個樣本）；GRU/LSTM 看的是
「這一天之前連續 T 天的特徵」（一個 T×F 的視窗 = 一個樣本）。

實作上刻意**不把視窗複製到每一列上**。訓練期動輒 30 萬列，每列複製一份
20×50 的視窗要吃掉好幾 GB，而那些視窗彼此高度重疊（相鄰兩天的視窗有 T-1 天
是一樣的）。所以這裡替每檔股票建一份連續的特徵矩陣，每一列只記「我是這檔的
第幾個位置」，真正要餵給網路時才即時切出視窗。

視窗的「連續」是指**該股票連續的特徵列**，不是連續的日曆日。停牌的股票中間
會少幾天，視窗就會橫跨比較長的日曆區間；這是這類模型的標準處理方式。
"""

import logging

import numpy as np

from app.services.features.frame import FeatureFrame

logger = logging.getLogger(__name__)

DEFAULT_SEQUENCE_LENGTH = 20
MIN_SEQUENCE_LENGTH = 5
MAX_SEQUENCE_LENGTH = 120


def index_feature_rows(rows: FeatureFrame, feature_keys: list[str]) -> None:
    """替每一列算出它在自己那檔股票裡的位置，並建好每檔的特徵矩陣（原地掛上去）。

    rows 必須是同一次 build_feature_rows 的完整輸出（含暖身期那段還不會被當成
    訓練目標、但要當歷史用的列），否則早期的樣本會湊不出完整視窗。
    """
    if len(rows) == 0:
        rows.seq_matrices = {}
        rows.seq_pos = np.zeros(0, dtype=np.int32)
        return

    idx = [rows.key_index[k] for k in feature_keys if k in rows.key_index]
    # 先依 (代號, 日期) 排好，同一檔的列才會連在一起且按時間遞增
    order = np.lexsort((rows.dates, rows.codes))
    sorted_codes = rows.codes[order]

    seq_pos = np.empty(len(rows), dtype=np.int32)
    matrices: dict[int, np.ndarray] = {}

    boundaries = np.flatnonzero(np.diff(sorted_codes)) + 1
    for start, stop in zip(
        np.concatenate(([0], boundaries)), np.concatenate((boundaries, [len(order)]))
    ):
        block = order[start:stop]
        code_id = int(sorted_codes[start])
        block_values = rows.values[np.ix_(block, idx)].astype(np.float32)
        # 舊版是「isfinite 才填，否則留 NaN」，inf 不能直接帶進網路
        block_values[~np.isfinite(block_values)] = np.nan
        matrices[code_id] = block_values
        seq_pos[block] = np.arange(stop - start, dtype=np.int32)

    rows.seq_matrices = matrices
    rows.seq_pos = seq_pos
    logger.info("index_feature_rows: %d 檔股票、共 %d 列建立序列索引", len(matrices), len(rows))


def filter_rows_with_history(rows: FeatureFrame, sequence_length: int) -> FeatureFrame:
    """丟掉前面歷史不足 T 天的列。

    這些列不是資料有問題，只是它前面沒有足夠長的歷史可以組成視窗（例如剛上市、
    或正好落在本地日K回補到的最前緣）。留著會變成用補零的假歷史去訓練。
    """
    if rows.seq_pos is None:
        raise RuntimeError("還沒建立序列索引，請先呼叫 index_feature_rows")
    keep = rows.seq_pos + 1 >= sequence_length
    dropped = int((~keep).sum())
    if dropped:
        logger.info(
            "filter_rows_with_history: 丟掉 %d 列（歷史不足 %d 天），剩 %d 列",
            dropped, sequence_length, int(keep.sum()),
        )
    return rows.mask(keep)


def stack_sequences(rows: FeatureFrame, sequence_length: int) -> np.ndarray:
    """把每一列的視窗切出來疊成 (N, T, F)。呼叫前請先過 filter_rows_with_history。"""
    if rows.seq_pos is None:
        raise RuntimeError("還沒建立序列索引，請先呼叫 index_feature_rows")
    if len(rows) == 0:
        return np.zeros((0, sequence_length, 0), dtype=np.float32)

    n_features = next(iter(rows.seq_matrices.values())).shape[1]
    out = np.empty((len(rows), sequence_length, n_features), dtype=np.float32)
    codes = rows.codes
    positions = rows.seq_pos
    for i in range(len(rows)):
        end = int(positions[i]) + 1
        out[i] = rows.seq_matrices[int(codes[i])][end - sequence_length : end]
    return out
