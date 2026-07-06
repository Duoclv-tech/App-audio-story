from pydantic import field_validator
from pydantic_settings import BaseSettings
from typing import List
import os

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "mysql+pymysql://truyenfull_user:truyenfull_pass@localhost:3307/truyenfull_db"
    DB_HOST: str = "localhost"
    DB_PORT: int = 3307
    DB_USER: str = "truyenfull_user"
    DB_PASSWORD: str = "truyenfull_pass"
    DB_NAME: str = "truyenfull_db"

    # Storage
    STORAGE_PATH: str = "./storage"

    # VBEE TTS (Official API)
    VBEE_APP_ID: str = "c1c5c478-719d-4ec6-b665-58ed39484375"
    VBEE_API_URL: str = "https://vbee.vn/api/v1"
    VBEE_BEARER_TOKEN: str = ""  # JWT Bearer token từ VBEE

    # Gemini AI (for grammar checking)
    GEMINI_API_KEY: str = ""  # Get from https://ai.google.dev

    # OpenAI (for spellcheck)
    OPENAI_API_KEY: str = ""  # Get from https://platform.openai.com/api-keys

    # Server
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    DEBUG: bool = True

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production"}:
                return False
            if normalized in {"debug", "dev", "development"}:
                return True
        return value

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Ignore extra env vars not defined in Settings

settings = Settings()

# Ensure storage directories exist
os.makedirs(os.path.join(settings.STORAGE_PATH, "stories"), exist_ok=True)
os.makedirs(os.path.join(settings.STORAGE_PATH, "audio"), exist_ok=True)
os.makedirs(os.path.join(settings.STORAGE_PATH, "videos"), exist_ok=True)
