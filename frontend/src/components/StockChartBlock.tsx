import { useStockCharts } from "../hooks/useStockCharts";
import type { Position } from "../types";
import { ChartTabs } from "./ChartTabs";

export function StockChartBlock({ position }: { position: Position }) {
  const { bars, points, loading } = useStockCharts(position.stock_code);
  const pnlClass = (position.unrealized_pnl ?? 0) >= 0 ? "buy-text" : "sell-text";

  return (
    <div className="stock-block">
      <div className="stock-block-header">
        <span className="title">
          {position.stock_code} {position.stock_name}
        </span>
        <span className="price">{position.current_price != null ? position.current_price.toFixed(2) : "-"}</span>
      </div>
      <div className="stock-block-meta">
        <span>持有 {position.quantity} 股</span>
        <span>均價 {position.avg_cost.toFixed(2)}</span>
        <span className={pnlClass}>
          未實現損益 {position.unrealized_pnl != null ? position.unrealized_pnl.toFixed(0) : "-"}
        </span>
      </div>

      <ChartTabs bars={bars} points={points} loading={loading} />
    </div>
  );
}
