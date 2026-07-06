# 📖 TruyenFull Processor - Web Application

A full-stack web application for downloading, processing, and converting stories from TruyenFull to audio using VBEE TTS.

## 🏗️ Architecture

```
Frontend: React + TypeScript + Tailwind CSS (Port: 5173)
Backend:  FastAPI + Python (Port: 8000)
Database: MySQL 8.0 (Docker, Port: 3307)
Storage:  Local filesystem
```

## 📦 Prerequisites

- **Docker & Docker Compose** (for MySQL)
- **Python 3.10+** (for backend)
- **Node.js 18+** (for frontend)
- **FFmpeg** (for audio processing)

## 🚀 Quick Start

### 1. Start MySQL Database

```bash
cd docker
docker-compose up -d
```

Wait for MySQL to be ready (~10 seconds).

### 2. Start Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env
# Edit .env and configure your settings

# Run server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Backend will be available at:

- API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Health Check: http://localhost:8000/health

### 3. Start Frontend

```bash
cd frontend

# Install dependencies
npm install

# Run dev server
npm run dev
```

Frontend will be available at: http://localhost:5173

## 📁 Project Structure

```
web_app/
├── docker/                    # Docker configuration
│   ├── docker-compose.yml
│   └── mysql/
│       ├── init.sql
│       └── my.cnf
├── backend/                   # FastAPI backend
│   ├── app/
│   │   ├── api/              # API endpoints
│   │   ├── services/         # Business logic
│   │   ├── models.py         # Database models
│   │   ├── schemas.py        # Pydantic schemas
│   │   ├── database.py       # Database config
│   │   ├── config.py         # Settings
│   │   └── main.py           # FastAPI app
│   ├── storage/              # File storage
│   ├── requirements.txt
│   └── .env
└── frontend/                  # React frontend
    ├── src/
    │   ├── components/
    │   ├── pages/
    │   ├── services/
    │   └── App.tsx
    ├── package.json
    └── vite.config.ts
```

## 🔧 Configuration

### Backend (.env)

```bash
# Database
DATABASE_URL=mysql+pymysql://truyenfull_user:truyenfull_pass@localhost:3307/truyenfull_db

# VBEE TTS API (required for TTS functionality)
VBEE_API_KEY=your_api_key_here
VBEE_API_URL=https://api.vbee.ai/v1

# Server
API_PORT=8000
DEBUG=True

# CORS
CORS_ORIGINS=http://localhost:5173
```

### Frontend

API proxy is configured in `vite.config.ts` to proxy `/api/*` requests to `http://localhost:8000`.

## 📊 Database

MySQL database is automatically initialized with the schema defined in `docker/mysql/init.sql`.

**Tables:**

- `stories` - Story metadata
- `chapters` - Chapter content
- `audio_files` - Generated audio files
- `merged_audio` - Merged audio files
- `tasks` - Background task tracking
- `censored_words` - Censored word tracking
- `settings` - Application settings

## 🎯 Workflow

1. **Input** - Enter TruyenFull URL and chapter range
2. **Download** - Download chapters from TruyenFull
3. **Edit** - Review and edit chapter content, check for censored words
4. **Confirm** - Configure TTS settings
5. **TTS** - Convert text to speech using VBEE API
6. **Merge** - Merge audio files into single file
7. **Complete** - Download merged audio file

## 🔌 API Endpoints

### Stories

- `POST /api/v1/stories` - Create story project
- `GET /api/v1/stories` - List all stories
- `GET /api/v1/stories/{id}` - Get story details
- `PUT /api/v1/stories/{id}` - Update story
- `DELETE /api/v1/stories/{id}` - Delete story
- `GET /api/v1/stories/{id}/stats` - Get story statistics

### Download

- `POST /api/v1/download/start` - Start download
- `GET /api/v1/download/{task_id}/status` - Check status
- `POST /api/v1/download/pause` - Pause download
- `POST /api/v1/download/resume` - Resume download
- `POST /api/v1/download/cancel` - Cancel download

### TTS

- `POST /api/v1/tts/start` - Start TTS processing
- `GET /api/v1/tts/{task_id}/status` - Check TTS status
- `GET /api/v1/tts/voices` - List available voices

### Audio

- `GET /api/v1/audio/{story_id}` - List audio files
- `POST /api/v1/audio/merge/start` - Start merging
- `GET /api/v1/audio/merge/{task_id}/status` - Check merge status

## 🛠️ Development

### Backend Development

```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload
```

### Frontend Development

```bash
cd frontend
npm run dev
```

### Database Management

```bash
# Stop database
cd docker
docker-compose down

# Restart database (fresh)
docker-compose down -v
docker-compose up -d

# View logs
docker-compose logs -f mysql
```

## 📝 TODO

- [ ] Implement core services (downloader, text_checker, tts_processor, audio_merger)
- [ ] Implement frontend UI components and pages
- [ ] Add WebSocket/SSE for real-time updates
- [ ] Add authentication (optional)
- [ ] Add file upload/download endpoints
- [ ] Implement error handling and retry logic
- [ ] Add unit tests
- [ ] Add integration tests

## 🤝 Contributing

This is a local development project. Core services need to be refactored from the existing `make_story/` directory.

## 📄 License

Private project for personal use.
