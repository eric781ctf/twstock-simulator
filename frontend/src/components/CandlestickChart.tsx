import { createChart, type CandlestickData, type IChartApi, type ISeriesApi } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { DailyBar } from "../types";

const RESET_EVENT = "twstock:reset-chart-range";

export function CandlestickChart({ bars }: { bars: DailyBar[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  // 建立一次圖表 + 監聽「重設所有圖表時間區間」事件，資料更新不會重建圖表，
  // 使用者手動縮放/拖曳的視窗範圍才不會每次背景刷新就被打回原狀。
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 220,
      layout: { background: { color: "transparent" }, textColor: "#7688a8", fontSize: 11 },
      grid: { vertLines: { color: "rgba(255,255,255,0.04)" }, horzLines: { color: "rgba(255,255,255,0.04)" } },
      rightPriceScale: { borderColor: "#202a42" },
      timeScale: { borderColor: "#202a42" },
    });
    chartRef.current = chart;

    seriesRef.current = chart.addCandlestickSeries({
      upColor: "#ff4f7e",
      downColor: "#2be3ae",
      borderUpColor: "#ff4f7e",
      borderDownColor: "#2be3ae",
      wickUpColor: "#ff4f7e",
      wickDownColor: "#2be3ae",
    });

    function resetRange() {
      chart.timeScale().fitContent();
    }
    window.addEventListener(RESET_EVENT, resetRange);

    const resizeObserver = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth });
    });
    resizeObserver.observe(container);

    return () => {
      window.removeEventListener(RESET_EVENT, resetRange);
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!seriesRef.current) return;
    const data: CandlestickData[] = bars.map((b) => ({
      time: b.trade_date,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    const hadNoData = seriesRef.current.data().length === 0;
    seriesRef.current.setData(data);
    if (hadNoData) chartRef.current?.timeScale().fitContent();
  }, [bars]);

  if (bars.length === 0) {
    return <div className="empty-hint">尚無日 K 資料</div>;
  }

  return <div ref={containerRef} />;
}
