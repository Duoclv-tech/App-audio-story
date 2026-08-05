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

    # AI Voice local TTS (embedded engine, runs on GPU)
    # Enabled by default; the engine self-disables at runtime if torch / the
    # model runtime, a CUDA GPU, or the downloaded model is missing (VBEE keeps
    # working).
    AIVOICE_LOCAL_ENABLED: bool = True
    AIVOICE_LOCAL_DEVICE: str = "cuda:0"        # set to "cpu" to force CPU (slow)
    AIVOICE_LOCAL_MODEL_PATH: str = str(paths.AIVOICE_LOCAL_MODEL_DIR)
    AIVOICE_LOCAL_BASE_PATH: str = str(paths.AIVOICE_LOCAL_BASE_DIR)
    # Upstream HuggingFace repo ids the weights are fetched from at install /
    # first run (see model download API). These are real external identifiers —
    # they must stay as-is or the download breaks.
    AIVOICE_LOCAL_MODEL_REPO: str = "kjanh/KhanhTTS-OmniVoice"
    AIVOICE_LOCAL_BASE_REPO: str = "k2-fsa/OmniVoice"

    # Gemini AI (for grammar checking) — configured via Settings UI (DB)
    GEMINI_API_KEY: str = ""  # optional .env fallback; primary source is DB

    # OpenAI (for spellcheck) — only used by the auto_run.py CLI
    OPENAI_API_KEY: str = ""  # set in .env if you use the CLI spellcheck step

    # DeepSeek (OpenAI-compatible spellcheck) — configured via Settings UI (DB)
    DEEPSEEK_API_KEY: str = ""  # optional .env fallback; primary source is DB

    # --- Licensing (node-locked activation) ---------------------------------
    # Storefront that signs/issues license tokens (see app/license/*).
    LICENSE_SERVER_URL: str = "https://storetoolmmo.com"
    # Offline grace window in days. 0 = activate online once, run offline forever
    # (current mode). >0 enables periodic online re-verify (required for revoke).
    LICENSE_TOKEN_GRACE_DAYS: int = 0
    # Block unactivated use. Always enforced in the frozen .exe regardless of
    # this flag (see app/license/service.enforcement_enabled); this only turns
    # enforcement ON in dev when you want to test the activation flow.
    LICENSE_ENFORCE: bool = False
    # Sent as app_version in activation requests.
    APP_VERSION: str = "1.0.0"

    # Server
    # Bind to loopback by default — the API has no authentication, so exposing
    # it on 0.0.0.0 would hand the whole file-browse/read/upload surface to the
    # LAN. Set API_HOST=0.0.0.0 explicitly in .env only when you intend that.
    # (The desktop build binds 127.0.0.1 on a dynamic port regardless.)
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000
    DEBUG: bool = False

    # CORS — fixed list of local dev origins (5173/5174 = Vite, 3000 = CRA)
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:5174,http://localhost:3000"

    # --- Network / process timeouts -----------------------------------------
    # (connect, read) seconds for `requests`. The read timeout is the max gap
    # *between bytes*, so it also bounds mid-stream stalls (not just connect).
    # Without these a stalled remote wedges a worker thread and leaves the Task
    # stuck "running" forever (story lock never released).
    VBEE_HTTP_TIMEOUT: tuple = (10, 60)         # TTS create/status calls
    VBEE_DOWNLOAD_TIMEOUT: tuple = (10, 120)    # streaming audio download
    SCRAPE_HTTP_TIMEOUT: tuple = (10, 30)       # story-site HTML scraping
    # Hard ceiling (seconds) for a single ffmpeg trim invocation; a watchdog
    # kills the process past this so a hung ffmpeg can't wedge a trim job.
    FFMPEG_TRIM_TIMEOUT: int = 3600

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
