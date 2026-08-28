import { useState } from "react";
import type { DailyBar, PricePoint } from "../types";
import { CandlestickChart } from "./CandlestickChart";
import { KDChart } from "./KDChart";
import { LineTrendChart } from "./LineTrendChart";

type Tab = "daily" | "intraday";

interface Props {
  bars: DailyBar[];
  points: PricePoint[];
  loading: boolean;
}

export function ChartTabs({ bars, points, loading }: Props) {
  const [tab, setTab] = useState<Tab>("daily");

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
          <CandlestickChart bars={bars} />
          <KDChart bars={bars} />
        </>
      ) : (
        <LineTrendChart points={points} />
      )}
    </>
  );
}
