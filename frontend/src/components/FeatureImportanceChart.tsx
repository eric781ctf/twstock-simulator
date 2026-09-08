import type { FeatureImportance } from "../types";

interface Props {
  items: FeatureImportance[];
  emptyText?: string;
  /** 線性模型的係數有正負號（代表影響方向），樹模型的重要性一律非負 */
  signed: boolean;
}

/**
 * 特徵重要性長條圖。沿用 BarChart 的視覺風格，但那個元件是「填滿到最大值的
 * 百分比」，只支援非負數值；邏輯迴歸的係數有正負號，長條必須能從中間往左或
 * 往右畫，所以另外做一個。
 */
export function FeatureImportanceChart({ items, emptyText = "尚無資料", signed }: Props) {
  if (items.length === 0) return <div className="empty-hint">{emptyText}</div>;

  const sorted = [...items].sort((a, b) => Math.abs(b.importance) - Math.abs(a.importance));
  const max = Math.max(...sorted.map((i) => Math.abs(i.importance)), 1e-9);
  // 各種模型給的重要性量級差很多：樹模型的 gain 可能是幾百，神經網路第一層的
  // 權重平均是 0.x，線性模型的係數又更小。固定小數位一定有一邊會被顯示成 0，
  // 所以位數由這組數字裡最大的那個決定。
  const decimals = max >= 100 ? 0 : max >= 10 ? 1 : max >= 1 ? 2 : max >= 0.01 ? 3 : 5;
  const format = (value: number) => value.toFixed(decimals);

  return (
    <div className="bar-chart feature-importance-chart">
      {sorted.map((item) => {
        const ratio = Math.abs(item.importance) / max;
        const isNegative = item.importance < 0;
        return (
          <div className="bar-chart-row" key={item.feature}>
            <span className="bar-chart-label" title={item.feature}>
              {item.label}
            </span>
            <div className="bar-chart-track">
              {signed ? (
                <div className="signed-bar-wrap">
                  <div className="signed-bar-zero" />
                  <div
                    className={`bar-chart-fill ${isNegative ? "negative" : "positive"}`}
                    style={{
                      width: `${(ratio * 100) / 2}%`,
                      marginLeft: isNegative ? `${50 - (ratio * 100) / 2}%` : "50%",
                    }}
                  />
                </div>
              ) : (
                <div className="bar-chart-fill" style={{ width: `${ratio * 100}%` }} />
              )}
            </div>
            <span className="bar-chart-count">{format(item.importance)}</span>
          </div>
        );
      })}
    </div>
  );
}
