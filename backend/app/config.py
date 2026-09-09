from pydantic import field_validator
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
    # 從別台裝置連進來時，來源會是「那台機器看到的位址」而不是 localhost，
    # 上面那份固定清單就對不上。位址每天會變（DHCP、浮動 IP）的情況沒辦法
    # 一一列舉，所以另外給一個正規表示式的開關，用 TWSTOCK_CORS_ORIGIN_REGEX
    # 設定。預設 None——放寬跨來源限制要是明確的選擇，不能是預設值。
    cors_origin_regex: str | None = None

    @field_validator("cors_origin_regex", mode="after")
    @classmethod
    def _blank_regex_means_off(cls, value: str | None) -> str | None:
        """空字串當成「沒設定」。

        docker-compose 用 ${VAR:-} 傳進來時，沒設定會變成空字串而不是 None，
        而空字串是一個合法的正規表示式——中介層會拿它去比對，行為取決於
        底層用 match 還是 fullmatch，太微妙了。直接在這裡收斂成 None。
        """
        return value or None

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
