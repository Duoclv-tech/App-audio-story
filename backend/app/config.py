from pydantic import field_validator
from pydantic_settings import BaseSettings
from typing import List

from app import paths

class Settings(BaseSettings):
    # Database — SQLite file under the per-user data dir (see app/paths.py).
    # Overridable via .env for anyone still pointing at MySQL (set DATABASE_URL).
    DATABASE_URL: str = f"sqlite:///{paths.DB_PATH}"

    # Storage — absolute path resolved by app/paths.py (works dev + frozen)
    STORAGE_PATH: str = str(paths.STORAGE_DIR)

    # VBEE TTS (Official API)
    # Credentials are configured at runtime via the Settings UI (stored in DB);
    # .env is only an optional fallback. No secrets are hardcoded here.
    VBEE_APP_ID: str = ""      # optional .env fallback; primary source is DB
    VBEE_API_URL: str = "https://vbee.vn/api/v1"
    VBEE_BEARER_TOKEN: str = ""  # optional .env fallback; primary source is DB

    # Gemini AI (for grammar checking) — configured via Settings UI (DB)
    GEMINI_API_KEY: str = ""  # optional .env fallback; primary source is DB

    # OpenAI (for spellcheck) — only used by the auto_run.py CLI
    OPENAI_API_KEY: str = ""  # set in .env if you use the CLI spellcheck step

    # Server
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    DEBUG: bool = True

    # CORS — fixed list of local dev origins (5173/5174 = Vite, 3000 = CRA)
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:5174,http://localhost:3000"

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

# Storage/cache directories are created by app.paths.ensure_data_dirs()
# (run on import of app.paths).
