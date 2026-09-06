import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { CalibrationChart } from "../components/CalibrationChart";
import { FeatureImportanceChart } from "../components/FeatureImportanceChart";
import { PredictionScatterChart } from "../components/PredictionScatterChart";
import { ReturnScatterChart } from "../components/ReturnScatterChart";
import type { ModelDetail, ModelHoldingItem } from "../types";

const EXIT_REASON_LABEL: Record<string, string> = {
  rule_condition: "規則條件",
  stop_loss: "停損",
  take_profit: "停利",
  max_hold_days: "持有到期",
  backtest_end: "回測結束平倉",
};

const SCORE_FORMULA_LABEL: Record<string, string> = {
  multiply: "預期報酬 × 機率",
  zscore_weighted: "標準化後加權平均",
};

function pct(value: number | null | undefined): string {
  if (value == null) return "-";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function cls(value: number | null | undefined): string {
  if (value == null) return "";
  return value >= 0 ? "buy-text" : "sell-text";
}

function num(value: number | null | undefined, digits = 3): string {
  return value == null ? "-" : value.toFixed(digits);
}

function HoldingsTable({ holdings, closed }: { holdings: ModelHoldingItem[]; closed: boolean }) {
  if (holdings.length === 0) {
    return <div className="empty-hint">{closed ? "還沒有平倉紀錄" : "目前沒有持有部位"}</div>;
  }
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>股票</th>
            <th>進場日</th>
            <th>成本</th>
            <th>{closed ? "出場日" : "持有天數"}</th>
            <th>{closed ? "出場價" : "目前價"}</th>
            <th>損益率</th>
            {closed && <th>出場原因</th>}
          </tr>
        </thead>
        <tbody>
          {holdings.map((h, i) => (
            <tr key={`${h.stock_code}-${h.entry_date}-${i}`}>
              <td style={{ textAlign: "left" }}>
                {h.stock_code} {h.stock_name}
              </td>
              <td>{h.entry_date}</td>
              <td>{h.entry_price.toFixed(2)}</td>
              <td>{closed ? h.exit_date : `${h.held_days} 天`}</td>
              <td>{closed ? h.exit_price?.toFixed(2) ?? "-" : h.current_price?.toFixed(2) ?? "-"}</td>
              <td className={cls(h.return_percent)}>{pct(h.return_percent)}</td>
              {closed && <td>{h.exit_reason ? EXIT_REASON_LABEL[h.exit_reason] ?? h.exit_reason : "-"}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ModelDetailPage() {
  const { id } = useParams();
  const [detail, setDetail] = useState<ModelDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    api
      .getPublicModel(Number(id))
      .then(setDetail)
      .catch((err) => setError(err instanceof Error ? err.message : "載入失敗"));
  }, [id]);

  if (error) return <div className="error-msg">{error}</div>;
  if (!detail) return <div className="empty-hint">載入中...</div>;

  const { summary, metrics } = detail;
  const test = metrics?.test;
  const backtest = metrics?.backtest;
  const isLinear = summary.model_type === "logistic_regression";

  return (
    <>
      <div className="section-title-row">
        <h2 className="section-title">
          {summary.model_family} <span className="model-card-version">v{summary.version}</span>
          {summary.is_archived && <span className="archived-badge">已封存</span>}
        </h2>
        <Link to="/" className="reset-range-btn">
          ← 回模型列表
        </Link>
      </div>

      {detail.warnings.length > 0 && (
        <div className="panel warning-panel">
          <h2>資料品質提醒</h2>
          {detail.warnings.map((w, i) => (
            <div key={i} className="order-hint warn">
              {w}
            </div>
          ))}
        </div>
      )}

      <div className="account-bar">
        <div className="stat">
          <span className="label">已實現平均損益率</span>
          <span className={`value ${cls(summary.average_realized_return_percent)}`}>
            {pct(summary.average_realized_return_percent)}
          </span>
        </div>
        <div className="stat">
          <span className="label">未實現平均損益率</span>
          <span className={`value ${cls(summary.average_unrealized_return_percent)}`}>
            {pct(summary.average_unrealized_return_percent)}
          </span>
        </div>
        <div className="stat">
          <span className="label">持有中 / 已平倉</span>
          <span className="value">
            {summary.open_holding_count} / {summary.closed_holding_count}
          </span>
        </div>
        <div className="stat">
          <span className="label">訓練耗時</span>
          <span className="value">
            {summary.training_duration_seconds ? `${summary.training_duration_seconds.toFixed(1)} 秒` : "-"}
          </span>
        </div>
        <div className="stat">
          <span className="label">每日選股平均耗時</span>
          <span className="value">
            {detail.average_scoring_seconds ? `${detail.average_scoring_seconds.toFixed(1)} 秒` : "-"}
          </span>
        </div>
      </div>

      <h2 className="section-title">目前持有</h2>
      <div className="panel">
        <HoldingsTable holdings={detail.open_holdings} closed={false} />
      </div>

      <h2 className="section-title">回測表現（測試期，模型完全沒看過的資料）</h2>
      <div className="panel">
        {backtest && (
          <div className="backtest-stats-grid">
            <div className="stat">
              <span className="label">模擬交易筆數</span>
              <span className="value">{backtest.holding_count ?? "-"}</span>
            </div>
            <div className="stat">
              <span className="label">平均報酬率</span>
              <span className={`value ${cls(backtest.average_return_percent)}`}>
                {pct(backtest.average_return_percent)}
              </span>
            </div>
            <div className="stat">
              <span className="label">中位數報酬率</span>
              <span className={`value ${cls(backtest.median_return_percent)}`}>
                {pct(backtest.median_return_percent)}
              </span>
            </div>
            <div className="stat">
              <span className="label">勝率</span>
              <span className="value">
                {backtest.win_rate != null ? `${(backtest.win_rate * 100).toFixed(1)}%` : "-"}（{backtest.win_count}勝
                {backtest.loss_count}敗）
              </span>
            </div>
            <div className="stat">
              <span className="label">最佳 / 最差</span>
              <span className="value">
                {pct(backtest.best_return_percent)} / {pct(backtest.worst_return_percent)}
              </span>
            </div>
          </div>
        )}
        <h3 className="tutorial-heading">每筆模擬交易的損益率</h3>
        <ReturnScatterChart
          points={detail.backtest_trades.map((t) => ({ date: t.entry_date, value: t.return_percent }))}
          emptyText="回測期間沒有產生任何交易"
        />
      </div>

      <h2 className="section-title">模型準確度</h2>
      <div className="panel">
        <h3 className="tutorial-heading">迴歸：預測報酬率 vs 實際報酬率</h3>
        {test && (
          <p className="order-hint">
            MAE {num(test.mae)}　RMSE {num(test.rmse)}　Rank IC {num(test.rank_ic, 4)}
            　（Rank IC 衡量排序品質，選股比起預測值準不準更在意這個）
          </p>
        )}
        <PredictionScatterChart
          points={detail.regression_points.map((p) => ({
            x: p.predicted_return_percent,
            y: p.actual_return_percent,
          }))}
          xLabel={`預測未來 ${summary.n_days} 日報酬率 (%)`}
          yLabel={`實際未來 ${summary.n_days} 日報酬率 (%)`}
        />
      </div>

      <div className="panel">
        <h3 className="tutorial-heading">分類：機率校準度</h3>
        {test && (
          <p className="order-hint">
            {`準確率 ${test.accuracy != null ? `${(test.accuracy * 100).toFixed(1)}%` : "-"}　AUC ${num(test.auc)}　Brier score ${num(test.brier_score)}　（Brier 越低代表機率越可信）`}
          </p>
        )}
        <CalibrationChart buckets={detail.calibration_buckets} />
      </div>

      <h2 className="section-title">模型倚重哪些特徵</h2>
      <div className="stats-section">
        <div className="panel">
          <h2>迴歸頭</h2>
          <p className="order-hint">
            {isLinear ? "線性模型的係數，有正負號代表影響方向" : "樹模型的特徵重要性，數值越大代表越常被用來分裂"}
          </p>
          <FeatureImportanceChart items={detail.regression_feature_importance} signed={isLinear} />
        </div>
        <div className="panel">
          <h2>分類頭</h2>
          <p className="order-hint">
            {isLinear ? "邏輯迴歸的係數，正值代表推高達標機率" : "樹模型的特徵重要性"}
          </p>
          <FeatureImportanceChart items={detail.classification_feature_importance} signed={isLinear} />
        </div>
      </div>

      <h2 className="section-title">訓練參數</h2>
      <div className="panel">
        <div className="strategy-card-body">
          <div>
            <span className="label">模型類型</span> {summary.model_type}
          </div>
          <div>
            <span className="label">預測目標</span> 未來 {summary.n_days} 個交易日報酬率，以及是否超過 {summary.threshold_percent}%
          </div>
          <div>
            <span className="label">選股分數</span> {SCORE_FORMULA_LABEL[summary.score_formula] ?? summary.score_formula}
            {detail.score_weights &&
              `（報酬權重 ${detail.score_weights.return}、機率權重 ${detail.score_weights.probability}）`}
          </div>
          <div>
            <span className="label">訓練特徵</span> {detail.feature_labels.join("、")}
          </div>
          <div>
            <span className="label">資料切分</span> 訓練 {detail.train_start}~{detail.train_end}　驗證{" "}
            {detail.validation_start}~{detail.validation_end}　測試 {detail.test_start}~{detail.test_end}
          </div>
          <div>
            <span className="label">出場規則</span>
            {detail.max_hold_days != null && `最長持有 ${detail.max_hold_days} 天　`}
            {detail.stop_loss_percent != null && `停損 ${detail.stop_loss_percent}%　`}
            {detail.take_profit_percent != null && `停利 ${detail.take_profit_percent}%　`}
            {detail.min_hold_days != null && `最少持有 ${detail.min_hold_days} 天`}
            {detail.sell_conditions.length > 0 && `　＋ ${detail.sell_conditions.length} 項規則條件`}
          </div>
        </div>
      </div>

      <h2 className="section-title">平倉紀錄</h2>
      <div className="panel">
        <HoldingsTable holdings={detail.closed_holdings} closed />
      </div>
    </>
  );
}
