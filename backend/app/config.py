from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://twstock:twstock@db:5432/twstock"
    initial_cash: float = 1_000_000
    poll_interval_seconds: int = 7
    trading_start: str = "09:00"
    trading_end: str = "13:30"
    after_hours_end: str = "20:00"
    commission_rate: float = 0.001425
    tax_rate: float = 0.003
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    admin_username: str = "admin"
    admin_password: str = "admin"

    # 沒有預設值：沒有透過 TWSTOCK_JWT_SECRET 設定就直接啟動失敗，
    # 避免有人忘記覆蓋、讓一個公開在原始碼裡的密鑰變成正式簽章金鑰。
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    class Config:
        env_prefix = "TWSTOCK_"
        env_file = ".env"


settings = Settings()
