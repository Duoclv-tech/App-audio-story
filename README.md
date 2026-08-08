# 📖 AudioStory

Turns web novels into **audiobooks and subtitled videos** through a guided, multi-step media pipeline:

```
Download chapters → Edit / censor text → AI grammar check → TTS (voice) → Merge audio → Render video → Export
```

Ships two ways: a **packaged Windows desktop app** (recommended for end users) and a **web app in dev mode** (backend + frontend) for development.

## 🏗️ Architecture

```
Frontend:  React 18 + TypeScript + Vite + Tailwind CSS   (dev port 5173)
Backend:   FastAPI + SQLAlchemy 2.0 + Uvicorn            (port 8000 / random in desktop)
Database:  SQLite (single file, per-user data dir)        — MySQL optional via DATABASE_URL
Media:     FFmpeg / ffprobe (subprocess), Pillow
Desktop:   pywebview (WebView2) + PyInstaller → .exe / Inno Setup installer
```

The desktop build runs the FastAPI server on `127.0.0.1:<random port>` and renders it in a native WebView2 window — no browser, no Docker, no external database.

## ✨ Features

- **Download** chapters from supported hosts, or paste / upload content directly and auto-split into chapters.
- **Edit & censor** — review chapter text, handle masked/censored/merged words, manage a banned-words list.
- **AI grammar check** — reviews and improves merged content. Provider is selectable (`AI_GRAMMAR_PROVIDER`): **OpenAI** (default), **DeepSeek**, or **Google Gemini**.
- **Text-to-speech, two engines:**
  - **VBEE** (cloud API) — 25 Vietnamese voices, configured via the Settings UI.
  - **AI Voice local** (local, embedded) — runs on NVIDIA GPU (or CPU, slower); self-disables if torch/CUDA/model is missing so VBEE keeps working.
- **Merge audio** into a single file per story.
- **Render video** from audio + background clips with subtitles (auto-detects NVENC GPU encoding, falls back to libx264). Includes a standalone **video trimmer**.
- **Quick Build** — point at a folder of `.txt`/`.docx` story files and batch-build one video per file through the full pipeline (replaces the old `auto_run.py` CLI).
- **Export** to documents (`python-docx`).
- **Crash recovery** — reconciles orphaned tasks and cleans temp files / VRAM on restart.
- **License activation** — node-locked, offline (Ed25519). Enforced in the packaged `.exe`.

## 🚀 Option A — Run the desktop app (end users)

Install and launch:

1. Run `packaging/Output/AudioStory-Setup.exe` (built with Inno Setup).
2. Launch **AudioStory** from the Start menu.
3. Activate your license on first run (Activation screen).
4. Open **Settings** and enter your API keys (VBEE / OpenAI / DeepSeek / Gemini) — keys are stored in the local SQLite DB, nothing is hardcoded.

User data lives in `%LOCALAPPDATA%\AudioStory\`: `app.db` (SQLite), `storage/`, `cache/`, `logs/`.

To run the frozen build without installing, from the repo: `dist/AudioStory/AudioStory.exe`.

## 🧑‍💻 Option B — Run in dev mode (developers)

No Docker or MySQL required — the backend creates a SQLite database automatically.

### 1. Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
venv\Scripts\activate          # Windows (Git Bash: source venv/Scripts/activate)

# Install dependencies
pip install -r requirements.txt

# (optional) create .env for overrides — API keys are normally set in the Settings UI
# copy .env.example .env

# Run the API server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Backend endpoints:

- API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Health Check: http://localhost:8000/health

Or run the full desktop shell in dev: `python backend/desktop.py`.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev            # Vite dev server on http://localhost:5173, proxies /api → :8000
```

> **FFmpeg** is required for audio/video steps. Place `ffmpeg.exe` / `ffprobe.exe` in `backend/bin/`, or install FFmpeg on the system PATH.

## 📁 Project Structure

```
web_app/
├── backend/                   # FastAPI backend
│   ├── app/
│   │   ├── api/               # Routers (stories, download, tts, video, license, …)
│   │   ├── services/          # Business logic (downloader, tts, video, spellcheck, …)
│   │   ├── license/           # Node-locked activation (Ed25519, offline)
│   │   ├── models.py          # SQLAlchemy models
│   │   ├── schemas.py         # Pydantic schemas
│   │   ├── database.py        # DB engine (SQLite default, MySQL optional)
│   │   ├── config.py          # Settings
│   │   ├── paths.py           # Per-user data dir resolution (dev + frozen)
│   │   └── main.py            # FastAPI app
│   ├── desktop.py             # Desktop entry point (uvicorn + pywebview)
│   ├── bin/                   # ffmpeg.exe / ffprobe.exe (not committed)
│   └── requirements.txt
├── frontend/                  # React + Vite frontend
│   └── src/{components,pages,services}
├── packaging/                 # PyInstaller specs + Inno Setup installer
│   ├── audiostory.spec        # PyInstaller spec (full build: VBEE + AI Voice local)
│   ├── installer.iss          # Inno Setup script
│   └── BUILD.md               # Build instructions
├── dist/                      # PyInstaller output (AudioStory.exe)
└── docs/PROJECT_DOCUMENTATION.md   # Full architecture & flow reference
```

## 🔧 Configuration

Runtime credentials (VBEE, Gemini) are read **from the `settings` table in the DB first**, then `.env` as a fallback — so they can be changed from the Settings UI without a restart. No secrets are hardcoded.

Optional `backend/.env` overrides:

```bash
# Point at MySQL instead of the default SQLite (advanced)
# DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/truyenfull_db

# Optional .env fallbacks (primary source is the Settings UI / DB)
VBEE_APP_ID=
VBEE_BEARER_TOKEN=
GEMINI_API_KEY=
OPENAI_API_KEY=          # OpenAI grammar/spellcheck (default provider)
DEEPSEEK_API_KEY=        # DeepSeek grammar/spellcheck (OpenAI-compatible)

# AI Voice local TTS
AIVOICE_LOCAL_ENABLED=True
AIVOICE_LOCAL_DEVICE=cuda:0  # set to "cpu" to force CPU

# Server (dev) — binds loopback by default; the API has no auth
API_HOST=127.0.0.1
API_PORT=8000
DEBUG=False
```

## 📊 Database

SQLite by default (`app.db`), created and migrated automatically on startup. Tables:

`stories` · `chapters` · `audio_files` · `merged_audio` · `tts_segments` · `tasks` · `voices` · `censored_words` · `banned_words` · `video_outputs` · `video_presets` · `build_presets` · `build_batches` · `build_jobs` · `prompts` · `settings`

(17 tables: `tts_segments` = per-segment AI Voice local TTS; `build_presets`/`build_batches`/`build_jobs` power Quick Build; `video_presets` is legacy and migrated into `build_presets` on startup.)

## 🎯 Workflow (8-step wizard)

State is tracked in `stories.current_step`; you can go back to any completed step.

```
(1) Input → (2) Download → (3) Edit → (4) Grammar → (5) TTS Config
                                                          │
(8) Complete ← (7) Video ← (6) TTS Process ←──────────────┘
```

1. **Input** — story URL / title / chapter range, or pasted/uploaded content.
2. **Download** — fetch chapters into the DB (auto).
3. **Edit** — review text, handle censored/merged words.
4. **Grammar** — AI grammar check (OpenAI / DeepSeek / Gemini) on merged content.
5. **TTS Config** — pick engine (VBEE / AI Voice local), voice, speed, volume.
6. **TTS Process** — synthesize audio, retry per chapter.
7. **Video** — render video from audio + background clips with subtitles.
8. **Complete** — download the finished audio / video.

## 🔌 API Endpoints

All routers are mounted under `/api/v1/*`:

`stories` · `chapters` · `download` · `text` · `tts` · `audio` · `video` · `video-presets` · `build-presets` · `quick-build` · `history` · `trim` · `settings` · `banned-words` · `prompts` · `export` · `license`

See interactive docs at http://localhost:8000/docs.

## 📦 Building the desktop app

See [`packaging/BUILD.md`](packaging/BUILD.md) for the full process. In short:

```bash
# 1. Build frontend (static)
cd frontend && npm run build

# 2. Package with PyInstaller (from repo root)
backend/venv/Scripts/pyinstaller.exe packaging/audiostory.spec --noconfirm
#   (full build: nhúng cả VBEE + AI Voice local; AI Voice local tự chạy GPU hoặc CPU)

# 3. Smoke-test the frozen build (no window)
dist/AudioStory/AudioStory.exe --selftest

# 4. Create the installer (requires Inno Setup 6)
iscc packaging\installer.iss
#   -> packaging/Output/AudioStory-Setup.exe
```

## 📄 License

Private project. Distribution is gated by node-locked license activation.
