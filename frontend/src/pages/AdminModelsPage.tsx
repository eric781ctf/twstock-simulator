import { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../api";
import { ConditionEditor } from "../components/ConditionEditor";
import { ScoreFormulaExplainer } from "../components/ScoreFormulaExplainer";
import { useAuth } from "../auth/AuthContext";
import type { Activation, Condition, ModelSummary, ModelTrainRequest, ModelType, TrainDefaults } from "../types";


const STATUS_LABEL: Record<ModelSummary["status"], string> = {
  queued: "排隊中",
  training: "訓練中",
  completed: "已完成",
  failed: "失敗",
};

// 訓練中的版本要持續看狀態，但訓練動輒數十秒到數分鐘，五分鐘輪詢一次就夠
const POLL_INTERVAL_MS = 5 * 60 * 1000;

function formatPercent(value: number | null): string {
  if (value == null) return "-";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "-";
  if (seconds < 60) return `${seconds.toFixed(1)} 秒`;
  return `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`;
}

export default function AdminModelsPage() {
  const { isAdmin } = useAuth();
  const [defaults, setDefaults] = useState<TrainDefaults | null>(null);
  const [models, setModels] = useState<ModelSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [family, setFamily] = useState("");
  const [modelType, setModelType] = useState<ModelType>("lightgbm");
  const [features, setFeatures] = useState<string[]>([]);
  const [nDays, setNDays] = useState("5");
  const [threshold, setThreshold] = useState("3");
  const [returnWeight, setReturnWeight] = useState("0.5");
  const [probabilityWeight, setProbabilityWeight] = useState("0.5");
  const [minHold, setMinHold] = useState("2");
  const [maxHold, setMaxHold] = useState("10");
  const [stopLoss, setStopLoss] = useState("5");
  const [takeProfit, setTakeProfit] = useState("8");
  const [sellConditions, setSellConditions] = useState<Condition[]>([]);
  const [hiddenSizes, setHiddenSizes] = useState("64, 32");
  const [activation, setActivation] = useState<Activation>("relu");
  const [dropout, setDropout] = useState("0.2");
  const [learningRate, setLearningRate] = useState("0.001");
  const [epochs, setEpochs] = useState("60");
  const [dates, setDates] = useState({
    train_start: "",
    train_end: "",
    validation_start: "",
    validation_end: "",
    test_start: "",
    test_end: "",
  });

  const refreshModels = useCallback(async () => {
    try {
      setModels(await api.getAdminModels());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    refreshModels();
    api.getTrainDefaults().then((res) => {
      setDefaults(res);
      setFeatures(res.default_features);
      setDates({
        train_start: res.train_start,
        train_end: res.train_end,
        validation_start: res.validation_start,
        validation_end: res.validation_end,
        test_start: res.test_start,
        test_end: res.test_end,
      });
    });
  }, [isAdmin, refreshModels]);

  useEffect(() => {
    if (!isAdmin) return;
    const timer = setInterval(refreshModels, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [isAdmin, refreshModels]);

  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }

  function toggleFeature(key: string) {
    setFeatures((prev) => (prev.includes(key) ? prev.filter((f) => f !== key) : [...prev, key]));
  }

  function optionalNumber(value: string): number | null {
    const n = Number(value);
    return value.trim() === "" || !Number.isFinite(n) ? null : n;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);

    if (!family.trim()) {
      setError("請輸入模型名稱");
      return;
    }
    if (features.length === 0) {
      setError("至少要勾選一項特徵");
      return;
    }
    if (isNeural && parsedHiddenSizes.length === 0) {
      setError("請輸入每層的神經元數，例如 64, 32");
      return;
    }

    const payload: ModelTrainRequest = {
      model_family: family.trim(),
      model_type: modelType,
      feature_config: features,
      n_days: Number(nDays),
      threshold_percent: Number(threshold),
      score_weights: { return: Number(returnWeight), probability: Number(probabilityWeight) },
      network_config: isNeural
        ? {
            hidden_sizes: parsedHiddenSizes,
            activation,
            dropout: Number(dropout),
            learning_rate: Number(learningRate),
            epochs: Number(epochs),
          }
        : null,
      min_hold_days: optionalNumber(minHold),
      max_hold_days: optionalNumber(maxHold),
      stop_loss_percent: optionalNumber(stopLoss),
      take_profit_percent: optionalNumber(takeProfit),
      sell_conditions: sellConditions,
      ...dates,
    };

    setBusy(true);
    try {
      const created = await api.trainModel(payload);
      setNotice(`已排入訓練：${created.model_family} v${created.version}，訓練在背景進行，狀態每 5 分鐘更新一次`);
      setFormOpen(false);
      await refreshModels();
    } catch (err) {
      setError(err instanceof Error ? err.message : "送出失敗");
    } finally {
      setBusy(false);
    }
  }

  async function handleToggleArchive(model: ModelSummary) {
    const action = model.is_archived ? "取消封存" : "封存";
    if (!window.confirm(`確定要${action}「${model.model_family} v${model.version}」嗎？`)) return;
    try {
      if (model.is_archived) await api.unarchiveModel(model.id);
      else await api.archiveModel(model.id);
      await refreshModels();
    } catch (err) {
      alert(err instanceof Error ? err.message : "操作失敗");
    }
  }

  // 哪些類型算神經網路由後端決定，前端不自己維護一份清單
  const isNeural = defaults?.model_types.find((t) => t.key === modelType)?.is_neural ?? false;
  const parsedHiddenSizes = hiddenSizes
    .split(/[,\s]+/)
    .map((v) => Number(v.trim()))
    .filter((v) => Number.isFinite(v) && v > 0);

  const hasRunning = models.some((m) => m.status === "queued" || m.status === "training");

  return (
    <>
      <h2 className="section-title">模型管理</h2>

      {notice && <div className="panel model-notice">{notice}</div>}

      {!formOpen && (
        <button className="submit strategy-new-btn" onClick={() => setFormOpen(true)}>
          + 訓練新模型
        </button>
      )}

      {formOpen && defaults && (
        <form className="panel" onSubmit={handleSubmit}>
          <h2>訓練新模型</h2>
          <p className="order-hint">
            本地日K資料最新到 <span className="admin-current-value">{defaults.latest_data_date ?? "無資料"}</span>
            　下方日期已依此帶入建議值（訓練 3 個月 / 驗證 2 個月 / 測試 1 個月），可自行調整
          </p>

          <input placeholder="模型名稱（同名字會累積成新版本）" value={family} onChange={(e) => setFamily(e.target.value)} />

          <div className="strategy-form-grid">
            <label>
              模型類型
              <select value={modelType} onChange={(e) => setModelType(e.target.value as ModelType)}>
                {defaults.model_types.map((t) => (
                  <option key={t.key} value={t.key}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              預測未來幾個交易日
              <input type="number" min={1} max={60} value={nDays} onChange={(e) => setNDays(e.target.value)} />
            </label>
            <label>
              報酬率門檻（%）
              <input type="number" step="0.1" value={threshold} onChange={(e) => setThreshold(e.target.value)} />
            </label>
            <label>
              預期報酬權重 w₁
              <input type="number" step="0.1" value={returnWeight} onChange={(e) => setReturnWeight(e.target.value)} />
            </label>
            <label>
              達標機率權重 w₂
              <input
                type="number"
                step="0.1"
                value={probabilityWeight}
                onChange={(e) => setProbabilityWeight(e.target.value)}
              />
            </label>
          </div>

          {isNeural && (
            <>
              <h3 className="tutorial-heading">網路結構</h3>
              <p className="order-hint">
                只有神經網路類型有「層」的概念（樹模型是一堆決策樹的集成，沒有層）。
                這裡設定的是共享 encoder 的結構——兩個輸出頭（預期報酬、達標機率）會接在最後一層之後，
                共用同一組隱藏層一起訓練。訓練一律使用 GPU，沒有可用的 GPU 會直接失敗。
              </p>
              <div className="strategy-form-grid">
                <label>
                  每層神經元數（用逗號分隔）
                  <input
                    placeholder="64, 32"
                    value={hiddenSizes}
                    onChange={(e) => setHiddenSizes(e.target.value)}
                  />
                </label>
                <label>
                  啟用函數
                  <select value={activation} onChange={(e) => setActivation(e.target.value as Activation)}>
                    <option value="relu">ReLU</option>
                    <option value="tanh">Tanh</option>
                    <option value="gelu">GELU</option>
                  </select>
                </label>
                <label>
                  Dropout
                  <input type="number" step="0.05" min={0} max={0.9} value={dropout} onChange={(e) => setDropout(e.target.value)} />
                </label>
                <label>
                  學習率
                  <input type="number" step="0.0001" value={learningRate} onChange={(e) => setLearningRate(e.target.value)} />
                </label>
                <label>
                  訓練輪數 epochs
                  <input type="number" min={1} max={1000} value={epochs} onChange={(e) => setEpochs(e.target.value)} />
                </label>
              </div>
              {parsedHiddenSizes.length > 0 && (
                <p className="order-hint network-preview">
                  結構預覽：{features.length} 個特徵 → {parsedHiddenSizes.join(" → ")} → 兩個輸出頭（迴歸 1、分類 1）
                </p>
              )}
            </>
          )}

          <h3 className="tutorial-heading">選股分數怎麼算</h3>
          <ScoreFormulaExplainer
            info={defaults.score_formula}
            weights={{ return: Number(returnWeight), probability: Number(probabilityWeight) }}
          />

          <h3 className="tutorial-heading">訓練特徵（已勾選 {features.length} 項）</h3>
          <div className="feature-checkbox-grid">
            {defaults.features.map((f) => (
              <label key={f.key} className={features.includes(f.key) ? "feature-checkbox active" : "feature-checkbox"}>
                <input type="checkbox" checked={features.includes(f.key)} onChange={() => toggleFeature(f.key)} />
                {f.label}
              </label>
            ))}
          </div>

          <h3 className="tutorial-heading">資料切分</h3>
          <p className="order-hint">依時間切分，不能隨機切——訓練期一定要早於驗證期，驗證期早於測試期</p>
          <div className="strategy-form-grid">
            {(
              [
                ["train_start", "訓練起"],
                ["train_end", "訓練迄"],
                ["validation_start", "驗證起"],
                ["validation_end", "驗證迄"],
                ["test_start", "測試起"],
                ["test_end", "測試迄"],
              ] as const
            ).map(([key, label]) => (
              <label key={key}>
                {label}
                <input
                  type="date"
                  value={dates[key]}
                  onChange={(e) => setDates((prev) => ({ ...prev, [key]: e.target.value }))}
                />
              </label>
            ))}
          </div>

          <h3 className="tutorial-heading">出場規則</h3>
          <p className="order-hint">
            判斷順序：最長持有天數 → 停損/停利 → 過了最少持有天數才看規則條件（留空代表不啟用該項）
          </p>
          <div className="strategy-form-grid">
            <label>
              最少持有天數
              <input type="number" min={0} value={minHold} onChange={(e) => setMinHold(e.target.value)} />
            </label>
            <label>
              最長持有天數
              <input type="number" min={1} value={maxHold} onChange={(e) => setMaxHold(e.target.value)} />
            </label>
            <label>
              停損（%）
              <input type="number" step="0.5" value={stopLoss} onChange={(e) => setStopLoss(e.target.value)} />
            </label>
            <label>
              停利（%）
              <input type="number" step="0.5" value={takeProfit} onChange={(e) => setTakeProfit(e.target.value)} />
            </label>
          </div>

          <ConditionEditor
            label="賣出規則條件"
            hint="全部條件都符合才會賣出（過了最少持有天數之後才會檢查）"
            conditions={sellConditions}
            onChange={setSellConditions}
          />

          {error && <div className="error-msg">{error}</div>}
          <div className="strategy-form-actions">
            <button className="submit" type="submit" disabled={busy}>
              {busy ? "送出中..." : "開始訓練"}
            </button>
            <button type="button" className="cancel-btn" onClick={() => setFormOpen(false)}>
              取消
            </button>
          </div>
        </form>
      )}

      <div className="panel">
        <h2>模型版本</h2>
        <p className="order-hint">
          {hasRunning ? "有模型正在訓練中，狀態每 5 分鐘自動更新一次" : "每次訓練都是新版本，封存後不再參與每日選股，歷史績效仍可查看"}
        </p>
        {loading ? (
          <div className="empty-hint">載入中...</div>
        ) : models.length === 0 ? (
          <div className="empty-hint">還沒有任何模型，點上面「訓練新模型」建立第一個</div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>模型</th>
                  <th>類型</th>
                  <th>狀態</th>
                  <th>訓練耗時</th>
                  <th>持有中</th>
                  <th>已平倉</th>
                  <th>已實現平均</th>
                  <th>未實現平均</th>
                  <th>訓練完成時間</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {models.map((m) => (
                  <tr key={m.id}>
                    <td style={{ textAlign: "left" }}>
                      {m.model_family} v{m.version}
                      {m.is_archived && <span className="archived-badge">已封存</span>}
                      {m.error_message && <div className="model-error">{m.error_message}</div>}
                    </td>
                    <td>{m.model_type}</td>
                    <td className={`model-status-${m.status}`}>{STATUS_LABEL[m.status]}</td>
                    <td>{formatDuration(m.training_duration_seconds)}</td>
                    <td>{m.open_holding_count}</td>
                    <td>{m.closed_holding_count}</td>
                    <td
                      className={
                        m.average_realized_return_percent == null
                          ? ""
                          : m.average_realized_return_percent >= 0
                            ? "buy-text"
                            : "sell-text"
                      }
                    >
                      {formatPercent(m.average_realized_return_percent)}
                    </td>
                    <td
                      className={
                        m.average_unrealized_return_percent == null
                          ? ""
                          : m.average_unrealized_return_percent >= 0
                            ? "buy-text"
                            : "sell-text"
                      }
                    >
                      {formatPercent(m.average_unrealized_return_percent)}
                    </td>
                    <td>{m.trained_at ? new Date(m.trained_at).toLocaleString("zh-TW", { hour12: false }) : "-"}</td>
                    <td>
                      {m.status === "completed" && (
                        <span className="cancel-link" onClick={() => handleToggleArchive(m)}>
                          {m.is_archived ? "取消封存" : "封存"}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
