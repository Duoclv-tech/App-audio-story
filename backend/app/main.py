from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from loguru import logger
import sys

from app import paths

# Make bundled ffmpeg/ffprobe (backend/bin or the frozen bundle) resolvable by
# the many literal 'ffmpeg'/'ffprobe' subprocess calls. No-op if the dir is
# absent (dev without bundled binaries -> falls back to system PATH).
paths.setup_ffmpeg_path()
# Stop ffmpeg/ffprobe from flashing console windows in the windowed build.
paths.hide_subprocess_windows()

from app.config import settings
from app.database import test_connection, init_db
from app.api import stories, chapters, download, text, tts, audio, video, settings_api, banned_words, prompts, export, trim, video_presets

# Configure loguru — log into the per-user data dir so it works when frozen
# (Program Files is read-only) and in dev alike.
logger.remove()
# In a windowed frozen build sys.stderr is None -> guard the console sink.
if sys.stderr is not None:
    logger.add(sys.stderr, level="INFO" if not settings.DEBUG else "DEBUG")
logger.add(str(paths.LOG_DIR / "app.log"), rotation="10 MB", level="DEBUG")

# Create FastAPI app
app = FastAPI(
    title="TruyenFull Processor API",
    description="API for processing stories from TruyenFull",
    version="1.0.0",
    debug=settings.DEBUG
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount storage folder for serving files
app.mount("/storage", StaticFiles(directory=settings.STORAGE_PATH), name="storage")

# Include routers
app.include_router(stories.router, prefix="/api/v1/stories", tags=["stories"])
app.include_router(chapters.router, prefix="/api/v1/chapters", tags=["chapters"])
app.include_router(download.router, prefix="/api/v1/download", tags=["download"])
app.include_router(text.router, prefix="/api/v1/text", tags=["text"])
app.include_router(tts.router, prefix="/api/v1/tts", tags=["tts"])
app.include_router(audio.router, prefix="/api/v1/audio", tags=["audio"])
app.include_router(video.router, prefix="/api/v1/video", tags=["video"])
app.include_router(settings_api.router, prefix="/api/v1/settings", tags=["settings"])
app.include_router(banned_words.router, prefix="/api/v1/banned-words", tags=["banned-words"])
app.include_router(prompts.router, prefix="/api/v1/prompts", tags=["prompts"])
app.include_router(export.router, prefix="/api/v1/export", tags=["export"])
app.include_router(trim.router, prefix="/api/v1/trim", tags=["trim"])
app.include_router(video_presets.router, prefix="/api/v1/video-presets", tags=["video-presets"])

@app.on_event("startup")
async def startup_event():
    """Startup event handler"""
    logger.info("Starting TruyenFull Processor API...")
    logger.info(f"Debug mode: {settings.DEBUG}")
    logger.info(f"CORS origins: {settings.cors_origins_list}")

    # Create tables (SQLite file is created on first run) then seed defaults.
    init_db()

    # Test database connection
    if test_connection():
        logger.info("Database connection successful")
    else:
        logger.error("Database connection failed!")

    # Seed default voices + settings if the DB is empty
    from app.seed import seed_defaults
    seed_defaults()

    # Reconcile work orphaned by a previous crash/force-quit: mark in-progress
    # tasks failed (no auto-resume — TTS is billable) and remove leftover *.work
    # temp dirs. Runs before requests are served, so nothing live is affected.
    from app.startup_recovery import run_startup_recovery
    run_startup_recovery()

@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler"""
    logger.info("Shutting down TruyenFull Processor API...")

@app.get("/api/info")
async def api_info():
    """API info endpoint"""
    return {
        "message": "TruyenFull Processor API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    db_status = test_connection()
    return {
        "status": "healthy" if db_status else "unhealthy",
        "database": "connected" if db_status else "disconnected",
        "version": "1.0.0"
    }

# --- Serve the built frontend (SPA) -----------------------------------------
# Registered LAST so /api/*, /storage and /docs match first. The catch-all
# returns index.html for client-side routes (/history, /processor/...) so a
# page refresh doesn't 404.
if paths.FRONTEND_DIST.is_dir():
    _ASSETS_DIR = paths.FRONTEND_DIST / "assets"
    if _ASSETS_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=_ASSETS_DIR), name="assets")

    _INDEX_HTML = paths.FRONTEND_DIST / "index.html"

    @app.get("/")
    async def spa_root():
        return FileResponse(_INDEX_HTML)

    _DIST_ROOT = paths.FRONTEND_DIST.resolve()

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        # Never swallow API/storage/docs paths — let them 404 as JSON.
        if full_path.startswith(("api/", "storage/")) or full_path in ("docs", "redoc", "openapi.json"):
            raise HTTPException(status_code=404, detail="Not found")
        # Serve a real static file only if it resolves INSIDE the dist dir
        # (guards against path traversal like ../../etc/...).
        candidate = (paths.FRONTEND_DIST / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(_DIST_ROOT):
            return FileResponse(candidate)
        return FileResponse(_INDEX_HTML)
else:
    @app.get("/")
    async def root_no_frontend():
        return {"message": "TruyenFull Processor API (frontend not built)", "docs": "/docs"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.DEBUG
    )
