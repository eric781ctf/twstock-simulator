import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { ModelSummary } from "../types";

function formatPercent(value: number | null): string {
  if (value == null) return "-";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function returnClass(value: number | null): string {
  if (value == null) return "";
  return value >= 0 ? "buy-text" : "sell-text";
}

export default function ModelsPage() {
  const [models, setModels] = useState<ModelSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getPublicModels()
      .then(setModels)
      .catch((err) => setError(err instanceof Error ? err.message : "載入失敗"));
  }, []);

  return (
    <>
      <h2 className="section-title">模型列表</h2>
      <p className="empty-hint" style={{ marginBottom: 16 }}>
        每個模型每個交易日收盤後會對全部上市股票算分數，選出前 10 名標記為持有，之後依出場規則決定何時賣出。
        已實現與未實現的平均損益率都列出來，怎麼解讀由你自己判斷。
      </p>

      {error && <div className="error-msg">{error}</div>}

      {models === null ? (
        <div className="empty-hint">載入中...</div>
      ) : models.length === 0 ? (
        <div className="panel">
          <div className="empty-hint">目前還沒有訓練完成的模型</div>
        </div>
      ) : (
        <div className="model-card-grid">
          {models.map((m) => (
            <Link key={m.id} to={`/models/${m.id}`} className={`panel model-card ${m.is_archived ? "archived" : ""}`}>
              <div className="model-card-header">
                <span className="model-card-title">
                  {m.model_family} <span className="model-card-version">v{m.version}</span>
                </span>
                {m.is_archived && <span className="archived-badge">已封存</span>}
              </div>
              <div className="model-card-meta">
                {m.model_type}　預測未來 {m.n_days} 日　門檻 {m.threshold_percent}%
              </div>
              <div className="model-card-stats">
                <div className="stat">
                  <span className="label">已實現平均</span>
                  <span className={`value ${returnClass(m.average_realized_return_percent)}`}>
                    {formatPercent(m.average_realized_return_percent)}
                  </span>
                </div>
                <div className="stat">
                  <span className="label">未實現平均</span>
                  <span className={`value ${returnClass(m.average_unrealized_return_percent)}`}>
                    {formatPercent(m.average_unrealized_return_percent)}
                  </span>
                </div>
                <div className="stat">
                  <span className="label">持有中</span>
                  <span className="value">{m.open_holding_count}</span>
                </div>
                <div className="stat">
                  <span className="label">已平倉</span>
                  <span className="value">{m.closed_holding_count}</span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
