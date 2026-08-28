import type { Position } from "../types";

export function PositionsTable({ positions }: { positions: Position[] }) {
  if (positions.length === 0) {
    return (
      <div className="panel">
        <h2>持有部位</h2>
        <div className="empty-hint">目前沒有持股</div>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>持有部位</h2>
      <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>股票</th>
            <th>股數</th>
            <th>均價</th>
            <th>現價</th>
            <th>市值</th>
            <th>未實現損益</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr key={p.stock_code}>
              <td style={{ textAlign: "left" }}>
                {p.stock_code} {p.stock_name}
              </td>
              <td>{p.quantity}</td>
              <td>{p.avg_cost.toFixed(2)}</td>
              <td>{p.current_price != null ? p.current_price.toFixed(2) : "-"}</td>
              <td>{p.market_value != null ? p.market_value.toFixed(0) : "-"}</td>
              <td className={p.unrealized_pnl != null && p.unrealized_pnl >= 0 ? "buy-text" : "sell-text"}>
                {p.unrealized_pnl != null ? p.unrealized_pnl.toFixed(0) : "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}
