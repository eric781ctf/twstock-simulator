export function KDCrossDiagram() {
  return (
    <svg viewBox="0 0 400 210" className="kd-diagram" role="img" aria-label="KD黃金交叉與死亡交叉示意圖">
      {/* 超買 / 超賣區底色 */}
      <rect x="20" y="20" width="360" height="32" className="kd-zone kd-zone-overbought" />
      <rect x="20" y="148" width="360" height="32" className="kd-zone kd-zone-oversold" />
      <text x="386" y="40" className="kd-zone-label">80 超買</text>
      <text x="386" y="168" className="kd-zone-label">20 超賣</text>

      {/* D 線（平滑） */}
      <polyline
        points="20,120 60,130 100,125 140,105 180,85 220,72 260,68 300,85 340,115 380,135"
        className="kd-line kd-line-d"
      />
      {/* K 線（敏感） */}
      <polyline
        points="20,140 60,155 100,120 140,90 180,70 220,60 260,75 300,110 340,140 380,130"
        className="kd-line kd-line-k"
      />

      {/* 黃金交叉標記 */}
      <circle cx="93" cy="126" r="5" className="kd-cross-dot kd-cross-golden" />
      <line x1="93" y1="126" x2="55" y2="185" className="kd-cross-leader" />
      <text x="8" y="200" className="kd-cross-label kd-cross-label-golden">
        黃金交叉：K 由下往上穿過 D
      </text>

      {/* 死亡交叉標記 */}
      <circle cx="245" cy="69" r="5" className="kd-cross-dot kd-cross-death" />
      <line x1="245" y1="69" x2="280" y2="16" className="kd-cross-leader" />
      <text x="200" y="14" className="kd-cross-label kd-cross-label-death">
        死亡交叉：K 由上往下穿過 D
      </text>
    </svg>
  );
}
