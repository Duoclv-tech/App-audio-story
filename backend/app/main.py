from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
import sys

from app.config import settings
from app.database import test_connection, init_db
from app.api import stories, chapters, download, text, tts, audio, video, settings_api, banned_words, prompts, export, trim, video_presets

# Configure loguru
logger.remove()
logger.add(sys.stderr, level="INFO" if not settings.DEBUG else "DEBUG")
logger.add("logs/app.log", rotation="10 MB", level="DEBUG")

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

    # Test database connection
    if test_connection():
        logger.info("Database connection successful")
    else:
        logger.error("Database connection failed!")

    # Initialize database tables
    # init_db()

@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler"""
    logger.info("Shutting down TruyenFull Processor API...")

@app.get("/")
async def root():
    """Root endpoint"""
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.DEBUG
    )
