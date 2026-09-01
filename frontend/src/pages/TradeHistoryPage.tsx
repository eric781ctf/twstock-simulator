import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { TradesTable } from "../components/TradesTable";
import type { RealizedPnlSummary, Trade } from "../types";

export default function TradeHistoryPage() {
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<RealizedPnlSummary | null>(null);

  async function load(start: string, end: string) {
    setLoading(true);
    try {
      const res = await api.getTrades({
        startDate: start || undefined,
        endDate: end || undefined,
      });
      setTrades(res);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load("", "");
    api.getRealizedPnlSummary().then(setSummary).catch(() => setSummary(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleFilter(e: FormEvent) {
    e.preventDefault();
    load(startDate, endDate);
  }

  function handleClear() {
    setStartDate("");
    setEndDate("");
    load("", "");
  }

  return (
    <>
      <h2 className="section-title">交易紀錄</h2>
      {summary && (
        <div className="account-bar">
          <div className="stat">
            <span className="label">累計已實現損益</span>
            <span className={`value ${summary.total_realized_pnl >= 0 ? "buy-text" : "sell-text"}`}>
              {summary.total_realized_pnl.toFixed(0)}
            </span>
          </div>
          <div className="stat">
            <span className="label">獲利筆數</span>
            <span className="value">{summary.win_count}</span>
          </div>
          <div className="stat">
            <span className="label">虧損筆數</span>
            <span className="value">{summary.loss_count}</span>
          </div>
          <div className="stat">
            <span className="label">勝率</span>
            <span className="value">{summary.win_rate != null ? `${(summary.win_rate * 100).toFixed(1)}%` : "-"}</span>
          </div>
        </div>
      )}
      <div className="panel">
        <form className="date-filter-form" onSubmit={handleFilter}>
          <label>
            起始日期
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </label>
          <label>
            結束日期
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </label>
          <button className="submit" type="submit">
            套用篩選
          </button>
          <button type="button" className="reset-range-btn" onClick={handleClear}>
            清除
          </button>
        </form>
      </div>

      {loading ? <div className="empty-hint">載入中...</div> : <TradesTable trades={trades} />}
    </>
  );
}
