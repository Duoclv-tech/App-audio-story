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
from app.api import stories, chapters, download, text, tts, audio, video, settings_api, banned_words, prompts, export, trim, video_presets, build_presets, quick_build, history, license as license_api
from app.license import service as license_service

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

# --- License gate -----------------------------------------------------------
# Blocks every /api/v1/* route until the machine is activated, EXCEPT the
# license routes themselves (so the activation screen can work). Enforced
# always in the packaged .exe; opt-in via LICENSE_ENFORCE in dev. The offline
# token check is cheap (device_id is cached; Ed25519 verify is microseconds).
from fastapi.responses import JSONResponse

_LICENSE_ALLOW_PREFIX = "/api/v1/license"


@app.middleware("http")
async def license_gate(request, call_next):
    if license_service.enforcement_enabled():
        path = request.url.path
        if path.startswith("/api/v1/") and not path.startswith(_LICENSE_ALLOW_PREFIX):
            if not license_service.is_activated():
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Ứng dụng chưa được kích hoạt. Vui lòng nhập mã kích hoạt.",
                        "reason": "not_activated",
                    },
                )
    return await call_next(request)


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
app.include_router(build_presets.router, prefix="/api/v1/build-presets", tags=["build-presets"])
app.include_router(quick_build.router, prefix="/api/v1/quick-build", tags=["quick-build"])
app.include_router(history.router, prefix="/api/v1/history", tags=["history"])
app.include_router(license_api.router, prefix="/api/v1/license", tags=["license"])

@app.on_event("startup")
async def startup_event():
    """Startup event handler"""
    logger.info("Starting TruyenFull Processor API...")
    logger.info(f"Debug mode: {settings.DEBUG}")
    logger.info(f"CORS origins: {settings.cors_origins_list}")

    # Fresh install: lay down the bundled seed DB (+ media for a full-dev build)
    # BEFORE the engine connects — otherwise SQLite creates an empty file first
    # and this is skipped. No-op when a user DB already exists.
    from app.seed import restore_seed_data_if_fresh
    restore_seed_data_if_fresh()

    # Create tables (SQLite file is created on first run) then seed defaults.
    init_db()

    # Additive column patches for models that gained columns after first ship
    # (create_all never ALTERs an existing table). Idempotent — safe every boot.
    from app.db_migrations import run_light_migrations
    run_light_migrations()

    # Merge legacy video_presets into the unified build_presets table (adds the
    # cfg column if missing, copies rows). Idempotent — safe on every boot.
    from app.preset_migration import migrate_video_presets
    migrate_video_presets()

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

    # One-time rename migration: an earlier build stored the local TTS engine as
    # "omnivoice" and its CPU-mode setting key as "OMNIVOICE_USE_CPU". Rewrite any
    # rows left from that build so history/filters keep matching the new name.
    from app.database import SessionLocal
    from sqlalchemy import text as _sql_text
    _mdb = SessionLocal()
    try:
        _mdb.execute(_sql_text("UPDATE tasks SET engine='ai_voice_local' WHERE engine='omnivoice'"))
        _mdb.execute(_sql_text("UPDATE merged_audio SET engine='ai_voice_local' WHERE engine='omnivoice'"))
        _mdb.execute(_sql_text("UPDATE settings SET setting_key='AIVOICE_LOCAL_USE_CPU' WHERE setting_key='OMNIVOICE_USE_CPU'"))
        # Batch history snapshots carry the engine inside a JSON blob.
        _mdb.execute(_sql_text(
            "UPDATE build_batches SET config_snapshot=json_set(config_snapshot,'$.engine','ai_voice_local') "
            "WHERE json_extract(config_snapshot,'$.engine')='omnivoice'"
        ))
        _mdb.commit()
    except Exception as _mig_e:  # noqa: BLE001
        logger.warning(f"[startup] engine rename migration skipped: {_mig_e}")
        _mdb.rollback()
    finally:
        _mdb.close()

    # AI Voice local per-segment TTS: a segment left 'processing' by a closed app has
    # no live task generating it — reset it to 'pending' so it can be re-run.
    from app.workers.tts_worker import resume_stuck_segments
    resume_stuck_segments()

    # Quick-build: fail any batch/job left mid-run by a closed app.
    from app.services.build_orchestrator import recover_interrupted
    recover_interrupted()

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
