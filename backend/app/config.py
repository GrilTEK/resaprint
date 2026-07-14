from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Core
    secret_key: str = "change-me-in-production"
    session_cookie_secure: bool = True
    session_max_age_seconds: int = 12 * 60 * 60
    pin_lockout_threshold: int = 5
    pin_lockout_minutes: int = 15

    # Database
    database_url: str = "postgresql+asyncpg://resaprint:resaprint@db:5432/resaprint"

    # IMAP ingestion
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"
    imap_processed_folder: str = "Processed"
    imap_poll_seconds: int = 60

    # Printing
    lan_print_timeout_seconds: float = 5.0


settings = Settings()
