"""雙任務模型訓練：同一組特徵，訓練一個迴歸頭（預測未來 N 天報酬率）跟一個
分類頭（預測是否超過門檻）。

v1 用的是傳統表格式 ML，所以「共用 encoder」在這裡的實際意義是：**兩個模型吃
同一份特徵矩陣、同一組標準化參數**，而不是像神經網路那樣共享權重。樹模型沒有
可以共享的隱藏層，硬要模擬只會把架構弄複雜卻沒有好處。真正的 shared encoder
要等之後改用 GRU/Transformer 才有意義。

評估指標刻意不只看 RMSE/Accuracy：
- 迴歸看 Rank IC（預測值與實際報酬的等級相關），因為選股實際上只在乎「排序對
  不對」，不在乎預測值本身準不準。
- 分類看 AUC 跟 Brier score，後者衡量「機率有沒有校準」——模型說 73% 的那些
  標的，實際上是不是真的有七成達標。
"""

import logging

import numpy as np
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, mean_absolute_error, roc_auc_score

logger = logging.getLogger(__name__)

MODEL_TYPES = ["xgboost", "lightgbm", "random_forest", "logistic_regression", "mlp"]

# 需要 GPU 且有「層」這個概念的模型類型；表單會對這些額外顯示網路結構設定
NEURAL_MODEL_TYPES = ["mlp"]

MODEL_TYPE_LABELS: dict[str, str] = {
    "xgboost": "XGBoost",
    "lightgbm": "LightGBM",
    "random_forest": "Random Forest",
    "logistic_regression": "Logistic / Linear Regression",
    "mlp": "MLP 神經網路（GPU，共享 encoder 雙任務）",
}


def build_models(model_type: str):
    """回傳 (迴歸模型, 分類模型)。四種選項都是成對的，logistic_regression 的
    迴歸對應物是普通線性回歸（邏輯迴歸本身只能做分類）。"""
    if model_type == "xgboost":
        from xgboost import XGBClassifier, XGBRegressor

        common = {"n_estimators": 300, "max_depth": 5, "learning_rate": 0.05, "subsample": 0.8, "n_jobs": 2}
        return XGBRegressor(**common), XGBClassifier(**common, eval_metric="logloss")

    if model_type == "lightgbm":
        from lightgbm import LGBMClassifier, LGBMRegressor

        common = {"n_estimators": 300, "max_depth": 6, "learning_rate": 0.05, "n_jobs": 2, "verbose": -1}
        return LGBMRegressor(**common), LGBMClassifier(**common)

    if model_type == "random_forest":
        common = {"n_estimators": 200, "max_depth": 10, "n_jobs": 2, "random_state": 42}
        return RandomForestRegressor(**common), RandomForestClassifier(**common)

    if model_type == "logistic_regression":
        return LinearRegression(), LogisticRegression(max_iter=1000)

    if model_type in NEURAL_MODEL_TYPES:
        # 神經網路的輸入維度要看特徵數、還要拿驗證集算 loss 曲線，
        # 不是 build 完再 fit 的兩段式流程，所以走 train_dual_task 裡的另一條路
        raise ValueError(f"{model_type} 由 train_dual_task 直接建立，不經過 build_models")

    raise ValueError(f"不支援的模型類型：{model_type}")


def _feature_importance(model, feature_keys: list[str]) -> list[dict]:
    """樹模型用內建的 feature_importances_（一律非負），線性模型用係數本身
    （有正負號，代表影響方向）。取不到就回空陣列，不讓整個訓練因此失敗。"""
    values = None
    if hasattr(model, "feature_importances_"):
        values = np.asarray(model.feature_importances_, dtype=float)
    elif hasattr(model, "coef_"):
        coef = np.asarray(model.coef_, dtype=float)
        values = coef[0] if coef.ndim > 1 else coef

    if values is None or len(values) != len(feature_keys):
        return []
    return [{"feature": key, "importance": float(v)} for key, v in zip(feature_keys, values)]


def _rank_ic(predicted: np.ndarray, actual: np.ndarray) -> float | None:
    """Spearman 等級相關：把兩邊都換成名次再算 Pearson。選股在意的是排序品質，
    所以這個數字比 RMSE 更能反映「照這個模型選股有沒有用」。"""
    if len(predicted) < 3:
        return None
    pred_rank = np.argsort(np.argsort(predicted)).astype(float)
    actual_rank = np.argsort(np.argsort(actual)).astype(float)
    if np.std(pred_rank) < 1e-9 or np.std(actual_rank) < 1e-9:
        return None
    return float(np.corrcoef(pred_rank, actual_rank)[0, 1])


def evaluate(
    regressor,
    classifier,
    x: np.ndarray,
    y_reg: np.ndarray,
    y_clf: np.ndarray,
) -> dict:
    """在給定資料集上評估雙任務表現。單一類別（例如驗證期完全沒有達標樣本）時
    AUC 算不出來，回 None 而不是讓整個訓練炸掉。"""
    pred_reg = regressor.predict(x)
    pred_proba = classifier.predict_proba(x)[:, 1] if hasattr(classifier, "predict_proba") else None
    pred_clf = classifier.predict(x)

    metrics: dict = {
        "sample_count": int(len(y_reg)),
        "mae": float(mean_absolute_error(y_reg, pred_reg)),
        "rmse": float(np.sqrt(np.mean((y_reg - pred_reg) ** 2))),
        "rank_ic": _rank_ic(pred_reg, y_reg),
        "accuracy": float(accuracy_score(y_clf, pred_clf)),
        "positive_rate": float(np.mean(y_clf)),
    }

    r2_denom = float(np.sum((y_reg - np.mean(y_reg)) ** 2))
    metrics["r2"] = float(1 - np.sum((y_reg - pred_reg) ** 2) / r2_denom) if r2_denom > 1e-9 else None

    if pred_proba is not None and len(np.unique(y_clf)) > 1:
        metrics["auc"] = float(roc_auc_score(y_clf, pred_proba))
        metrics["brier_score"] = float(brier_score_loss(y_clf, pred_proba))
        metrics["log_loss"] = float(log_loss(y_clf, pred_proba, labels=[0, 1]))
    else:
        metrics["auc"] = None
        metrics["brier_score"] = None
        metrics["log_loss"] = None

    return metrics


MIN_HEALTHY_TRAIN_SAMPLES = 2000


def build_data_warnings(train_metrics: dict, validation_metrics: dict, test_metrics: dict) -> list[str]:
    """訓練資料本身有問題時，要讓看的人知道「這個模型的數字不能當真」，
    而不是讓他對著一個過擬合的漂亮訓練分數做決策。

    本地歷史是逐檔慢慢回補的，越早的日期有資料的股票越少、近期則幾乎全市場
    都有，所以很容易出現「訓練集比測試集小很多」這種先天畸形的切分。
    """
    warnings: list[str] = []
    train_n = train_metrics["sample_count"]
    test_n = test_metrics["sample_count"]

    if train_n < MIN_HEALTHY_TRAIN_SAMPLES:
        warnings.append(
            f"訓練樣本只有 {train_n} 列，統計上偏少，模型很可能只是背下訓練資料。"
            "建議先把日K回補得更完整，或把訓練區間往前拉長。"
        )
    if test_n > train_n * 2:
        warnings.append(
            f"測試樣本（{test_n} 列）明顯多於訓練樣本（{train_n} 列），"
            "通常代表早期日期的本地日K還沒回補齊，切分出來的訓練集偏薄。"
        )
    if train_metrics.get("auc") and validation_metrics.get("auc"):
        if train_metrics["auc"] - validation_metrics["auc"] > 0.25:
            warnings.append(
                f"訓練 AUC（{train_metrics['auc']:.2f}）遠高於驗證 AUC"
                f"（{validation_metrics['auc']:.2f}），是典型的過擬合徵兆。"
            )
    return warnings


def train_dual_task(
    model_type: str,
    feature_keys: list[str],
    x_train: np.ndarray,
    y_train_reg: np.ndarray,
    y_train_clf: np.ndarray,
    x_validation: np.ndarray,
    y_validation_reg: np.ndarray,
    y_validation_clf: np.ndarray,
    network_config: dict | None = None,
) -> tuple[object, object, dict]:
    """訓練並用驗證集評估。回傳 (迴歸模型, 分類模型, metrics)。

    神經網路類型走另一條路：它是「一個共享 encoder + 兩個輸出頭」的單一模型，
    回傳的兩個物件其實是同一個網路的兩種介面，不是兩個獨立訓練的模型。
    """
    if len(np.unique(y_train_clf)) < 2:
        raise ValueError("訓練集裡沒有任何一筆達到門檻（或全部都達標），請調低/調高報酬率門檻")

    network_info: dict | None = None

    if model_type in NEURAL_MODEL_TYPES:
        from app.services.ml.torch_models import train_torch_dual_task

        config = network_config or {}
        torch_model = train_torch_dual_task(
            x_train,
            y_train_reg,
            y_train_clf,
            x_validation,
            y_validation_reg,
            y_validation_clf,
            hidden_sizes=config.get("hidden_sizes") or [64, 32],
            activation=config.get("activation") or "relu",
            dropout=float(config.get("dropout", 0.2)),
            learning_rate=float(config.get("learning_rate", 0.001)),
            epochs=int(config.get("epochs", 60)),
        )
        regressor = torch_model.as_regressor()
        classifier = torch_model.as_classifier()
        network_info = {
            "layers": torch_model.summary(),
            "total_params": torch_model.total_params(),
            "loss_curve": torch_model.loss_curve,
            "device": torch_model.device_name,
            "epochs": torch_model.epochs_run,
            "hidden_sizes": torch_model.hidden_sizes,
            "activation": torch_model.activation,
            "dropout": torch_model.dropout,
        }
        importance = torch_model.input_weight_importance(feature_keys)
        regression_importance = classification_importance = importance
    else:
        regressor, classifier = build_models(model_type)
        regressor.fit(x_train, y_train_reg)
        classifier.fit(x_train, y_train_clf)
        regression_importance = _feature_importance(regressor, feature_keys)
        classification_importance = _feature_importance(classifier, feature_keys)

    metrics = {
        "train": evaluate(regressor, classifier, x_train, y_train_reg, y_train_clf),
        "validation": evaluate(regressor, classifier, x_validation, y_validation_reg, y_validation_clf),
        "regression_feature_importance": regression_importance,
        "classification_feature_importance": classification_importance,
    }
    if network_info is not None:
        metrics["network"] = network_info
    logger.info(
        "train_dual_task(%s): 訓練 %d 列、驗證 %d 列，驗證 RankIC=%s AUC=%s",
        model_type,
        len(y_train_reg),
        len(y_validation_reg),
        metrics["validation"]["rank_ic"],
        metrics["validation"]["auc"],
    )
    return regressor, classifier, metrics


SCORE_FORMULA_KEY = "zscore_weighted"

# 選股分數的公式與說明放在實作旁邊，改公式時不會忘記同步改說明；
# 前端（admin 表單與公開詳情頁）直接拿這份資料顯示，不各自抄一份。
SCORE_FORMULA_INFO: dict = {
    "key": SCORE_FORMULA_KEY,
    "name": "橫斷面標準化加權",
    "formula": "分數 = w₁ × z(預期報酬) + w₂ × z(達標機率)",
    "definition": "z(x) = ( x − 當日全市場平均 ) ÷ 當日全市場標準差",
    "summary": "把兩個模型輸出各自換算成「相對於當天全市場的位置」，再依權重相加，取分數最高的前 10 名。",
    "reasons": [
        "兩個輸出的單位天差地遠：預期報酬是百分比（可能 -10 到 +10），達標機率是 0 到 1。"
        "不先換算就相乘或相加，等於讓其中一邊主導整個排名。",
        "標準化的基準是「當天的全市場」，比的是這檔股票今天相對於其他股票的位置，"
        "所以大盤整體大漲或大跌的日子不會讓所有股票的分數一起被推高或壓低。",
        "只用到兩個輸出的相對高低，不依賴機率的絕對數值正確——"
        "模型說「85%」時實際未必真有 85%，但「這檔比那檔更看好」通常還是成立的。",
    ],
    "limitation": "標準化是線性轉換，會保留原本的排序。"
    "如果模型在某個信心區間的排序本身就是錯的（例如最有把握的那批反而表現最差），"
    "換這個公式並不會修正它——請搭配下方的機率校準曲線一起看。",
}


def compute_scores(
    predicted_returns: np.ndarray,
    probabilities: np.ndarray,
    score_weights: dict | None,
) -> np.ndarray:
    """把雙任務的兩個輸出合成一個排名分數（橫斷面標準化後加權平均）。

    這是機構多因子模型合成訊號的標準做法。先前也提供過「預期報酬 × 機率」的
    簡單版，但那個寫法會把虛高的機率直接乘進去放大——而機率恰好是這類模型
    最不可靠的部分，所以不再提供。
    """
    weights = score_weights or {}
    w_return = float(weights.get("return", 0.5))
    w_probability = float(weights.get("probability", 0.5))

    def zscore(values: np.ndarray) -> np.ndarray:
        std = float(np.std(values))
        if std < 1e-9:
            return np.zeros_like(values)  # 當天所有股票的預測都一樣，給 0 就好
        return (values - float(np.mean(values))) / std

    return w_return * zscore(predicted_returns) + w_probability * zscore(probabilities)
