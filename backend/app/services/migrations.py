"""輕量、冪等的 schema 補丁，取代 Alembic：`Base.metadata.create_all` 只會建立
新表，不會替既有的表補上新欄位，若直接改 models.py 加欄位，舊資料庫會直接壞掉。
每一段都要能重複執行、不能對既有資料造成損失。"""

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def run_lightweight_migrations(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS nickname VARCHAR(50)"))
        conn.execute(text("UPDATE users SET nickname = username WHERE nickname IS NULL"))
        conn.execute(text("ALTER TABLE users ALTER COLUMN nickname SET NOT NULL"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS frozen_until TIMESTAMPTZ"))
    logger.info("run_lightweight_migrations 完成")
