import { useState } from "react";
import { yahooStockUrl } from "../lib/yahoo";
import type { DailyBar, PricePoint } from "../types";
import { CandlestickChart } from "./CandlestickChart";
import { KDChart } from "./KDChart";
import { LineTrendChart } from "./LineTrendChart";

type Tab = "daily" | "intraday";

interface Props {
  bars: DailyBar[];
  points: PricePoint[];
  loading: boolean;
  size?: "normal" | "large";
  /** 提供股票代碼＋市場別時，盤中走勢沒資料會顯示連到 Yahoo 股市的連結。 */
  stockCode?: string;
  market?: "TWSE" | "TPEX";
}

const HEIGHTS = {
  normal: { candle: 220, kd: 110, line: 220 },
  large: { candle: 420, kd: 160, line: 420 },
};

export function ChartTabs({ bars, points, loading, size = "normal", stockCode, market }: Props) {
  const [tab, setTab] = useState<Tab>("daily");
  const heights = HEIGHTS[size];
  const fallbackLink = stockCode && market ? yahooStockUrl(stockCode, market) : undefined;

  return (
    <>
      <div className="chart-tabs">
        <button className={tab === "daily" ? "active" : ""} onClick={() => setTab("daily")}>
          日 K 線
        </button>
        <button className={tab === "intraday" ? "active" : ""} onClick={() => setTab("intraday")}>
          盤中走勢
        </button>
      </div>

      {loading ? (
        <div className="empty-hint">載入中...</div>
      ) : tab === "daily" ? (
        <>
          <CandlestickChart bars={bars} height={heights.candle} />
          <KDChart bars={bars} height={heights.kd} />
        </>
      ) : (
        <LineTrendChart points={points} height={heights.line} fallbackLink={fallbackLink} />
      )}
    </>
  );
}
