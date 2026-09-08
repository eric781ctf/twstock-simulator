import type { NetworkInfo } from "../types";

/**
 * 網路結構表 + 訓練 loss 曲線。
 *
 * 結構表刻意對齊 Keras `model.summary()` 的呈現方式（每層 type、output shape、
 * 參數量、最後總計），因為那是大家看神經網路結構時最熟悉的格式。
 * batch 維度寫成 None，那一維取決於餵幾筆進去，不是結構的一部分。
 */
export function NetworkSummary({ info }: { info: NetworkInfo }) {
  return (
    <>
      <div className="network-meta">
        <div className="stat">
          <span className="label">訓練裝置</span>
          <span className="value">{info.device}</span>
        </div>
        <div className="stat">
          <span className="label">隱藏層</span>
          <span className="value">{info.hidden_sizes.join(" → ")}</span>
        </div>
        <div className="stat">
          <span className="label">啟用函數</span>
          <span className="value">{info.activation}</span>
        </div>
        <div className="stat">
          <span className="label">Dropout</span>
          <span className="value">{info.dropout}</span>
        </div>
        <div className="stat">
          <span className="label">訓練輪數</span>
          <span className="value">{info.epochs}</span>
        </div>
        <div className="stat">
          <span className="label">總參數量</span>
          <span className="value">{info.total_params.toLocaleString()}</span>
        </div>
      </div>

      <div className="table-scroll">
        <table className="network-table">
          <thead>
            <tr>
              <th style={{ textAlign: "left" }}>Layer</th>
              <th style={{ textAlign: "left" }}>Type</th>
              <th style={{ textAlign: "left" }}>Output Shape</th>
              <th>Param #</th>
            </tr>
          </thead>
          <tbody>
            {info.layers.map((layer, i) => (
              <tr key={`${layer.name}-${i}`}>
                <td style={{ textAlign: "left" }}>{layer.name}</td>
                <td style={{ textAlign: "left" }}>{layer.type}</td>
                <td style={{ textAlign: "left" }} className="mono">
                  {layer.output_shape}
                </td>
                <td>{layer.params.toLocaleString()}</td>
              </tr>
            ))}
            <tr className="network-total-row">
              <td style={{ textAlign: "left" }} colSpan={3}>
                Total params
              </td>
              <td>{info.total_params.toLocaleString()}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h3 className="tutorial-heading">訓練過程的 Loss</h3>
      <p className="order-hint">
        兩條線分開看：訓練 loss 一直降但驗證 loss 開始往上，就是過擬合的訊號——
        代表網路開始在背訓練資料，而不是學到能套用到新資料的規律。
      </p>
      <LossCurve points={info.loss_curve} />
    </>
  );
}

const PADDING = { top: 16, right: 16, bottom: 34, left: 56 };
const VIEW_WIDTH = 720;
const HEIGHT = 260;

function LossCurve({ points }: { points: NetworkInfo["loss_curve"] }) {
  if (points.length === 0) return <div className="empty-hint">沒有 loss 紀錄</div>;

  const all = points.flatMap((p) => [p.train_loss, p.validation_loss]).filter((v) => Number.isFinite(v));
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  const plotWidth = VIEW_WIDTH - PADDING.left - PADDING.right;
  const plotHeight = HEIGHT - PADDING.top - PADDING.bottom;

  const toX = (epoch: number) =>
    PADDING.left + ((epoch - points[0].epoch) / Math.max(points.length - 1, 1)) * plotWidth;
  const toY = (value: number) => PADDING.top + plotHeight - ((value - min) / span) * plotHeight;

  const line = (key: "train_loss" | "validation_loss") =>
    points.map((p, i) => `${i === 0 ? "M" : "L"} ${toX(p.epoch)} ${toY(p[key])}`).join(" ");

  const ticks = [min, min + span / 2, max];

  return (
    <div className="svg-chart">
      <svg viewBox={`0 0 ${VIEW_WIDTH} ${HEIGHT}`} width="100%" height={HEIGHT} role="img">
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
              {t.toFixed(3)}
            </text>
          </g>
        ))}
        <path d={line("train_loss")} fill="none" stroke="#4fd8ff" strokeWidth="2" />
        <path d={line("validation_loss")} fill="none" stroke="#ff4f7e" strokeWidth="2" />
        <text x={PADDING.left + plotWidth / 2} y={HEIGHT - 6} textAnchor="middle" fontSize="11" fill="#7688a8">
          Epoch（{points[0].epoch} ~ {points[points.length - 1].epoch}）
        </text>
      </svg>
      <div className="svg-chart-legend">
        <span>
          <i style={{ background: "#4fd8ff" }} />
          訓練 loss
        </span>
        <span>
          <i style={{ background: "#ff4f7e" }} />
          驗證 loss
        </span>
      </div>
    </div>
  );
}
