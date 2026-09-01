import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { ConditionEditor } from "../components/ConditionEditor";
import type { Condition, RankBy, RankDirection, Strategy, StrategyInput, StrategyTradeRecord } from "../types";

const RANK_LABEL: Record<RankBy, string> = {
  change_percent: "當日漲跌幅",
  k_value: "K 值",
  d_value: "D 值",
  volume: "成交量",
};

const CONDITION_SUMMARY: Record<Condition["type"], (c: Condition) => string> = {
  kd_value: (c) => {
    const cond = c as Extract<Condition, { type: "kd_value" }>;
    const op = { gt: ">", lt: "<", gte: "≥", lte: "≤" }[cond.operator];
    return `${cond.line.toUpperCase()} 值 ${op} ${cond.value}`;
  },
  kd_cross: (c) => {
    const cond = c as Extract<Condition, { type: "kd_cross" }>;
    return cond.direction === "golden" ? "KD 黃金交叉" : "KD 死亡交叉";
  },
  ma_compare: (c) => {
    const cond = c as Extract<Condition, { type: "ma_compare" }>;
    return `${cond.fast}日均線 ${cond.operator === "gt" ? ">" : "<"} ${cond.slow}日均線`;
  },
  price_vs_ma: (c) => {
    const cond = c as Extract<Condition, { type: "price_vs_ma" }>;
    return `股價 ${cond.operator === "gt" ? ">" : "<"} ${cond.period}日均線`;
  },
  streak: (c) => {
    const cond = c as Extract<Condition, { type: "streak" }>;
    return `連續${cond.direction === "up" ? "上漲" : "下跌"} ${cond.days} 天`;
  },
  cumulative_change: (c) => {
    const cond = c as Extract<Condition, { type: "cumulative_change" }>;
    const op = cond.operator === "gte" ? "≥" : "≤";
    return `近 ${cond.days} 天累積漲跌幅 ${op} ${cond.percent}%`;
  },
};

function summarize(conditions: Condition[]): string {
  if (conditions.length === 0) return "（未設定）";
  return conditions.map((c) => CONDITION_SUMMARY[c.type](c)).join("、");
}

const EMPTY_FORM: StrategyInput = {
  name: "",
  quantity: 1,
  buy_conditions: [],
  sell_conditions: [],
  rank_by: "change_percent",
  rank_direction: "desc",
  top_n: 1,
};

export default function StrategyPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<StrategyInput>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tradesFor, setTradesFor] = useState<number | null>(null);
  const [trades, setTrades] = useState<StrategyTradeRecord[]>([]);

  const refresh = useCallback(async () => {
    const res = await api.getStrategies();
    setStrategies(res);
    setLoading(false);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  function openNewForm() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setError(null);
    setFormOpen(true);
  }

  function openEditForm(strategy: Strategy) {
    setEditingId(strategy.id);
    setForm({
      name: strategy.name,
      quantity: strategy.quantity,
      buy_conditions: strategy.buy_conditions,
      sell_conditions: strategy.sell_conditions,
      rank_by: strategy.rank_by,
      rank_direction: strategy.rank_direction,
      top_n: strategy.top_n,
    });
    setError(null);
    setFormOpen(true);
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.name.trim()) {
      setError("請輸入策略名稱");
      return;
    }
    if (form.buy_conditions.length === 0 && form.sell_conditions.length === 0) {
      setError("至少要設定一個買進或賣出條件");
      return;
    }
    setBusy(true);
    try {
      if (editingId != null) {
        await api.updateStrategy(editingId, form);
      } else {
        await api.createStrategy(form);
      }
      setFormOpen(false);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "儲存失敗");
    } finally {
      setBusy(false);
    }
  }

  async function handleToggleActive(strategy: Strategy) {
    try {
      if (strategy.is_active) {
        await api.deactivateStrategy(strategy.id);
      } else {
        await api.activateStrategy(strategy.id);
      }
      await refresh();
    } catch (err) {
      alert(err instanceof Error ? err.message : "操作失敗");
    }
  }

  async function handleDelete(strategy: Strategy) {
    if (!window.confirm(`確定要刪除策略「${strategy.name}」嗎？`)) return;
    try {
      await api.deleteStrategy(strategy.id);
      await refresh();
    } catch (err) {
      alert(err instanceof Error ? err.message : "刪除失敗");
    }
  }

  async function handleShowTrades(strategy: Strategy) {
    if (tradesFor === strategy.id) {
      setTradesFor(null);
      return;
    }
    const res = await api.getStrategyTrades(strategy.id);
    setTrades(res);
    setTradesFor(strategy.id);
  }

  return (
    <>
      <h2 className="section-title">策略</h2>
      <p className="empty-hint" style={{ marginBottom: 16 }}>
        買進條件會掃描全市場（不限自選股），依排序條件挑出前 N 檔下單；賣出條件套用在目前所有持股上。同時間只會有一組策略啟用中，條件每分鐘檢查一次。
      </p>

      {!formOpen && (
        <button className="submit strategy-new-btn" onClick={openNewForm}>
          + 新增策略
        </button>
      )}

      {formOpen && (
        <form className="panel" onSubmit={handleSave}>
          <h2>{editingId != null ? "編輯策略" : "新增策略"}</h2>
          <input
            placeholder="策略名稱"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />

          <ConditionEditor
            label="買進條件"
            hint="全部條件都符合才會買進"
            conditions={form.buy_conditions}
            onChange={(conditions) => setForm({ ...form, buy_conditions: conditions })}
          />
          <ConditionEditor
            label="賣出條件"
            hint="全部條件都符合才會賣出（套用在目前持股）"
            conditions={form.sell_conditions}
            onChange={(conditions) => setForm({ ...form, sell_conditions: conditions })}
          />

          <div className="strategy-form-grid">
            <label>
              每次買進/賣出股數
              <input
                type="number"
                min={1}
                max={999}
                value={form.quantity}
                onChange={(e) => setForm({ ...form, quantity: Number(e.target.value) })}
              />
            </label>
            <label>
              買進候選排序依據
              <select value={form.rank_by} onChange={(e) => setForm({ ...form, rank_by: e.target.value as RankBy })}>
                {Object.entries(RANK_LABEL).map(([value, text]) => (
                  <option key={value} value={value}>
                    {text}
                  </option>
                ))}
              </select>
            </label>
            <label>
              排序方向
              <select
                value={form.rank_direction}
                onChange={(e) => setForm({ ...form, rank_direction: e.target.value as RankDirection })}
              >
                <option value="desc">由高到低</option>
                <option value="asc">由低到高</option>
              </select>
            </label>
            <label>
              買進前 N 檔
              <input
                type="number"
                min={1}
                max={50}
                value={form.top_n}
                onChange={(e) => setForm({ ...form, top_n: Number(e.target.value) })}
              />
            </label>
          </div>

          {error && <div className="error-msg">{error}</div>}
          <div className="strategy-form-actions">
            <button className="submit" type="submit" disabled={busy}>
              {busy ? "儲存中..." : "儲存"}
            </button>
            <button type="button" className="cancel-btn" onClick={() => setFormOpen(false)}>
              取消
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <div className="empty-hint">載入中...</div>
      ) : strategies.length === 0 ? (
        <div className="panel">
          <div className="empty-hint">還沒有任何策略，點上面「新增策略」建立第一組吧</div>
        </div>
      ) : (
        strategies.map((strategy) => (
          <div className={`panel strategy-card ${strategy.is_active ? "active" : ""}`} key={strategy.id}>
            <div className="strategy-card-header">
              <h2>
                {strategy.name}
                {strategy.is_active && <span className="strategy-active-badge">啟用中</span>}
              </h2>
              <div className="strategy-card-actions">
                <button
                  className={strategy.is_active ? "strategy-toggle-btn stop" : "strategy-toggle-btn"}
                  onClick={() => handleToggleActive(strategy)}
                >
                  {strategy.is_active ? "停用策略" : "啟用策略"}
                </button>
                <span className="cancel-link" onClick={() => openEditForm(strategy)}>
                  編輯
                </span>
                <span className="cancel-link danger-link" onClick={() => handleDelete(strategy)}>
                  刪除
                </span>
              </div>
            </div>
            <div className="strategy-card-body">
              <div>
                <span className="label">買進條件</span> {summarize(strategy.buy_conditions)}
              </div>
              <div>
                <span className="label">賣出條件</span> {summarize(strategy.sell_conditions)}
              </div>
              <div>
                <span className="label">下單股數</span> {strategy.quantity} 股／次，買進取{RANK_LABEL[strategy.rank_by]}
                {strategy.rank_direction === "desc" ? "由高到低" : "由低到高"}前 {strategy.top_n} 檔
              </div>
            </div>
            <span className="cancel-link" onClick={() => handleShowTrades(strategy)}>
              {tradesFor === strategy.id ? "收合成交紀錄" : "查看成交紀錄"}
            </span>
            {tradesFor === strategy.id && (
              <div className="table-scroll" style={{ marginTop: 10 }}>
                {trades.length === 0 ? (
                  <div className="empty-hint">這組策略還沒有成交紀錄</div>
                ) : (
                  <table>
                    <thead>
                      <tr>
                        <th>股票</th>
                        <th>方向</th>
                        <th>股數</th>
                        <th>成交價</th>
                        <th>狀態</th>
                        <th>日期</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trades.map((t) => (
                        <tr key={t.id}>
                          <td style={{ textAlign: "left" }}>
                            {t.stock_code} {t.stock_name}
                          </td>
                          <td className={t.side === "buy" ? "buy-text" : "sell-text"}>{t.side === "buy" ? "買" : "賣"}</td>
                          <td>{t.quantity ?? "-"}</td>
                          <td>{t.price != null ? t.price.toFixed(2) : "-"}</td>
                          <td>{t.status ?? "-"}</td>
                          <td>{t.trade_date}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </div>
        ))
      )}
    </>
  );
}
