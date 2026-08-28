import { api } from "../api";
import type { Order } from "../types";

const STATUS_LABEL: Record<Order["status"], string> = {
  pending: "待成交",
  filled: "已成交",
  cancelled: "已取消",
  expired: "已失效",
};

interface Props {
  orders: Order[];
  onChanged: () => void;
  title: string;
  emptyText: string;
  timeField?: "created_at" | "filled_at";
  timeLabel?: string;
}

export function OrdersTable({
  orders,
  onChanged,
  title,
  emptyText,
  timeField = "created_at",
  timeLabel = "時間",
}: Props) {
  async function handleCancel(id: number) {
    try {
      await api.cancelOrder(id);
      onChanged();
    } catch (err) {
      alert(err instanceof Error ? err.message : "取消失敗");
    }
  }

  if (orders.length === 0) {
    return (
      <div className="panel">
        <h2>{title}</h2>
        <div className="empty-hint">{emptyText}</div>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>{title}</h2>
      <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>股票</th>
            <th>方向</th>
            <th>限價</th>
            <th>股數</th>
            <th>狀態</th>
            <th>成交價</th>
            <th>{timeLabel}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => {
            const t = timeField === "filled_at" ? o.filled_at : o.created_at;
            return (
              <tr key={o.id}>
                <td style={{ textAlign: "left" }}>{o.stock_code}</td>
                <td className={o.side === "buy" ? "buy-text" : "sell-text"}>{o.side === "buy" ? "買" : "賣"}</td>
                <td>{o.price.toFixed(2)}</td>
                <td>{o.quantity}</td>
                <td className={`status-${o.status}`}>{STATUS_LABEL[o.status]}</td>
                <td>{o.filled_price != null ? o.filled_price.toFixed(2) : "-"}</td>
                <td>{t ? new Date(t).toLocaleTimeString("zh-TW", { hour12: false }) : "-"}</td>
                <td>
                  {o.status === "pending" && (
                    <span className="cancel-link" onClick={() => handleCancel(o.id)}>
                      取消
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>
    </div>
  );
}
