import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { OrderPanel, type OrderPrefill } from "../components/OrderPanel";
import { OrdersTable } from "../components/OrdersTable";
import type { Account, MarketSession, Order, Position } from "../types";

const SESSION_LABEL: Record<MarketSession["status"], string> = {
  trading: "盤中交易",
  after_hours: "盤後交易（以收盤價買進）",
  closed: "非交易時間",
};

export default function TradePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const prefill = (location.state as OrderPrefill | null) ?? null;

  const [account, setAccount] = useState<Account | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [pendingOrders, setPendingOrders] = useState<Order[]>([]);
  const [filledOrdersToday, setFilledOrdersToday] = useState<Order[]>([]);
  const [marketSession, setMarketSession] = useState<MarketSession | null>(null);

  const refresh = useCallback(async () => {
    const [accountRes, positionsRes, pendingRes, filledRes] = await Promise.all([
      api.getAccount(),
      api.getPositions(),
      api.getOrders({ status: "pending" }),
      api.getOrders({ status: "filled", todayOnly: true }),
    ]);
    setAccount(accountRes);
    setPositions(positionsRes);
    setPendingOrders(pendingRes);
    setFilledOrdersToday(filledRes);
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 6000);
    return () => clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    async function refreshSession() {
      const session = await api.getMarketSession();
      setMarketSession(session);
    }
    refreshSession();
    const timer = setInterval(refreshSession, 30000);
    return () => clearInterval(timer);
  }, []);

  // 從自選股 block 帶著預設股票/方向跳轉過來後，清掉 navigation state，
  // 避免之後從導覽列重新進入交易頁時又被套用一次。
  useEffect(() => {
    if (location.state) {
      navigate(location.pathname, { replace: true, state: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state]);

  const positionsMarketValue = positions.reduce((sum, p) => sum + (p.market_value ?? 0), 0);

  return (
    <>
      {marketSession && (
        <div className={`market-session-badge ${marketSession.status}`}>
          <span className="market-session-dot" />
          {SESSION_LABEL[marketSession.status]}
        </div>
      )}
      {account && (
        <div className="account-bar">
          <div className="stat">
            <span className="label">現金餘額</span>
            <span className="value">{account.cash_balance.toLocaleString()}</span>
          </div>
          <div className="stat">
            <span className="label">凍結資金</span>
            <span className="value">{account.frozen_cash.toLocaleString()}</span>
          </div>
          <div className="stat">
            <span className="label">可用資金</span>
            <span className="value">{account.available_cash.toLocaleString()}</span>
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

      <div className="layout">
        <div>
          <OrderPanel onOrderPlaced={refresh} prefill={prefill} marketSession={marketSession} />
        </div>
        <div>
          <OrdersTable
            orders={pendingOrders}
            onChanged={refresh}
            title="委託回報"
            emptyText="今日沒有待成交的委託"
          />
          <OrdersTable
            orders={filledOrdersToday}
            onChanged={refresh}
            title="成交回報"
            emptyText="今日沒有成交紀錄"
            timeField="filled_at"
            timeLabel="成交時間"
          />
        </div>
      </div>
    </>
  );
}
