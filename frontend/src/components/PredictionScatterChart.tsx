import { useMemo } from "react";

export interface ScatterPoint {
  x: number;
  y: number;
}

interface Props {
  points: ScatterPoint[];
  xLabel: string;
  yLabel: string;
  emptyText?: string;
  height?: number;
}

const PADDING = { top: 16, right: 16, bottom: 40, left: 52 };
const VIEW_WIDTH = 720;

function niceRange(values: number[]): [number, number] {
  if (values.length === 0) return [-1, 1];
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) return [min - 1, max + 1];
  const pad = (max - min) * 0.05;
  return [min - pad, max + pad];
}

/**
 * 在 [min, max] 之間取一組「整數好讀」的刻度。
 *
 * 先前是直接取最小值、中位、最大值三個點，所以軸上出現的是 −8.3 / 0.4 / 9.1
 * 這種被資料極端值決定的數字——刻度太少，而且沒有一個是能心算的整數，
 * 要判斷某個點大概落在多少幾乎只能用猜的。
 *
 * 這裡改成先把「理想間距」吸附到 1／2／2.5／5／10 的某個 10 的次方倍，再從
 * 範圍內第一個間距倍數開始鋪，所以刻度一定落在整數或 .5 這種位置上。
 */
const NICE_STEPS = [1, 2, 2.5, 5, 10];

function ticksForStep(min: number, max: number, step: number): number[] {
  const ticks: number[] = [];
  // i * step 會帶出 0.30000000000000004 這種浮點尾巴。不修的話零刻度會是
  // -1.4e-16，toFixed(0) 印出來就成了「-0」
  for (let i = Math.ceil(min / step); i * step <= max + step * 1e-9; i += 1) {
    ticks.push(Number((i * step).toPrecision(12)));
  }
  return ticks;
}

function niceTicks(min: number, max: number, target: number): number[] {
  const span = max - min;
  if (!(span > 0)) return [min];

  // 候選間距橫跨兩個數量級，才不會在邊界上被卡住：例如範圍 24.8、目標 9 個，
  // 理想間距 2.75——一律往上取會跳到 5（只剩 5 個刻度），但 2.5 給的 9 個
  // 才是要的。所以是挑「刻度數最接近目標」的那一階，而不是最小的合格者。
  const magnitude = 10 ** Math.floor(Math.log10(span / target));
  const candidates = [
    ...NICE_STEPS.map((n) => n * magnitude * 0.1),
    ...NICE_STEPS.map((n) => n * magnitude),
    ...NICE_STEPS.map((n) => n * magnitude * 10),
  ];

  let best = ticksForStep(min, max, candidates[0]);
  let bestGap = Infinity;
  for (const step of candidates) {
    const ticks = ticksForStep(min, max, step);
    if (ticks.length < 2) continue;
    // 同分時取刻度比較多的：這個函式存在的理由就是原本刻度太少
    const gap = Math.abs(ticks.length - target);
    if (gap < bestGap || (gap === bestGap && ticks.length > best.length)) {
      best = ticks;
      bestGap = gap;
    }
  }
  return best;
}

/**
 * 刻度標籤要幾位小數：取「剛好能完整表示這個間距」的位數。
 *
 * 不能只看間距的數量級——2.5 比 1 大，但它需要一位小數，用零位會把刻度印成
 * 3，而格線其實畫在 2.5 的位置，等於標錯。
 */
function decimalsFor(ticks: number[]): number {
  if (ticks.length < 2) return 1;
  const step = Math.abs(ticks[1] - ticks[0]);
  for (let d = 0; d <= 4; d += 1) {
    const scaled = step * 10 ** d;
    if (Math.abs(scaled - Math.round(scaled)) < 1e-9) return d;
  }
  return 4;
}

/**
 * 預測值 vs 實際值的散佈圖。lightweight-charts 的 X 軸只能是時間，畫不了這種
 * 任意數值對數值的圖，所以直接手刻 SVG（專案本來就有手刻 SVG 圖的前例）。
 *
 * 對角線是「完美預測」的參考線：點越貼近這條線代表預測越準。
 */
export function PredictionScatterChart({ points, xLabel, yLabel, emptyText = "尚無資料", height = 320 }: Props) {
  const geometry = useMemo(() => {
    if (points.length === 0) return null;
    const [xMin, xMax] = niceRange(points.map((p) => p.x));
    const [yMin, yMax] = niceRange(points.map((p) => p.y));
    const plotWidth = VIEW_WIDTH - PADDING.left - PADDING.right;
    const plotHeight = height - PADDING.top - PADDING.bottom;

    const toX = (v: number) => PADDING.left + ((v - xMin) / (xMax - xMin)) * plotWidth;
    const toY = (v: number) => PADDING.top + plotHeight - ((v - yMin) / (yMax - yMin)) * plotHeight;

    // 對角線只畫在兩軸都涵蓋得到的範圍內
    const diagMin = Math.max(xMin, yMin);
    const diagMax = Math.min(xMax, yMax);

    return { xMin, xMax, yMin, yMax, plotWidth, plotHeight, toX, toY, diagMin, diagMax };
  }, [points, height]);

  if (!geometry) return <div className="empty-hint">{emptyText}</div>;

  const { xMin, xMax, yMin, yMax, plotWidth, plotHeight, toX, toY, diagMin, diagMax } = geometry;
  // X 軸有 650 個單位可用、標籤短，放得下比較多；Y 軸只有兩百多，放太多會擠成一片
  const xTicks = niceTicks(xMin, xMax, 9);
  const yTicks = niceTicks(yMin, yMax, 6);
  const xDecimals = decimalsFor(xTicks);
  const yDecimals = decimalsFor(yTicks);

  return (
    <div className="svg-chart">
      <svg viewBox={`0 0 ${VIEW_WIDTH} ${height}`} width="100%" height={height} role="img">
        <rect
          x={PADDING.left}
          y={PADDING.top}
          width={plotWidth}
          height={plotHeight}
          fill="rgba(255,255,255,0.02)"
          stroke="#202a42"
        />

        {yTicks.map((t) => (
          <g key={`y${t}`}>
            <line x1={PADDING.left} x2={PADDING.left + plotWidth} y1={toY(t)} y2={toY(t)} stroke="rgba(255,255,255,0.05)" />
            <text x={PADDING.left - 8} y={toY(t) + 4} textAnchor="end" fontSize="11" fill="#7688a8">
              {t.toFixed(yDecimals)}
            </text>
          </g>
        ))}
        {xTicks.map((t) => (
          <g key={`x${t}`}>
            <line x1={toX(t)} x2={toX(t)} y1={PADDING.top} y2={PADDING.top + plotHeight} stroke="rgba(255,255,255,0.05)" />
            <text x={toX(t)} y={height - PADDING.bottom + 16} textAnchor="middle" fontSize="11" fill="#7688a8">
              {t.toFixed(xDecimals)}
            </text>
          </g>
        ))}

        {/* 0 軸：漲跌分界，比格線重要所以畫得明顯一點 */}
        {yMin < 0 && yMax > 0 && (
          <line x1={PADDING.left} x2={PADDING.left + plotWidth} y1={toY(0)} y2={toY(0)} stroke="#303e63" />
        )}
        {xMin < 0 && xMax > 0 && (
          <line x1={toX(0)} x2={toX(0)} y1={PADDING.top} y2={PADDING.top + plotHeight} stroke="#303e63" />
        )}

        {diagMin < diagMax && (
          <line
            x1={toX(diagMin)}
            y1={toY(diagMin)}
            x2={toX(diagMax)}
            y2={toY(diagMax)}
            stroke="#9b6bff"
            strokeDasharray="4 4"
            strokeWidth="1.5"
          />
        )}

        {points.map((p, i) => (
          <circle key={i} cx={toX(p.x)} cy={toY(p.y)} r="1.8" fill="#4fd8ff" fillOpacity="0.45" />
        ))}

        <text x={PADDING.left + plotWidth / 2} y={height - 6} textAnchor="middle" fontSize="11" fill="#7688a8">
          {xLabel}
        </text>
        <text
          x={-(PADDING.top + plotHeight / 2)}
          y={13}
          textAnchor="middle"
          fontSize="11"
          fill="#7688a8"
          transform="rotate(-90)"
        >
          {yLabel}
        </text>
      </svg>
      <div className="svg-chart-legend">
        <span>
          <i style={{ background: "#4fd8ff" }} />
          每個點 = 一檔股票在某個測試日
        </span>
        <span>
          <i style={{ background: "#9b6bff" }} />
          虛線 = 完美預測（越貼近越準）
        </span>
      </div>
    </div>
  );
}
