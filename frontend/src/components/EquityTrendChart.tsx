import { createChart, type IChartApi, type ISeriesApi, type LineData } from "lightweight-charts";
import { useEffect, useRef } from "react";

export interface EquityPoint {
  date: string;
  value: number;
}

interface Props {
  points: EquityPoint[];
  height?: number;
  color?: string;
  emptyText?: string;
}

// 跟 CandlestickChart 一樣直接餵日期字串當 time（逐日資料，不需要像
// LineTrendChart 那樣處理分鐘級時間戳跟時區）。
export function EquityTrendChart({ points, height = 220, color = "#4fd8ff", emptyText = "尚無資料" }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      width: container.clientWidth,
      height,
      layout: { background: { color: "transparent" }, textColor: "#7688a8", fontSize: 11 },
      grid: { vertLines: { color: "rgba(255,255,255,0.04)" }, horzLines: { color: "rgba(255,255,255,0.04)" } },
      rightPriceScale: { borderColor: "#202a42" },
      timeScale: { borderColor: "#202a42" },
    });
    chartRef.current = chart;

    seriesRef.current = chart.addLineSeries({
      color,
      lineWidth: 2,
      lastValueVisible: true,
      priceLineColor: color,
    });

    const resizeObserver = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth });
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height, color]);

  useEffect(() => {
    if (!seriesRef.current) return;
    const data: LineData[] = points.map((p) => ({ time: p.date, value: p.value }));
    seriesRef.current.setData(data);
    chartRef.current?.timeScale().fitContent();
  }, [points]);

  if (points.length === 0) {
    return <div className="empty-hint">{emptyText}</div>;
  }

  return <div ref={containerRef} />;
}
