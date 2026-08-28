import { createChart, type IChartApi, type ISeriesApi, type LineData } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { computeKD } from "../lib/kd";
import type { DailyBar } from "../types";

const RESET_EVENT = "twstock:reset-chart-range";

export function KDChart({ bars }: { bars: DailyBar[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const kSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const dSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 110,
      layout: { background: { color: "transparent" }, textColor: "#7688a8", fontSize: 11 },
      grid: { vertLines: { color: "rgba(255,255,255,0.04)" }, horzLines: { color: "rgba(255,255,255,0.04)" } },
      rightPriceScale: { borderColor: "#202a42" },
      timeScale: { borderColor: "#202a42" },
    });
    chartRef.current = chart;

    kSeriesRef.current = chart.addLineSeries({ color: "#ffb454", lineWidth: 2, title: "K" });
    dSeriesRef.current = chart.addLineSeries({ color: "#9b6bff", lineWidth: 2, title: "D" });

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
      kSeriesRef.current = null;
      dSeriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!kSeriesRef.current || !dSeriesRef.current) return;
    const kd = computeKD(bars);
    const kData: LineData[] = kd.map((p) => ({ time: p.time, value: p.k }));
    const dData: LineData[] = kd.map((p) => ({ time: p.time, value: p.d }));
    const hadNoData = kSeriesRef.current.data().length === 0;
    kSeriesRef.current.setData(kData);
    dSeriesRef.current.setData(dData);
    if (hadNoData) chartRef.current?.timeScale().fitContent();
  }, [bars]);

  if (bars.length === 0) return null;

  return (
    <div className="kd-chart">
      <div className="kd-chart-label">KD (9)</div>
      <div ref={containerRef} />
    </div>
  );
}
