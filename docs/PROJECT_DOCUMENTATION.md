# 📚 Tài liệu dự án — TruyenFull Processor (Web App)

> Tài liệu tổng hợp: kiến trúc, stack công nghệ, luồng nghiệp vụ (flow) và chi tiết từng chức năng.
> Cập nhật: 2026-07-06.

---

## 1. Tổng quan

**TruyenFull Processor** là một ứng dụng full-stack biến **truyện chữ trên web thành audiobook và video**. Nó không "chỉ chạy web" — web chỉ là giao diện điều khiển; phần lõi là một **pipeline xử lý media** nhiều bước.

Luồng giá trị cốt lõi:

```
Tải truyện từ web  →  Sửa/kiểm duyệt văn bản  →  TTS (giọng đọc)  →  Ghép audio  →  Render video có phụ đề  →  Xuất file
```

Có **2 cách vận hành**:

| Cách | Mô tả | Khi nào dùng |
|------|-------|--------------|
| **Web App** (có UI) | Chạy `start.bat` / `run.sh`, thao tác qua trình duyệt theo wizard | Làm thủ công, kiểm soát từng bước |
| **Batch CLI** | Chạy `python auto_run.py <url...>` — chạy trọn pipeline không cần server | Tự động hóa hàng loạt nhiều truyện |

---

## 2. Kiến trúc & Stack công nghệ

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend — React + TS + Vite + Tailwind        (port 5173)      │
│  proxy /api → backend                                            │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP (axios / SSE)
┌───────────────────────────▼─────────────────────────────────────┐
│  Backend — FastAPI + SQLAlchemy                 (port 8000)      │
│  ┌── api/ (routers)  ── services/ (logic)  ── workers/ (nền) ──┐ │
│  └──────────────────────────────────────────────────────────────┘│
│         │ FFmpeg / ffprobe (subprocess)     │ HTTP APIs           │
└─────────┼───────────────────────────────────┼────────────────────┘
          │                                   │
   ┌──────▼──────┐               ┌────────────▼─────────────┐
   │  MySQL 8.0  │               │ VBEE TTS · Gemini ·      │
   │ (Docker)    │               │ OpenAI · Ollama (local)  │
   │  port 3307  │               └──────────────────────────┘
   └─────────────┘
```

### 2.1. Frontend

| Thành phần | Công nghệ |
|------------|-----------|
| Framework | React 18.2 + TypeScript 5.3 |
| Build tool | Vite 5.1 (`@vitejs/plugin-react`) |
| Routing | `react-router-dom` 6.21 |
| HTTP | `axios` 1.6 + SSE (`EventSource`) cho tiến trình cắt video |
| State | `zustand` 4.5 (có cài nhưng thực tế page dùng `useState` cục bộ) |
| UI | Tailwind CSS + `lucide-react` (icon) + `clsx`; **tự viết component**, không dùng thư viện UI |
| Dev server | Port **5173**, proxy `/api/*` → `http://localhost:8000` (`vite.config.ts`) |

### 2.2. Backend

| Thành phần | Công nghệ |
|------------|-----------|
| Web framework | FastAPI 0.109 + Uvicorn 0.27 |
| ORM / DB driver | SQLAlchemy 2.0 + PyMySQL / aiomysql |
| Validation / config | Pydantic 2.5 + pydantic-settings |
| Scraping | `requests` + `beautifulsoup4` + `chardet` |
| Xử lý media | **FFmpeg / ffprobe CLI** (gọi qua `subprocess`) — tự dò **NVENC** (GPU), fallback libx264 |
| Ảnh | **Pillow** (tạo mask hình cho watermark) |
| Xuất tài liệu | `python-docx` |
| Logging | `loguru` (ghi `logs/app.log`, xoay vòng 10 MB) |

> ⚠️ **Pillow** và **FFmpeg binary** được code dùng nhưng không nằm trong `requirements.txt` — cần cài riêng (FFmpeg là dependency hệ thống).

### 2.3. Database & Hạ tầng

| Thành phần | Chi tiết |
|------------|----------|
| MySQL | `mysql:8.0` trong Docker, container `truyenfull_mysql`, host port **3307** → container 3306 |
| DB / user | `truyenfull_db` / `truyenfull_user` |
| Charset | `utf8mb4` / `utf8mb4_unicode_ci`, timezone `+07:00` |
| Init scripts | `01_init.sql` (bảng chính) + `02_init_voices.sql` (14 giọng VBEE) auto-load |
| Migration thủ công | `03_add_prompts.sql`, `migration_add_current_step.sql` — **không auto-load**, chạy tay |

### 2.4. Tích hợp bên ngoài

| Dịch vụ | Vai trò | Cấu hình |
|---------|---------|----------|
| **VBEE TTS** | Chuyển văn bản → giọng đọc (bắt buộc cho TTS) | `VBEE_APP_ID`, `VBEE_BEARER_TOKEN` |
| **Google Gemini** | Kiểm tra ngữ pháp / cải thiện văn bản bằng AI | `GEMINI_API_KEY` |
| **OpenAI** | Spellcheck tiếng Việt (dùng trong `auto_run.py`) | `OPENAI_API_KEY` |
| **Ollama** | Spellcheck local (tùy chọn, `localhost:11434`) | model mặc định `gemma4:26b` |

Credentials nhạy cảm (VBEE, Gemini) được đọc **ưu tiên từ bảng `settings` trong DB**, sau đó mới tới `.env` → cho phép cấu hình runtime qua trang Settings mà không cần restart.

---

## 3. Luồng nghiệp vụ (Flow)

Nghiệp vụ là một **wizard 8 bước**, trạng thái lưu ở `stories.current_step`. Người dùng có thể quay lại bước ≤ bước đã đạt.

```
 (1) Input ──▶ (2) Download ──▶ (3) Edit ──▶ (4) Grammar ──▶ (5) TTS Config
                                                                    │
 (8) Complete ◀── (7) Video ◀── (6) TTS Process ◀───────────────────┘
```

| # | Bước | UI | Mô tả |
|---|------|----|-------|
| 1 | **Input** | hiện | Nhập URL truyện, tiêu đề, chương bắt đầu/kết thúc, tùy chọn danh sách URL chương tùy chỉnh |
| 2 | **Download** | ẩn (tự chạy) | Tải chương từ nguồn về DB |
| 3 | **Edit** | hiện | Xem/sửa nội dung chương, xử lý từ bị che/kiểm duyệt/dính chữ |
| 4 | **Grammar** | hiện | Kiểm tra ngữ pháp AI (Gemini); xem/sửa "nội dung gộp" (merged content) |
| 5 | **TTS Config** | hiện | Chọn giọng đọc VBEE, tốc độ, âm lượng |
| 6 | **TTS Process** | hiện | Chuyển văn bản → audio, theo dõi/ retry từng chương |
| 7 | **Video** | hiện | Dựng video từ audio + clip nền (bước phức tạp nhất) |
| 8 | **Complete** | hiện | Tải audio/video hoàn chỉnh |

**Mô hình xử lý bất đồng bộ** (không dùng message queue như Celery — theo dõi qua bảng `tasks` + registry in-memory):

| Tác vụ | Cơ chế |
|--------|--------|
| Download / Merge / TTS `/start` | **Đồng bộ** (await ngay trong request) |
| TTS `/start-background`, `/start-merged` | `BackgroundTasks` của FastAPI |
| Video `/start` | **Thread daemon** riêng (tạo event loop mới) |
| Trim video `/process` | `asyncio` executor + **SSE** stream tiến trình |
| Tiến trình dài ở ProcessorPage | Frontend **poll** endpoint `.../status` lặp lại |

---

## 4. Mô hình dữ liệu (Database)

`stories` là bảng gốc; xóa story sẽ cascade toàn bộ dữ liệu con.

```
stories ──1:n──▶ chapters ──1:n──▶ audio_files
   │                 └────1:n──▶ censored_words
   ├──1:n──▶ merged_audio
   ├──1:n──▶ tasks            (theo dõi mọi background job)
   └──1:n──▶ video_outputs

Bảng độc lập (không FK): settings · voices · banned_words · prompts · video_presets
```

| Bảng | Vai trò | Cột đáng chú ý |
|------|---------|----------------|
| `stories` | Dự án truyện | `current_step`, `merged_content` (toàn bộ chương gộp), `is_favorite`, `custom_chapter_urls` (JSON) |
| `chapters` | Từng chương | `content`, `char_count`, `has_censored_words`, `censored_count`; UNIQUE(story_id, chapter_number) |
| `audio_files` | File audio mỗi chương | `status` (idle/processing/success/failed), `request_id` (VBEE), `audio_link` |
| `merged_audio` | Audio ghép của cả truyện | `file_path`, `duration`, `total_chapters` |
| `tasks` | Theo dõi job nền | `type`, `status`, `progress`, `total/completed/failed_items` |
| `censored_words` | Từ bị che/cấm/dính | `word_type` ('censored'/'banned'/'stuck'/'numbering'), `suggested_replacement`, `fixed` |
| `video_outputs` | Kết quả render video | `audio_speed` (1.07), `transition_effect`, `resolution` (1920x1080) |
| `settings` | Cấu hình runtime (key-value JSON) | override API key, tts_voice/speed/volume... |
| `voices` | Danh mục 14 giọng VBEE | `code`, `gender`, `locale`, `rank` (mặc định Ngọc Huyền) |
| `banned_words` | Từ điển từ cấm → từ thay thế | `banned_word`, `replacement_word`, `is_active` |
| `prompts` | Thư viện prompt AI | `title`, `content`, `category` |
| `video_presets` | Cấu hình video lưu sẵn | `cfg` (JSON — toàn bộ config) |

---

## 5. Chi tiết chức năng

### 5.1. 📥 Tải truyện (Downloader)

Service `downloader.py` (`StoryDownloader`) scrape truyện đa nguồn, tự nhận diện domain để chọn CSS selector phù hợp.

**Nguồn được hỗ trợ:**

| Nguồn | Cách lấy nội dung |
|-------|-------------------|
| truyenfull.vision / .vn (mặc định) | scrape `.chapter-c` |
| truyenmoiii.org | scrape `.chapter-content` (article) |
| truyenhay.blog | WordPress, `.entry-content` |
| nguyettruyen.net, metruyen.mobi/.fit, vivutruyen.net, metruyenhot | scrape theo selector riêng |
| **daotruyen.me** | **JSON API** (không scrape) |

**Kỹ thuật chống anti-scraping:** loại bỏ span giả (`class="fake"`), đọc text từ CSS `::before`/attribute, tải song song với `asyncio.Semaphore(3)`, fallback nhiều URL pattern.

**Endpoints** (`/api/v1/download`): `POST /start`, `GET /{task_id}/status`, `POST /pause|/resume|/cancel`.

### 5.2. ✏️ Kiểm tra & sửa văn bản

Nhiều lớp kiểm tra, kết hợp regex và AI:

**a) `text_checker.py` (regex, không AI):**
- `find_censored_words` — phát hiện từ bị che dấu `*` + từ cấm từ DB.
- `find_banned_words` — đối chiếu bảng `banned_words`.
- `find_stuck_words` — từ dính / quá dài.
- `find_numbering_lines` — dòng đánh số (12 pattern số/La Mã) để loại bỏ.
- `check_text_quality` — chấm điểm 0–100 (chuẩn ~9500 ký tự/chương).

**b) `vietnamese_word_splitter.py`** — tách từ tiếng Việt bị dính bằng từ điển + **quy hoạch động (DP)**.

**c) AI grammar (Gemini)** — `gemini_service.py`: `check_grammar` trả JSON danh sách lỗi, `improve_text` tối ưu văn bản cho TTS.

**d) Spellcheck LLM (dùng trong batch)** — `openai_spellcheck.py` (gpt-4o-mini) và `ollama_spellcheck.py` (local, structured output). Chia chunk, dedup theo (sai, đúng).

**Endpoints** (`/api/v1/chapters`): `check-grammar`, `check-grammar-save`, `story/{id}/check-grammar`, `censored-word/{id}/accept`, `create-chapter-zero`, và nhóm AI: `ai-grammar-check`, `ai-improve`.

**Quản lý từ cấm** (`/api/v1/banned-words`): CRUD đầy đủ, có phân trang + search + filter active. UI: trang **Từ kiểm duyệt**.

### 5.3. 🔊 Text-to-Speech (VBEE)

Service `tts_processor.py` (`VbeeTTSProcessor`) tích hợp **VBEE Official API**.

- Cơ chế **indirect**: gửi request → nhận `request_id` → **poll** trạng thái (tối đa 60 lần × 5s) → tải link audio.
- `process_chapter` — TTS từng chương, lưu `storage/audio/<story>/chapter_N.mp3`.
- `process_story` — chạy song song có kiểm soát (`Semaphore(2)` + delay 2s tránh rate limit).
- `process_merged_content` — TTS **một lần** cho toàn bộ `merged_content` → 1 file duy nhất (chế độ chính hiện tại).
- 14 giọng seed sẵn (7 nữ + 7 nam, giọng Bắc/Nam/Trung).

**Endpoints** (`/api/v1/tts`): `start`, `prepare`, `start-background`, `start-merged`, `retry-chapter/{id}`, `audio-status/{story_id}`, `merged-status/{story_id}`, `voices`.

### 5.4. 🎵 Ghép Audio (Merger)

Service `audio_merger.py` (`AudioMerger`) — ghép nhiều file bằng **FFmpeg**:
- `_merge_simple` — concat demuxer (nhanh).
- `_merge_with_crossfade` — filter `acrossfade` (chuyển mượt).
- Sắp xếp tự nhiên theo `chapter_number`, lưu `MergedAudio`.

**Endpoints** (`/api/v1/audio`): `POST /merge/start`, `GET /merge/{task_id}/status`.

### 5.5. 🎬 Render Video (phức tạp nhất)

Service `video_processor.py` (`VideoProcessor`, ~2400 dòng) dựng video từ clip nền + audio bằng FFmpeg. Tự dò **NVENC (h264_nvenc)** để tăng tốc GPU, fallback libx264.

**Pipeline dựng video** (`_run_merge_pipeline`):
```
speed audio → ghép clip nền (concat, batch 50, xfade random) → overlay banner
  → merge audio+video (-shortest) → chuỗi hậu kỳ:
     overlay → visualizer → watermark → stickers → subtitle → text watermark → fade → strip metadata
```

**Nhóm tính năng cấu hình** (schema `VideoProcessRequest` ~90 trường):

| Nhóm | Chi tiết |
|------|----------|
| **Nguồn** | thư mục clip nền, file audio, ảnh/video banner |
| **Chuyển cảnh** | ~25 hiệu ứng (fade, dissolve, wipe, slide, circleopen, zoomin, crossfade...), duration, random mỗi junction |
| **Watermark ảnh** | vị trí, kích thước, **hình mask** (circle/rounded/star/sun — `shape_masks.py` + Pillow), opacity |
| **Watermark chữ** | font, size, màu, góc xoay, opacity, vị trí |
| **Phụ đề** | SRT → ASS (`subtitle_renderer.py`), animation (none/fade/pop/slide_up/typewriter), font/màu/viền/shadow/canh lề |
| **Sticker** | overlay ảnh/GIF động, kéo thả, bật/tắt theo khung thời gian |
| **Audio visualizer** | bars / waveform / spectrum / cqt, gradient 2 màu, mirror, vị trí |
| **Chống trùng lặp (`ad_*`)** | lật ngẫu nhiên, zoom, chỉnh màu (saturation/contrast/gamma/hue), jitter tốc độ clip, strip metadata |
| **Font** | 8 font (Be Vietnam Pro, Montserrat, Oswald, Inter, Anton, Noto Sans, Quicksand + DejaVu), tự tải .ttf |

**Tiến trình:** đọc `-progress pipe:1` của FFmpeg, cập nhật % vào bảng `tasks`. Có **retry tối đa 2 lần**, lưu `VideoOutput`.

**Preview:** `render_preview` dựng nhanh 60s qua cùng pipeline (có cache theo hash config; bỏ cache khi bật randomness).

**Endpoints** (`/api/v1/video`, file ~1000 dòng): `start`, `{task_id}/status`, `result/{story_id}`, file browser server-side (`browse`, `browse-files`, `browse-images`), serve preview (`preview-image/video/audio`), `fonts`, upload/đọc SRT, `sample-clip`, `folder-clips`, render preview async, thư viện + upload sticker (có chống path traversal).

### 5.6. ✂️ Cắt Video (module độc lập)

Tính năng riêng ở trang `/video-trimmer`, **không đụng DB** (file ở `storage/trim_temp/{file_id}/`, job tracking in-memory). Xử lý **server-side bằng native FFmpeg** (quyết định trong `IMPLEMENTATION_PLAN.md`, đảo ngược bản spec ban đầu định dùng FFmpeg.wasm client-side).

- **Chiến lược quality-first:** không có filter & `exact_frame=OFF` → **stream copy** (`-c copy`, nhanh); có filter hoặc exact → **re-encode** libx264 (CRF theo độ phân giải). Stream copy fail → fallback re-encode audio AAC.
- Đa đoạn (multi-segment concat), đổi tỉ lệ khung (crop/letterbox/blur), fade, mute, speed (atempo), watermark drawtext xoay.
- `generate_waveform` — vẽ waveform từ PCM.

**Endpoints** (`/api/v1/trim`): `POST /upload`, `GET /waveform/{id}`, `POST /process`, `GET /progress/{job_id}` (**SSE**), `GET /download/{job_id}`, `POST /clear/{id}`.

### 5.7. 📤 Xuất tài liệu

Service `word_exporter.py` (`WordExporter`) qua `python-docx`:
- `.docx` — mỗi chương một trang (page break), tách "Chương 0" làm intro, có title page + style riêng.
- `.txt` — xuất text thuần.

**Endpoints** (`/api/v1/export`): `GET /{story_id}/word`, `GET /{story_id}/txt`.

### 5.8. 🗂️ Prompts, Settings, Presets

- **Prompts** (`/api/v1/prompts`) — CRUD thư viện prompt AI (title/content/category), có categories. UI: trang **Prompts**.
- **Settings** (`/api/v1/settings`) — key-value, lưu credential runtime (VBEE_APP_ID, VBEE_BEARER_TOKEN, GEMINI_API_KEY). UI: trang **Cài đặt**.
- **Video Presets** (`/api/v1/video-presets`) — lưu/tải toàn bộ cấu hình video (trừ đường dẫn tuyệt đối).

---

## 6. Bản đồ giao diện (Frontend)

| Route | Trang | Chức năng |
|-------|-------|-----------|
| `/` | HomePage | Giới thiệu; nút "Tạo Project Mới" → tạo story draft → mở Processor |
| `/processor/:storyId` | **ProcessorPage** | Wizard 8 bước (God component ~5900 dòng) — trung tâm nghiệp vụ |
| `/history` | HistoryPage | Danh sách project (phân trang, search, favorite), mở/xóa/export |
| `/settings` | SettingsPage | Cấu hình VBEE + Gemini credentials |
| `/banned-words` | BannedWordsPage | CRUD từ kiểm duyệt |
| `/prompts` | PromptsPage | CRUD prompt AI |
| `/video-trimmer` | VideoTrimmerPage | Công cụ cắt video độc lập (SSE) |

**Components tái sử dụng:** `layout/` (header + sidebar), `trim/` (UploadZone, VideoPreview, Waveform, Timeline, TimeInput, ExportSettings, WatermarkEditor), `subtitle/` (SubtitlePanel, SubtitleOverlay), `sticker/` (StickerPanel, StickerOverlay).

---

## 7. Cách chạy dự án

### 7.1. Yêu cầu
- Docker & Docker Compose (cho MySQL)
- Python 3.10+
- Node.js 18+
- **FFmpeg** (bắt buộc cho audio/video)

### 7.2. Chạy Web App

**Windows:**
```bat
start.bat   :: khởi động MySQL (Docker) → Backend (uvicorn) → Frontend (Vite)
stop.bat    :: dừng tất cả
```

**Linux/macOS:**
```bash
./run.sh    # backend & frontend chạy nền, log ở logs/, PID ở *.pid
./stop.sh   # dừng theo pidfile/port + docker compose down
```

Sau khi chạy:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000 — Docs: `/docs` — Health: `/health`

### 7.3. Chạy Batch CLI (không cần server)

```bash
python auto_run.py <url1> <url2> ...  --start 1 --end 10 [--no-video] [--stop-after <stage>]
```

`auto_run.py` tự khởi động MySQL, import trực tiếp services và chạy trọn pipeline: tải chương → thay từ cấm → spellcheck (OpenAI) → build merged content → TTS VBEE (có **fallback 2 bộ credential**) → ghép audio → render video (tùy chọn). Kết quả lưu ở `backend/storage/audio/<Title>/` kèm báo cáo `auto_run_<ts>.txt`.

---

## 8. Cấu hình (`.env`)

Backend (`backend/.env`):

| Biến | Ý nghĩa |
|------|---------|
| `DATABASE_URL` | `mysql+pymysql://truyenfull_user:...@localhost:3307/truyenfull_db` |
| `STORAGE_PATH` | `./storage` |
| `VBEE_APP_ID`, `VBEE_BEARER_TOKEN` | Credential VBEE TTS |
| `GEMINI_API_KEY` | Kiểm tra ngữ pháp AI |
| `OPENAI_API_KEY` | Spellcheck (batch) |
| `API_HOST`, `API_PORT`, `DEBUG` | Server |
| `CORS_ORIGINS` | Danh sách origin cho phép (CSV) |

Frontend (`frontend/.env`): `VITE_API_URL=http://localhost:8000`.

---

## 9. ⚠️ Lưu ý bảo mật (quan trọng)

Trong quá trình khảo sát phát hiện **secret thật đang bị phơi bày** trong mã nguồn:

1. `backend/.env` chứa `OPENAI_API_KEY` (dạng `sk-...` thật), `VBEE_BEARER_TOKEN` (JWT), `VBEE_APP_ID` — **không được che**.
2. `auto_run.py` **hardcode lặp lại 2 bộ credential VBEE** ngay trong file.
3. Mật khẩu DB (`root123`, `truyenfull_pass`) hardcode trong `docker-compose.yml`.

**Khuyến nghị:**
- **Rotate ngay** `OPENAI_API_KEY` và VBEE token (coi như đã lộ).
- Đưa secret ra biến môi trường / secret manager, không hardcode trong `auto_run.py`.
- Thêm `.env` vào `.gitignore` trước khi biến dự án thành git repo (hiện chưa phải git repo → chưa có bảo vệ).

---

## 10. Ghi chú kỹ thuật & điểm cần biết

- **Không có message queue** (Celery/Redis) — Redis đã được để sẵn comment trong `docker-compose.yml` cho tương lai. Tiến trình theo dõi qua bảng `tasks` + registry in-memory → **không bền vững khi restart backend**.
- **`init_db()` bị comment** trong `main.py` — bảng **không tự tạo** lúc chạy; phụ thuộc hoàn toàn vào init script của Docker. Migration (`current_step`, `prompts`) phải chạy tay.
- **ProcessorPage là "God component"** ~5900 dòng gộp toàn bộ 8 bước + nhiều dialog → khó bảo trì; ứng viên số 1 để refactor tách nhỏ.
- Một vài service (`vietnamese_word_splitter.py`, `openai_spellcheck.py`, `ollama_spellcheck.py`) hiện **chưa được router web gọi trực tiếp** — chủ yếu phục vụ `auto_run.py` hoặc là tiện ích dự phòng.
- Các endpoint serve/upload file đều có **kiểm tra path traversal** và giới hạn kích thước (SRT ≤ 5MB, upload video ≤ 2GB).

---

## 11. Tuần tự chi tiết từng bước xử lý (Sequence)

Mục này mô tả **thứ tự thực thi cụ thể** của từng pipeline: ai gọi ai, dữ liệu chuyển trạng thái ra sao, cột DB nào được cập nhật. Các sơ đồ dùng cú pháp Mermaid (GitHub render được).

**Quy ước diễn viên:** `FE` = Frontend · `API` = router FastAPI · `WK` = worker (`app/workers`) · `SV` = service · `DB` = MySQL · `EXT` = dịch vụ ngoài (VBEE/Gemini/OpenAI) · `FF` = FFmpeg.

---

### 11.0. Toàn cảnh end-to-end (một truyện đi hết 8 bước)

```mermaid
sequenceDiagram
    actor User
    participant FE as Frontend
    participant API as Backend API
    participant DB as MySQL
    participant EXT as VBEE/Gemini
    participant FF as FFmpeg

    User->>FE: Tạo project mới
    FE->>API: POST /stories/create-process
    API->>DB: INSERT story (status=draft, current_step=1)
    User->>FE: Nhập URL + phạm vi chương → Download
    FE->>API: POST /download/start
    API->>EXT: scrape các nguồn truyện
    API->>DB: INSERT chapters, story.current_step=3
    User->>FE: Sửa/kiểm duyệt (Edit) + Grammar
    FE->>API: check-grammar / merged-content
    API->>EXT: (tùy chọn) Gemini AI check
    User->>FE: Chọn giọng → Chạy TTS
    FE->>API: POST /tts/start-merged
    API->>EXT: VBEE TTS (indirect + poll)
    API->>DB: merged_audio, story.current_step=6
    User->>FE: Cấu hình + Render video
    FE->>API: POST /video/start
    API->>FF: dựng video (concat→overlay→...)
    API->>DB: video_outputs, story.current_step=7
    User->>FE: Tải audio/video (Complete)
```

Trạng thái `story.current_step` tăng dần: **1** (tạo) → **3** (đã tải) → **4** (sẵn sàng TTS) → **6** (TTS xong) → **7** (hoàn tất). Frontend chỉ cho nhảy tới bước ≤ `current_step`.

---

### 11.1. Tải truyện (Download)

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant API as download.py
    participant WK as download_worker
    participant SV as StoryDownloader
    participant DB as MySQL

    FE->>API: POST /download/start {story_id, url, start, end}
    API->>DB: INSERT task(type=download, status=queued)
    API->>WK: await download_chapters_task()
    WK->>DB: task.status=processing
    loop mỗi chương (Semaphore=3, song song)
        WK->>SV: download_chapter(n)
        SV->>SV: nhận diện domain → chọn CSS/JSON
        SV->>SV: fetch + gỡ span "fake" + đọc CSS ::before
        SV-->>WK: {title, content, char_count}
        WK->>DB: INSERT chapter, task.completed_items++
    end
    WK->>DB: story.status=downloaded, current_step=3
    API-->>FE: task_id
    FE->>API: GET /download/{task_id}/status (poll)
```

**Các bước:**
1. FE gọi `POST /download/start`; API tạo `task` (queued) và **await** `download_chapters_task` (đồng bộ trong request).
2. Worker mở session riêng, đặt `task.status=processing`.
3. `StoryDownloader.__init__` phân tích domain → chọn selector (hoặc chế độ JSON API cho daotruyen.me).
4. Tải song song tối đa **3 chương/lần** (`asyncio.Semaphore(3)`); mỗi chương gỡ text giả, thử fallback URL pattern.
5. Mỗi chương thành công → `INSERT chapters` + tăng `task.completed_items`.
6. Xong toàn bộ → `story.status=downloaded`, `current_step=3`.
7. FE **poll** `GET /download/{task_id}/status` để cập nhật tiến trình.

---

### 11.2. Kiểm tra & sửa văn bản (Edit + Grammar)

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant API as chapters.py
    participant TC as TextChecker (regex)
    participant AI as GeminiService
    participant DB as MySQL

    FE->>API: POST /chapters/{id}/check-grammar-save
    API->>TC: find_censored_words + find_banned_words + find_stuck_words
    TC->>DB: đối chiếu bảng banned_words
    TC-->>API: danh sách lỗi + suggested_replacement
    API->>DB: INSERT censored_words, chapter.has_censored_words
    FE->>API: POST /chapters/censored-word/{id}/accept
    API->>DB: thay từ trong content, censored_word.fixed=true
    opt Kiểm tra AI
        FE->>API: POST /chapters/{id}/ai-grammar-check
        API->>AI: check_grammar(content) → JSON lỗi
        AI-->>API: [{wrong, correct, reason}]
    end
    FE->>API: PUT /stories/{id}/merged-content (lưu bản gộp)
```

**Các bước:**
1. **Regex layer** (`TextChecker`): quét từ bị che (`*`), từ cấm (đối chiếu DB `banned_words`), từ dính, dòng đánh số → lưu vào `censored_words` với `word_type` và `suggested_replacement`.
2. Người dùng **Accept** từng gợi ý → API thay chuỗi trong `chapter.content`, đánh dấu `fixed=true`.
3. **AI layer** (tùy chọn): gọi Gemini `check_grammar` (trả JSON) hoặc `ai-improve` để tối ưu văn bản cho TTS.
4. Cuối bước 4, các chương được gộp thành `stories.merged_content` (nguồn dữ liệu cho TTS chế độ merged).

---

### 11.3. TTS chế độ merged (chính)

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant API as tts.py
    participant BG as BackgroundTasks
    participant SV as VbeeTTSProcessor
    participant EXT as VBEE API
    participant DB as MySQL

    FE->>API: POST /tts/start-merged {story_id, voice, speed}
    API->>DB: task(type=tts), MergedAudio(status=processing)
    API->>BG: process_merged_tts_task() (chạy nền)
    API-->>FE: task_id (trả ngay)
    BG->>SV: process_merged_content(merged_content)
    SV->>EXT: POST /tts (response_type=indirect) → request_id
    loop poll tối đa 60 lần × 5s
        SV->>EXT: GET status(request_id)
        EXT-->>SV: processing / success + audio_link
    end
    SV->>EXT: download audio → storage/audio/<story>/merged_audio.mp3
    SV->>DB: MergedAudio(status=success), story.current_step=6
    FE->>API: GET /tts/merged-status/{story_id} (poll)
```

**Các bước:**
1. FE gọi `/tts/start-merged`; API tạo `task` + record `MergedAudio(processing)` rồi đẩy vào **BackgroundTasks** (trả `task_id` ngay, không chặn request).
2. Worker gọi VBEE theo cơ chế **indirect**: gửi text → nhận `request_id`.
3. **Poll** trạng thái VBEE tối đa 60 lần × 5s cho tới khi `success`.
4. Tải file audio về `storage/audio/<story>/merged_audio.mp3`.
5. Cập nhật `MergedAudio(success)` + `story.current_step=6`.
6. FE **poll** `/tts/merged-status/{story_id}`.

> Chế độ **theo từng chương** (`/tts/prepare` → `/tts/start-background`): tạo `audio_files(idle)` cho mỗi chương, TTS song song `Semaphore(2)` + delay 2s tránh rate-limit; lỗi chương nào thì `retry-chapter/{id}`.

---

### 11.4. Ghép Audio (Merge)

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant API as audio.py
    participant WK as merge_worker
    participant SV as AudioMerger
    participant FF as FFmpeg
    participant DB as MySQL

    FE->>API: POST /audio/merge/start {story_id}
    API->>DB: lấy audio_files(status=success) theo chapter_number
    API->>WK: merge_audio_task() (await)
    WK->>SV: merge_story_audio()
    alt crossfade
        SV->>FF: filter acrossfade nối từng cặp
    else nối nhanh
        SV->>FF: concat demuxer (-f concat)
    end
    FF-->>SV: merged.mp3
    SV->>DB: INSERT merged_audio, story.current_step=7
    API-->>FE: task_id → poll /merge/{task_id}/status
```

**Các bước:** lấy các `audio_files(success)` sắp theo `chapter_number` (natural sort) → chọn `_merge_simple` (concat demuxer, nhanh) hoặc `_merge_with_crossfade` (mượt) → lưu `merged_audio`. (Ở chế độ merged-TTS, bước này thường đã có sẵn 1 file nên có thể bỏ qua.)

---

### 11.5. Render Video (phức tạp nhất)

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant API as video.py
    participant TH as Thread daemon
    participant SV as VideoProcessor
    participant FF as FFmpeg
    participant DB as MySQL

    FE->>API: POST /video/start {audio, folder, ~90 config}
    API->>API: validate audio + folder
    API->>DB: INSERT task(type=video)
    API->>TH: run_video_task() (thread + event loop mới)
    API-->>FE: task_id (trả ngay)
    TH->>SV: process_story_video()
    Note over SV,FF: _run_merge_pipeline
    SV->>FF: 1) speed_up_audio (atempo)
    SV->>FF: 2) concat clip nền (batch 50, xfade random)
    SV->>FF: 3) overlay banner
    SV->>FF: 4) merge audio+video (-shortest)
    loop hậu kỳ (mỗi hiệu ứng 1 pass)
        SV->>FF: overlay→visualizer→watermark→stickers→subtitle→text→fade→strip_metadata
        FF-->>SV: -progress pipe:1 → task.progress
    end
    SV->>DB: INSERT video_outputs(success)
    Note over SV: retry tối đa 2 lần nếu fail
    FE->>API: GET /video/{task_id}/status (poll)
```

**Các bước:**
1. API validate audio + thư mục clip, tạo `task`, chạy `run_video_task` trong **thread daemon** riêng (tạo event loop mới) → trả `task_id` ngay.
2. `VideoProcessor` dò **NVENC** (test encode 1 frame) → chọn encoder GPU/CPU.
3. **Pipeline `_run_merge_pipeline`** theo đúng thứ tự: tăng tốc audio (1.07×) → ghép clip nền (batch 50 tránh giới hạn CLI, xfade ngẫu nhiên mỗi mối nối) → overlay banner → merge audio+video (`-shortest`).
4. **Chuỗi hậu kỳ**, mỗi hiệu ứng là 1 pass FFmpeg, theo thứ tự cố định: `overlay → visualizer → watermark → stickers → subtitle → text_watermark → fade → strip_metadata`.
5. Tiến trình đọc từ `-progress pipe:1` của FFmpeg → cập nhật `task.progress` (phân bổ 90–99% cho hậu kỳ).
6. Thành công → `INSERT video_outputs(success)`, `story.current_step=7`. Lỗi → **retry tối đa 2 lần**.
7. FE **poll** `/video/{task_id}/status`; xong thì lấy `/video/result/{story_id}`.

> **Preview** dùng cùng pipeline nhưng chỉ 60s: `POST /render-preview` (chạy thread, cache theo hash config — bỏ cache khi bật randomness) → poll `/preview-status` → lấy `/preview-file`.

---

### 11.6. Cắt video độc lập (Trim — dùng SSE)

```mermaid
sequenceDiagram
    participant FE as VideoTrimmerPage
    participant API as trim.py
    participant SV as video_trimmer
    participant FF as FFmpeg

    FE->>API: POST /trim/upload (multipart, chunk 1MB, ≤2GB)
    API->>SV: probe metadata → trim_temp/{file_id}/
    FE->>API: GET /trim/waveform/{file_id}
    FE->>API: POST /trim/process {segments, quality, watermark...}
    API->>API: tạo job_id (in-memory _JobState)
    API-->>FE: job_id
    par render nền
        API->>SV: trim() trong executor
        SV->>SV: needs_reencode? copy : re-encode
        alt không filter & exact=OFF
            SV->>FF: -c copy (stream copy, nhanh)
        else có filter/exact
            SV->>FF: re-encode libx264 (+ fallback AAC)
        end
    and stream tiến trình
        FE->>API: GET /trim/progress/{job_id} (SSE)
        API-->>FE: event %/status liên tục
    end
    FE->>API: GET /trim/download/{job_id}
    FE->>API: POST /trim/clear/{file_id}
```

**Điểm khác biệt:** module này **không đụng DB**, job tracking bằng dict in-memory, và dùng **SSE (`EventSource`)** để stream tiến trình thay vì poll như các bước khác. Chiến lược quality-first: ưu tiên `-c copy` (stream copy) khi không có filter, chỉ re-encode khi bắt buộc.

---

### 11.7. Batch CLI (`auto_run.py` — chạy trọn gói không cần server)

```mermaid
sequenceDiagram
    actor User
    participant CLI as auto_run.py
    participant DK as Docker
    participant SV as Services (import trực tiếp)
    participant EXT as OpenAI / VBEE
    participant FS as storage/audio/<Title>

    User->>CLI: python auto_run.py <url...> --start 1 --end 10
    CLI->>DK: ensure_mysql_running() (tự docker compose up)
    loop mỗi URL
        CLI->>SV: tải chương (StoryDownloader)
        CLI->>SV: auto_replace_banned_words()
        CLI->>EXT: auto_spellcheck_merged() (OpenAI)
        CLI->>SV: build merged_content
        CLI->>EXT: TTS VBEE (_tts_with_fallback: thử 2 bộ credential)
        CLI->>SV: ghép audio (AudioMerger)
        opt ENABLE_VIDEO_STEP
            CLI->>SV: render video (VideoProcessor)
        end
        CLI->>FS: merged_audio.mp3 + story_<ts>.txt + banned_hits_<ts>.txt
    end
    CLI->>FS: write_summary_report() → auto_run_<ts>.txt
```

**Các bước:** tự khởi động MySQL → với mỗi URL: tải chương → thay từ cấm (DB) → spellcheck OpenAI trên bản gộp → build `merged_content` → **TTS VBEE có fallback 2 bộ credential** → ghép audio → render video (tùy chọn) → xuất file + báo cáo tổng hợp. Không qua FastAPI/HTTP — import thẳng service.

---

### Bảng tóm tắt cơ chế theo dõi tiến trình

| Pipeline | Kiểu thực thi | Theo dõi | Cập nhật step |
|----------|---------------|----------|---------------|
| Download | await (đồng bộ) | poll `task/status` | → 3 |
| Grammar/Edit | đồng bộ | trả trực tiếp | (giữ) |
| TTS merged | BackgroundTasks | poll `merged-status` | → 6 |
| Merge audio | await (đồng bộ) | poll `merge/status` | → 7 |
| Video render | Thread daemon | poll `video/status` (`-progress`) | → 7 |
| Trim video | asyncio executor | **SSE** stream | (không DB) |
| Batch CLI | tuần tự trong process | log + summary report | (ghi thẳng DB) |
