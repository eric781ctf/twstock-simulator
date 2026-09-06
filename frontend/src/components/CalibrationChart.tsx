import type { CalibrationBucket } from "../types";

interface Props {
  buckets: CalibrationBucket[];
  emptyText?: string;
  height?: number;
}

const PADDING = { top: 16, right: 16, bottom: 40, left: 52 };
const VIEW_WIDTH = 720;

/**
 * 分桶校準曲線（reliability diagram）：把預測機率分成幾桶，比較每一桶的
 * 「平均預測機率」跟「實際達標比例」。
 *
 * 對角線代表完美校準——模型說 70% 的那批，實際上真的有七成達標。點偏在對角線
 * 上方代表模型低估、下方代表高估（過度自信）。
 *
 * 這裡刻意不畫成原始散佈圖：分類的實際結果只有 0 跟 1 兩個值，散佈圖會變成
 * 上下兩條線，看不出校準好壞。
 */
export function CalibrationChart({ buckets, emptyText = "尚無資料", height = 320 }: Props) {
  if (buckets.length === 0) return <div className="empty-hint">{emptyText}</div>;

  const plotWidth = VIEW_WIDTH - PADDING.left - PADDING.right;
  const plotHeight = height - PADDING.top - PADDING.bottom;
  const toX = (v: number) => PADDING.left + v * plotWidth;
  const toY = (v: number) => PADDING.top + plotHeight - v * plotHeight;

  const maxCount = Math.max(...buckets.map((b) => b.sample_count));
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const path = buckets.map((b, i) => `${i === 0 ? "M" : "L"} ${toX(b.average_predicted)} ${toY(b.actual_rate)}`).join(" ");

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

        {ticks.map((t) => (
          <g key={t}>
            <line x1={PADDING.left} x2={PADDING.left + plotWidth} y1={toY(t)} y2={toY(t)} stroke="rgba(255,255,255,0.05)" />
            <text x={PADDING.left - 8} y={toY(t) + 4} textAnchor="end" fontSize="11" fill="#7688a8">
              {(t * 100).toFixed(0)}%
            </text>
            <line x1={toX(t)} x2={toX(t)} y1={PADDING.top} y2={PADDING.top + plotHeight} stroke="rgba(255,255,255,0.05)" />
            <text x={toX(t)} y={height - PADDING.bottom + 16} textAnchor="middle" fontSize="11" fill="#7688a8">
              {(t * 100).toFixed(0)}%
            </text>
          </g>
        ))}

        <line
          x1={toX(0)}
          y1={toY(0)}
          x2={toX(1)}
          y2={toY(1)}
          stroke="#9b6bff"
          strokeDasharray="4 4"
          strokeWidth="1.5"
        />

        <path d={path} fill="none" stroke="#4fd8ff" strokeWidth="2" />
        {buckets.map((b, i) => (
          <circle
            key={i}
            cx={toX(b.average_predicted)}
            cy={toY(b.actual_rate)}
            r={4 + (b.sample_count / maxCount) * 5}
            fill="#4fd8ff"
            fillOpacity="0.75"
          >
            <title>
              {`預測 ${(b.average_predicted * 100).toFixed(1)}% / 實際 ${(b.actual_rate * 100).toFixed(1)}% （${b.sample_count} 筆）`}
            </title>
          </circle>
        ))}

        <text x={PADDING.left + plotWidth / 2} y={height - 6} textAnchor="middle" fontSize="11" fill="#7688a8">
          模型預測的達標機率
        </text>
        <text
          x={-(PADDING.top + plotHeight / 2)}
          y={13}
          textAnchor="middle"
          fontSize="11"
          fill="#7688a8"
          transform="rotate(-90)"
        >
          實際達標比例
        </text>
      </svg>
      <div className="svg-chart-legend">
        <span>
          <i style={{ background: "#4fd8ff" }} />
          圓點大小 = 該區間的樣本數
        </span>
        <span>
          <i style={{ background: "#9b6bff" }} />
          虛線 = 完美校準（點在上方代表低估、下方代表過度自信）
        </span>
      </div>
    </div>
  );
}
