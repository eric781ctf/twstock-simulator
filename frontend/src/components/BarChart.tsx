import type { DailyBarBucket } from "../types";

export function BarChart({ buckets }: { buckets: DailyBarBucket[] }) {
  const max = Math.max(1, ...buckets.map((b) => b.count));
  return (
    <div className="bar-chart">
      {buckets.map((b) => (
        <div className="bar-chart-row" key={b.label}>
          <span className="bar-chart-label">{b.label}</span>
          <div className="bar-chart-track">
            <div className="bar-chart-fill" style={{ width: `${(b.count / max) * 100}%` }} />
          </div>
          <span className="bar-chart-count">{b.count.toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}
