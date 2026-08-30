import { createChart, type IChartApi, type ISeriesApi, type LineData, type Time, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { PricePoint } from "../types";

const RESET_EVENT = "twstock:reset-chart-range";

// lightweight-charts 的時間軸預設一律用 UTC 顯示 tick 值，不會依瀏覽器時區轉換，
// 所以要自己用 Asia/Taipei 時區格式化，不然台股盤中時段會被顯示成凌晨。這個圖表
// 只會餵 UTCTimestamp（數字），time 理論上不會是其他型別，但簽名要符合 Time 聯集。
function formatTaipeiTime(time: Time, withSeconds = false): string {
  if (typeof time !== "number") return "";
  return new Date(time * 1000).toLocaleTimeString("zh-TW", {
    timeZone: "Asia/Taipei",
    hour: "2-digit",
    minute: "2-digit",
    second: withSeconds ? "2-digit" : undefined,
    hour12: false,
  });
}

// 後端每 7 秒記一筆，一天累積下來上千筆原始 tick，畫出來又密又抖，跟券商 APP
// 慣見的分時走勢圖（每分鐘一筆）差很多。這裡依分鐘分桶，每桶取最後一筆，
// 讓線的呈現方式更接近一般看到的分時走勢圖。
function downsampleToMinute(points: PricePoint[]): PricePoint[] {
  const byMinute = new Map<number, PricePoint>();
  for (const p of points) {
    const minuteKey = Math.floor(new Date(p.ts).getTime() / 60000);
    byMinute.set(minuteKey, p); // 同一分鐘內後面的會覆蓋前面的，留下該分鐘最後一筆
  }
  return [...byMinute.entries()].sort((a, b) => a[0] - b[0]).map(([, p]) => p);
}

interface Props {
  points: PricePoint[];
  height?: number;
  /** 沒有累積分時資料時（例如剛搜尋、還沒加自選股的股票），顯示連到外部站台的連結取代空白訊息。 */
  fallbackLink?: string;
}

export function LineTrendChart({ points, height = 220, fallbackLink }: Props) {
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
      timeScale: {
        borderColor: "#202a42",
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time: Time) => formatTaipeiTime(time),
      },
      localization: {
        timeFormatter: (time: Time) => formatTaipeiTime(time, true),
      },
    });
    chartRef.current = chart;

    seriesRef.current = chart.addLineSeries({
      color: "#4fd8ff",
      lineWidth: 2,
      lastValueVisible: true,
      priceLineColor: "#4fd8ff",
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
    const data: LineData[] = downsampleToMinute(points).map((p) => ({
      time: Math.floor(new Date(p.ts).getTime() / 1000) as UTCTimestamp,
      value: p.price,
    }));
    const hadNoData = seriesRef.current.data().length === 0;
    seriesRef.current.setData(data);
    if (hadNoData) chartRef.current?.timeScale().fitContent();
  }, [points]);

  if (points.length === 0) {
    if (fallbackLink) {
      return (
        <div className="empty-hint">
          這檔股票還沒有累積分時走勢資料（只有自選股會持續記錄）。
          <br />
          <a href={fallbackLink} target="_blank" rel="noreferrer" className="external-link">
            前往 Yahoo 股市查看完整走勢 ↗
          </a>
        </div>
      );
    }
    return <div className="empty-hint">今日盤中走勢累積中，稍候再回來看</div>;
  }

  return <div ref={containerRef} />;
}
