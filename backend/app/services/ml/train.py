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

MODEL_TYPES = ["xgboost", "lightgbm", "random_forest", "logistic_regression"]

MODEL_TYPE_LABELS: dict[str, str] = {
    "xgboost": "XGBoost",
    "lightgbm": "LightGBM",
    "random_forest": "Random Forest",
    "logistic_regression": "Logistic / Linear Regression",
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
) -> tuple[object, object, dict]:
    """訓練並用驗證集評估。回傳 (迴歸模型, 分類模型, metrics)。"""
    regressor, classifier = build_models(model_type)

    regressor.fit(x_train, y_train_reg)
    # 分類頭如果訓練集只有單一類別（門檻設太極端），sklearn 會直接拋錯，
    # 這裡先擋下來給看得懂的訊息。
    if len(np.unique(y_train_clf)) < 2:
        raise ValueError("訓練集裡沒有任何一筆達到門檻（或全部都達標），請調低/調高報酬率門檻")
    classifier.fit(x_train, y_train_clf)

    metrics = {
        "train": evaluate(regressor, classifier, x_train, y_train_reg, y_train_clf),
        "validation": evaluate(regressor, classifier, x_validation, y_validation_reg, y_validation_clf),
        "regression_feature_importance": _feature_importance(regressor, feature_keys),
        "classification_feature_importance": _feature_importance(classifier, feature_keys),
    }
    logger.info(
        "train_dual_task(%s): 訓練 %d 列、驗證 %d 列，驗證 RankIC=%s AUC=%s",
        model_type,
        len(y_train_reg),
        len(y_validation_reg),
        metrics["validation"]["rank_ic"],
        metrics["validation"]["auc"],
    )
    return regressor, classifier, metrics


def compute_scores(
    predicted_returns: np.ndarray,
    probabilities: np.ndarray,
    score_formula: str,
    score_weights: dict | None,
) -> np.ndarray:
    """把雙任務的兩個輸出合成一個排名分數。

    - multiply：預期報酬 × 機率，直覺、接近期望值，但沒有校正兩者的尺度。
    - zscore_weighted：兩邊各自做橫斷面標準化（同一天全市場一起比）再加權平均，
      這是機構多因子模型合成訊號的標準做法，比較不受單邊尺度失真影響。
    """
    if score_formula == "zscore_weighted":
        weights = score_weights or {}
        w_return = float(weights.get("return", 0.5))
        w_probability = float(weights.get("probability", 0.5))

        def zscore(values: np.ndarray) -> np.ndarray:
            std = float(np.std(values))
            if std < 1e-9:
                return np.zeros_like(values)
            return (values - float(np.mean(values))) / std

        return w_return * zscore(predicted_returns) + w_probability * zscore(probabilities)

    return predicted_returns * probabilities
