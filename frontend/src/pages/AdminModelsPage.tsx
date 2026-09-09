import { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../api";
import { ConditionEditor } from "../components/ConditionEditor";
import { ScoreFormulaExplainer } from "../components/ScoreFormulaExplainer";
import { useAuth } from "../auth/AuthContext";
import type {
  Activation,
  Condition,
  ModelSummary,
  ModelTrainRequest,
  ModelType,
  ModelTypeOption,
  TrainDefaults,
} from "../types";


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

/** 模型名稱本身只寫演算法名稱，「需要 GPU」「吃序列」這類特性由旗標推導出來，
 * 不寫死在名稱字串裡——不然旗標改了名稱卻沒改，下拉選單就會騙人。 */
function typeHints(option: ModelTypeOption): string {
  const hints = [option.is_neural && "需要 GPU", option.is_sequence && "吃連續 N 天序列"].filter(Boolean);
  return hints.length > 0 ? `　— ${hints.join("、")}` : "";
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
  const [sequenceLength, setSequenceLength] = useState("20");
  const [patience, setPatience] = useState("10");
  const [batchSize, setBatchSize] = useState("512");
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
            sequence_length: Number(sequenceLength),
            patience: Number(patience),
            batch_size: Number(batchSize),
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

  async function handleDelete(model: ModelSummary) {
    const name = `${model.model_family} v${model.version}`;
    // 確認訊息要具體講出會失去什麼。訓練失敗的版本本來就沒有資料，
    // 但已完成的版本可能帶著一整段持有紀錄，那是刪掉就回不來的東西。
    const holdings = model.open_holding_count + model.closed_holding_count;
    const detail =
      model.status === "completed"
        ? `這會一併刪掉它的回測預測、${holdings} 筆持有紀錄、每日執行紀錄與模型檔案，且無法還原。\n\n` +
          "如果只是想讓它停止每日選股、但保留歷史，請改用「封存」。"
        : "這個版本沒有訓練成功，刪掉不會影響任何歷史資料。";

    if (!window.confirm(`確定要刪除「${name}」嗎？\n\n${detail}`)) return;
    try {
      const result = await api.deleteModel(model.id);
      setNotice(
        `已刪除 ${result.label}：預測 ${result.deleted_predictions} 筆、持有 ${result.deleted_holdings} 筆、` +
          `執行紀錄 ${result.deleted_scoring_runs} 筆${result.removed_artifact ? "，模型檔案已移除" : ""}`
      );
      await refreshModels();
    } catch (err) {
      alert(err instanceof Error ? err.message : "刪除失敗");
    }
  }

  // 哪些類型算神經網路／序列模型由後端決定，前端不自己維護一份清單
  const selectedType = defaults?.model_types.find((t) => t.key === modelType);
  const isNeural = selectedType?.is_neural ?? false;
  const isSequence = selectedType?.is_sequence ?? false;
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
                    {typeHints(t)}
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
                只有神經網路類型有「層」的概念（樹模型是一堆決策樹合起來投票，沒有層）。
                這裡設定的是共享 encoder 的結構——兩個輸出頭（預期報酬、達標機率）會接在最後一層之後，
                共用同一組隱藏層一起訓練。訓練一律使用 GPU，沒有可用的 GPU 會直接失敗。
              </p>
              {isSequence && (
                <p className="order-hint">
                  這是循環神經網路：一個樣本不是「某一天的特徵」，而是「這一天之前連續 N 天的特徵」，
                  由網路自己去看這段期間怎麼變化。相對地，前面歷史不足 N 天的股票（剛上市、或本地日K
                  還沒回補到那麼早）當天就不會被列入選股候選。
                </p>
              )}
              <div className="strategy-form-grid">
                <label>
                  Hidden sizes
                  <input
                    placeholder="64, 32"
                    value={hiddenSizes}
                    onChange={(e) => setHiddenSizes(e.target.value)}
                  />
                </label>
                {isSequence ? (
                  <label>
                    Sequence length
                    <input
                      type="number"
                      min={5}
                      max={120}
                      value={sequenceLength}
                      onChange={(e) => setSequenceLength(e.target.value)}
                    />
                  </label>
                ) : (
                  <label>
                    Activation
                    <select value={activation} onChange={(e) => setActivation(e.target.value as Activation)}>
                      <option value="relu">ReLU</option>
                      <option value="tanh">Tanh</option>
                      <option value="gelu">GELU</option>
                    </select>
                  </label>
                )}
                <label>
                  Dropout
                  <input type="number" step="0.05" min={0} max={0.9} value={dropout} onChange={(e) => setDropout(e.target.value)} />
                </label>
                <label>
                  Learning rate
                  <input type="number" step="0.0001" value={learningRate} onChange={(e) => setLearningRate(e.target.value)} />
                </label>
                <label>
                  Epochs
                  <input type="number" min={1} max={1000} value={epochs} onChange={(e) => setEpochs(e.target.value)} />
                </label>
                <label>
                  Early stopping patience
                  <input type="number" min={0} max={200} value={patience} onChange={(e) => setPatience(e.target.value)} />
                </label>
                <label>
                  Batch size
                  <input
                    type="number"
                    min={8}
                    max={16384}
                    value={batchSize}
                    onChange={(e) => setBatchSize(e.target.value)}
                  />
                </label>
              </div>
              <p className="order-hint">
                Hidden sizes 是每層的神經元數，用逗號分隔（例如 <code>64, 32</code> 代表兩層）。
                Sequence length 是一個樣本往回看幾個交易日，只有 GRU / LSTM 會用到。
                Early stopping patience 設 0 代表關閉早停。
              </p>
              <p className="order-hint">
                Batch size 是一次送進網路幾筆。<b>顯示記憶體不足（CUDA out of memory）時就調小它</b>，
                代價是訓練變慢；記憶體還很寬裕時調大則會快一些。序列模型每一筆要展開成
                「序列長度 × 特徵數」，同樣的 batch size 會比一般網路吃掉更多記憶體。
              </p>
              <p className="order-hint">
                早停：連續這麼多輪的驗證 loss 沒有創新低就停止訓練，並且還原成
                <b>驗證 loss 最低的那一輪</b>的權重。關掉的話會跑滿設定的輪數，存下來的是最後一輪——
                如果中間就開始過擬合，那組權重會比最好的那組差。
              </p>
              {parsedHiddenSizes.length > 0 && (
                <p className="order-hint network-preview">
                  結構預覽：
                  {isSequence
                    ? `${sequenceLength} 天 × ${features.length} 個特徵 → ${parsedHiddenSizes.join(" → ")} → 取最後一個時間步 → 兩個輸出頭（迴歸 1、分類 1）`
                    : `${features.length} 個特徵 → ${parsedHiddenSizes.join(" → ")} → 兩個輸出頭（迴歸 1、分類 1）`}
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
                      <div className="model-row-actions">
                        {m.status === "completed" && (
                          <span className="cancel-link" onClick={() => handleToggleArchive(m)}>
                            {m.is_archived ? "取消封存" : "封存"}
                          </span>
                        )}
                        {/* 訓練中的不給刪：那筆資料正被背景 process 寫著 */}
                        {m.status !== "training" && (
                          <span className="cancel-link danger-link" onClick={() => handleDelete(m)}>
                            刪除
                          </span>
                        )}
                      </div>
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
