from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    echryn_api_key: str = "change-me"
    echryn_public_base_url: str = "http://localhost:8080"
    echryn_data_dir: str = "/tmp/echryn"
    echryn_cache_ttl_seconds: int = 7 * 24 * 3600
    echryn_max_media_mb: int = 80
    echryn_max_frames: int = 12
    echryn_mode_default: str = "auto"

    instagram_sessionid: str | None = None
    instagram_csrftoken: str | None = None
    instagram_ds_user_id: str | None = None
    instagram_user_agent: str = "Mozilla/5.0"

    vision_api_url: str | None = None
    vision_api_key: str | None = None
    vision_model: str | None = None

    speech_api_url: str | None = None
    speech_api_key: str | None = None
    speech_model: str | None = None

    @property
    def data_dir(self) -> Path:
        p = Path(self.echryn_data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
