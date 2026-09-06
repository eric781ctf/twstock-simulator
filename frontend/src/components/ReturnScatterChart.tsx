import { createChart, type IChartApi, type ISeriesApi, type LineData } from "lightweight-charts";
import { useEffect, useRef } from "react";

export interface ReturnPoint {
  date: string;
  value: number;
}

interface Props {
  points: ReturnPoint[];
  height?: number;
  emptyText?: string;
}

/**
 * 每筆交易的損益率散佈圖（X 軸是進場日期）。X 軸是時間，所以可以用
 * lightweight-charts；把線隱藏、只留下點，就成了散佈圖。
 *
 * 同一天可能有多筆交易，但 lightweight-charts 的一個 series 對同一個時間點
 * 只能有一個值，所以每筆交易各自成為一個 series（點數不多，回測期間頂多
 * 幾十到幾百筆）。
 */
export function ReturnScatterChart({ points, height = 260, emptyText = "尚無交易紀錄" }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line">[]>([]);

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

    const resizeObserver = new ResizeObserver(() => chart.applyOptions({ width: container.clientWidth }));
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = [];
    };
  }, [height]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    seriesRef.current.forEach((s) => chart.removeSeries(s));
    seriesRef.current = [];

    // 同一天多筆交易要拆成不同 series，否則同一個時間點只留得下最後一筆
    const byDate = new Map<string, number[]>();
    for (const p of points) {
      const list = byDate.get(p.date) ?? [];
      list.push(p.value);
      byDate.set(p.date, list);
    }
    const maxPerDate = Math.max(1, ...[...byDate.values()].map((v) => v.length));

    for (let slot = 0; slot < maxPerDate; slot++) {
      const data: LineData[] = [];
      for (const [date, values] of [...byDate.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
        if (values[slot] !== undefined) data.push({ time: date, value: values[slot] });
      }
      if (data.length === 0) continue;
      const series = chart.addLineSeries({
        lineVisible: false,
        pointMarkersVisible: true,
        pointMarkersRadius: 3,
        color: "#4fd8ff",
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
      });
      series.setData(data);
      seriesRef.current.push(series);
    }

    if (seriesRef.current.length > 0) {
      // 0% 基準線：一眼看出賺賠分界
      seriesRef.current[0].createPriceLine({
        price: 0,
        color: "#303e63",
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: false,
        title: "",
      });
      chart.timeScale().fitContent();
    }
  }, [points]);

  if (points.length === 0) return <div className="empty-hint">{emptyText}</div>;

  return <div ref={containerRef} />;
}
