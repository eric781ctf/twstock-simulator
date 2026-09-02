import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { AddWatchlistBox } from "../components/AddWatchlistBox";
import { EquityTrendChart } from "../components/EquityTrendChart";
import { StockChartBlock } from "../components/StockChartBlock";
import { WatchlistChartBlock } from "../components/WatchlistChartBlock";
import type { Account, EquitySnapshot, Position, WatchlistItem } from "../types";

export default function HomePage() {
  const [account, setAccount] = useState<Account | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [equityHistory, setEquityHistory] = useState<EquitySnapshot[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const [accountRes, positionsRes, watchlistRes] = await Promise.all([
      api.getAccount(),
      api.getPositions(),
      api.getWatchlist(),
    ]);
    setAccount(accountRes);
    setPositions(positionsRes);
    setWatchlist(watchlistRes);
    setLoading(false);
  }, []);

  const refreshEquityHistory = useCallback(async () => {
    try {
      setEquityHistory(await api.getEquityHistory());
    } catch {
      // 績效走勢圖不是核心功能，載入失敗不影響其他區塊，安靜略過即可
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 15000);
    return () => clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    refreshEquityHistory();
    const timer = setInterval(refreshEquityHistory, 60000);
    return () => clearInterval(timer);
  }, [refreshEquityHistory]);

  async function handleRemove(stockCode: string) {
    try {
      await api.removeFromWatchlist(stockCode);
      refresh();
    } catch (err) {
      alert(err instanceof Error ? err.message : "移除失敗");
    }
  }

  function handleResetAllRanges() {
    window.dispatchEvent(new Event("twstock:reset-chart-range"));
  }

  const positionsMarketValue = positions.reduce((sum, p) => sum + (p.market_value ?? 0), 0);
  const heldCodes = new Set(positions.map((p) => p.stock_code));
  const watchlistOnly = watchlist.filter((w) => !heldCodes.has(w.stock_code));

  const equityFirst = equityHistory[0];
  const equityLast = equityHistory[equityHistory.length - 1];
  const equityReturnPercent =
    equityFirst && equityFirst.total_assets > 0
      ? ((equityLast.total_assets - equityFirst.total_assets) / equityFirst.total_assets) * 100
      : null;

  return (
    <>
      {account && (
        <div className="account-bar">
          <div className="stat">
            <span className="label">現金餘額</span>
            <span className="value">{account.cash_balance.toLocaleString()}</span>
          </div>
          <div className="stat">
            <span className="label">部位市值</span>
            <span className="value">{positionsMarketValue.toLocaleString()}</span>
          </div>
          <div className="stat">
            <span className="label">總資產</span>
            <span className="value">{(account.cash_balance + positionsMarketValue).toLocaleString()}</span>
          </div>
        </div>
      )}

      <div className="section-title-row">
        <h2 className="section-title">績效走勢</h2>
        {equityReturnPercent != null && (
          <span className={`equity-return-badge ${equityReturnPercent >= 0 ? "buy-text" : "sell-text"}`}>
            {equityReturnPercent >= 0 ? "+" : ""}
            {equityReturnPercent.toFixed(2)}%
          </span>
        )}
      </div>
      <div className="panel">
        <EquityTrendChart
          points={equityHistory.map((s) => ({ date: s.snapshot_date, value: s.total_assets }))}
          emptyText="績效資料每日排程累積中，稍候再回來看"
        />
      </div>

      {loading ? (
        <div className="empty-hint">載入中...</div>
      ) : (
        <>
          <h2 className="section-title">持股</h2>
          {positions.length === 0 ? (
            <div className="panel">
              <div className="empty-hint">目前沒有持股，去「交易」頁下單買進零股吧</div>
            </div>
          ) : (
            <div className="stock-blocks">
              {positions.map((p) => (
                <StockChartBlock key={p.stock_code} position={p} />
              ))}
            </div>
          )}

          <div className="section-title-row">
            <h2 className="section-title">自選股（{watchlist.length}/20）</h2>
            <button className="reset-range-btn" onClick={handleResetAllRanges}>
              重設所有圖表時間區間
            </button>
          </div>
          <AddWatchlistBox disabled={watchlist.length >= 20} onAdded={refresh} />
          {watchlistOnly.length > 0 && (
            <div className="stock-blocks">
              {watchlistOnly.map((w) => (
                <WatchlistChartBlock key={w.stock_code} item={w} onRemove={handleRemove} />
              ))}
            </div>
          )}
        </>
      )}
    </>
  );
}
