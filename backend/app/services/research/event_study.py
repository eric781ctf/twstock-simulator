"""階段 1 事件研究：VCP 收斂突破與族群聯動，在台股 2021–2026 到底有沒有用。

不訓練模型。對每一個訊號，直接量「訊號成立之後的報酬」跟「同一天全市場」比
差多少。回答的問題只有一個：這個訊號本身有沒有資訊，還有它是不是只在多頭年
有用。

**執行假設跟 next_open 模式一致**：訊號在 D 日收盤確認，D+1 開盤買進，持有
h 個交易日後在開盤賣出。開盤跳空漲停（≥ 9.5%）的樣本視為買不到，直接排除。

**基準線**：同一天、同樣流動性門檻、同樣買得到的全部普通股的平均報酬。超額
報酬＝訊號股的報酬減這個平均，所以大盤漲跌已經扣掉了。

**統計**：同一天常常有很多檔同時觸發，它們的報酬高度相關，不能當成獨立樣本。
所以先把每一天的事件平均成一個數字，再對「每天一個數字」的序列算 t 值；持有
期會重疊，t 值用 Newey-West 修正（lag＝持有天數）。對稀疏事件而言這個 lag 是
近似值，因為事件日之間不一定相鄰。

**多重比較**：這裡同時測十幾個訊號 × 三個持有期。測得越多，靠運氣出現一個
t > 2 的機會越高。參考 Harvey, Liu & Zhu (2016, Review of Financial Studies)
的建議，t > 3 才當成值得追下去的訊號。

執行：docker compose exec -e PYTHONPATH=/app backend python -m app.services.research.event_study
"""

import json
import logging
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from app.config import settings
from app.database import SessionLocal
from app.services.research import clusters as cluster_mod
from app.services.research import vcp
from app.services.research.panel import (
    LIMIT_UP_THRESHOLD,
    PricePanel,
    jump_in_window,
    liquidity_mask,
    load_panel,
    shift,
)

logger = logging.getLogger(__name__)

HORIZONS = (5, 10, 20)
START = date(2021, 1, 1)             # VCP 需要 250 天暖身，全部訊號從同一天起算才可比
MIN_VALUE_TRADED = 10_000_000        # 20 日平均成交值至少一千萬台幣
EVENT_COOLDOWN = 20                  # 同一檔 20 天內的重複突破只算第一次
TOP_FRACTION = 0.2                   # 「強勢」＝排名前 20%
T_THRESHOLD = 3.0                    # 多重比較之下的門檻
ROUND_TRIP_COST = (settings.commission_rate * 2 + settings.tax_rate) * 100

OUTPUT = Path("/app/model_artifacts/research/event_study.json")


@dataclass
class Signal:
    key: str
    family: str
    label: str
    mask: np.ndarray
    # event＝稀疏事件（突破）；state＝每天都有一批成立的狀態（強勢族群）
    kind: str


# ── 報酬 ──────────────────────────────────────────────────────────────

def forward_returns(panel: PricePanel, h: int, liquid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """回傳 (原始報酬%, 可交易遮罩)。進場 D+1 開盤、出場 D+1+h 開盤。"""
    entry = shift(panel.open, -1)
    exit_ = shift(panel.open, -(1 + h))
    settled = settle_delisted_exits(panel, exit_, h)
    if settled:
        logger.info("持有 %d 天：%d 個樣本的持有期跨過下市日，用最後收盤價結算", h, settled)
    with np.errstate(invalid="ignore", divide="ignore"):
        raw = (exit_ / entry - 1) * 100
        gap = entry / panel.close - 1
    tradable = (
        np.isfinite(raw)
        & liquid
        & ~(gap >= LIMIT_UP_THRESHOLD)          # 開盤鎖漲停，買不到
        & ~jump_in_window(panel, 1, 1 + h)      # 持有期間有公司行動，報酬不可信
    )
    return raw, tradable


def settle_delisted_exits(panel: PricePanel, exit_: np.ndarray, h: int) -> int:
    """持有期跨過下市日的樣本，出場價改用最後一個交易日的收盤價（就地修改）。

    不處理的話，出場日沒有價格 → 報酬是 NaN → 整筆被當成「不可交易」丟掉，
    被丟掉的剛好是持有到下市的那一批。最後收盤價對併購下市（收購價附近成交）
    是好的近似；對全額交割後停止買賣的，實際能拿回的通常更少，所以這樣算
    仍然偏樂觀，只是比整筆丟掉誠實得多。

    只處理「進場時還有價格、出場日落在最後一根 K 棒之後、而且出場日沒有超出
    面板尾端」的樣本；面板尾端本來就沒有未來價格，那跟下市無關。回傳結算筆數。
    """
    T = exit_.shape[0]
    settled = 0
    for i in np.flatnonzero(panel.delisted):
        traded = np.flatnonzero(np.isfinite(panel.close[:, i]))
        if len(traded) == 0 or traded[-1] >= T - 1:
            continue
        last = traded[-1]
        # 訊號日 t：進場 t+1 ≤ last，出場 t+1+h > last，且出場日仍在面板內
        days = np.arange(max(last - h, 0), min(last, T - 1 - h))
        days = days[~np.isfinite(exit_[days, i])]
        exit_[days, i] = panel.close[last, i]
        settled += len(days)
    return settled


def lookback_returns(panel: PricePanel, days: int) -> np.ndarray:
    """過去 days 天的收盤報酬，期間有公司行動的設為 NaN。"""
    with np.errstate(invalid="ignore", divide="ignore"):
        out = panel.close / shift(panel.close, days) - 1
    out[jump_in_window(panel, -(days - 1), 0)] = np.nan
    return out


def cross_section_rank(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """每一天在 valid 範圍內的百分位排名（0~1）。"""
    ranks = np.full(values.shape, np.nan)
    for t in range(values.shape[0]):
        ok = valid[t] & np.isfinite(values[t])
        n = ok.sum()
        if n < 20:
            continue
        ranks[t, ok] = values[t, ok].argsort().argsort() / (n - 1)
    return ranks


# ── 族群 ──────────────────────────────────────────────────────────────

def group_signals(panel: PricePanel, labels: np.ndarray, liquid: np.ndarray) -> dict[str, np.ndarray]:
    """算出族群類訊號的遮罩。

    族群報酬＝同族群、當天有效的成員平均。族群排名是在「當天有效的族群」
    之間排，至少要有 3 檔有效成員的族群才參與排名。
    """
    T, N = panel.shape
    r1 = lookback_returns(panel, 1)
    r5 = lookback_returns(panel, 5)
    r20 = lookback_returns(panel, 20)

    def group_mean_and_rank(stock_returns: np.ndarray):
        member_mean = np.full((T, N), np.nan)
        group_rank = np.full((T, N), np.nan)
        for t in range(T):
            lab = labels[t]
            ok = (lab >= 0) & np.isfinite(stock_returns[t]) & liquid[t]
            if ok.sum() < 20:
                continue
            k = lab.max() + 1
            sums = np.bincount(lab[ok], weights=stock_returns[t, ok], minlength=k)
            counts = np.bincount(lab[ok], minlength=k)
            active = counts >= 3
            if active.sum() < 5:
                continue
            means = np.where(active, sums / np.maximum(counts, 1), np.nan)
            order = np.full(k, np.nan)
            active_ids = np.where(active)[0]
            order[active_ids] = means[active_ids].argsort().argsort() / (len(active_ids) - 1)
            has_group = lab >= 0
            member_mean[t, has_group] = means[lab[has_group]]
            group_rank[t, has_group] = order[lab[has_group]]
        return member_mean, group_rank

    g1, rank1 = group_mean_and_rank(r1)
    g5, rank5 = group_mean_and_rank(r5)
    g20, rank20 = group_mean_and_rank(r20)
    top = 1 - TOP_FRACTION

    with np.errstate(invalid="ignore"):
        return {
            "G1": rank5 >= top,
            "G1_weak": rank5 <= TOP_FRACTION,
            "G2": rank20 >= top,
            "G3": (rank5 >= top) & (r5 < g5),
            "G4": (rank5 >= top) & (r5 >= g5),
            "G5": (rank1 >= top) & (r1 < g1),
        }


# ── 統計 ──────────────────────────────────────────────────────────────

def newey_west_t(series: np.ndarray, lag: int) -> float:
    n = len(series)
    if n < 10:
        return float("nan")
    mean = series.mean()
    x = series - mean
    variance = (x @ x) / n
    for k in range(1, min(lag, n - 1) + 1):
        weight = 1 - k / (lag + 1)
        variance += 2 * weight * (x[k:] @ x[:-k]) / n
    if variance <= 0:
        return float("nan")
    return float(mean / np.sqrt(variance / n))


def evaluate(signal: Signal, raw: np.ndarray, tradable: np.ndarray, h: int, years: np.ndarray, start_index: int) -> dict:
    T = raw.shape[0]
    benchmark = np.full(T, np.nan)
    rows = signal.mask & tradable
    for t in range(T):
        if tradable[t].sum() >= 50:
            benchmark[t] = raw[t, tradable[t]].mean()

    daily_excess, daily_raw, day_years, day_index = [], [], [], []
    wins = events = 0
    for t in range(start_index, T):
        if not np.isfinite(benchmark[t]):
            continue
        hit = rows[t]
        n = hit.sum()
        if n == 0:
            continue
        excess = raw[t, hit] - benchmark[t]
        daily_excess.append(excess.mean())
        daily_raw.append(raw[t, hit].mean())
        day_years.append(years[t])
        day_index.append(t)
        wins += int((excess > 0).sum())
        events += int(n)

    if not daily_excess:
        return {"events": 0}
    daily_excess = np.array(daily_excess)
    daily_raw = np.array(daily_raw)
    day_years = np.array(day_years)
    day_index = np.array(day_index)

    # 保守對照：每 h 天只取一天，持有期完全不重疊，用最普通的 t 值。
    # 只對「狀態」訊號有意義——它每天都有樣本，抽樣後還剩夠多天；稀疏事件
    # 抽完幾乎不剩
    t_non_overlap = float("nan")
    if signal.kind == "state":
        sampled = daily_excess[(day_index - start_index) % h == 0]
        if len(sampled) >= 10:
            t_non_overlap = float(sampled.mean() / (sampled.std(ddof=1) / np.sqrt(len(sampled))))

    by_year = {}
    for year in sorted(set(day_years.tolist())):
        sel = day_years == year
        by_year[int(year)] = {
            "days": int(sel.sum()),
            "excess": float(daily_excess[sel].mean()),
        }

    return {
        "events": events,
        "days": int(len(daily_excess)),
        "excess": float(daily_excess.mean()),
        "t": newey_west_t(daily_excess, h),
        "t_non_overlap": t_non_overlap,
        "win_rate": wins / events,
        "raw": float(daily_raw.mean()),
        # 扣的是「超額」而不是原始報酬：策略要跟買大盤不動比，而買大盤不動
        # 幾乎不付交易成本。原始報酬扣成本會把大盤漲幅也算成策略的功勞
        "excess_net": float(daily_excess.mean() - ROUND_TRIP_COST),
        "by_year": by_year,
    }


# ── 主流程 ────────────────────────────────────────────────────────────

def build_signals(panel: PricePanel, liquid: np.ndarray) -> tuple[list[Signal], dict]:
    t0 = time.perf_counter()
    structure, strength = vcp.trend_template_parts(panel)
    template = structure & strength
    contraction = vcp.contraction(panel)
    dryup = vcp.volume_dryup(panel)
    breakout = vcp.breakout(panel)
    logger.info("VCP 部件算完，%.0f 秒", time.perf_counter() - t0)

    def event(mask):
        return vcp.first_occurrence(mask & liquid, EVENT_COOLDOWN)

    clusters = cluster_mod.monthly_clusters(panel, liquid)
    cohesion = cluster_mod.out_of_sample_cohesion(panel, clusters)
    groups = group_signals(panel, clusters.labels, liquid)
    logger.info("族群訊號算完，%.0f 秒", time.perf_counter() - t0)

    r5 = lookback_returns(panel, 5)
    r20 = lookback_returns(panel, 20)
    top = 1 - TOP_FRACTION
    with np.errstate(invalid="ignore"):
        s5 = cross_section_rank(r5, liquid) >= top
        s20 = cross_section_rank(r20, liquid) >= top

    signals = [
        Signal("V0", "VCP", "趨勢模板成立（狀態）", template & liquid, "state"),
        # 以下兩個是看到 V0 顯著之後才加的分解，只用來解釋 V0，不是事前宣告的假說
        Signal("V0a", "VCP", "〔事後拆解〕只看均線結構（模板前 7 項）", structure & liquid, "state"),
        Signal("V0b", "VCP", "〔事後拆解〕只看相對強度前 30%", strength & liquid, "state"),
        Signal("V1", "VCP", "帶量突破（不看其他條件）", event(breakout), "event"),
        Signal("V2", "VCP", "趨勢模板＋帶量突破", event(template & breakout), "event"),
        Signal("V3", "VCP", "完整 VCP：模板＋收斂＋量縮＋突破", event(template & contraction & dryup & breakout), "event"),
        Signal("G1", "族群", "強勢族群成員（族群 5 日前 20%）", groups["G1"], "state"),
        Signal("G1_weak", "族群", "弱勢族群成員（族群 5 日後 20%）", groups["G1_weak"], "state"),
        Signal("G2", "族群", "強勢族群成員（族群 20 日前 20%）", groups["G2"], "state"),
        Signal("G3", "族群", "強勢族群裡的落後者（5 日）", groups["G3"], "state"),
        Signal("G4", "族群", "強勢族群裡的領頭者（5 日）", groups["G4"], "state"),
        Signal("G5", "族群", "族群昨天大漲、自己沒跟上", groups["G5"], "state"),
        Signal("S1", "對照", "個股 5 日報酬前 20%（不看族群）", s5, "state"),
        Signal("S2", "對照", "個股 20 日報酬前 20%（不看族群）", s20, "state"),
    ]
    cluster_info = {
        "months": len(clusters.summaries),
        "median_cluster_count": float(np.median([s["cluster_count"] for s in clusters.summaries])),
        "median_largest": float(np.median([s["largest"] for s in clusters.summaries])),
        "coverage": float(np.mean([s["clustered"] / max(s["eligible"], 1) for s in clusters.summaries])),
        **cohesion,
    }
    return signals, cluster_info


def run() -> dict:
    started = time.perf_counter()
    with SessionLocal() as db:
        panel = load_panel(db)
    liquid = liquidity_mask(panel, MIN_VALUE_TRADED)
    years = panel.year_of()
    start_index = next(i for i, d in enumerate(panel.dates) if d >= START)

    signals, cluster_info = build_signals(panel, liquid)

    results: dict = {"signals": {}, "clusters": cluster_info}
    for h in HORIZONS:
        raw, tradable = forward_returns(panel, h, liquid)
        for signal in signals:
            outcome = evaluate(signal, raw, tradable, h, years, start_index)
            results["signals"].setdefault(signal.key, {
                "family": signal.family, "label": signal.label, "kind": signal.kind, "horizons": {},
            })["horizons"][h] = outcome
        logger.info("持有 %d 天評估完成", h)

    results["meta"] = {
        "start": str(panel.dates[start_index]),
        "end": str(panel.dates[-1]),
        "stocks": panel.shape[1],
        "round_trip_cost_percent": ROUND_TRIP_COST,
        "seconds": time.perf_counter() - started,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return results


def report(results: dict) -> str:
    lines = []
    meta = results["meta"]
    lines.append(f"期間 {meta['start']} ~ {meta['end']}，普通股 {meta['stocks']} 檔，來回成本 {meta['round_trip_cost_percent']:.3f}%")
    c = results["clusters"]
    lines.append(
        f"分群：{c['months']} 個月，每月族群數中位 {c['median_cluster_count']:.0f}，最大群中位 {c['median_largest']:.0f} 檔，"
        f"有歸屬 {c['coverage']*100:.0f}%，樣本外群內相關 {c['within_cluster_corr']:.3f} vs 任兩檔 {c['all_pairs_corr']:.3f}"
    )
    lines.append("")
    header = (f"{'代號':6s} {'訊號':36s} {'持有':>4s} {'事件數':>8s} {'日數':>5s} {'超額%':>7s} "
              f"{'t(NW)':>6s} {'t不重疊':>7s} {'勝率':>6s} {'原始%':>7s} {'超額扣成本%':>10s}")
    lines.append(header)
    for key, sig in results["signals"].items():
        for h, r in sig["horizons"].items():
            if not r.get("events"):
                lines.append(f"{key:6s} {sig['label']:36s} {h:>4} {'0':>8s}")
                continue
            flag = " ◀" if abs(r["t"]) >= T_THRESHOLD else ""
            t_no = r["t_non_overlap"]
            t_no_text = f"{t_no:>+7.2f}" if np.isfinite(t_no) else f"{'-':>7s}"
            lines.append(
                f"{key:6s} {sig['label']:36s} {h:>4} {r['events']:>8d} {r['days']:>5d} "
                f"{r['excess']:>+7.3f} {r['t']:>+6.2f} {t_no_text} {r['win_rate']*100:>5.1f}% "
                f"{r['raw']:>+7.3f} {r['excess_net']:>+10.3f}{flag}"
            )
        lines.append("")

    years = sorted({y for sig in results["signals"].values() for y in sig["horizons"][10].get("by_year", {})})
    lines.append("逐年超額報酬%（持有 10 天）")
    lines.append(f"{'代號':6s} " + " ".join(f"{y:>8d}" for y in years))
    for key, sig in results["signals"].items():
        by_year = sig["horizons"][10].get("by_year", {})
        cells = []
        for y in years:
            v = by_year.get(y) or by_year.get(str(y))
            cells.append(f"{v['excess']:>+8.3f}" if v else f"{'-':>8s}")
        lines.append(f"{key:6s} " + " ".join(cells))
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    print(report(run()))
