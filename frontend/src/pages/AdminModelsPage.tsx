import { useCallback, useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { api } from "../api";
import { ConditionEditor } from "../components/ConditionEditor";
import { useAuth } from "../auth/AuthContext";
import type {
  Activation,
  FeatureScaling,
  LabelMode,
  ValidationMode,
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

// 沒有東西在跑的時候，五分鐘看一次就夠。但只要有模型在訓練，就改成十秒——
// 進度是逐個 epoch 更新的，五分鐘才刷一次等於看不到它在動。
const POLL_INTERVAL_MS = 5 * 60 * 1000;
const ACTIVE_POLL_INTERVAL_MS = 10 * 1000;

const PHASE_LABEL: Record<string, string> = {
  preparing: "準備資料",
  training: "訓練中",
  backtesting: "回測中",
};

/** 把訓練進度整理成一行字。沒有進度資料就回 null，由呼叫端決定顯示什麼。 */
function progressText(model: ModelSummary): string | null {
  const p = model.training_progress;
  if (!p) return null;
  const phase = PHASE_LABEL[p.phase] ?? p.phase;
  if (p.phase !== "training" || !p.epoch) return phase;

  const total = p.total_epochs ? ` / ${p.total_epochs}` : "";
  const loss = p.validation_loss != null ? `　驗證 loss ${p.validation_loss.toFixed(3)}` : "";
  const best = p.best_epoch ? `　最佳第 ${p.best_epoch} 輪` : "";
  return `${phase}　epoch ${p.epoch}${total}${loss}${best}`;
}

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
  const [presetKey, setPresetKey] = useState("curated");
  const [nDays, setNDays] = useState("5");
  const [threshold, setThreshold] = useState("3");
  const [labelMode, setLabelMode] = useState<LabelMode>("excess");
  const [validationMode, setValidationMode] = useState<ValidationMode>("walk_forward");
  const [featureScaling, setFeatureScaling] = useState<FeatureScaling>("cross_sectional_rank");
  const [industryNeutral, setIndustryNeutral] = useState(false);
  const [wfTrain, setWfTrain] = useState("6");
  const [wfValidation, setWfValidation] = useState("2");
  const [wfTest, setWfTest] = useState("2");
  const [wfStep, setWfStep] = useState("2");
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
  const [nEstimators, setNEstimators] = useState("300");
  const [treeDepth, setTreeDepth] = useState("6");
  const [treeLearningRate, setTreeLearningRate] = useState("0.05");
  const [subsample, setSubsample] = useState("0.8");
  const [colsample, setColsample] = useState("0.8");
  const [minChildSamples, setMinChildSamples] = useState("20");
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

  const hasRunning = models.some((m) => m.status === "queued" || m.status === "training");

  useEffect(() => {
    if (!isAdmin) return;
    const timer = setInterval(refreshModels, hasRunning ? ACTIVE_POLL_INTERVAL_MS : POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [isAdmin, refreshModels, hasRunning]);

  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }

  function toggleFeature(key: string) {
    setFeatures((prev) => (prev.includes(key) ? prev.filter((f) => f !== key) : [...prev, key]));
    // 手動動過就不再是任何一個預設集了。不改成「自訂」的話，畫面會宣稱還在
    // 「精選」但送出的清單其實已經不一樣
    setPresetKey("custom");
  }

  function applyPreset(key: string) {
    setPresetKey(key);
    const preset = defaults?.feature_presets.find((p) => p.key === key);
    if (preset) setFeatures(preset.features);
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
      label_mode: labelMode,
      validation_mode: validationMode,
      feature_scaling: featureScaling,
      industry_neutral: industryNeutral,
      walk_forward_config:
        validationMode === "walk_forward"
          ? {
              train_months: Number(wfTrain),
              validation_months: Number(wfValidation),
              test_months: Number(wfTest),
              step_months: Number(wfStep),
            }
          : null,
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
      tree_config: isTree
        ? {
            n_estimators: Number(nEstimators),
            max_depth: Number(treeDepth),
            learning_rate: Number(treeLearningRate),
            subsample: Number(subsample),
            colsample: Number(colsample),
            min_child_samples: Number(minChildSamples),
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
  const isTree = selectedType?.is_tree ?? false;
  const hasLearningRate = selectedType?.has_learning_rate ?? true;
  const parsedHiddenSizes = hiddenSizes
    .split(/[,\s]+/)
    .map((v) => Number(v.trim()))
    .filter((v) => Number.isFinite(v) && v > 0);

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
              特徵標準化
              <select
                value={featureScaling}
                onChange={(e) => setFeatureScaling(e.target.value as FeatureScaling)}
              >
                <option value="cross_sectional_rank">橫斷面排名</option>
                <option value="zscore">z-score</option>
              </select>
            </label>
            <label>
              產業中性化
              <select
                value={industryNeutral ? "on" : "off"}
                onChange={(e) => setIndustryNeutral(e.target.value === "on")}
              >
                <option value="off">關閉</option>
                <option value="on">開啟（減掉同業中位數）</option>
              </select>
            </label>
            <label>
              預測目標
              <select value={labelMode} onChange={(e) => setLabelMode(e.target.value as LabelMode)}>
                <option value="excess">超額報酬（減掉大盤）</option>
                <option value="absolute">絕對報酬</option>
              </select>
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

          {isTree && (
            <>
              <h3 className="tutorial-heading">樹模型參數</h3>
              <p className="order-hint">
                這幾個名稱是通用的，後端會翻譯成各套件自己的參數名（例如「葉節點最少樣本數」在
                XGBoost 是 min_child_weight、在 LightGBM 是 min_child_samples、在 Random Forest 是
                min_samples_leaf）。
              </p>
              <div className="strategy-form-grid">
                <label>
                  n_estimators
                  <input
                    type="number"
                    min={10}
                    max={5000}
                    value={nEstimators}
                    onChange={(e) => setNEstimators(e.target.value)}
                  />
                </label>
                <label>
                  max_depth
                  <input type="number" min={1} max={32} value={treeDepth} onChange={(e) => setTreeDepth(e.target.value)} />
                </label>
                <label>
                  learning_rate
                  <input
                    type="number"
                    step="0.01"
                    min={0.001}
                    max={1}
                    value={hasLearningRate ? treeLearningRate : ""}
                    disabled={!hasLearningRate}
                    placeholder={hasLearningRate ? "" : "此模型沒有學習率"}
                    onChange={(e) => setTreeLearningRate(e.target.value)}
                  />
                </label>
                <label>
                  subsample
                  <input
                    type="number"
                    step="0.05"
                    min={0.1}
                    max={1}
                    value={subsample}
                    onChange={(e) => setSubsample(e.target.value)}
                  />
                </label>
                <label>
                  colsample
                  <input
                    type="number"
                    step="0.05"
                    min={0.1}
                    max={1}
                    value={colsample}
                    onChange={(e) => setColsample(e.target.value)}
                  />
                </label>
                <label>
                  min_child_samples
                  <input
                    type="number"
                    min={1}
                    max={10000}
                    value={minChildSamples}
                    onChange={(e) => setMinChildSamples(e.target.value)}
                  />
                </label>
              </div>
              <p className="order-hint">
                <b>train 分數遠高於 test 時，這裡是第一個該動的地方。</b>
                減少 n_estimators、降低 max_depth、調高 min_child_samples、把 subsample / colsample
                調小，都是讓模型「別把訓練資料背起來」的手段。
                {!hasLearningRate && "　Random Forest 的樹是各自獨立長的，不是一棵補一棵，所以沒有學習率這個概念。"}
              </p>
            </>
          )}

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

          <p className="order-hint">
            <b>特徵標準化</b>決定模型看到的數字以什麼為基準。z-score 用<b>整個訓練期</b>的平均與標準差，
            等於拿去年的數值直接跟今年比；橫斷面排名只用<b>當天</b>的全市場，比的是「這檔今天排第幾」——
            而那正是選股要的，極端值也自動被壓進 0~1，不用另外處理。
          </p>
          <p className="order-hint">
            <b>預測目標</b>決定模型要學什麼。「超額報酬」是個股報酬減掉同一段期間的大盤報酬——
            大盤漲 3% 的日子幾乎每檔都達標、跌 3% 的日子幾乎每檔都不達標，用絕對報酬的話模型有
            相當一部分容量會耗在猜大盤上。這個系統實際做的是「每天挑相對最強的前 10 名」，
            超額報酬才對得上這件事。
            　注意換成超額報酬之後，同樣的門檻代表的意思不一樣了（達標率會明顯下降），
            兩種模式的數字不能直接互相比較。
          </p>

          <h3 className="tutorial-heading">選股分數怎麼算</h3>
          {/* 權重就是上面那兩個欄位，這裡不重複整套公式說明，連到模型教學即可 */}
          <p className="order-hint">
            分數 = {defaults.score_formula.formula.replace("分數 = ", "")}
            ，兩個權重就是上面的 w₁ / w₂。完整說明見{" "}
            <Link to="/model-tutorial#score-formula">模型教學</Link>。
          </p>

          <h3 className="tutorial-heading">訓練特徵（已勾選 {features.length} / {defaults.features.length} 項）</h3>
          <div className="strategy-form-grid">
            <label>
              特徵集
              <select value={presetKey} onChange={(e) => applyPreset(e.target.value)}>
                {defaults.feature_presets.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.label}（{p.features.length} 項）
                  </option>
                ))}
                <option value="custom">自訂</option>
              </select>
            </label>
          </div>
          <p className="order-hint">
            {defaults.feature_presets.find((p) => p.key === presetKey)?.description ??
              "自己勾選要用哪些特徵。動過任何一個勾選就會切換到這個模式。"}
          </p>
          <div className="feature-checkbox-grid">
            {defaults.features.map((f) => (
              <label key={f.key} className={features.includes(f.key) ? "feature-checkbox active" : "feature-checkbox"}>
                <input type="checkbox" checked={features.includes(f.key)} onChange={() => toggleFeature(f.key)} />
                {f.label}
              </label>
            ))}
          </div>

          <h3 className="tutorial-heading">驗證方式</h3>
          <div className="strategy-form-grid">
            <label>
              模式
              <select
                value={validationMode}
                onChange={(e) => setValidationMode(e.target.value as ValidationMode)}
              >
                <option value="walk_forward">滾動視窗（多折）</option>
                <option value="single">單次切分</option>
              </select>
            </label>
            {validationMode === "walk_forward" && (
              <>
                <label>
                  訓練月數
                  <input type="number" min={1} max={60} value={wfTrain} onChange={(e) => setWfTrain(e.target.value)} />
                </label>
                <label>
                  驗證月數
                  <input
                    type="number"
                    min={1}
                    max={24}
                    value={wfValidation}
                    onChange={(e) => setWfValidation(e.target.value)}
                  />
                </label>
                <label>
                  測試月數
                  <input type="number" min={1} max={24} value={wfTest} onChange={(e) => setWfTest(e.target.value)} />
                </label>
                <label>
                  每次滾動月數
                  <input type="number" min={1} max={24} value={wfStep} onChange={(e) => setWfStep(e.target.value)} />
                </label>
              </>
            )}
          </div>
          <p className="order-hint">
            {validationMode === "walk_forward" ? (
              <>
                同一組設定在多段不同時期各測一次，回報平均與<b>標準差</b>。
                標準差才是重點——平均 Rank IC +0.02 但標準差 0.06 的訊號站不住腳，
                換一段測試期就可能翻正負號。下方六個日期此時只用來界定<b>整段範圍</b>
                （第一折從「訓練起」開始，一路滾到「測試迄」為止），每一折的實際切分由上面的月數決定。
              </>
            ) : (
              <>
                只切一次，用下方六個日期。測試期只有一段市況，
                得到的分數很可能只是「那段期間剛好」——實測同一個架構跑兩次就能讓測試 Rank IC 翻正負號。
                除非你要重現某個特定切分，否則建議用滾動視窗。
              </>
            )}
          </p>

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
          {hasRunning
            ? "有模型正在訓練中，進度每 10 秒自動更新一次"
            : "每次訓練都是新版本，封存後不再參與每日選股，歷史績效仍可查看"}
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
                    <td className={`model-status-${m.status}`}>
                      {STATUS_LABEL[m.status]}
                      {progressText(m) && <div className="model-progress">{progressText(m)}</div>}
                    </td>
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
