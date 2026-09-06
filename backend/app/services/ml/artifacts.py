"""模型檔案的存取。存在 backend/model_artifacts/{model_id}/ 底下（已在
.gitignore），因為 backend 整個資料夾本來就掛成 volume，容器重建也不會遺失。

一併存下訓練集算出來的標準化參數與特徵順序——推論時一定要用「訓練當下」的
同一組數字跟同樣的欄位順序，不然分布跟欄位都會對錯。
"""

import logging
from pathlib import Path

import joblib
import numpy as np

from app.services.ml.selection import ModelBundle

logger = logging.getLogger(__name__)

ARTIFACT_ROOT = Path(__file__).resolve().parents[3] / "model_artifacts"


def artifact_dir(model_id: int) -> Path:
    return ARTIFACT_ROOT / str(model_id)


def save_bundle(
    model_id: int,
    regressor,
    classifier,
    feature_keys: list[str],
    scaler_mean: np.ndarray,
    scaler_std: np.ndarray,
) -> str:
    target = artifact_dir(model_id)
    target.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "regressor": regressor,
            "classifier": classifier,
            "feature_keys": feature_keys,
            "scaler_mean": scaler_mean,
            "scaler_std": scaler_std,
        },
        target / "bundle.joblib",
    )
    logger.info("save_bundle: 模型 %d 已存到 %s", model_id, target)
    return str(target)


def load_bundle(model_artifact_path: str) -> ModelBundle:
    payload = joblib.load(Path(model_artifact_path) / "bundle.joblib")
    return ModelBundle(
        regressor=payload["regressor"],
        classifier=payload["classifier"],
        feature_keys=payload["feature_keys"],
        scaler_mean=payload["scaler_mean"],
        scaler_std=payload["scaler_std"],
    )
