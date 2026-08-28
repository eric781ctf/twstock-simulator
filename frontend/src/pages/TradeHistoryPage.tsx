import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { TradesTable } from "../components/TradesTable";
import type { Trade } from "../types";

export default function TradeHistoryPage() {
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);

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
