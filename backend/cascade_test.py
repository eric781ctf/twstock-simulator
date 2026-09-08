from datetime import date
from app.database import SessionLocal
from app.models import PredictionModel, ModelPrediction, ModelHolding, ModelScoringRun
from app.services.ml import artifacts

db = SessionLocal()
m = PredictionModel(
    model_family="__cascade_test__", version=1, model_type="lightgbm",
    feature_config=["change_percent"], n_days=5, threshold_percent=2.0,
    score_formula="zscore_weighted", sell_conditions=[],
    train_start=date(2025,1,1), train_end=date(2025,2,1),
    validation_start=date(2025,2,2), validation_end=date(2025,3,1),
    test_start=date(2025,3,2), test_end=date(2025,4,1),
    status="completed",
)
db.add(m); db.commit(); db.refresh(m)

for i in range(3):
    db.add(ModelPrediction(model_id=m.id, stock_code="2330", as_of_date=date(2025,3,3),
                           predicted_return_percent=1.0, actual_return_percent=0.5,
                           predicted_probability=0.6, actual_label=True))
db.add(ModelHolding(model_id=m.id, stock_code="2330", source="live",
                    entry_date=date(2025,3,3), entry_price=100.0, status="open"))
db.add(ModelHolding(model_id=m.id, stock_code="2317", source="backtest",
                    entry_date=date(2025,3,3), entry_price=50.0, status="closed",
                    exit_date=date(2025,3,10), exit_price=52.0, return_percent=3.4))
db.add(ModelScoringRun(model_id=m.id, run_date=date(2025,3,3), duration_seconds=1.0, status="success"))
db.commit()

# 假造一個模型檔案資料夾，確認也會被清掉
d = artifacts.artifact_dir(m.id); d.mkdir(parents=True, exist_ok=True)
(d / "bundle.joblib").write_bytes(b"dummy")
print(f"MODEL_ID={m.id} 檔案存在={d.exists()}")
db.close()
