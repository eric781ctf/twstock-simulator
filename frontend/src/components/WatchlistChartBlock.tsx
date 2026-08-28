import { useNavigate } from "react-router-dom";
import { useStockCharts } from "../hooks/useStockCharts";
import type { OrderSide, WatchlistItem } from "../types";
import { ChartTabs } from "./ChartTabs";

interface Props {
  item: WatchlistItem;
  onRemove: (stockCode: string) => void;
}

export function WatchlistChartBlock({ item, onRemove }: Props) {
  const { bars, points, loading } = useStockCharts(item.stock_code);
  const navigate = useNavigate();

  function goToTrade(side: OrderSide) {
    navigate("/trade", {
      state: { stockCode: item.stock_code, stockName: item.stock_name, market: item.market, side },
    });
  }

  function goToDetail() {
    navigate(`/search?code=${item.stock_code}`);
  }

  return (
    <div className="stock-block">
      <div className="stock-block-header">
        <span className="title clickable" onClick={goToDetail}>
          {item.stock_code} {item.stock_name}
        </span>
        <span className="price">{item.current_price != null ? item.current_price.toFixed(2) : "-"}</span>
      </div>
      <div className="stock-block-meta">
        <span>{item.market}</span>
        <span className="cancel-link" onClick={() => onRemove(item.stock_code)}>
          從自選股移除
        </span>
      </div>
      <div className="block-trade-actions">
        <button className="buy-btn" onClick={() => goToTrade("buy")}>
          買進
        </button>
        <button className="sell-btn" onClick={() => goToTrade("sell")}>
          賣出
        </button>
      </div>

      <ChartTabs bars={bars} points={points} loading={loading} />
    </div>
  );
}
