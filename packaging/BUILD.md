# 🏗️ Build hướng dẫn — TruyenFull Processor Desktop (.exe)

Quy trình đóng gói web app thành app Windows cài-là-chạy.

## Yêu cầu máy build
- Windows 10/11 x64
- Python 3.13 + venv ở `backend/venv` (đã cài `requirements.lock.txt` — có torch bản cu124 cho AI Voice local)
- Node.js 18+ (để build frontend)
- FFmpeg static (`ffmpeg.exe`, `ffprobe.exe`) đặt sẵn trong `backend/bin/`
- [Inno Setup 6](https://jrsoftware.org/isdl.php) (để tạo Setup.exe) — chỉ cần ở bước cuối

## Các bước

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
backend/venv/Scripts/pyinstaller.exe packaging/truyenfull.spec --noconfirm
# -> dist/TruyenFullProcessor/TruyenFullProcessor.exe  (onedir, ~6-10GB)
```

> **AI Voice local chạy trên cả GPU lẫn CPU.** Máy có GPU NVIDIA → chạy nhanh; máy không có GPU → app **tự động chuyển sang CPU** (`effective_device()` trong `ai_voice_local_processor.py`), vẫn chạy được chỉ chậm hơn (~15–20× so với realtime). Không bắt buộc phải có GPU khi cài.

### 3. Kiểm tra nhanh bản đóng gói (không mở cửa sổ)
```bash
dist/TruyenFullProcessor/TruyenFullProcessor.exe --selftest
# ghi kết quả ra %LOCALAPPDATA%\TruyenFullProcessor\selftest_result.txt
# tất cả dòng phải [PASS] và "SELFTEST OK"
```

### 4. Tạo bộ cài (Setup.exe)
```bash
iscc packaging\installer.iss
# -> packaging/Output/TruyenFullProcessor-Setup.exe
```

## Kiến trúc runtime
- **Tài nguyên đóng gói (read-only)** nằm trong `_internal/`: `frontend/dist`, `bin/ffmpeg.exe`, `bin/ffprobe.exe`, `assets/fonts`.
- **Dữ liệu người dùng (ghi được)** ở `%LOCALAPPDATA%\TruyenFullProcessor\`: `app.db` (SQLite), `storage/`, `cache/`, `logs/`.
- App mở uvicorn (FastAPI) trên `127.0.0.1:<port ngẫu nhiên>` rồi hiển thị bằng cửa sổ WebView2 (pywebview).

## Ghi chú
- Bản build luôn là bản FULL (nhúng cả VBEE + AI Voice local). Người dùng chọn engine nào để dùng ngay trong app.
- AI Voice local chạy CPU khi không có GPU; có thể ép chế độ CPU/GPU qua setting `AIVOICE_LOCAL_USE_CPU` (mặc định auto-detect theo phần cứng).
- `.env` **không** được đóng gói. Người dùng tự nhập API key (VBEE/OpenAI/Gemini) trong trang Settings; key lưu vào SQLite.
- Đổi icon app: đặt `packaging/app.ico` rồi build lại (spec tự nhận).
- Nếu build lỗi thiếu module: thêm vào `hiddenimports` trong `packaging/truyenfull.spec`.
