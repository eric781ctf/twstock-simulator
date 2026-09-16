"""資料自動分群：用過去的報酬相關性找出「會一起動」的族群。

為什麼不用官方產業代碼：台股實際在炒的族群（CoWoS、散熱、重電、矽光子）都是
跨代碼的，而官方「半導體業」把台積電跟上百檔小型 IC 設計放在同一格，太粗。

**不偷看未來**：每個月第一個交易日，只用那天之前 120 個交易日的報酬分群，
分出來的結果套用到當月每一天。下個月重分一次。所以 2023 年 3 月的族群，
只知道 2023 年 3 月以前的事——那時還沒有人知道之後誰會跟誰一起漲。

**先扣掉大盤**：每天每檔的報酬減掉當天全市場的平均報酬再算相關。不扣的話，
大盤漲跌會讓幾乎所有股票都高度相關，分出來只會是「一大群跟著大盤走的」。

用階層式分群（average linkage、距離＝1−相關係數）。它不需要事先指定每群多大，
而且同一份相關矩陣可以反覆切出不同粒度，方便檢查結果穩不穩。
"""

import logging
from dataclasses import dataclass

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from app.services.research.panel import PricePanel

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 120
MIN_VALID_DAYS = 100        # 120 天裡至少要有 100 天有報酬，停牌太多的不分
DISTANCE_CUT = 0.80         # 距離 1−corr 小於這個才併成一群，相當於殘差相關 > 0.20
MIN_CLUSTER_SIZE = 5        # 不到 5 檔的群不算族群，族群平均會被單一檔主導


@dataclass
class MonthlyClusters:
    # labels[t, i]：第 t 天第 i 檔所屬的族群編號，-1 表示沒有族群
    labels: np.ndarray
    # 每次分群的摘要，給報告看分群本身合不合理
    summaries: list[dict]


def residual_returns(panel: PricePanel) -> np.ndarray:
    """每天的報酬減掉當天全市場平均。公司行動跳動那天當作缺值。"""
    close = panel.close
    previous = np.vstack([np.full((1, close.shape[1]), np.nan), close[:-1]])
    returns = close / previous - 1
    returns[panel.jump] = np.nan
    market = np.nanmean(returns, axis=1, keepdims=True)
    return returns - market


def _cluster_window(residuals: np.ndarray, eligible: np.ndarray) -> np.ndarray:
    """對一個 120 天窗口分群，回傳每檔的族群編號（不合格的是 -1）。"""
    labels = np.full(residuals.shape[1], -1)
    idx = np.where(eligible)[0]
    if len(idx) < MIN_CLUSTER_SIZE * 2:
        return labels

    window = residuals[:, idx]
    # 缺值補 0＝「那天跟大盤一樣」。已經篩過只留有效天數夠多的股票，補的量很少
    window = np.nan_to_num(window, nan=0.0)
    std = window.std(axis=0)
    keep = std > 0
    idx, window = idx[keep], window[:, keep]
    z = (window - window.mean(axis=0)) / window.std(axis=0)
    corr = (z.T @ z) / z.shape[0]
    np.clip(corr, -1.0, 1.0, out=corr)

    distance = 1.0 - corr
    np.fill_diagonal(distance, 0.0)
    tree = linkage(squareform(distance, checks=False), method="average")
    raw = fcluster(tree, t=DISTANCE_CUT, criterion="distance")

    ids, counts = np.unique(raw, return_counts=True)
    big = {cid for cid, n in zip(ids, counts) if n >= MIN_CLUSTER_SIZE}
    remap = {cid: k for k, cid in enumerate(sorted(big))}
    for position, cid in zip(idx, raw):
        if cid in remap:
            labels[position] = remap[cid]
    return labels


def monthly_clusters(panel: PricePanel, liquid: np.ndarray) -> MonthlyClusters:
    """每月第一個交易日重新分群，套用到當月。

    liquid 是流動性遮罩；分群日當天不夠流動的股票不分群。
    """
    residuals = residual_returns(panel)
    T, N = panel.shape
    labels = np.full((T, N), -1)
    summaries: list[dict] = []

    month_starts = [
        t for t in range(1, T)
        if (panel.dates[t].year, panel.dates[t].month)
        != (panel.dates[t - 1].year, panel.dates[t - 1].month)
    ]
    for m, start in enumerate(month_starts):
        if start < LOOKBACK_DAYS:
            continue
        end = month_starts[m + 1] if m + 1 < len(month_starts) else T
        history = residuals[start - LOOKBACK_DAYS:start]
        eligible = (np.isfinite(history).sum(axis=0) >= MIN_VALID_DAYS) & liquid[start]
        month_labels = _cluster_window(history, eligible)
        labels[start:end] = month_labels

        sizes = np.bincount(month_labels[month_labels >= 0]) if (month_labels >= 0).any() else np.array([])
        summaries.append(
            {
                "start": panel.dates[start],
                "eligible": int(eligible.sum()),
                "clustered": int((month_labels >= 0).sum()),
                "cluster_count": int(len(sizes)),
                "largest": int(sizes.max()) if len(sizes) else 0,
                "median_size": float(np.median(sizes)) if len(sizes) else 0.0,
                "labels": month_labels,
                "start_index": start,
                "end_index": end,
            }
        )
    logger.info("monthly_clusters: 分群 %d 個月", len(summaries))
    return MonthlyClusters(labels=labels, summaries=summaries)


def out_of_sample_cohesion(panel: PricePanel, clusters: MonthlyClusters) -> dict:
    """分群到底有沒有抓到真的共同運動？拿**分群之後那個月**的資料來檢查。

    在分群用的那 120 天上，群內相關當然高——那是分群演算法自己挑出來的。
    有意義的問題是：下個月還是一起動嗎？如果群內相關在樣本外掉回跟隨便
    兩檔差不多，分出來的就只是雜訊。
    """
    residuals = residual_returns(panel)
    within, overall = [], []
    for summary in clusters.summaries:
        s, e = summary["start_index"], summary["end_index"]
        labels = summary["labels"]
        members = np.where(labels >= 0)[0]
        if e - s < 10 or len(members) < 20:
            continue
        window = np.nan_to_num(residuals[s:e, members], nan=0.0)
        std = window.std(axis=0)
        ok = std > 0
        window, member_labels = window[:, ok], labels[members][ok]
        z = (window - window.mean(axis=0)) / window.std(axis=0)
        corr = (z.T @ z) / z.shape[0]
        upper = np.triu_indices_from(corr, k=1)
        same = member_labels[upper[0]] == member_labels[upper[1]]
        if same.any():
            within.append(float(corr[upper][same].mean()))
            overall.append(float(corr[upper].mean()))
    return {
        "months": len(within),
        "within_cluster_corr": float(np.mean(within)) if within else float("nan"),
        "all_pairs_corr": float(np.mean(overall)) if overall else float("nan"),
    }
