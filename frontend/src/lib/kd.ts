import type { DailyBar } from "../types";

export interface KDPoint {
  time: string;
  k: number;
  d: number;
}

/** 台股慣用的 KD 隨機指標算法：RSV 用 n 日高低區間，K/D 用 2:1 平滑。*/
export function computeKD(bars: DailyBar[], period = 9): KDPoint[] {
  const result: KDPoint[] = [];
  let prevK = 50;
  let prevD = 50;

  for (let i = 0; i < bars.length; i++) {
    const window = bars.slice(Math.max(0, i - period + 1), i + 1);
    const high = Math.max(...window.map((b) => b.high));
    const low = Math.min(...window.map((b) => b.low));
    const close = bars[i].close;
    const rsv = high === low ? 50 : ((close - low) / (high - low)) * 100;

    const k = (prevK * 2 + rsv) / 3;
    const d = (prevD * 2 + k) / 3;
    result.push({ time: bars[i].trade_date, k, d });
    prevK = k;
    prevD = d;
  }

  return result;
}
