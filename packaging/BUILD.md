# 🏗️ Build hướng dẫn — AudioStory Desktop (.exe)

Quy trình đóng gói web app thành app Windows cài-là-chạy.

## Yêu cầu máy build
- Windows 10/11 x64
- Python 3.13 + venv ở `backend/venv` (đã cài `requirements.lock.txt` — có torch bản cu124 cho AI Voice local)
- Node.js 18+ (để build frontend)
- FFmpeg static (`ffmpeg.exe`, `ffprobe.exe`) đặt sẵn trong `backend/bin/`
- [Inno Setup 6](https://jrsoftware.org/isdl.php) (để tạo Setup.exe) — chỉ cần ở bước cuối

## Cách nhanh nhất: script tự động

`packaging/build.ps1` chạy tuần tự toàn bộ: build frontend → PyInstaller → self-test → tạo Setup.exe.

```powershell
# Bản phát hành (DB ship kèm CHỈ reference data: từ kiểm duyệt + prompt)
powershell -ExecutionPolicy Bypass -File packaging/build.ps1

# Bản full-dev (ship TOÀN BỘ data test: app.db đầy đủ + storage audio/video)
powershell -ExecutionPolicy Bypass -File packaging/build.ps1 -Mode fulldev

# Chỉ build app trong dist/ (bỏ qua bước tạo Setup.exe)
powershell -ExecutionPolicy Bypass -File packaging/build.ps1 -Fast

# Tạo Setup.exe bằng installer-dev.iss (nén nhanh, cho vòng lặp dev)
powershell -ExecutionPolicy Bypass -File packaging/build.ps1 -DevInstaller
```

> Seed DB được tạo bởi `packaging/make_seed_db.py` (build.ps1 gọi tự động): copy DB nguồn (mặc định `%LOCALAPPDATA%\AudioStory\app.db`) rồi lược bỏ dữ liệu tùy chế độ (product = giữ reference; fulldev = giữ tất cả).

Nếu muốn làm từng bước thủ công, xem bên dưới.

## Các bước thủ công

### 1. Build frontend (React → static)
```bash
cd frontend
npm install          # lần đầu
npm run build        # -> frontend/dist  (dùng vite build, KHÔNG chạy tsc)
```

### 2. Đóng gói app bằng PyInstaller

Chỉ có **một bản build duy nhất** — bản **FULL**, nhúng sẵn cả 2 engine TTS: VBEE (cloud) + AI Voice local (local). Gói nặng ~6–10GB.

```bash
# từ repo root
backend/venv/Scripts/pyinstaller.exe packaging/audiostory.spec --noconfirm
# -> dist/AudioStory/AudioStory.exe  (onedir, ~6-10GB)
```

> **AI Voice local chạy trên cả GPU lẫn CPU.** Máy có GPU NVIDIA → chạy nhanh; máy không có GPU → app **tự động chuyển sang CPU** (`effective_device()` trong `ai_voice_local_processor.py`), vẫn chạy được chỉ chậm hơn (~15–20× so với realtime). Không bắt buộc phải có GPU khi cài.

### 3. Kiểm tra nhanh bản đóng gói (không mở cửa sổ)
```bash
dist/AudioStory/AudioStory.exe --selftest
# ghi kết quả ra %LOCALAPPDATA%\AudioStory\selftest_result.txt
# tất cả dòng phải [PASS] và "SELFTEST OK"
```

### 4. Tạo bộ cài (Setup.exe)
```bash
iscc packaging\installer.iss
# -> packaging/Output/AudioStory-Setup.exe
```

## Build bản Linux (VBEE-only)

Có sẵn spec + script riêng cho Linux (mirror `.github/workflows/build-ubuntu.yml`):

```bash
# Deps hệ thống 1 lần (Ubuntu 22.04/24.04):
sudo apt-get install -y libgirepository1.0-dev libcairo2-dev pkg-config \
  gobject-introspection gir1.2-gtk-3.0 gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0

# Build (dùng packaging/audiostory_linux.spec)
./packaging/build-linux.sh [--skip-frontend]
# -> dist/AudioStory/AudioStory
# -> dist/AudioStory-linux-x86_64.tar.gz
```

Bản Linux là **VBEE-only** (không nhúng AI Voice local).

## Các file trong `packaging/`
- `audiostory.spec` — PyInstaller spec Windows (bản FULL: VBEE + AI Voice local).
- `audiostory_linux.spec` — PyInstaller spec Linux (VBEE-only).
- `installer.iss` — Inno Setup (nén tối đa, bản phát hành).
- `installer-dev.iss` — Inno Setup (nén nhanh, cho vòng lặp dev).
- `build.ps1` — script build tự động Windows (frontend → PyInstaller → selftest → iscc).
- `build-linux.sh` — script build tự động Linux.
- `make_seed_db.py` — tạo `default_seed.db` (seed DB ship kèm bản cài).

## Kiến trúc runtime
- **Tài nguyên đóng gói (read-only)** nằm trong `_internal/`: `frontend/dist`, `bin/ffmpeg.exe`, `bin/ffprobe.exe`, `assets/fonts`.
- **Dữ liệu người dùng (ghi được)** ở `%LOCALAPPDATA%\AudioStory\`: `app.db` (SQLite), `storage/`, `cache/`, `logs/`.
- App mở uvicorn (FastAPI) trên `127.0.0.1:<port ngẫu nhiên>` rồi hiển thị bằng cửa sổ WebView2 (pywebview).

## Ghi chú
- Bản build luôn là bản FULL (nhúng cả VBEE + AI Voice local). Người dùng chọn engine nào để dùng ngay trong app.
- AI Voice local chạy CPU khi không có GPU; có thể ép chế độ CPU/GPU qua setting `AIVOICE_LOCAL_USE_CPU` (mặc định auto-detect theo phần cứng).
- `.env` **không** được đóng gói. Người dùng tự nhập API key (VBEE/OpenAI/Gemini) trong trang Settings; key lưu vào SQLite.
- Đổi icon app: đặt `packaging/app.ico` rồi build lại (spec tự nhận).
- Nếu build lỗi thiếu module: thêm vào `hiddenimports` trong `packaging/audiostory.spec`.
