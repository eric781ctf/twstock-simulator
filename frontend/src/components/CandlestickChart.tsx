import { createChart, type CandlestickData, type IChartApi, type ISeriesApi, type LineData } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { computeMA } from "../lib/ma";
import type { DailyBar } from "../types";

const RESET_EVENT = "twstock:reset-chart-range";

const MA_LINES = [
  { period: 5, label: "週線 (5)", color: "#ffd23f" },
  { period: 20, label: "月線 (20)", color: "#c9a6ff" },
  { period: 60, label: "季線 (60)", color: "#f4f6fb" },
] as const;

export function CandlestickChart({ bars }: { bars: DailyBar[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const maSeriesRef = useRef<ISeriesApi<"Line">[]>([]);

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

    maSeriesRef.current = MA_LINES.map((ma) =>
      chart.addLineSeries({
        color: ma.color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
    );

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
      maSeriesRef.current = [];
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

    MA_LINES.forEach((ma, i) => {
      const maData: LineData[] = computeMA(bars, ma.period).map((p) => ({ time: p.time, value: p.value }));
      maSeriesRef.current[i]?.setData(maData);
    });

    if (hadNoData) chartRef.current?.timeScale().fitContent();
  }, [bars]);

  if (bars.length === 0) {
    return <div className="empty-hint">尚無日 K 資料</div>;
  }

  return (
    <div>
      <div className="ma-legend">
        {MA_LINES.map((ma) => (
          <span key={ma.period}>
            <i style={{ background: ma.color }} />
            {ma.label}
          </span>
        ))}
      </div>
      <div ref={containerRef} />
    </div>
  );
}
