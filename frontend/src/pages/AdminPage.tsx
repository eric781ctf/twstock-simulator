import { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth/AuthContext";
import type { AdminAccount } from "../types";

export default function AdminPage() {
  const { isAdmin } = useAuth();
  const [accounts, setAccounts] = useState<AdminAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [resetAmount, setResetAmount] = useState("");
  const [addAmount, setAddAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const res = await api.getAdminAccounts();
    setAccounts(res);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    refresh();
  }, [isAdmin, refresh]);

  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }

  async function handleResetCash(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const amount = Number(resetAmount);
    if (!amount || amount <= 0) {
      setError("請輸入有效金額");
      return;
    }
    setBusy(true);
    try {
      await api.resetAllCash(amount);
      setResetAmount("");
      await refresh();
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

  return (
    <>
      <h2 className="section-title">管理後台</h2>

      <div className="admin-actions">
        <form className="panel admin-action-card" onSubmit={handleResetCash}>
          <h2>設定所有帳戶啟動資金</h2>
          <p className="order-hint">將所有一般帳戶的現金餘額直接設定為以下金額</p>
          <div className="admin-action-row">
            <input
              type="number"
              placeholder="金額"
              value={resetAmount}
              onChange={(e) => setResetAmount(e.target.value)}
            />
            <button className="submit" type="submit" disabled={busy}>
              設定
            </button>
          </div>
        </form>

        <form className="panel admin-action-card" onSubmit={handleAddCash}>
          <h2>為所有帳戶加值</h2>
          <p className="order-hint">為每個一般帳戶的現金餘額增加以下金額</p>
          <div className="admin-action-row">
            <input type="number" placeholder="金額" value={addAmount} onChange={(e) => setAddAmount(e.target.value)} />
            <button className="submit" type="submit" disabled={busy}>
              加值
            </button>
          </div>
        </form>
      </div>

      {error && <div className="error-msg">{error}</div>}

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
