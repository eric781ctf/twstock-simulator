"""PyTorch 雙任務神經網路（MLP），在 GPU 上訓練。

這是第一個做到「真正共享 encoder」的模型類型：樹模型沒有可以共享的隱藏層，
所以 XGBoost/LightGBM 那條路其實是各自訓練兩個獨立模型、只是吃同一份特徵；
這裡則是同一組隱藏層同時餵給迴歸頭與分類頭，兩個任務的梯度會一起更新
共享層，也就是原始規劃圖裡的那個架構。

    特徵 ─→ 共享隱藏層(可設幾層、每層幾個神經元) ─┬─→ 迴歸頭 → 未來 N 日報酬率
                                                  └─→ 分類頭 → 達標機率

GPU 是必要條件而不是加分項：設定要用 GPU 卻沒有 GPU 時直接讓訓練失敗，
不靜默退回 CPU——不然使用者會以為跑的是 GPU，實際上慢很多卻毫無察覺。
"""

import logging

import numpy as np
import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

DEFAULT_HIDDEN_SIZES = [64, 32]
DEFAULT_EPOCHS = 60
DEFAULT_LEARNING_RATE = 0.001
DEFAULT_DROPOUT = 0.2
DEFAULT_BATCH_SIZE = 512
# 推論時一次送進顯示卡幾筆。比訓練的 batch 大是因為推論不用存反向傳播要用的
# 中間結果，但仍然要有上限——評估時整個訓練集會一次傳進來。
PREDICT_BATCH = 4096

# 早停：連續這麼多個 epoch 驗證 loss 沒創新低就停。預設開著——實測 GRU 的驗證
# loss 在第 2 個 epoch 就觸底，後面 28 輪都在過擬合，不停的話存下來的是那 28 輪
# 之後的權重。設 0 可以關閉。
DEFAULT_PATIENCE = 10
# 小於這個幅度的下降不算「創新低」，避免在雜訊上一直重置耐心值
MIN_IMPROVEMENT = 1e-4

ACTIVATIONS = ["relu", "tanh", "gelu"]


class GpuUnavailableError(RuntimeError):
    pass


def resolve_device():
    """一律要求 GPU。找不到就直接報錯，讓訓練標成 failed 並寫清楚原因。"""
    if not torch.cuda.is_available():
        raise GpuUnavailableError(
            "找不到可用的 GPU（torch.cuda.is_available() 為 False）。"
            "深度學習模型設定為必須使用 GPU 訓練，請確認容器有掛到顯示卡"
            "（docker-compose 的 deploy.resources.devices）與 NVIDIA driver 正常。"
        )
    return torch.device("cuda")


def describe_device() -> str:
    if not torch.cuda.is_available():
        return "無可用 GPU"
    return f"{torch.cuda.get_device_name(0)}（CUDA {torch.version.cuda}）"


def _activation_module(name: str):
    return {"relu": nn.ReLU, "tanh": nn.Tanh, "gelu": nn.GELU}.get(name, nn.ReLU)()


class DualTaskMLP(nn.Module):
    """共享 encoder + 兩個輸出頭。

    必須定義在模組層級：模型要用 pickle 存檔，而 pickle 記的是「模組路徑 +
    類別名稱」，定義在函式裡的區域類別找不到路徑，存檔時會直接失敗。
    """

    def __init__(self, n_features: int, hidden_sizes: list[int], activation: str, dropout: float):
        super().__init__()
        layers = []
        prev = n_features
        for size in hidden_sizes:
            layers.append(nn.Linear(prev, size))
            layers.append(_activation_module(activation))
            if dropout > 0:
                layers.append(nn.Dropout(dropout))
            prev = size
        self.encoder = nn.Sequential(*layers)
        self.regression_head = nn.Linear(prev, 1)
        self.classification_head = nn.Linear(prev, 1)

    def forward(self, x):
        shared = self.encoder(x)
        # 分類頭輸出 logit，損失用 BCEWithLogits（數值上比先 sigmoid 再取 log 穩定）
        return self.regression_head(shared).squeeze(-1), self.classification_head(shared).squeeze(-1)


class DualTaskRNN(nn.Module):
    """GRU / LSTM 版本的雙任務網路。

    跟 MLP 的差別只在 encoder：MLP 吃「某一天的特徵」，這裡吃「這一天之前連續
    T 天的特徵」，讓網路自己去抓時間上的變化，而不是靠我們手動算好的
    5日/20日乖離率之類的彙總特徵。

        (batch, T, 特徵數) ─→ RNN 層 ─→ 取最後一個時間步 ─┬─→ 迴歸頭
                                                          └─→ 分類頭

    PyTorch 的 nn.GRU/nn.LSTM 用 num_layers 疊多層時，每層的 hidden size 必須
    一樣。這裡改成自己疊一串各自獨立的單層 RNN，admin 才能像設定 MLP 那樣
    指定「64 → 32」這種逐層縮小的結構，結構表上也才看得到每層真正的 shape。
    """

    def __init__(self, n_features: int, hidden_sizes: list[int], cell: str, dropout: float):
        super().__init__()
        self.cell = cell
        rnn_cls = nn.LSTM if cell == "lstm" else nn.GRU
        self.rnn_layers = nn.ModuleList()
        self.dropouts = nn.ModuleList()
        prev = n_features
        for size in hidden_sizes:
            self.rnn_layers.append(rnn_cls(prev, size, batch_first=True))
            # dropout=0 時放 Identity，層數才會跟 dropouts 對齊，forward 不用分支
            self.dropouts.append(nn.Dropout(dropout) if dropout > 0 else nn.Identity())
            prev = size
        self.regression_head = nn.Linear(prev, 1)
        self.classification_head = nn.Linear(prev, 1)

    def forward(self, x):
        out = x
        for rnn, drop in zip(self.rnn_layers, self.dropouts):
            out, _ = rnn(out)
            out = drop(out)
        # 只取最後一個時間步：那是「看完整段歷史之後」的狀態，也是要拿來預測的那一天
        shared = out[:, -1, :]
        return self.regression_head(shared).squeeze(-1), self.classification_head(shared).squeeze(-1)


def build_network(
    n_features: int,
    hidden_sizes: list[int],
    activation: str,
    dropout: float,
    model_kind: str = "mlp",
):
    if model_kind in ("gru", "lstm"):
        return DualTaskRNN(n_features, hidden_sizes, model_kind, dropout)
    return DualTaskMLP(n_features, hidden_sizes, activation, dropout)


def _layer_row(module, name: str, output_shape: str) -> dict:
    return {
        "name": name,
        "type": type(module).__name__,
        "output_shape": output_shape,
        "params": int(sum(p.numel() for p in module.parameters())),
    }


def summarize_network(model, n_features: int, sequence_length: int | None = None) -> list[dict]:
    """產生類似 Keras model.summary() 的逐層資訊：每層的輸出形狀與參數量。

    batch 維度寫成 None，跟 Keras 的慣例一致——那一維取決於餵進去多少筆，
    不是網路結構的一部分。序列模型的輸入多一個時間維度，寫成 (None, T, 特徵數)。
    """
    if isinstance(model, DualTaskRNN):
        return _summarize_rnn(model, n_features, sequence_length or 0)
    return _summarize_mlp(model, n_features)


def _summarize_mlp(model, n_features: int) -> list[dict]:
    rows: list[dict] = [{"name": "input", "type": "Input", "output_shape": f"(None, {n_features})", "params": 0}]
    current = n_features
    counters: dict[str, int] = {}

    for module in model.encoder:
        kind = type(module).__name__
        if isinstance(module, nn.Linear):
            current = module.out_features
        counters[kind] = counters.get(kind, 0) + 1
        rows.append(_layer_row(module, f"{kind.lower()}_{counters[kind]}", f"(None, {current})"))

    rows.append(_layer_row(model.regression_head, "head_linear_1", "(None, 1)"))
    rows.append(_layer_row(model.classification_head, "head_linear_2", "(None, 1)"))
    return rows


def _summarize_rnn(model, n_features: int, sequence_length: int) -> list[dict]:
    rows: list[dict] = [
        {"name": "input", "type": "Input", "output_shape": f"(None, {sequence_length}, {n_features})", "params": 0}
    ]
    current = n_features
    for i, (rnn, drop) in enumerate(zip(model.rnn_layers, model.dropouts), start=1):
        current = rnn.hidden_size
        kind = type(rnn).__name__.lower()
        rows.append(_layer_row(rnn, f"{kind}_{i}", f"(None, {sequence_length}, {current})"))
        if not isinstance(drop, nn.Identity):
            rows.append(_layer_row(drop, f"dropout_{i}", f"(None, {sequence_length}, {current})"))

    # 這一步沒有參數，但少了它讀的人會看不懂 shape 為什麼突然掉一個維度
    rows.append({"name": "last_timestep", "type": "Slice", "output_shape": f"(None, {current})", "params": 0})
    rows.append(_layer_row(model.regression_head, "head_linear_1", "(None, 1)"))
    rows.append(_layer_row(model.classification_head, "head_linear_2", "(None, 1)"))
    return rows


class _RegressorView:
    """讓 PyTorch 模型長得像 sklearn 的 regressor，既有的評估/推論程式碼就不用改。"""

    def __init__(self, owner: "TorchDualTaskModel"):
        self._owner = owner

    def predict(self, x: np.ndarray) -> np.ndarray:
        return self._owner.predict_both(x)[0]


class _ClassifierView:
    def __init__(self, owner: "TorchDualTaskModel"):
        self._owner = owner

    def predict(self, x: np.ndarray) -> np.ndarray:
        return (self._owner.predict_both(x)[1] >= 0.5).astype(int)

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        probability = self._owner.predict_both(x)[1]
        return np.column_stack([1 - probability, probability])


class TorchDualTaskModel:
    """訓練好的雙任務網路，加上推論時要用的東西。

    存檔時一律把權重搬回 CPU：GPU 上的 tensor 直接 pickle 會綁死在當初那張卡的
    device id，換一台機器或多卡環境載入就會出事。
    """

    def __init__(
        self,
        network,
        n_features: int,
        hidden_sizes: list[int],
        activation: str,
        dropout: float,
        model_kind: str = "mlp",
        sequence_length: int | None = None,
    ):
        self.network = network
        self.n_features = n_features
        self.hidden_sizes = hidden_sizes
        self.activation = activation
        self.dropout = dropout
        self.model_kind = model_kind
        self.sequence_length = sequence_length
        self.loss_curve: list[dict] = []
        self.device_name: str = ""
        self.epochs_run: int = 0
        self.configured_epochs: int = 0
        self.best_epoch: int = 0
        self.early_stopped: bool = False
        self.patience: int = 0

    def as_regressor(self):
        return _RegressorView(self)

    def as_classifier(self):
        return _ClassifierView(self)

    def predict_both(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """分批做前向傳播，回傳 (預測報酬率, 達標機率)。

        一定要分批：評估時會一口氣傳進整個訓練集（三十幾萬筆），而 RNN 每一筆
        還要展開成 T 個時間步、每步都留著中間狀態，整批直接進顯示卡會要到
        幾十 GB。分批不影響結果，只影響一次佔用多少顯示記憶體。
        """
        device = next(self.network.parameters()).device
        self.network.eval()
        x = np.asarray(x, dtype=np.float32)

        regressions: list[np.ndarray] = []
        probabilities: list[np.ndarray] = []
        with torch.no_grad():
            for start in range(0, len(x), PREDICT_BATCH):
                tensor = torch.as_tensor(x[start : start + PREDICT_BATCH], device=device)
                regression, logits = self.network(tensor)
                regressions.append(regression.cpu().numpy())
                probabilities.append(torch.sigmoid(logits).cpu().numpy())

        if not regressions:
            return np.array([]), np.array([])
        return np.concatenate(regressions), np.concatenate(probabilities)

    def summary(self) -> list[dict]:
        return summarize_network(self.network, self.n_features, self.sequence_length)

    def total_params(self) -> int:
        return int(sum(p.numel() for p in self.network.parameters()))

    def input_weight_importance(self, feature_keys: list[str]) -> list[dict]:
        """神經網路沒有樹模型那種內建的特徵重要性。這裡用第一層權重的絕對值
        平均當作粗略指標——只能看出「這個特徵在第一層被用得多重」，跟樹模型的
        分裂貢獻不是同一回事，詳情頁會標註清楚。"""
        weights = self._first_layer_input_weights()
        if weights is None or len(weights) != len(feature_keys):
            return []
        return [{"feature": key, "importance": float(w)} for key, w in zip(feature_keys, weights)]

    def _first_layer_input_weights(self) -> np.ndarray | None:
        """取第一層「吃輸入特徵」的那組權重，對輸出維度取絕對值平均。

        RNN 的 weight_ih_l0 把 3 個閘（LSTM 是 4 個）的權重直接疊在同一個矩陣的
        列方向，形狀是 (閘數 × hidden, 特徵數)。我們只在乎「每個輸入特徵被用得
        多重」，所以直接對整個列方向取平均就好，不用先拆開閘。
        """
        if isinstance(self.network, DualTaskRNN):
            if not self.network.rnn_layers:
                return None
            return self.network.rnn_layers[0].weight_ih_l0.detach().abs().mean(dim=0).cpu().numpy()

        first_linear = next((m for m in self.network.encoder if isinstance(m, nn.Linear)), None)
        if first_linear is None:
            return None
        return first_linear.weight.detach().abs().mean(dim=0).cpu().numpy()

    def to_cpu(self) -> None:
        self.network.to("cpu")


def train_torch_dual_task(
    x_train: np.ndarray,
    y_train_reg: np.ndarray,
    y_train_clf: np.ndarray,
    x_validation: np.ndarray,
    y_validation_reg: np.ndarray,
    y_validation_clf: np.ndarray,
    hidden_sizes: list[int],
    activation: str,
    dropout: float,
    learning_rate: float,
    epochs: int,
    batch_size: int = DEFAULT_BATCH_SIZE,
    model_kind: str = "mlp",
    patience: int = DEFAULT_PATIENCE,
) -> TorchDualTaskModel:
    """x_train 是 (N, 特徵數)（MLP）或 (N, T, 特徵數)（GRU/LSTM）。

    patience 是早停的耐心值：連續這麼多個 epoch 的驗證 loss 沒有創新低就停止，
    並且**還原到驗證 loss 最低的那一輪的權重**。設 0 關閉，跑滿所有 epoch 並
    採用最後一輪的權重。
    """
    from torch.utils.data import DataLoader, TensorDataset

    device = resolve_device()
    n_features = x_train.shape[-1]
    sequence_length = int(x_train.shape[1]) if x_train.ndim == 3 else None
    network = build_network(n_features, hidden_sizes, activation, dropout, model_kind).to(device)

    dataset = TensorDataset(
        torch.as_tensor(x_train, dtype=torch.float32),
        torch.as_tensor(y_train_reg, dtype=torch.float32),
        torch.as_tensor(y_train_clf, dtype=torch.float32),
    )
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    # 驗證集留在 CPU、分批送上去算。序列資料每筆多了一個時間維度，整批直接塞
    # 進顯示卡在 T 拉長時會爆掉，而這裡只是算 loss，分批完全不影響結果。
    x_val_t = torch.as_tensor(x_validation, dtype=torch.float32)
    y_val_reg_t = torch.as_tensor(y_validation_reg, dtype=torch.float32)
    y_val_clf_t = torch.as_tensor(y_validation_clf, dtype=torch.float32)

    optimizer = torch.optim.Adam(network.parameters(), lr=learning_rate)
    regression_loss = nn.MSELoss()
    classification_loss = nn.BCEWithLogitsLoss()

    model = TorchDualTaskModel(
        network, n_features, hidden_sizes, activation, dropout, model_kind, sequence_length
    )
    model.device_name = describe_device()

    best_loss = float("inf")
    best_state: dict | None = None
    epochs_since_best = 0

    def validation_loss() -> float:
        """整個驗證集的平均 loss，用樣本數加權（最後一批通常比較小）。"""
        network.eval()
        total = 0.0
        seen = 0
        with torch.no_grad():
            for start in range(0, len(x_val_t), batch_size):
                xb = x_val_t[start : start + batch_size].to(device)
                yb_reg = y_val_reg_t[start : start + batch_size].to(device)
                yb_clf = y_val_clf_t[start : start + batch_size].to(device)
                pred_reg, pred_logit = network(xb)
                batch_loss = (
                    regression_loss(pred_reg, yb_reg).item()
                    + classification_loss(pred_logit, yb_clf).item()
                )
                total += batch_loss * len(xb)
                seen += len(xb)
        return total / max(seen, 1)

    for epoch in range(1, epochs + 1):
        network.train()
        epoch_total = 0.0
        batches = 0
        for xb, yb_reg, yb_clf in loader:
            xb = xb.to(device, non_blocking=True)
            yb_reg = yb_reg.to(device, non_blocking=True)
            yb_clf = yb_clf.to(device, non_blocking=True)

            optimizer.zero_grad()
            pred_reg, pred_logit = network(xb)
            # 兩個任務的損失直接相加，共享層會同時收到兩邊的梯度——
            # 這就是「多任務」相對於「訓練兩個獨立模型」的差別所在
            loss = regression_loss(pred_reg, yb_reg) + classification_loss(pred_logit, yb_clf)
            loss.backward()
            optimizer.step()
            epoch_total += float(loss.item())
            batches += 1

        current_validation = validation_loss()
        model.loss_curve.append(
            {
                "epoch": epoch,
                "train_loss": epoch_total / max(batches, 1),
                "validation_loss": current_validation,
            }
        )

        if current_validation < best_loss - MIN_IMPROVEMENT:
            best_loss = current_validation
            model.best_epoch = epoch
            # 存到 CPU 並複製一份：state_dict 給的是還在 GPU 上、之後會被就地
            # 更新的同一批 tensor，不複製的話「最佳權重」會跟著後面的訓練變動
            best_state = {k: v.detach().cpu().clone() for k, v in network.state_dict().items()}
            epochs_since_best = 0
        else:
            epochs_since_best += 1
            if patience > 0 and epochs_since_best >= patience:
                model.early_stopped = True
                break

    model.epochs_run = len(model.loss_curve)
    model.configured_epochs = epochs
    model.patience = patience

    # 早停開著時一律還原最佳權重。不還原的話，即使提早停了，帶走的仍然是
    # 「已經開始變差的那幾輪」的權重——那正是早停要避免的事。
    if patience > 0 and best_state is not None:
        network.load_state_dict(best_state)
        network.to(device)

    logger.info(
        "train_torch_dual_task(%s): %s，%d 層、%d 個參數，跑了 %d/%d epochs"
        "（最佳第 %d 輪，驗證 loss %.4f%s）",
        model_kind,
        model.device_name,
        len(hidden_sizes),
        model.total_params(),
        model.epochs_run,
        epochs,
        model.best_epoch,
        best_loss,
        "，已還原該輪權重" if patience > 0 and best_state is not None else "，未啟用早停",
    )
    return model
