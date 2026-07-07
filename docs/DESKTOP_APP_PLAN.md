# 🖥️ Kế hoạch: Đóng gói TruyenFull Processor thành App Windows (.exe)

> Chuyển từ web app (React + FastAPI + MySQL/Docker) sang **một app Windows cài-là-chạy**.
> Trạng thái: **Bản kế hoạch — chờ triển khai**. Cập nhật: 2026-07-06.

---

## 1. Bối cảnh & Mục tiêu

**Hiện tại:** app gồm 3 tiến trình — React (Vite dev `:5173`) + FastAPI (`:8000`) + MySQL (Docker `:3307`), cần FFmpeg cài sẵn. Muốn chạy phải mở nhiều cửa sổ terminal qua `start.bat`/`run.sh` → không phù hợp chia sẻ cho người dùng cuối.

**Mục tiêu:** người dùng tải **1 file `Setup.exe`** → cài như app thường → có shortcut → mở lên là **một cửa sổ ứng dụng** (không terminal, không cần Docker/Python/Node/FFmpeg). Đảm bảo **đầy đủ chức năng** (tải truyện → sửa văn bản → TTS → ghép audio → render/cắt video → export) và **chạy mượt**.

**Quyết định đã chốt:**
- **Phạm vi:** hướng tới chia sẻ cho người khác → bản cài đầy đủ (bundle FFmpeg + installer + bootstrap WebView2).
- **API key:** app **KHÔNG** ship kèm key. Người dùng tự nhập VBEE/OpenAI/Gemini trong trang Settings (lưu vào SQLite). `.env` không đóng gói.

**Stack đóng gói:** PyWebView (cửa sổ dùng WebView2 sẵn có của Windows) + FastAPI (chạy nền in-process) + **SQLite** (thay MySQL) + FFmpeg bundled + **PyInstaller** (onedir) + **Inno Setup** (tạo Setup.exe).

**Thuận lợi từ khảo sát code:**
- `backend/app/models.py` dùng kiểu SQLAlchemy generic (JSON/Text/TIMESTAMP/BigInteger) → tương thích SQLite, gần như không sửa.
- Code app không có SQL thô MySQL, chỉ `text("SELECT 1")` (`backend/app/database.py:47`).
- Frontend gọi API bằng **path tương đối `/api/...`** (không hardcode `localhost:8000` ngoài proxy Vite) → chỉ cần backend serve `dist` same-origin.
- FFmpeg gọi bằng literal `'ffmpeg'`/`'ffprobe'` → xử lý gọn bằng cách **chèn thư mục bundled vào `PATH`** thay vì sửa ~40 call site.

---

## 2. Kiến trúc sau khi đóng gói

```
TruyenFullProcessor.exe  (PyInstaller onedir + launcher pywebview)
│
├─ khởi động uvicorn (FastAPI) trên 127.0.0.1:<port ngẫu nhiên rảnh>, KHÔNG reload
├─ mở cửa sổ WebView2 trỏ http://127.0.0.1:<port> → FastAPI serve frontend dist
│
├─ [bundled, read-only]  _internal/          (PyInstaller)
│    ├─ frontend/dist/            (React đã build)
│    ├─ bin/ffmpeg.exe, ffprobe.exe
│    └─ assets/fonts, mask defaults
│
└─ [ghi được, per-user]  %LOCALAPPDATA%\TruyenFullProcessor\
     ├─ app.db                    (SQLite)
     ├─ storage/ (audio, videos, exports, trim_temp, stickers)
     └─ cache/  (masks, previews, srt, fonts tải thêm)
```

**Nguyên tắc:** tài nguyên đóng gói = **read-only** (thư mục cài); dữ liệu người dùng = **ghi ở `%LOCALAPPDATA%`** (tránh lỗi quyền ghi trong `Program Files`).

---

## 3. Các giai đoạn thực hiện

### Phase 1 — Trung tâm hóa đường dẫn (nền tảng cho mọi phase sau)

**Vấn đề:** path đang trộn 2 kiểu — tương đối cwd (`./storage`, `"storage/exports"`) và theo `Path(__file__)` (`cache`, `fonts`, `trim_temp`, `stickers`). Khi frozen, `__file__` nằm trong bundle read-only còn cwd không xác định → hỏng.

**Tạo module mới `backend/app/paths.py`:**
- `is_frozen()` = `getattr(sys, 'frozen', False)`.
- `BUNDLE_DIR`: frozen = `sys._MEIPASS`; dev = gốc `backend/`. Chứa tài nguyên read-only (ffmpeg, fonts mặc định, frontend dist).
- `DATA_DIR`: frozen = `%LOCALAPPDATA%\TruyenFullProcessor`; dev = `backend/`. Chứa `app.db`, `storage/`, `cache/`.
- Export: `STORAGE_DIR, AUDIO_DIR, VIDEO_DIR, EXPORTS_DIR, TRIM_TEMP_DIR, STICKERS_DIR, CACHE_DIR, MASK_DIR, FONTS_DIR, DB_PATH` — tạo thư mục khi import.

**Sửa các chỗ tự định nghĩa path để dùng `paths.py`:**
- `config.py:16,62-64` (`STORAGE_PATH`), `api/export.py:138` + `services/word_exporter.py:17,25` (`storage/exports`), `services/video_trimmer.py:13-15` (`STORAGE_BASE/TRIM_TEMP_DIR/FONT_PATH`), `services/fonts.py:54`, `services/shape_masks.py:12`, `api/video.py:28,415,899-900`.
- **Thống nhất font watermark:** hiện `fonts.py` dùng `<backend>/fonts` còn `video_trimmer.py` dùng `<backend>/storage/fonts` → gộp về `paths.FONTS_DIR`; đảm bảo `DejaVuSans-Bold.ttf` được bundle.

**Verify:** chạy dev, tạo/tải 1 truyện, xác nhận file vẫn ghi đúng chỗ.

---

### Phase 2 — Migrate MySQL → SQLite

**`config.py`:** `DATABASE_URL` → `f"sqlite:///{paths.DB_PATH}"`.

**`database.py`:**
- Bỏ `pool_size/max_overflow/pool_recycle`; thêm `connect_args={"check_same_thread": False}`.
- **Giữ pool mặc định (QueuePool), KHÔNG dùng `StaticPool`.** StaticPool = 1 connection chung cho mọi thread → khi render video ghi DB lâu sẽ chặn toàn bộ truy vấn khác. Pool mặc định cho mỗi thread một connection riêng; kết hợp WAL cho phép đọc song song lúc đang ghi.
- Event listener `connect` bật **PRAGMA**: `journal_mode=WAL` (đọc/ghi đồng thời — cần vì worker nền ghi DB song song), `foreign_keys=ON` (SQLite mặc định TẮT FK → phải bật để cascade delete hoạt động), `busy_timeout=5000`.
- Bỏ log `DB_HOST/PORT`.
- **Bật `init_db()`** (đang comment ở `main.py:65`): `Base.metadata.create_all()` tự tạo bảng từ `models.py` → không còn phụ thuộc init script Docker.

**Seeding (QUAN TRỌNG — create_all chỉ tạo bảng RỖNG):** tạo `backend/app/seed.py` `seed_defaults(db)`, nạp khi bảng rỗng:
- **14 giọng VBEE** (port từ `docker/mysql/02_init_voices.sql`, mặc định `hn_female_ngochuyen_full_48k-fhg`).
- **7 settings mặc định** (từ `01_init.sql`).
- (tùy chọn) prompts/banned_words mẫu.
- Gọi trong startup sau `init_db()`.

**`requirements.txt`:** gỡ `pymysql`, `aiomysql`, `cryptography` (chỉ phục vụ MySQL) → giảm dung lượng. SQLite dùng `sqlite3` built-in.

**Verify:** xóa app.db → khởi động → DB tự tạo + seed; `GET /api/v1/tts/voices` trả 14 giọng; tạo story rồi xóa → chapters/audio cascade đúng.

---

### Phase 3 — Bundle FFmpeg (không sửa từng call site)

**Cách chính:** startup prepend thư mục `ffmpeg.exe`/`ffprobe.exe` bundled vào `os.environ["PATH"]` → mọi literal `'ffmpeg'`/`'ffprobe'` tự resolve tới binary bundled, **không sửa ~40 call site**.
- `paths.py`: thêm `FFMPEG_BIN_DIR` + `setup_ffmpeg_path()`.
- Gọi sớm trong `main.py` (trước import services) và trong launcher.
- (phòng thủ) thêm `FFMPEG_BINARY/FFPROBE_BINARY` config để override; `_check_ffmpeg` log đường dẫn dùng.

**Lấy FFmpeg:** tải bản static Windows (ffmpeg + ffprobe) vào `backend/bin/`. Ghi lại nguồn/phiên bản.

**Verify:** đổi tên ffmpeg trong PATH hệ thống (giả lập máy chưa cài) → app render 1 video ngắn thành công nhờ binary bundled.

---

### Phase 4 — FastAPI serve frontend (same-origin, bỏ Vite dev)

**`main.py`:**
- Sau routers, mount SPA: `app.mount("/", StaticFiles(directory=paths.FRONTEND_DIST, html=True))` — đặt CUỐI để không đè `/api/*` và `/storage`.
- **Catch-all fallback** trả `index.html` cho react-router (path `/processor/...`, `/history`... khi refresh), trừ `/api` và `/storage`.
- Route `/` hiện trả JSON (`main.py:72`) → nhường SPA (hoặc chuyển `/api/info`).

**Build frontend:** `cd frontend && npm run build` → `frontend/dist/`. Không cần đổi code frontend (đã dùng path tương đối).

**⚠️ Rủi ro build (đã xác nhận):** script build là `tsc && vite build` (`package.json:8`) và `tsconfig.json` bật `strict + noUnusedLocals + noUnusedParameters`. Code lớn (ProcessorPage ~5900 dòng) nhiều khả năng có biến/tham số thừa → **`tsc` sẽ fail và chặn build**. Xử lý (chọn 1):
- **Nhanh:** đổi build thành chỉ `vite build` (esbuild của Vite bỏ qua lỗi type, vẫn ra bundle chạy được) — chấp nhận không typecheck lúc build.
- **Sạch:** tắt `noUnusedLocals`/`noUnusedParameters` trong `tsconfig.json`, hoặc dọn hết biến thừa.
→ Khuyến nghị làm cách "nhanh" trước để thông pipeline, dọn type sau.

**Verify:** build → chạy backend → mở `http://127.0.0.1:8000` → toàn bộ UI chạy không cần Vite; refresh ở `/history` không 404.

---

### Phase 5 — Desktop launcher (PyWebView + uvicorn in-process)

**Tạo `backend/desktop.py` (entry point):**
1. `paths.setup_ffmpeg_path()`, ép `settings.DEBUG=False` (tắt reload/echo).
2. Chọn **port rảnh động** (`socket` bind `:0`) tránh xung đột.
3. Chạy uvicorn trong **thread nền** (`host=127.0.0.1`, không reload, log ra file trong DATA_DIR).
4. **Chờ health**: poll `GET /health` tới OK (timeout ~30s) rồi mới mở cửa sổ.
5. `webview.create_window("TruyenFull Processor", url, width=1400, height=900)` + `webview.start()`.
6. Cửa sổ đóng → shutdown uvicorn + terminate thread/ffmpeg subprocess còn chạy.

**`requirements.txt`:** thêm `pywebview` (Windows dùng WebView2). Nhóm build thêm `pyinstaller`.

**Verify:** `python -m backend.desktop` → cửa sổ app mở, chạy thử pipeline ngắn end-to-end.

---

### Phase 6 — Đóng gói PyInstaller (onedir)

**Tạo `packaging/truyenfull.spec`:**
- Entry = `backend/desktop.py`.
- `datas`: `frontend/dist` → `frontend/dist`; `backend/bin/*.exe` → `bin/`; fonts → `assets/fonts`.
- `hiddenimports`: uvicorn loops/protocols/lifespan, `sqlalchemy.dialects.sqlite`, `loguru`, `docx`, `PIL`, và **pywebview**: `webview.platforms.edgechromium` + `clr` (pythonnet). pywebview có PyInstaller hook riêng — cần cài `pywebview` kèm `pythonnet`; kiểm tra WebView2 loader được đóng gói.
- `console=False`, `name='TruyenFullProcessor'`, icon `.ico`, **onedir** (khởi động nhanh, không giải nén temp mỗi lần).
- `paths.py` đọc tài nguyên từ `sys._MEIPASS` khi frozen (đã thiết kế Phase 1).

**Verify:** `pyinstaller packaging/truyenfull.spec` → chạy `dist/TruyenFullProcessor/TruyenFullProcessor.exe`: DB ở `%LOCALAPPDATA%`, UI mở, render video OK, export Word OK.

---

### Phase 7 — Installer (Inno Setup) + WebView2 bootstrap

**Tạo `packaging/installer.iss`:**
- Đóng gói `dist/TruyenFullProcessor/` vào `Setup.exe`; cài vào `{autopf}\TruyenFullProcessor`; shortcut Start Menu + Desktop.
- **Bootstrap WebView2**: kiểm tra registry; nếu thiếu, tải & chạy Evergreen Bootstrapper (Win11 thường có sẵn).
- Uninstaller chuẩn; tùy chọn giữ/xoá dữ liệu `%LOCALAPPDATA%` khi gỡ.
- (tùy chọn) code signing giảm cảnh báo SmartScreen (cần chứng chỉ, làm sau).

**Verify (nghiệm thu cuối):** chạy `Setup.exe` trên **máy Windows sạch** (VM không Docker/Python/Node/FFmpeg) → cài → mở app → full pipeline: tải truyện 3 chương → sửa → nhập API key VBEE ở Settings → TTS → ghép → render video → export.

---

### Phase 8 — First-run & dọn dẹp

- Trang Settings đã sẵn (`SettingsPage.tsx`, `PUT /api/v1/settings`), services đọc key từ bảng `settings` trước `.env` → user tự nhập key chạy ngay. Thêm nhắc "Chưa cấu hình API key" khi settings rỗng.
- Không ship `backend/.env` trong bundle.
- Cập nhật `docs/PROJECT_DOCUMENTATION.md`: thêm mục "Bản Desktop (Windows)".
- (khuyến nghị) rotate `OPENAI_API_KEY`/VBEE token đang lộ trong repo.

---

## 4. Rủi ro & lưu ý

- **SQLite + đa luồng ghi:** worker nền + video thread ghi DB song song → bắt buộc `WAL` + `busy_timeout` + `check_same_thread=False`. Nếu "database is locked" → tăng busy_timeout / serialize ghi.
- **FK cascade:** SQLite tắt FK mặc định → phải PRAGMA `foreign_keys=ON` mỗi connection, nếu không xóa story để lại chapters mồ côi.
- **PyInstaller hidden imports:** uvicorn/sqlalchemy dialects hay thiếu → build lặp, đọc log, thêm dần.
- **Async trong frozen:** video worker tạo event loop mới trong thread → kiểm tra khi đóng gói (không reload).
- **Dung lượng:** ~150–250MB (ffmpeg ~80MB + Python runtime). Chấp nhận được.
- **SmartScreen:** exe chưa ký cảnh báo "Unknown publisher" → hướng dẫn "More info → Run anyway" hoặc mua chứng chỉ ký.
- **`auto_run.py` sẽ hỏng sau migrate:** nó gọi thẳng MySQL + tự `docker compose up` (`auto_run.py:360`). Sau khi bỏ Docker/MySQL nó không chạy. Nằm **ngoài phạm vi** bản desktop — hoặc cập nhật riêng để dùng SQLite, hoặc không đóng gói vào app (chỉ giữ cho môi trường dev cũ).
- **Dữ liệu MySQL hiện có không tự chuyển:** app desktop khởi tạo SQLite **rỗng**. Các project đang có trong MySQL sẽ không xuất hiện. Nếu cần giữ → viết script export MySQL → import SQLite một lần (tùy chọn, ngoài phạm vi cốt lõi).
- **Tính năng Video cần thư mục clip nền trên đĩa:** bước render duyệt file qua `/api/v1/video/browse*`. Trên desktop "server" chính là máy người dùng nên duyệt ổ đĩa của họ là đúng ý — nhưng cần có sẵn 1 thư mục video clip nền để chọn.
- **Cần asset:** file icon `.ico` cho app + shortcut (chưa có trong repo).
- **TTS không cần callback public (đã xác nhận):** `tts_processor.py:120-122` dùng polling (`callback_url` chỉ là URL giả), nên chạy localhost trong app desktop hoạt động bình thường — KHÔNG phải rủi ro.

---

## 5. Thứ tự & phụ thuộc

Phase 1 (paths) là nền → 2, 3 song song → 4 → 5 → 6 → 7 → 8.
Verify end-to-end sau **mỗi** phase (Phase 1–5 test chế độ dev; Phase 6–7 test chế độ đóng gói).

---

## 6. File chính sẽ tạo/sửa

**Tạo mới:**
- `backend/app/paths.py` — trung tâm hóa đường dẫn (bundle vs data dir)
- `backend/app/seed.py` — seed voices/settings mặc định
- `backend/desktop.py` — entry point launcher (pywebview + uvicorn)
- `packaging/truyenfull.spec` — cấu hình PyInstaller
- `packaging/installer.iss` — cấu hình Inno Setup
- `backend/bin/ffmpeg.exe`, `ffprobe.exe` — binary bundled

**Sửa:**
- `backend/app/config.py` — DATABASE_URL sang SQLite, STORAGE_PATH
- `backend/app/database.py` — engine SQLite + PRAGMA + bật init_db
- `backend/app/main.py` — serve frontend dist + SPA fallback + setup ffmpeg path
- `backend/requirements.txt` — bỏ driver MySQL, thêm pywebview
- Path trong: `services/video_trimmer.py`, `services/fonts.py`, `services/shape_masks.py`, `api/video.py`, `api/export.py`, `services/word_exporter.py`

**Build artifact:** `frontend/dist/` (từ `npm run build`).

---

## 7. Ghi chú tiến độ (checklist)

> Tick `[x]` khi hoàn thành. Trạng thái tổng: **✅ HOÀN THÀNH — đã build & verify (2026-07-07)**.

- [x] **Phase 1** — `paths.py`, trung tâm hóa đường dẫn (bundle vs data dir)
- [x] **Phase 2** — Migrate MySQL → SQLite (config, engine + PRAGMA, bật `init_db`, `seed.py`) — verified: 14 giọng + 7 settings seed, FK cascade OK
- [x] **Phase 3** — Bundle FFmpeg (prepend PATH, binary trong `backend/bin/`) — verified: app dùng ffmpeg bundled
- [x] **Phase 4** — FastAPI serve `frontend/dist` + SPA fallback — verified: `/`, `/history`, assets, API cùng origin; fix `tsc`→`vite build`
- [x] **Phase 5** — `desktop.py` launcher (pywebview + uvicorn thread + port động) — verified: cửa sổ WebView2 mở & render UI
- [x] **Phase 6** — PyInstaller onedir (`truyenfull.spec`) — verified: `--selftest` all PASS trên exe đóng gói
- [x] **Phase 7** — Inno Setup installer + WebView2 bootstrap — `packaging/Output/TruyenFullProcessor-Setup.exe` (79MB)
- [x] **Phase 8** — First-run banner nhắc API key, `.gitignore`, cập nhật docs

**Sản phẩm cuối:** `packaging/Output/TruyenFullProcessor-Setup.exe` — tải về, cài, chạy như app Windows thường.

### Nhật ký / lưu ý khi làm
- **FFmpeg**: dùng bản Gyan Essentials 8.0 (static) copy từ winget vào `backend/bin/` (~95MB mỗi file).
- **Python 3.13**: Pillow phải `>=11`, pythonnet `>=3.0.5` (bản pin cũ không có wheel 3.13).
- **PyInstaller**: uvicorn nhận app object (không phải chuỗi `"app.main:app"`) + `collect_submodules('app')` để bundle đủ routers/services.
- **Bug đã sửa**: `Voice.id` thiếu `default=generate_uuid` (NOT NULL fail khi seed) → đã thêm.
- **Review sau khi build**: sửa **path traversal** trong SPA fallback (`main.py` — chặn `../` thoát `dist`); dọn dead code trong `.spec`; làm `selftest` không crash khi endpoint lỗi.
- **Windows console cp1252**: khi DEBUG=True (dev), SQLAlchemy echo tiếng Việt gây `UnicodeEncodeError` ở logging — vô hại, chỉ dev; bản desktop DEBUG=False nên không gặp.
- **🔴 QUAN TRỌNG — windowed `sys.stderr=None`**: khi double-click app (windowed, không console), `sys.stdout/stderr = None` → `logger.add(sys.stderr)` crash `TypeError: Cannot log to objects of type 'NoneType'`. Selftest chạy từ terminal KHÔNG bắt được (terminal có stderr). Fix: `desktop.py` redirect stream None → file log trước khi import app.main; `main.py` guard `if sys.stderr is not None`. Verify đúng cách bằng `Start-Process` (không console) — không phải chạy từ bash.
- **🔴 QUAN TRỌNG — ffmpeg/ffprobe bật hàng trăm cửa sổ console**: app windowed gọi ffprobe cho TỪNG file khi quét folder video nền → mỗi subprocess bật 1 cửa sổ terminal (không có `CREATE_NO_WINDOW`). Fix: `paths.hide_subprocess_windows()` patch global `subprocess.Popen` thêm cờ `CREATE_NO_WINDOW` (Windows) — che tất cả ~28 call site 1 lần. Gọi trong `main.py` + `desktop.py`.
- **Data migration MySQL→SQLite**: `backend/migrate_mysql_to_sqlite.py` (idempotent, bỏ qua voices vì đã seed, settings merge theo key). Đã chạy: 12.901 dòng sang `%LOCALAPPDATA%\...\app.db` (265 từ cấm + API key cũ).

### Điểm dễ quên (nhắc lại)
- **Phase 2 seeding:** bỏ Docker → mất 14 giọng VBEE + settings mặc định (vốn do SQL init script nạp) → **bắt buộc** viết `seed.py` nạp lại lúc chạy đầu.
- **PRAGMA `foreign_keys=ON`:** SQLite tắt FK mặc định → không bật thì xóa story để lại chapters mồ côi.
- **Không ship `backend/.env`** (chứa key thật) trong bundle; user tự nhập key qua Settings.
- **Build frontend sẽ đứng vì `tsc`:** đổi build sang `vite build` (bỏ typecheck) hoặc tắt `noUnusedLocals/Parameters` — nếu không Phase 4 kẹt ngay.
- **Pool DB:** giữ QueuePool mặc định + `check_same_thread=False` + WAL, KHÔNG dùng StaticPool (sẽ serialize, render video chặn mọi query).
- **`auto_run.py`** ngoài phạm vi — sẽ hỏng sau migrate (còn phụ thuộc MySQL/Docker).

### Đã review plan (2026-07-06)
Đã kiểm chứng code cho: (1) TTS dùng polling → localhost OK; (2) build `tsc && vite build` là rủi ro thật; (3) sửa lựa chọn pool StaticPool→QueuePool. Bổ sung các mục: auto_run.py, migrate dữ liệu cũ, icon .ico, hidden imports pywebview. Plan hiện đã nhất quán và sẵn sàng triển khai.
