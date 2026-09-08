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


def build_network(n_features: int, hidden_sizes: list[int], activation: str, dropout: float):
    return DualTaskMLP(n_features, hidden_sizes, activation, dropout)


def summarize_network(model, n_features: int) -> list[dict]:
    """產生類似 Keras model.summary() 的逐層資訊：每層的輸出形狀與參數量。

    batch 維度寫成 None，跟 Keras 的慣例一致——那一維取決於餵進去多少筆，
    不是網路結構的一部分。
    """
    rows: list[dict] = []
    current = n_features
    counters: dict[str, int] = {}

    def add(module, label_prefix: str, out_features: int):
        kind = type(module).__name__
        counters[kind] = counters.get(kind, 0) + 1
        params = sum(p.numel() for p in module.parameters())
        rows.append(
            {
                "name": f"{label_prefix}{kind.lower()}_{counters[kind]}",
                "type": kind,
                "output_shape": f"(None, {out_features})",
                "params": int(params),
            }
        )

    rows.append({"name": "input", "type": "Input", "output_shape": f"(None, {n_features})", "params": 0})

    for module in model.encoder:
        if isinstance(module, nn.Linear):
            current = module.out_features
        add(module, "", current)

    add(model.regression_head, "head_", model.regression_head.out_features)
    add(model.classification_head, "head_", model.classification_head.out_features)
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

    def __init__(self, network, n_features: int, hidden_sizes: list[int], activation: str, dropout: float):
        self.network = network
        self.n_features = n_features
        self.hidden_sizes = hidden_sizes
        self.activation = activation
        self.dropout = dropout
        self.loss_curve: list[dict] = []
        self.device_name: str = ""
        self.epochs_run: int = 0

    def as_regressor(self):
        return _RegressorView(self)

    def as_classifier(self):
        return _ClassifierView(self)

    def predict_both(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        device = next(self.network.parameters()).device
        self.network.eval()
        with torch.no_grad():
            tensor = torch.as_tensor(np.asarray(x, dtype=np.float32), device=device)
            regression, logits = self.network(tensor)
            probability = torch.sigmoid(logits)
        return regression.cpu().numpy(), probability.cpu().numpy()

    def summary(self) -> list[dict]:
        return summarize_network(self.network, self.n_features)

    def total_params(self) -> int:
        return int(sum(p.numel() for p in self.network.parameters()))

    def input_weight_importance(self, feature_keys: list[str]) -> list[dict]:
        """神經網路沒有樹模型那種內建的特徵重要性。這裡用第一層權重的絕對值
        平均當作粗略指標——只能看出「這個特徵在第一層被用得多重」，跟樹模型的
        分裂貢獻不是同一回事，詳情頁會標註清楚。"""
        first_linear = next((m for m in self.network.encoder if isinstance(m, nn.Linear)), None)
        if first_linear is None:
            return []
        weights = first_linear.weight.detach().abs().mean(dim=0).cpu().numpy()
        if len(weights) != len(feature_keys):
            return []
        return [{"feature": key, "importance": float(w)} for key, w in zip(feature_keys, weights)]

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
) -> TorchDualTaskModel:
    from torch.utils.data import DataLoader, TensorDataset

    device = resolve_device()
    n_features = x_train.shape[1]
    network = build_network(n_features, hidden_sizes, activation, dropout).to(device)

    dataset = TensorDataset(
        torch.as_tensor(x_train, dtype=torch.float32),
        torch.as_tensor(y_train_reg, dtype=torch.float32),
        torch.as_tensor(y_train_clf, dtype=torch.float32),
    )
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    x_val_t = torch.as_tensor(x_validation, dtype=torch.float32, device=device)
    y_val_reg_t = torch.as_tensor(y_validation_reg, dtype=torch.float32, device=device)
    y_val_clf_t = torch.as_tensor(y_validation_clf, dtype=torch.float32, device=device)

    optimizer = torch.optim.Adam(network.parameters(), lr=learning_rate)
    regression_loss = nn.MSELoss()
    classification_loss = nn.BCEWithLogitsLoss()

    model = TorchDualTaskModel(network, n_features, hidden_sizes, activation, dropout)
    model.device_name = describe_device()

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

        network.eval()
        with torch.no_grad():
            val_reg, val_logit = network(x_val_t)
            val_loss = float(
                regression_loss(val_reg, y_val_reg_t).item()
                + classification_loss(val_logit, y_val_clf_t).item()
            )

        model.loss_curve.append(
            {"epoch": epoch, "train_loss": epoch_total / max(batches, 1), "validation_loss": val_loss}
        )

    model.epochs_run = epochs
    logger.info(
        "train_torch_dual_task: %s，%d 層、%d 個參數、%d epochs，最終驗證 loss %.4f",
        model.device_name,
        len(hidden_sizes),
        model.total_params(),
        epochs,
        model.loss_curve[-1]["validation_loss"] if model.loss_curve else float("nan"),
    )
    return model
