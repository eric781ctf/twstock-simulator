from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FeatureFlag, User
from app.services.auth import get_current_user

router = APIRouter(prefix="/feature-flags", tags=["feature-flags"])


@router.get("")
def get_feature_flags(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, bool]:
    """任何登入使用者都能查——前端要用它決定像「策略」這種功能該不該顯示
    維護中畫面，不能只給管理員看。"""
    return {f.key: f.enabled for f in db.query(FeatureFlag).all()}
