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
  const xTicks = [xMin, (xMin + xMax) / 2, xMax];
  const yTicks = [yMin, (yMin + yMax) / 2, yMax];

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
              {t.toFixed(1)}
            </text>
          </g>
        ))}
        {xTicks.map((t) => (
          <g key={`x${t}`}>
            <line x1={toX(t)} x2={toX(t)} y1={PADDING.top} y2={PADDING.top + plotHeight} stroke="rgba(255,255,255,0.05)" />
            <text x={toX(t)} y={height - PADDING.bottom + 16} textAnchor="middle" fontSize="11" fill="#7688a8">
              {t.toFixed(1)}
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
