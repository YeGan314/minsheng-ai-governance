from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    APP_ENV: str = "development"
    SQLITE_PATH: str = "/data/minsheng-governance.db"
    APP_ENCRYPTION_KEY: str = ""
    MIGRATE_LEGACY_GOVERNANCE: bool = True
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    # Optional external intake connector; local application state is stored in SQLite.
    DATABASE_URL: str = ""
    LEGACY_GOVERNANCE_DATABASE_URL: str = ""
    GEOSERVER_URL: str = "http://minsheng-geoserver:8080/geoserver"
    GEOSERVER_USER: str = ""
    GEOSERVER_PASSWORD: str = ""
    TIANDITU_TK: str = ""
    REDIS_URL: str = "redis://redis:6379/0"


settings = Settings()
