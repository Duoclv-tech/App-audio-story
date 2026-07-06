# Video Trimmer — Implementation Plan

## 1. Scope & quyết định cuối

**Mục tiêu:** Thêm trang "Cắt video" vào web_app, cho phép upload file video, trim theo giờ:phút:giây, xuất ra MP4.

**Decisions:**
- Xử lý ở **server-side** (native FFmpeg, nhanh hơn wasm, không giới hạn RAM browser).
- **Chỉ xuất MP4** (H.264 + AAC). Bỏ MOV / MKV / WebM / GIF.
- **Không lưu DB** — file upload/output nằm ở `backend/storage/trim_temp/{file_id}/`.
- Trang riêng `/video-trimmer`, thêm menu sidebar (icon Scissors).
- Không có multi-clip.
- Waveform: **backend generate** (dùng ffmpeg resample), frontend vẽ từ JSON array.
- Progress: **SSE** stream từ backend (parse FFmpeg stderr).
- Upload progress: axios `onUploadProgress`.
- **Bỏ nút "Đổi thư mục"** → browser tự lưu vào Downloads.
- Chỉ support Chrome/Edge (đã confirm với user).

---

## 2. Chiến lược FFmpeg (quality-first)

### Logic chọn command

```
Có filter (aspect ratio ≠ Gốc, watermark, fade in/out, mute)?
├── YES → Re-encode
└── NO
    ├── exact_frame = OFF → Stream copy (chấp nhận ±keyframe, hiện cảnh báo UI)
    └── exact_frame = ON  → Re-encode CRF 12 (visually lossless)
```

### Command templates

**Stream copy (case nhanh nhất):**
```bash
ffmpeg -y -ss {start} -i input.ext -t {duration} \
  -c copy -avoid_negative_ts make_zero -movflags +faststart \
  output.mp4
```
→ Nếu fail (thường do audio codec không tương thích MP4, ví dụ Opus), **tự động fallback re-encode audio**:
```bash
ffmpeg -y -ss {start} -i input.ext -t {duration} \
  -c:v copy -c:a aac -b:a 192k \
  -avoid_negative_ts make_zero -movflags +faststart \
  output.mp4
```

**Re-encode (filter hoặc exact frame):**
```bash
ffmpeg -y -ss {start} -i input.ext -t {duration} \
  -vf "{filter_chain}" \
  -c:v libx264 -pix_fmt yuv420p -crf {crf} -preset {preset} \
  -c:a aac -b:a 192k \
  -avoid_negative_ts make_zero -movflags +faststart \
  output.mp4
```

**CRF / preset mapping:**

| Quality UI | CRF | Preset | Ghi chú |
|---|---|---|---|
| Gốc (không nén) + exact_frame ON | 12 | slow | Visually lossless |
| Gốc (không nén) + exact_frame OFF | — | — | Stream copy path |
| Cao · 1080p | 18 | medium | Gần lossless thị giác |
| Trung bình · 720p | 23 | medium | Default balance |
| Thấp · 480p | 28 | fast | Nhỏ, nhanh |
| Tuỳ chỉnh (bitrate) | `-b:v {n}k` | medium | User nhập số |

### Filter chain (chỉ build khi re-encode)

**Scale quality (downscale):**
```
scale=-2:{height}:flags=lanczos
```
(áp dụng cho 1080p / 720p / 480p; `-2` giữ aspect ratio chẵn)

**Aspect ratio — Crop giữa:**
```
crop={w}:{h}:(in_w-{w})/2:(in_h-{h})/2
```

**Aspect ratio — Letterbox:**
```
scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,
pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black
```

**Aspect ratio — Blur background** (dùng filter_complex thay vì -vf):
```
[0:v]split=2[fg][bg];
[bg]scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h},gblur=sigma=20[blurred];
[fg]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos[scaled];
[blurred][scaled]overlay=(W-w)/2:(H-h)/2[outv]
```

**Watermark text** (font bundled vào `backend/storage/fonts/DejaVuSans-Bold.ttf`):
```
drawtext=fontfile='{FONT_PATH}':text='{escaped_text}':
  fontsize=36:fontcolor=white@0.85:
  borderw=2:bordercolor=black@0.85:
  x=(w-text_w)/2:y=h-text_h-20
```
(Escape single quotes và `:` trong text input)

**Fade:**
```
fade=t=in:st=0:d=1,fade=t=out:st={duration-1}:d=1
```
(chỉ áp dụng khi `duration > 2`)

**Mute:** thêm flag `-an` thay vì `-c:a aac`.

### Progress parsing

Chạy FFmpeg với `-progress pipe:1 -nostats`, parse output:
```
out_time_ms=12345678
progress=continue
...
progress=end
```
→ Tính `percent = out_time_ms / (target_duration * 1_000_000) * 100`.

---

## 3. Backend

### 3.1 Files mới

```
backend/app/api/trim.py               ← router mới
backend/app/services/video_trimmer.py ← FFmpeg logic
backend/storage/fonts/DejaVuSans-Bold.ttf ← font cho watermark
backend/storage/trim_temp/            ← thư mục temp (tạo runtime)
```

### 3.2 Files sửa

- `backend/app/main.py` — thêm `from app.api import trim` + `include_router(trim.router, prefix="/api/v1/trim", tags=["trim"])`

### 3.3 API endpoints

| Method | Path | Mục đích |
|---|---|---|
| `POST` | `/api/v1/trim/upload` | Multipart upload video → lưu temp → trả `{file_id, duration, width, height, video_codec, audio_codec}` |
| `GET` | `/api/v1/trim/waveform/{file_id}` | Trả array float (peak values) để vẽ waveform |
| `POST` | `/api/v1/trim/process` | Body params trim → start FFmpeg → trả `{job_id}` |
| `GET` | `/api/v1/trim/progress/{job_id}` | SSE stream `{percent, status}` |
| `GET` | `/api/v1/trim/download/{job_id}` | Serve file output (trigger browser download) |
| `POST` | `/api/v1/trim/clear/{file_id}` | Xóa folder temp (khi user upload file mới) |

### 3.4 Schema (Pydantic)

```python
class TrimUploadResponse(BaseModel):
    file_id: str
    duration: float
    width: int
    height: int
    video_codec: str
    audio_codec: Optional[str]
    original_filename: str

class AspectRatio(BaseModel):
    # "original" | "16:9" | "9:16" | "1:1" | "4:3" | "4:5" | "21:9" | "16:10" | "3:4" | "custom"
    mode: str
    custom_w: Optional[int] = None
    custom_h: Optional[int] = None

class TrimProcessRequest(BaseModel):
    file_id: str
    start_sec: float
    end_sec: float
    quality: str  # "original" | "1080p" | "720p" | "480p" | "custom"
    custom_bitrate_kbps: Optional[int] = None
    aspect_ratio: AspectRatio
    crop_mode: str = "crop"  # "crop" | "letterbox" | "blur"
    keep_audio: bool = True
    mute: bool = False
    exact_frame: bool = True
    fade: bool = False
    watermark_text: Optional[str] = None
    output_filename: str  # user-provided (đã có .mp4 extension)

class TrimProcessResponse(BaseModel):
    job_id: str

class TrimProgressEvent(BaseModel):
    percent: float
    status: str  # "running" | "completed" | "failed"
    error: Optional[str] = None
```

### 3.5 Logic `video_trimmer.py`

```
class VideoTrimmer:
    def probe(input_path) -> dict
        # ffprobe → duration, width, height, video_codec, audio_codec

    def generate_waveform(input_path, samples=500) -> list[float]
        # ffmpeg -i input -af "aresample=8000,asetnsamples=N,astats=metadata=1:reset=1"
        # Hoặc đơn giản: ffmpeg -i input -ac 1 -filter:a aresample=8000 -map 0:a -c:a pcm_s16le -f data -
        # Read raw PCM, downsample to `samples` buckets, return normalized [0..1]

    def build_filter_chain(params) -> (filter_str, use_filter_complex)
        # Quyết định -vf vs -filter_complex (blur dùng filter_complex)

    def needs_reencode(params) -> bool
        # True nếu: aspect_ratio != original, watermark, fade, mute, exact_frame,
        #          quality != "original"

    def trim(input_path, output_path, params, progress_cb) -> dict
        # Build command theo logic ở mục 2
        # Spawn subprocess, đọc -progress pipe, gọi progress_cb(percent)
        # Nếu stream copy fail → fallback re-encode audio
        # Return {success, duration, file_size, error?}
```

### 3.6 Job tracking in-memory

Không dùng DB. Dùng dict module-level:
```python
_jobs: dict[str, JobState] = {}
# JobState: {percent, status, error, output_path, input_file_id}
```
SSE endpoint đọc từ dict này, yield event mỗi 500ms cho đến khi `status != "running"`.

### 3.7 File size limit

FastAPI mặc định OK nhưng cần:
- Dùng `UploadFile` (stream, không load vào RAM)
- `async def upload()` + write theo chunks 1MB
- Không cần thay đổi uvicorn config cho 2GB

### 3.8 Cleanup

- Khi `POST /clear/{file_id}` → `shutil.rmtree(storage/trim_temp/{file_id})`
- Khi `POST /upload` lần mới → không auto-clean old (user quyết định)
- Không cài cron job cleanup — chấp nhận tích tụ, user clear qua UI khi cần

---

## 4. Frontend

### 4.1 Files mới

```
frontend/src/pages/VideoTrimmerPage.tsx
frontend/src/services/trimApi.ts          ← wrapper axios cho endpoints trim
frontend/src/components/trim/UploadZone.tsx
frontend/src/components/trim/VideoPreview.tsx
frontend/src/components/trim/Waveform.tsx
frontend/src/components/trim/Timeline.tsx
frontend/src/components/trim/TimeInput.tsx
frontend/src/components/trim/ExportSettings.tsx
```

### 4.2 Files sửa

- `frontend/src/App.tsx` — thêm `<Route path="/video-trimmer" element={<VideoTrimmerPage />} />`
- `frontend/src/components/layout/Layout.tsx` — thêm `<Link to="/video-trimmer">` với icon `Scissors` (lucide-react)

### 4.3 State chính trong `VideoTrimmerPage`

```typescript
// Upload state
file: File | null
fileId: string | null           // từ backend sau khi upload
uploadProgress: number          // 0..100
metadata: { duration, width, height, videoCodec, audioCodec } | null

// Trim selection (dùng chung timeline + time inputs)
startSec: number
endSec: number

// Export settings
quality: 'original' | '1080p' | '720p' | '480p' | 'custom'
customBitrate: number
aspectRatio: { mode: string, customW?, customH? }
cropMode: 'crop' | 'letterbox' | 'blur'
mute: boolean
exactFrame: boolean
fade: boolean
watermarkText: string
outputFilename: string

// Processing
jobId: string | null
processProgress: number         // 0..100
processStatus: 'idle' | 'running' | 'completed' | 'failed'
```

### 4.4 Bidirectional sync

- `startSec/endSec` là **single source of truth**.
- `Timeline` component nhận `startSec, endSec, duration, onChange(start, end)` → drag handle gọi `onChange`.
- `TimeInput` component nhận `valueSec, onChange(sec)` → gõ vào 3 ô h/m/s, debounce 300ms, parse → gọi `onChange`.
- "↙ lấy vị trí hiện tại" → đọc `videoRef.current.currentTime`, gọi `onChange`.
- "▶ Xem trước đoạn này" → `videoRef.current.currentTime = startSec; videoRef.current.play()`, tự pause khi `>= endSec`.

### 4.5 Upload flow

```
User chọn file
  ↓
Tạo URL.createObjectURL(file) → gán cho <video> preview
  ↓ (song song)
axios.post('/api/v1/trim/upload', formData, { onUploadProgress })
  ↓
Nhận {file_id, duration, ...} → lưu state
  ↓
Fetch /api/v1/trim/waveform/{file_id} → vẽ Waveform
```

### 4.6 Process flow

```
User bấm "✂️ Bắt đầu cắt video"
  ↓
axios.post('/api/v1/trim/process', params) → nhận {job_id}
  ↓
Mở EventSource('/api/v1/trim/progress/{job_id}')
  ↓ (cập nhật progress bar mỗi event)
Nhận status=completed → đóng EventSource
  ↓
Trigger download: window.location = '/api/v1/trim/download/{job_id}'
```

### 4.7 Thay đổi so với HTML mockup

- **Bỏ toàn bộ bước 4a "Định dạng đầu ra"** (pills MP4/MOV/MKV/WebM/GIF) — chỉ MP4 mặc định, không hiển thị UI chọn.
- **Bỏ checkbox "Cắt nhiều đoạn (multi-clip)"**.
- **Bỏ phần "Thư mục lưu"** (bỏ nút "📂 Đổi thư mục"). Giữ lại input "Tên file".
- Time inputs `<input>`: **bỏ `readonly`**, cho phép nhập tay + vẫn drag timeline được (sync 2 chiều).
- Output filename mặc định: `{original_basename}_cut_{HHMMSS}_{HHMMSS}.mp4`.
- Khi aspect_ratio = "original" → **ẩn** pills crop mode.
- Khi quality = "original" + exact_frame OFF → hiển thị **badge cảnh báo** dưới Step 5: "⚠️ Stream copy — điểm cắt có thể lệch ±2s do keyframe. Tick 'Cắt chính xác theo frame' để frame-accurate."

### 4.8 Validation (frontend)

- `startSec < endSec`
- `endSec <= metadata.duration`
- `endSec - startSec > 0.1` (tối thiểu 0.1s)
- Watermark text: max 100 ký tự, trim whitespace
- Custom bitrate: 100..50000 kbps
- Custom aspect ratio: w, h ∈ [1..100]

Disable nút "Bắt đầu cắt" khi validation fail, show tooltip lỗi.

---

## 5. Thứ tự implement

1. **Backend**
   1. Tạo `backend/storage/fonts/` + copy `DejaVuSans-Bold.ttf` (system font hoặc download)
   2. Tạo `backend/app/services/video_trimmer.py` — các method `probe`, `generate_waveform`, `build_filter_chain`, `needs_reencode`, `trim`
   3. Tạo `backend/app/api/trim.py` — 6 endpoints + schemas inline (hoặc bổ sung vào `schemas.py`)
   4. Sửa `main.py` — include router
   5. **Test manual qua /docs** với file nhỏ trước

2. **Frontend**
   1. Tạo `services/trimApi.ts` — thin wrapper axios
   2. Tạo các component con (UploadZone, Timeline, TimeInput, Waveform, VideoPreview, ExportSettings)
   3. Tạo `VideoTrimmerPage.tsx` — orchestrate state + flow
   4. Sửa `App.tsx` + `Layout.tsx` (route + menu)
   5. **Test end-to-end** trên browser Chrome

3. **Manual QA checklist** (mục 6)

---

## 6. QA Checklist

### Functional
- [ ] Upload file .mp4 nhỏ (<100MB) → thấy metadata, waveform, preview
- [ ] Upload file lớn (~1GB) → upload progress bar hoạt động
- [ ] Kéo handle trái/phải timeline → time input cập nhật
- [ ] Gõ số vào time input → handle timeline dịch chuyển
- [ ] "↙ lấy vị trí hiện tại" hoạt động đúng
- [ ] "▶ Xem trước đoạn này" play từ start, tự pause tại end
- [ ] Trim đơn giản (quality=original, exact_frame=OFF) → nhanh, stream copy
- [ ] Trim với aspect ratio 9:16 + crop → output đúng kích thước
- [ ] Trim với letterbox → viền đen đúng
- [ ] Trim với blur background → nền mờ hiển thị đúng
- [ ] Watermark text hiển thị đúng font, vị trí
- [ ] Fade in/out nhìn thấy được
- [ ] Mute → output không có âm thanh
- [ ] Exact frame ON + quality=original → re-encode CRF 12
- [ ] Progress bar update real-time trong khi FFmpeg chạy
- [ ] Download file output thành công, play được
- [ ] Output MP4 play được trên VLC + browser

### Edge cases
- [ ] Upload file có audio Opus (vd WebM) → stream copy fallback re-encode audio, không crash
- [ ] `startSec >= endSec` → button disabled
- [ ] `endSec > duration` → clamp về duration
- [ ] Watermark text chứa dấu `'` hoặc `:` → escape đúng, không vỡ filter
- [ ] Custom aspect ratio 0:0 → validation chặn
- [ ] Upload file rồi upload file khác → file_id mới, UI reset đúng

### Error handling
- [ ] FFmpeg fail → UI hiện error message
- [ ] SSE connection drop → retry hoặc thông báo
- [ ] Network lỗi khi upload → thông báo rõ ràng

---

## 7. Các file quan trọng cần check khi debug

- `backend/logs/app.log` — loguru output, FFmpeg stderr được log ở đây
- `backend/storage/trim_temp/{file_id}/` — input + output files
- Browser DevTools Network tab — upload progress, SSE stream
- `ffprobe backend/storage/trim_temp/{file_id}/output.mp4` — verify output metadata
