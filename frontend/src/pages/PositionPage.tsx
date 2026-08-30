import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { PnlTable } from "../components/PnlTable";
import { PositionsTable } from "../components/PositionsTable";
import type { Account, Position } from "../types";

type PositionTab = "positions" | "pnl";

export default function PositionPage() {
  const [account, setAccount] = useState<Account | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [positionTab, setPositionTab] = useState<PositionTab>("positions");

  const refresh = useCallback(async () => {
    const [accountRes, positionsRes] = await Promise.all([api.getAccount(), api.getPositions()]);
    setAccount(accountRes);
    setPositions(positionsRes);
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 6000);
    return () => clearInterval(timer);
  }, [refresh]);

  const positionsMarketValue = positions.reduce((sum, p) => sum + (p.market_value ?? 0), 0);

  return (
    <>
      <h2 className="section-title">部位</h2>

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

      <div className="chart-tabs">
        <button className={positionTab === "positions" ? "active" : ""} onClick={() => setPositionTab("positions")}>
          持有部位
        </button>
        <button className={positionTab === "pnl" ? "active" : ""} onClick={() => setPositionTab("pnl")}>
          損益
        </button>
      </div>
      {positionTab === "positions" ? <PositionsTable positions={positions} /> : <PnlTable positions={positions} />}
    </>
  );
}
