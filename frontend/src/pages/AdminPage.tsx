import { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../api";
import { AmountInput } from "../components/AmountInput";
import { BarChart } from "../components/BarChart";
import { useAuth } from "../auth/AuthContext";
import type { AdminAccount, DailyBarStats, FeatureFlag } from "../types";

export default function AdminPage() {
  const { isAdmin } = useAuth();
  const [accounts, setAccounts] = useState<AdminAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [defaultInitialCash, setDefaultInitialCashState] = useState<number | null>(null);
  const [resetAmount, setResetAmount] = useState("");
  const [addAmount, setAddAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dailyBarStats, setDailyBarStats] = useState<DailyBarStats | null>(null);
  const [featureFlags, setFeatureFlags] = useState<FeatureFlag[]>([]);

  const refresh = useCallback(async () => {
    const res = await api.getAdminAccounts();
    setAccounts(res);
    setLoading(false);
  }, []);

  const refreshDefaultCash = useCallback(async () => {
    const res = await api.getDefaultInitialCash();
    setDefaultInitialCashState(res.amount);
  }, []);

  const refreshDailyBarStats = useCallback(async () => {
    const res = await api.getDailyBarStats();
    setDailyBarStats(res);
  }, []);

  const refreshFeatureFlags = useCallback(async () => {
    const res = await api.getAdminFeatureFlags();
    setFeatureFlags(res);
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    refresh();
    refreshDefaultCash();
    refreshDailyBarStats();
    refreshFeatureFlags();
  }, [isAdmin, refresh, refreshDefaultCash, refreshDailyBarStats, refreshFeatureFlags]);

  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }

  async function handleSetDefaultCash(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const amount = Number(resetAmount);
    if (!amount || amount <= 0) {
      setError("請輸入有效金額");
      return;
    }
    setBusy(true);
    try {
      await api.setDefaultInitialCash(amount);
      setResetAmount("");
      await refreshDefaultCash();
    } catch (err) {
      setError(err instanceof Error ? err.message : "設定失敗");
    } finally {
      setBusy(false);
    }
  }

  async function handleAddCash(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const amount = Number(addAmount);
    if (!amount || amount <= 0) {
      setError("請輸入有效金額");
      return;
    }
    setBusy(true);
    try {
      await api.addCashToAll(amount);
      setAddAmount("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "加值失敗");
    } finally {
      setBusy(false);
    }
  }

  async function handleFreeze(userId: number, nickname: string) {
    if (!window.confirm(`確定要凍結「${nickname}」一天嗎？`)) return;
    try {
      await api.freezeAccount(userId);
      await refresh();
    } catch (err) {
      alert(err instanceof Error ? err.message : "凍結失敗");
    }
  }

  async function handleDelete(userId: number, nickname: string) {
    if (!window.confirm(`確定要刪除「${nickname}」的帳號嗎？此操作無法復原。`)) return;
    try {
      await api.deleteAccount(userId);
      await refresh();
    } catch (err) {
      alert(err instanceof Error ? err.message : "刪除失敗");
    }
  }

  async function handleToggleFlag(flag: FeatureFlag) {
    const next = !flag.enabled;
    const action = next ? "開啟" : "關閉";
    if (!window.confirm(`確定要${action}「${flag.label}」嗎？`)) return;

    setFeatureFlags((prev) => prev.map((f) => (f.key === flag.key ? { ...f, enabled: next } : f)));
    try {
      await api.setFeatureFlag(flag.key, next);
    } catch (err) {
      alert(err instanceof Error ? err.message : "切換失敗");
      await refreshFeatureFlags();
    }
  }

  return (
    <>
      <h2 className="section-title">管理後台</h2>

      <div className="admin-actions">
        <form className="panel admin-action-card" onSubmit={handleSetDefaultCash}>
          <h2>新帳號啟動資金</h2>
          <p className="order-hint">
            目前預設值：
            <span className="admin-current-value">
              {defaultInitialCash != null ? defaultInitialCash.toLocaleString() : "載入中..."}
            </span>
            　只影響之後新註冊的帳號，不會更動現有帳戶的餘額
          </p>
          <div className="admin-action-row">
            <AmountInput placeholder="金額" value={resetAmount} onChange={setResetAmount} />
            <button className="submit" type="submit" disabled={busy}>
              設定
            </button>
          </div>
        </form>

        <form className="panel admin-action-card" onSubmit={handleAddCash}>
          <h2>為所有帳戶加值</h2>
          <p className="order-hint">為每個一般帳戶的現金餘額增加以下金額</p>
          <div className="admin-action-row">
            <AmountInput placeholder="金額" value={addAmount} onChange={setAddAmount} />
            <button className="submit" type="submit" disabled={busy}>
              加值
            </button>
          </div>
        </form>
      </div>

      {error && <div className="error-msg">{error}</div>}

      <div className="stats-section">
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

        <div className="panel">
          <h2>上櫃（TPEx）日K資料完整度</h2>
          {dailyBarStats ? (
            <>
              <div className="stats-summary-row">
                <div className="stat">
                  <span className="label">股票總數</span>
                  <span className="value">{dailyBarStats.tpex.total_stocks.toLocaleString()}</span>
                </div>
                <div className="stat">
                  <span className="label">已累積足夠</span>
                  <span className="value" style={{ color: "var(--sell)" }}>
                    {dailyBarStats.tpex.sufficient.toLocaleString()}
                  </span>
                </div>
                <div className="stat">
                  <span className="label">尚未足夠</span>
                  <span className="value" style={{ color: "var(--buy)" }}>
                    {dailyBarStats.tpex.insufficient.toLocaleString()}
                  </span>
                </div>
              </div>
              <p className="order-hint">上櫃沒有官方回補端點，只能逐日累積，數字只會越來越多</p>
              <BarChart buckets={dailyBarStats.tpex.buckets} />
            </>
          ) : (
            <div className="empty-hint">載入中...</div>
          )}
        </div>
      </div>

      <div className="panel">
        <h2>功能開關</h2>
        <p className="order-hint">關閉的功能會立即停用，不需要重新部署</p>
        {featureFlags.length === 0 ? (
          <div className="empty-hint">載入中...</div>
        ) : (
          featureFlags.map((flag) => (
            <div className="feature-flag-row" key={flag.key}>
              <span className="feature-flag-name">
                {flag.label}
                <span className="feature-flag-key">{flag.key}</span>
              </span>
              <label className="toggle-switch">
                <input type="checkbox" checked={flag.enabled} onChange={() => handleToggleFlag(flag)} />
                <span className="toggle-switch-slider" />
              </label>
            </div>
          ))
        )}
      </div>

      <div className="panel">
        <h2>所有帳戶</h2>
        {loading ? (
          <div className="empty-hint">載入中...</div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>暱稱</th>
                  <th>帳號</th>
                  <th>現金餘額</th>
                  <th>凍結資金</th>
                  <th>狀態</th>
                  <th>建立時間</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((a) => {
                  const isFrozen = a.frozen_until != null && new Date(a.frozen_until) > new Date();
                  return (
                    <tr key={a.user_id}>
                      <td style={{ textAlign: "left" }}>
                        {a.nickname}
                        {a.is_admin && <span className="admin-tag">管理員</span>}
                      </td>
                      <td>{a.username}</td>
                      <td>{a.cash_balance != null ? a.cash_balance.toLocaleString() : "-"}</td>
                      <td>{a.frozen_cash != null ? a.frozen_cash.toLocaleString() : "-"}</td>
                      <td>
                        {isFrozen ? (
                          <span className="frozen-badge">
                            凍結至 {new Date(a.frozen_until as string).toLocaleString("zh-TW", { hour12: false })}
                          </span>
                        ) : (
                          "正常"
                        )}
                      </td>
                      <td>{new Date(a.created_at).toLocaleDateString("zh-TW")}</td>
                      <td>
                        {!a.is_admin && (
                          <div className="admin-row-actions">
                            <span className="cancel-link" onClick={() => handleFreeze(a.user_id, a.nickname)}>
                              凍結一天
                            </span>
                            <span className="cancel-link danger-link" onClick={() => handleDelete(a.user_id, a.nickname)}>
                              刪除
                            </span>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
