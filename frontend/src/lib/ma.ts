import type { DailyBar } from "../types";

export interface MAPoint {
  time: string;
  value: number;
}

/** 簡單移動平均（用收盤價），資料不足 period 天之前不畫，跟一般看盤軟體一致。 */
export function computeMA(bars: DailyBar[], period: number): MAPoint[] {
  const result: MAPoint[] = [];
  let windowSum = 0;

  for (let i = 0; i < bars.length; i++) {
    windowSum += bars[i].close;
    if (i >= period) {
      windowSum -= bars[i - period].close;
    }
    if (i >= period - 1) {
      result.push({ time: bars[i].trade_date, value: windowSum / period });
    }
  }

  return result;
}
