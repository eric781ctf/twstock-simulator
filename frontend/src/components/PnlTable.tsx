import type { Position } from "../types";

export function PnlTable({ positions }: { positions: Position[] }) {
  if (positions.length === 0) {
    return (
      <div className="panel">
        <h2>損益</h2>
        <div className="empty-hint">目前沒有持股</div>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>損益</h2>
      <table>
        <thead>
          <tr>
            <th>股票</th>
            <th>股數</th>
            <th>投資成本</th>
            <th>成本均價</th>
            <th>現價</th>
            <th>市值</th>
            <th>損益</th>
            <th>損益率</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => {
            const cost = p.avg_cost * p.quantity;
            const pnl = p.unrealized_pnl;
            const pnlPct = cost > 0 && pnl != null ? (pnl / cost) * 100 : null;
            const pnlClass = pnl != null && pnl >= 0 ? "buy-text" : "sell-text";
            return (
              <tr key={p.stock_code}>
                <td style={{ textAlign: "left" }}>
                  {p.stock_code} {p.stock_name}
                </td>
                <td>{p.quantity}</td>
                <td>{cost.toFixed(0)}</td>
                <td>{p.avg_cost.toFixed(2)}</td>
                <td>{p.current_price != null ? p.current_price.toFixed(2) : "-"}</td>
                <td>{p.market_value != null ? p.market_value.toFixed(0) : "-"}</td>
                <td className={pnlClass}>{pnl != null ? pnl.toFixed(0) : "-"}</td>
                <td className={pnlClass}>{pnlPct != null ? `${pnlPct.toFixed(2)}%` : "-"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
