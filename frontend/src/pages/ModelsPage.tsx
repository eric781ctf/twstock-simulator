import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { ModelSummary } from "../types";

/** 訓練期的成績 vs 上線之後的成績。兩者不該擺在同一張卡上比較——一個是
 *  對歷史資料的量測，一個是實際跑出來的結果，混在一起看很容易誤讀。 */
type Tab = "training" | "live";

type SortKey = "recent" | "rank_ic" | "backtest_return" | "total_return" | "realized_return";

const SORT_OPTIONS: Record<Tab, { key: SortKey; label: string }[]> = {
  training: [
    { key: "recent", label: "建立時間（新到舊）" },
    { key: "rank_ic", label: "測試 Rank IC（高到低）" },
    { key: "backtest_return", label: "回測平均報酬（高到低）" },
  ],
  live: [
    { key: "recent", label: "建立時間（新到舊）" },
    { key: "total_return", label: "目前持有總損益率（高到低）" },
    { key: "realized_return", label: "已實現平均（高到低）" },
  ],
};

function formatPercent(value: number | null): string {
  if (value == null) return "-";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function formatNumber(value: number | null, digits = 4): string {
  if (value == null) return "-";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
}

/** 卡片上只要看得出是哪一天、大概幾點就夠，秒數與時區沒有意義 */
function formatCreatedAt(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "-";
  const d = new Date(t);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function returnClass(value: number | null): string {
  if (value == null) return "";
  return value >= 0 ? "buy-text" : "sell-text";
}

/** 缺值一律排到最後，不管升冪降冪。沒有量到的東西不該因為被當成 0
 *  就擠到中間，看起來像是「量過而且普通」。 */
function byDescending(get: (m: ModelSummary) => number | null) {
  return (a: ModelSummary, b: ModelSummary) => {
    const x = get(a);
    const y = get(b);
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    return y - x;
  };
}

const SORTERS: Record<SortKey, (a: ModelSummary, b: ModelSummary) => number> = {
  // 用時間戳比大小而不是字串比對：字串只有在格式完全一致時才排得對，
  // 時區寫法一變（+00:00 vs Z）順序就會悄悄跑掉
  recent: (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
  rank_ic: byDescending((m) => m.test_rank_ic),
  backtest_return: byDescending((m) => m.backtest_average_return_percent),
  total_return: byDescending((m) => m.total_unrealized_return_percent),
  realized_return: byDescending((m) => m.average_realized_return_percent),
};

export default function ModelsPage() {
  const [models, setModels] = useState<ModelSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("training");
  const [showArchived, setShowArchived] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("recent");

  useEffect(() => {
    api
      .getPublicModels()
      .then(setModels)
      .catch((err) => setError(err instanceof Error ? err.message : "載入失敗"));
  }, []);

  // 換分頁時排序選項也跟著換，先前選的鍵在新分頁可能不存在
  function switchTab(next: Tab) {
    setTab(next);
    if (!SORT_OPTIONS[next].some((o) => o.key === sortKey)) setSortKey("recent");
  }

  const archivedCount = models?.filter((m) => m.is_archived).length ?? 0;

  const visible = useMemo(() => {
    if (!models) return [];
    const filtered = showArchived ? models : models.filter((m) => !m.is_archived);
    return [...filtered].sort(SORTERS[sortKey]);
  }, [models, showArchived, sortKey]);

  return (
    <>
      <h2 className="section-title">模型列表</h2>
      <p className="empty-hint" style={{ marginBottom: 16 }}>
        每個模型每個交易日收盤後會對全部上市股票算分數，選出前 10 名標記為持有，之後依出場規則決定何時賣出。
        「訓練表現」是對歷史資料的量測，「實際表現」是上線之後真的跑出來的結果——兩者不能互相取代。
      </p>

      {error && <div className="error-msg">{error}</div>}

      <div className="model-list-toolbar">
        <div className="model-tabs">
          <button
            type="button"
            className={`model-tab ${tab === "training" ? "active" : ""}`}
            onClick={() => switchTab("training")}
          >
            訓練表現
          </button>
          <button
            type="button"
            className={`model-tab ${tab === "live" ? "active" : ""}`}
            onClick={() => switchTab("live")}
          >
            實際表現
          </button>
        </div>

        <div className="model-list-controls">
          {/* 每段文字都包在自己的 span 裡。裸文字節點在 flex 容器裡會變成匿名
              flex item，被壓縮時中文哪裡都能斷，「顯示已封存」會斷成三行 */}
          <label className="model-sort">
            <span>排序</span>
            <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)}>
              {SORT_OPTIONS[tab].map((o) => (
                <option key={o.key} value={o.key}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          {archivedCount > 0 && (
            <button
              type="button"
              className={`model-chip ${showArchived ? "active" : ""}`}
              aria-pressed={showArchived}
              onClick={() => setShowArchived((v) => !v)}
            >
              <span>含已封存</span>
              <span className="model-chip-count">{archivedCount}</span>
            </button>
          )}
        </div>
      </div>

      {models === null ? (
        <div className="empty-hint">載入中...</div>
      ) : visible.length === 0 ? (
        <div className="panel">
          <div className="empty-hint">
            {models.length === 0
              ? "目前還沒有訓練完成的模型"
              : "目前沒有未封存的模型，勾選「顯示已封存」看看"}
          </div>
        </div>
      ) : (
        <div className="model-card-list">
          {visible.map((m) => (
            <Link
              key={m.id}
              to={`/models/${m.id}`}
              className={`panel model-card ${m.is_archived ? "archived" : ""}`}
            >
              <div className="model-card-header">
                <span className="model-card-title">
                  {m.model_family} <span className="model-card-version">v{m.version}</span>
                </span>
                <span className="model-card-created">
                  建立於 {formatCreatedAt(m.created_at)}
                  {m.is_archived && <span className="archived-badge">已封存</span>}
                </span>
              </div>
              <div className="model-card-meta">
                {m.model_type}　預測未來 {m.n_days} 日　門檻 {m.threshold_percent}%
                {m.label_mode === "excess" && "　超額報酬"}
                {m.industry_neutral && "　產業中性化"}
              </div>

              {tab === "training" ? (
                <div className="model-card-stats">
                  <div className="stat">
                    <span className="label">測試 Rank IC</span>
                    <span className={`value ${returnClass(m.test_rank_ic)}`}>
                      {formatNumber(m.test_rank_ic)}
                      {m.test_rank_ic_std != null && (
                        <span className="value-suffix">± {m.test_rank_ic_std.toFixed(3)}</span>
                      )}
                    </span>
                  </div>
                  <div className="stat">
                    <span className="label">
                      {m.fold_count ? `${m.fold_count} 折為正` : "驗證方式"}
                    </span>
                    <span className="value">
                      {m.fold_count ? `${m.positive_folds ?? 0} / ${m.fold_count}` : "單次切分"}
                    </span>
                  </div>
                  <div className="stat">
                    <span className="label">回測平均報酬</span>
                    <span className={`value ${returnClass(m.backtest_average_return_percent)}`}>
                      {formatPercent(m.backtest_average_return_percent)}
                    </span>
                  </div>
                  <div className="stat">
                    <span className="label">
                      回測勝率
                      {m.backtest_holding_count ? `（${m.backtest_holding_count} 筆）` : ""}
                    </span>
                    <span className="value">
                      {m.backtest_win_rate != null ? `${(m.backtest_win_rate * 100).toFixed(1)}%` : "-"}
                    </span>
                  </div>
                </div>
              ) : (
                <div className="model-card-stats">
                  <div className="stat">
                    <span className="label">目前持有總損益率</span>
                    <span className={`value ${returnClass(m.total_unrealized_return_percent)}`}>
                      {formatPercent(m.total_unrealized_return_percent)}
                    </span>
                  </div>
                  <div className="stat">
                    <span className="label">已實現平均</span>
                    <span className={`value ${returnClass(m.average_realized_return_percent)}`}>
                      {formatPercent(m.average_realized_return_percent)}
                    </span>
                  </div>
                  <div className="stat">
                    <span className="label">持有中</span>
                    <span className="value">{m.open_holding_count}</span>
                  </div>
                  <div className="stat">
                    <span className="label">已平倉</span>
                    <span className="value">{m.closed_holding_count}</span>
                  </div>
                </div>
              )}
            </Link>
          ))}
        </div>
      )}

      {tab === "live" && (
        <p className="empty-hint" style={{ marginTop: 12 }}>
          總損益率是「目前持有部位的總市值 ÷ 總成本」，每檔各算一股，所以高價股的權重比較大；
          已實現平均則是每一筆平倉損益率的等權平均。兩個數字回答的問題不同，都已扣掉手續費與證交稅。
        </p>
      )}
    </>
  );
}
