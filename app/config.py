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
    echryn_evidence_max_frames: int = 6
    echryn_frame_webp_quality: int = 70
    echryn_frame_max_width: int = 640
    echryn_scene_threshold: float = 0.24
    echryn_scene_min_gap_seconds: float = 0.6
    echryn_mode_default: str = "auto"

    echryn_speech_model: str = "base"
    echryn_speech_device: str = "cpu"
    echryn_speech_compute_type: str = "int8"
    echryn_whisper_beam_size: int = 1
    echryn_vad_threshold: float = 0.55
    echryn_vad_min_speech_ms: int = 350
    echryn_vad_min_silence_ms: int = 300
    echryn_vad_speech_pad_ms: int = 150
    echryn_min_total_speech_seconds: float = 0.6

    instagram_sessionid: str | None = None
    instagram_csrftoken: str | None = None
    instagram_ds_user_id: str | None = None
    instagram_user_agent: str = "Mozilla/5.0"

    @property
    def data_dir(self) -> Path:
        p = Path(self.echryn_data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
