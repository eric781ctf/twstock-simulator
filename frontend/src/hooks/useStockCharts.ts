import { useEffect, useState } from "react";
import { api } from "../api";
import type { DailyBar, PricePoint } from "../types";

const REFRESH_INTERVAL_MS = 30000;

export function useStockCharts(stockCode: string) {
  const [bars, setBars] = useState<DailyBar[]>([]);
  const [points, setPoints] = useState<PricePoint[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!stockCode) {
      setBars([]);
      setPoints([]);
      setLoading(false);
      return;
    }

    let cancelled = false;
    let firstLoad = true;
    setLoading(true);

    async function load() {
      try {
        const [dailyRes, intradayRes] = await Promise.all([
          api.getDailyHistory(stockCode),
          api.getIntraday(stockCode),
        ]);
        if (cancelled) return;
        setBars(dailyRes);
        setPoints(intradayRes);
      } catch {
        // 背景定期刷新失敗時保留現有資料，只有第一次載入失敗才清空顯示「無資料」
        if (!cancelled && firstLoad) {
          setBars([]);
          setPoints([]);
        }
      } finally {
        if (!cancelled && firstLoad) {
          setLoading(false);
          firstLoad = false;
        }
      }
    }

    load();
    const timer = setInterval(load, REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [stockCode]);

  return { bars, points, loading };
}
