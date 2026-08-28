import type { Trade } from "../types";

export function TradesTable({ trades }: { trades: Trade[] }) {
  if (trades.length === 0) {
    return (
      <div className="panel">
        <h2>成交紀錄</h2>
        <div className="empty-hint">尚無成交紀錄</div>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>成交紀錄</h2>
      <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>股票</th>
            <th>方向</th>
            <th>成交價</th>
            <th>股數</th>
            <th>金額</th>
            <th>手續費</th>
            <th>交易稅</th>
            <th>時間</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr key={t.id}>
              <td style={{ textAlign: "left" }}>{t.stock_code}</td>
              <td className={t.side === "buy" ? "buy-text" : "sell-text"}>{t.side === "buy" ? "買" : "賣"}</td>
              <td>{t.price.toFixed(2)}</td>
              <td>{t.quantity}</td>
              <td>{t.amount.toFixed(0)}</td>
              <td>{t.fee.toFixed(0)}</td>
              <td>{t.tax.toFixed(0)}</td>
              <td>{new Date(t.executed_at).toLocaleTimeString("zh-TW", { hour12: false })}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}
