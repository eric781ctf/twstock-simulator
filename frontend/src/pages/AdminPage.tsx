import { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../api";
import { BarChart } from "../components/BarChart";
import { useAuth } from "../auth/AuthContext";
import type {
  BackfillStatus,
  ChipStatus,
  DailyBarStats,
  IndustryStatus,
  SchedulerFlag,
  ShareholdingStatus,
} from "../types";

function formatWait(seconds: number): string {
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest === 0 ? `${minutes} 分` : `${minutes} 分 ${rest} 秒`;
}

// 這個系統已經沒有一般使用者帳號了，所以管理後台只留下跟「模型要用的資料」
// 有關的東西：TWSE 日K的回補進度與完整度。上櫃(TPEx)不在模型範圍內，
// 帳號啟動資金/加值/帳號列表都是舊的多使用者模擬器留下來的，不再顯示。
export default function AdminPage() {
  const { isAdmin } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [dailyBarStats, setDailyBarStats] = useState<DailyBarStats | null>(null);
  const [backfillStatus, setBackfillStatus] = useState<BackfillStatus | null>(null);
  const [backfillTargetInput, setBackfillTargetInput] = useState("");
  const [chipStatus, setChipStatus] = useState<ChipStatus | null>(null);
  const [chipTargetInput, setChipTargetInput] = useState("");
  const [shareholding, setShareholding] = useState<ShareholdingStatus | null>(null);
  const [industry, setIndustry] = useState<IndustryStatus | null>(null);
  const [dataBusy, setDataBusy] = useState(false);
  const [backfillBusy, setBackfillBusy] = useState(false);
  const [schedulers, setSchedulers] = useState<SchedulerFlag[]>([]);

  const refreshDailyBarStats = useCallback(async () => {
    const res = await api.getDailyBarStats();
    setDailyBarStats(res);
  }, []);

  const refreshBackfillStatus = useCallback(async () => {
    const res = await api.getBackfillStatus();
    setBackfillStatus(res);
  }, []);

  const refreshChipStatus = useCallback(async () => {
    setChipStatus(await api.getChipStatus());
  }, []);

  const refreshShareholding = useCallback(async () => {
    setShareholding(await api.getShareholdingStatus());
  }, []);

  const refreshIndustry = useCallback(async () => {
    setIndustry(await api.getIndustryStatus());
  }, []);

  const refreshSchedulers = useCallback(async () => {
    setSchedulers(await api.getModelSchedulers());
  }, []);

  const progress = backfillStatus?.progress ?? null;
  const isBackfillRunning =
    progress != null && ["preparing", "running", "throttling"].includes(progress.phase);

  useEffect(() => {
    if (!isAdmin) return;
    refreshDailyBarStats();
    refreshBackfillStatus();
    refreshChipStatus();
    refreshShareholding();
    refreshIndustry();
    refreshSchedulers();
  }, [
    isAdmin,
    refreshDailyBarStats,
    refreshBackfillStatus,
    refreshChipStatus,
    refreshShareholding,
    refreshIndustry,
    refreshSchedulers,
  ]);

  // 回補大多數時間都停在節流等待，狀態列要會自己動，不然使用者分不出來是
  // 系統卡住還是正在乖乖等。只在真的有任務在跑時輪詢，閒置時不用一直打。
  useEffect(() => {
    if (!isAdmin || !isBackfillRunning) return;
    const timer = setInterval(() => {
      refreshBackfillStatus();
      refreshChipStatus();
    }, 5000);
    return () => clearInterval(timer);
  }, [isAdmin, isBackfillRunning, refreshBackfillStatus, refreshChipStatus]);

  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }

  async function handleTriggerBackfill(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const months = Number(backfillTargetInput);
    if (!months || months <= 0) {
      setError("請輸入有效的月數");
      return;
    }
    setBackfillBusy(true);
    try {
      const res = await api.triggerBackfill(months);
      setBackfillStatus(res);
      setBackfillTargetInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "觸發回補失敗");
    } finally {
      setBackfillBusy(false);
    }
  }

  async function handleTriggerChipBackfill(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const months = Number(chipTargetInput);
    if (!months || months <= 0) {
      setError("請輸入有效的月數");
      return;
    }
    setBackfillBusy(true);
    try {
      setChipStatus(await api.triggerChipBackfill(months));
      setChipTargetInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "觸發回補失敗");
    } finally {
      setBackfillBusy(false);
    }
  }

  // 這三個都是「一次請求就結束」的同步，跟日K／籌碼面那種要跑幾十分鐘的
  // 回補不一樣，所以共用一個 busy 旗標、不需要進度輪詢。
  async function runDataAction<T>(action: () => Promise<T>, setter: (v: T) => void, fallback: string) {
    setError(null);
    setDataBusy(true);
    try {
      setter(await action());
    } catch (err) {
      setError(err instanceof Error ? err.message : fallback);
    } finally {
      setDataBusy(false);
    }
  }

  async function handleToggleScheduler(flag: SchedulerFlag) {
    const next = !flag.enabled;
    if (!window.confirm(`確定要${next ? "開啟" : "關閉"}「${flag.label}」嗎？

${flag.description}`)) return;

    setSchedulers((prev) => prev.map((f) => (f.key === flag.key ? { ...f, enabled: next } : f)));
    try {
      await api.setFeatureFlag(flag.key, next);
    } catch (err) {
      alert(err instanceof Error ? err.message : "切換失敗");
      await refreshSchedulers();
    }
  }

  return (
    <>
      <h2 className="section-title">管理後台</h2>

      {error && <div className="error-msg">{error}</div>}

      <form className="panel admin-action-card" onSubmit={handleTriggerBackfill}>
        <h2>TWSE 日K回補進度</h2>
        <p className="order-hint">
          目前本地上市股票日K最早回補到：
          <span className="admin-current-value">
            {backfillStatus ? (backfillStatus.earliest_date ?? "尚無資料") : "載入中..."}
          </span>
          　目前目標回補月數：
          <span className="admin-current-value">{backfillStatus ? backfillStatus.target_months : "-"}</span>
        </p>
        <p className="order-hint">
          設定新的目標月數後會在背景繼續往前補（僅 TWSE 上市，有限流保護，可能要跑一段時間）
        </p>

        <div className="admin-action-row">
          <input
            type="number"
            min={1}
            placeholder="目標月數"
            value={backfillTargetInput}
            onChange={(e) => setBackfillTargetInput(e.target.value)}
          />
          <button className="submit" type="submit" disabled={backfillBusy || isBackfillRunning}>
            {backfillBusy ? "觸發中..." : isBackfillRunning ? "回補進行中" : "繼續回補"}
          </button>
        </div>
      </form>

      <div className="panel admin-action-card">
        <h2>回補進度</h2>
        <p className="order-hint">
          日K與籌碼面共用同一個回補佇列，一次只跑一種——兩者都打 TWSE，同時跑只會讓請求密度加倍，
          正是節流想避免的事。
        </p>
    {progress && (
        <div className={`backfill-progress phase-${progress.phase}`}>
          <div className="backfill-progress-head">
            <span className="backfill-phase">
              <span className="backfill-dot" />
              {progress.job_label}：{progress.phase_label}
            </span>
            {isBackfillRunning && progress.total > 0 && (
              <span className="backfill-counts">
                本輪 {progress.processed}/{progress.total} 個交易日
              </span>
            )}
          </div>

          {isBackfillRunning && progress.total > 0 && (
            <div className="backfill-bar">
              <div
                className="backfill-bar-fill"
                style={{ width: `${Math.round((progress.processed / progress.total) * 100)}%` }}
              />
            </div>
          )}

          <div className="backfill-detail">
            {progress.phase === "running" && progress.current_target && (
              <>正在抓 {progress.current_target} 的全市場資料　已寫入 {progress.written_bars} 筆</>
            )}
            {progress.phase === "throttling" && (
              <>
                主動放慢請求速度（{progress.wait_reason}）
                {progress.wait_seconds_remaining != null && `　還要等 ${formatWait(progress.wait_seconds_remaining)}`}
              </>
            )}
            {progress.phase === "rate_limited" && <>{progress.message}</>}
            {(progress.phase === "completed" || progress.phase === "failed") && progress.message}
            {progress.phase === "idle" && <>目前沒有回補任務在跑</>}
            {progress.phase === "preparing" && <>正在盤點還有哪些日期需要回補</>}
          </div>
        </div>
      )}

      </div>

      <form className="panel admin-action-card" onSubmit={handleTriggerChipBackfill}>
        <h2>籌碼面資料</h2>
        <p className="order-hint">
          三大法人買賣超與融資融券餘額，來自 TWSE 每日公開的 T86 與 MI_MARGN。
          目前涵蓋：
          <span className="admin-current-value">
            {chipStatus ? (chipStatus.earliest_date ? `${chipStatus.earliest_date} ~ ${chipStatus.latest_date}` : "尚無資料") : "載入中..."}
          </span>
          　共
          <span className="admin-current-value">{chipStatus ? chipStatus.total_rows.toLocaleString() : "-"}</span>
          筆
        </p>
        <p className="order-hint">
          籌碼面要跟日K涵蓋同一段期間，模型才用得上——只補近期的話，訓練期大部分的樣本這些特徵都會是空的。
          一天要打兩支端點，所以比日K慢一倍。
        </p>
        <div className="admin-action-row">
          <input
            type="number"
            min={1}
            placeholder="目標月數"
            value={chipTargetInput}
            onChange={(e) => setChipTargetInput(e.target.value)}
          />
          <button className="submit" type="submit" disabled={backfillBusy || isBackfillRunning}>
            {backfillBusy ? "觸發中..." : isBackfillRunning ? "回補進行中" : "回補籌碼面"}
          </button>
        </div>
      </form>

      <div className="panel admin-action-card">
        <h2>集保股權分散表</h2>
        <p className="order-hint">
          每週五的持股分級快照（TDCC），用來算大戶／散戶籌碼流向。目前涵蓋：
          <span className="admin-current-value">
            {shareholding
              ? shareholding.earliest_date
                ? `${shareholding.earliest_date} ~ ${shareholding.latest_date}`
                : "尚無資料"
              : "載入中..."}
          </span>
          　共
          <span className="admin-current-value">{shareholding ? shareholding.week_count : "-"}</span>
          週、
          <span className="admin-current-value">{shareholding ? shareholding.total_rows.toLocaleString() : "-"}</span>
          筆
        </p>
        <p className="order-hint">
          TDCC 的線上端點<strong>只提供最新一週</strong>，沒有歷史查詢——所以歷史只能靠先前存下來的
          CSV 匯入（放在 backend/tdcc_data/），之後每週由「抓最新一週」接著累積。
        </p>
        {shareholding?.message && <p className="order-hint">{shareholding.message}</p>}
        <div className="admin-action-row">
          <button
            className="submit"
            type="button"
            disabled={dataBusy}
            onClick={() => runDataAction(api.importShareholding, setShareholding, "匯入失敗")}
          >
            {dataBusy ? "處理中..." : "匯入本機 CSV"}
          </button>
          <button
            className="submit"
            type="button"
            disabled={dataBusy}
            onClick={() => runDataAction(api.fetchShareholding, setShareholding, "抓取失敗")}
          >
            {dataBusy ? "處理中..." : "抓最新一週"}
          </button>
        </div>
      </div>

      <div className="panel admin-action-card">
        <h2>產業別</h2>
        <p className="order-hint">
          來自 TWSE 上市公司基本資料，用來做特徵的「產業中性化」——把每個特徵減掉當天同產業的
          中位數，剩下的才是這檔相對同業的強弱，避免整個族群同漲同跌被當成個股訊號。目前已分類：
          <span className="admin-current-value">
            {industry ? `${industry.classified} / ${industry.total_stocks}` : "載入中..."}
          </span>
          　共
          <span className="admin-current-value">{industry ? industry.industry_count : "-"}</span>
          個產業
        </p>
        <p className="order-hint">
          這支端點給的是<strong>現在</strong>的分類，拿不到歷史，所以早期樣本是用現況回推的。
          產業別極少變動，這個近似可以接受，但要知道有這件事。ETF 與受益證券本來就沒有產業別。
        </p>
        {industry && industry.top_industries.length > 0 && (
          <p className="order-hint">
            檔數最多：{industry.top_industries.map((i) => `${i.label} ${i.count}`).join("、")}
          </p>
        )}
        {industry?.message && <p className="order-hint">{industry.message}</p>}
        <div className="admin-action-row">
          <button
            className="submit"
            type="button"
            disabled={dataBusy}
            onClick={() => runDataAction(api.syncIndustries, setIndustry, "同步失敗")}
          >
            {dataBusy ? "處理中..." : "同步產業別"}
          </button>
        </div>
      </div>

      <div className="panel">
        <h2>排程開關</h2>
        <p className="order-hint">只列出跟預測模型有關的排程，關閉會立即生效，不需要重新部署</p>
        {schedulers.length === 0 ? (
          <div className="empty-hint">載入中...</div>
        ) : (
          schedulers.map((flag) => (
            <div className="scheduler-flag-row" key={flag.key}>
              <div className="scheduler-flag-info">
                <span className="scheduler-flag-name">{flag.label}</span>
                <span className="scheduler-flag-desc">{flag.description}</span>
              </div>
              <label className="toggle-switch">
                <input type="checkbox" checked={flag.enabled} onChange={() => handleToggleScheduler(flag)} />
                <span className="toggle-switch-slider" />
              </label>
            </div>
          ))
        )}
      </div>

      <div className="panel">
        <h2>上市（TWSE）日K資料完整度</h2>
        {dailyBarStats ? (
          <>
            <div className="stats-summary-row">
              <div className="stat">
                <span className="label">股票總數</span>
                <span className="value">{dailyBarStats.twse.total_stocks.toLocaleString()}</span>
              </div>
              <div className="stat">
                <span className="label">已回補</span>
                <span className="value" style={{ color: "var(--sell)" }}>
                  {dailyBarStats.twse.sufficient.toLocaleString()}
                </span>
              </div>
              <div className="stat">
                <span className="label">未回補</span>
                <span className="value" style={{ color: "var(--buy)" }}>
                  {dailyBarStats.twse.insufficient.toLocaleString()}
                </span>
              </div>
            </div>
            <p className="order-hint">依「目前累積的日K筆數」分布，40 筆以上視為已回補足夠資料</p>
            <BarChart buckets={dailyBarStats.twse.buckets} />
          </>
        ) : (
          <div className="empty-hint">載入中...</div>
        )}
      </div>
    </>
  );
}
