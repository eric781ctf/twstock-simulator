from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://twstock:twstock@db:5432/twstock"
    initial_cash: float = 1_000_000
    poll_interval_seconds: int = 7
    trading_start: str = "09:00"
    trading_end: str = "13:30"
    commission_rate: float = 0.001425
    tax_rate: float = 0.003
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    class Config:
        env_prefix = "TWSTOCK_"


settings = Settings()
