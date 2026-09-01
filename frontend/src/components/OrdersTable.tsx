import { api } from "../api";
import type { Order, OrderType } from "../types";

const STATUS_LABEL: Record<Order["status"], string> = {
  pending: "待成交",
  filled: "已成交",
  cancelled: "已取消",
  expired: "已失效",
};

const ORDER_TYPE_LABEL: Record<OrderType, string> = {
  limit: "限價",
  market: "市價",
  stop: "停損",
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
            <th>類型</th>
            <th>價格{/* 限價=限價；停損=觸發價；市價=送出當下市價 */}</th>
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
                <td>{ORDER_TYPE_LABEL[o.order_type]}</td>
                <td>{o.order_type === "market" ? "-" : (o.order_type === "stop" ? o.stop_price ?? o.price : o.price).toFixed(2)}</td>
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
