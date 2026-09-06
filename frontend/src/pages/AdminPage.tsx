import { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../api";
import { BarChart } from "../components/BarChart";
import { useAuth } from "../auth/AuthContext";
import type { BackfillStatus, DailyBarStats, SchedulerFlag } from "../types";

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
    refreshSchedulers();
  }, [isAdmin, refreshDailyBarStats, refreshBackfillStatus, refreshSchedulers]);

  // 回補大多數時間都停在節流等待，狀態列要會自己動，不然使用者分不出來是
  // 系統卡住還是正在乖乖等。只在真的有任務在跑時輪詢，閒置時不用一直打。
  useEffect(() => {
    if (!isAdmin || !isBackfillRunning) return;
    const timer = setInterval(refreshBackfillStatus, 5000);
    return () => clearInterval(timer);
  }, [isAdmin, isBackfillRunning, refreshBackfillStatus]);

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

        {progress && (
          <div className={`backfill-progress phase-${progress.phase}`}>
            <div className="backfill-progress-head">
              <span className="backfill-phase">
                <span className="backfill-dot" />
                {progress.phase_label}
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
                <>正在抓 {progress.current_target} 的全市場收盤資料　已寫入 {progress.written_bars} 筆日K</>
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
