export function CandlestickDiagram() {
  return (
    <svg viewBox="0 0 360 260" className="candle-diagram" role="img" aria-label="紅K與黑K圖示">
      {/* 紅K：收盤 > 開盤 */}
      <text x="90" y="24" textAnchor="middle" className="candle-label candle-label-buy">
        紅K（收盤&gt;開盤）
      </text>
      <line x1="90" y1="40" x2="90" y2="210" className="candle-wick candle-wick-buy" />
      <rect x="66" y="90" width="48" height="70" rx="3" className="candle-body candle-body-buy" />
      <text x="130" y="70" className="candle-note">上影線：最高價</text>
      <line x1="94" y1="65" x2="122" y2="65" className="candle-leader" />
      <text x="130" y="128" className="candle-note">實體：開盤↔收盤</text>
      <line x1="114" y1="125" x2="122" y2="125" className="candle-leader" />
      <text x="130" y="190" className="candle-note">下影線：最低價</text>
      <line x1="94" y1="185" x2="122" y2="185" className="candle-leader" />

      {/* 黑K：收盤 < 開盤 */}
      <text x="280" y="24" textAnchor="middle" className="candle-label candle-label-sell">
        黑K（收盤&lt;開盤）
      </text>
      <line x1="280" y1="40" x2="280" y2="210" className="candle-wick candle-wick-sell" />
      <rect x="256" y="90" width="48" height="70" rx="3" className="candle-body candle-body-sell" />

      <text x="20" y="245" className="candle-footnote">
        實體越長，代表這段時間漲跌力道越明確；影線越長，代表曾經衝高或殺低但被拉回。
      </text>
    </svg>
  );
}
