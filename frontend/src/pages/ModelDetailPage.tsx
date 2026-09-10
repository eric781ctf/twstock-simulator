import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { CalibrationChart } from "../components/CalibrationChart";
import { FeatureImportanceChart } from "../components/FeatureImportanceChart";
import { NetworkSummary } from "../components/NetworkSummary";
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

      <h2 className="section-title">選股分數怎麼算</h2>
      <div className="panel">
        <p className="order-hint">
          每個交易日收盤後，模型會對全部上市股票各算一個分數，取最高的前 10 名買進。
        </p>
        {/* 公式的完整說明只寫在模型教學一處，這裡只放這個模型自己的權重再連過去，
            免得同一套解釋散在多頁、改了其中一份就開始互相矛盾 */}
        <div className="formula-box">
          <div className="formula-main">{detail.score_formula_info.formula}</div>
          <div className="formula-weights">
            這個模型的權重：w₁（預期報酬）= <b>{detail.score_weights?.return ?? 0.5}</b>　 w₂（達標機率）={" "}
            <b>{detail.score_weights?.probability ?? 0.5}</b>
          </div>
        </div>
        <p className="order-hint">
          這個公式在算什麼、為什麼要先做橫斷面標準化、它沒有解決什麼——
          <Link to="/model-tutorial#score-formula">模型教學裡有完整說明</Link>。
        </p>
      </div>

      {detail.walk_forward && detail.folds.length > 0 && (
        <>
          <h2 className="section-title">滾動驗證（{detail.walk_forward.fold_count} 折）</h2>
          <div className="panel">
            <p className="order-hint">
              同一組設定在多段不同時期各測一次。<b>標準差比平均更重要</b>——
              平均值再漂亮，只要折與折之間跳得比平均還大，那個數字就站不住腳。
            </p>

            <div className="backtest-stats-grid">
              {(
                [
                  ["測試 Rank IC", detail.walk_forward.test_rank_ic, 4],
                  ["測試 AUC", detail.walk_forward.test_auc, 4],
                  ["驗證 Rank IC", detail.walk_forward.validation_rank_ic, 4],
                ] as const
              ).map(([label, stat, digits]) =>
                stat ? (
                  <div className="stat" key={label}>
                    <span className="label">{label}</span>
                    <span className={`value ${cls(stat.mean)}`}>
                      {stat.mean >= 0 ? "+" : ""}
                      {stat.mean.toFixed(digits)}
                    </span>
                    <span className="label">
                      ± {stat.std.toFixed(digits)}　{stat.positive_folds}/{stat.count} 折為正
                    </span>
                  </div>
                ) : null
              )}
            </div>

            <h3 className="tutorial-heading">每一折</h3>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>折</th>
                    <th>訓練期</th>
                    <th>測試期</th>
                    <th>訓練 IC</th>
                    <th>驗證 IC</th>
                    <th>測試 IC</th>
                    <th>測試 AUC</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.folds.map((f) => (
                    <tr key={f.fold.index}>
                      <td>{f.fold.index}</td>
                      <td>
                        {f.fold.train_start} ~ {f.fold.train_end}
                      </td>
                      <td>
                        {f.fold.test_start} ~ {f.fold.test_end}
                      </td>
                      <td>{num(f.train.rank_ic, 4)}</td>
                      <td>{num(f.validation.rank_ic, 4)}</td>
                      <td className={cls(f.test.rank_ic)}>{num(f.test.rank_ic, 4)}</td>
                      <td>{num(f.test.auc, 4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="order-hint">
              折與折之間的訓練期高度重疊（每次只往前滾幾個月），所以這不等於幾次完全獨立的驗證，
              但已經比單一次固定切分可信得多。下方的圖表與回測用的是<b>最後一折</b>——
              它是用最近的資料訓練的，也就是真的會被拿去每日選股的那一個。
            </p>
          </div>
        </>
      )}

      <h2 className="section-title">模型準確度</h2>
      <div className="panel">
        <h3 className="tutorial-heading">
          迴歸：預測 vs 實際{summary.label_mode === "excess" ? "超額報酬" : "報酬率"}
        </h3>
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

      {detail.network && (
        <>
          <h2 className="section-title">網路結構</h2>
          <div className="panel">
            <p className="order-hint">
              這是一個共享 encoder 的雙任務網路：同一組隱藏層同時餵給「預期報酬」與「達標機率」兩個輸出頭，
              兩邊的梯度會一起更新共享層。樹模型（XGBoost 等）沒有這個結構，是各自訓練兩個獨立模型。
            </p>
            {detail.network.sequence_length && (
              <p className="order-hint">
                這個模型是循環神經網路（{detail.network.kind?.toUpperCase()}）：一個樣本是
                「這一天之前連續 {detail.network.sequence_length} 個交易日」的特徵，網路依序讀完這段歷史，
                取最後一個時間步的狀態去預測。所以下表的 shape 比一般網路多一個時間維度
                （None、時間步、特徵數）。
              </p>
            )}
            <NetworkSummary info={detail.network} />
          </div>
        </>
      )}

      <h2 className="section-title">模型倚重哪些特徵</h2>
      {detail.network ? (
        // 神經網路的兩個輸出頭吃的是同一組共享隱藏層，第一層權重只有一份，
        // 拆成「迴歸頭 / 分類頭」兩張圖會畫出兩張一模一樣的圖，看起來像是
        // 分別量出來的，其實不是——所以這裡只畫一張，並寫清楚它代表什麼。
        <div className="panel">
          <h2>共享 encoder 的第一層權重</h2>
          <p className="order-hint">
            神經網路沒有內建的特徵重要性，這裡用第一層權重的絕對值平均當粗略指標，跟樹模型的分裂貢獻不是同一回事。
            迴歸頭與分類頭共用同一組隱藏層，所以這份指標對兩個任務是同一份，無法拆開來看誰倚重誰。
          </p>
          <FeatureImportanceChart items={detail.regression_feature_importance} signed={false} />
        </div>
      ) : (
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
      )}

      <h2 className="section-title">訓練參數</h2>
      <div className="panel">
        <div className="strategy-card-body">
          <div>
            <span className="label">模型類型</span> {summary.model_type}
          </div>
          <div>
            <span className="label">預測目標</span> 未來 {summary.n_days} 個交易日的
            {summary.label_mode === "excess" ? "超額報酬（個股減掉大盤）" : "絕對報酬"}
            ，以及是否超過 {summary.threshold_percent}%
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
