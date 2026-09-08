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


def _move_to_cpu_for_save(obj) -> None:
    """PyTorch 的 tensor 直接 pickle 會把 device id 一起記住，換一台機器或多卡
    環境載入就會出事。存檔前一律搬回 CPU。"""
    owner = getattr(obj, "_owner", None)
    if owner is not None and hasattr(owner, "to_cpu"):
        owner.to_cpu()


def _move_to_gpu_if_available(obj) -> None:
    """推論時有 GPU 就用，沒有就留在 CPU 照樣能跑。

    這跟訓練的規則刻意不同：訓練沒 GPU 會直接失敗（不然使用者以為在用 GPU、
    實際上慢很多卻沒察覺），但推論只是每天跑一次的前向傳播，CPU 也很快，
    沒必要為此讓整個排程掛掉。"""
    owner = getattr(obj, "_owner", None)
    if owner is None or not hasattr(owner, "network"):
        return
    try:
        import torch

        if torch.cuda.is_available():
            owner.network.to("cuda")
    except Exception:
        logger.warning("載入模型後無法搬到 GPU，改用 CPU 推論", exc_info=True)


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
    _move_to_cpu_for_save(regressor)
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
    _move_to_gpu_if_available(payload["regressor"])
    return ModelBundle(
        regressor=payload["regressor"],
        classifier=payload["classifier"],
        feature_keys=payload["feature_keys"],
        scaler_mean=payload["scaler_mean"],
        scaler_std=payload["scaler_std"],
    )
