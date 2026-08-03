# Plan: Build nhanh (Quick Build)

> Trạng thái: **ĐÃ CODE xong GĐ1–3** (2026-07-30). Mockup UI: `_mockups/quick-build-mockup.html`.
>
> **File đã tạo/sửa:**
> - BE model/schema: `models.py` (BuildPreset/BuildBatch/BuildJob), `schemas.py`
> - BE API: `api/build_presets.py`, `api/quick_build.py`, `main.py` (đăng ký router + recovery), `api/video.py` (GPU guard)
> - BE service: `services/build_orchestrator.py`, `services/gpu_guard.py`
> - FE: `services/quickBuildApi.ts`, `pages/QuickBuildPage.tsx`, `App.tsx`, `components/layout/Layout.tsx`, `pages/HomePage.tsx`, `pages/ProcessorPage.tsx` (nút Lưu Build Preset)
>
> **Đã verify:** BE import + tạo bảng OK · build-preset CRUD 200 · scan-folder 403 khi không phải localhost (guard đúng) · `clean_story_text`/`_resolve_config`/`_build_video_config` chạy đúng · FE `tsc --noEmit` sạch.
> **Chưa chạy end-to-end thật:** TTS + render (cần GPU/VBEE key + folder clip thật) — nhưng dùng đúng hàm wizard đang chạy production.
>
> **Bổ sung sau GĐ1–3 (2026-08-02):**
> - Card 2 thêm ô **Folder clip nền chung** (override cho cả batch; ưu tiên: folder riêng từng dòng > folder chung > preset).
> - Progress view giống mockup: **% render thật** (đọc `Task.progress` của video task) + thanh bar, size + giờ hoàn tất, số thứ tự, nút **✕ Bỏ** job đang chờ (endpoint `/job/{id}/cancel` → status `skipped`, orchestrator `db.refresh` skip).
> - **Phase 3.5 Auto-SRT ĐÃ LÀM (ước lượng):** `subtitle_renderer.build_estimated_srt(text, total_duration, out_path)` tách câu→cụm→wrap, phân bổ thời gian theo độ dài ký tự. Dùng cho **cả VBEE lẫn OmniVoice** vì quick-build đi đường `process_merged_content` (1 file, không có timing per-câu). Orchestrator `_make_subtitle` sinh SRT vào `paths.SRT_CACHE_DIR`, đổ vào `subtitle_srt_path` của video config; lỗi phụ đề KHÔNG làm hỏng job. Bật/tắt qua toggle chung + override từng dòng/bulk (`auto_subtitle`). Style phụ đề lấy từ `video_cfg` của preset. **Hạn chế:** canh giờ là ước lượng theo ký tự, không phải timing thật của giọng đọc.
>
> **Code review (workflow high, 23 agent) → đã sửa hết 10 finding:**
> 1. GPU guard viết lại `try_acquire/release/is_busy` atomic — acquire đồng bộ ở endpoint (hết TOCTOU), release trong `_run_batch finally`. Chặn 2 chiều: wizard render (`video.py`) + wizard OmniVoice TTS (`tts.py start-merged`, `segments/run`) đều check `is_busy()`; batch check `_wizard_gpu_busy` (Task video + omni-tts) + `tts_worker.any_story_active()`.
> 2. `recover_interrupted` xử lý cả job `pending` (không còn kẹt "Chờ" vĩnh viễn).
> 3. Validate `video_folder` sớm (đầu `_run_one_job` + trong `start`) — không phí lượt TTS.
> 4. `_mark_job_error` defensive (không để job kẹt `running`) + sweep cuối `_run_batch`.
> 5+9. Set `current_step` (3→6→8) → story quick-build là draft resumable, không phải rác; done hiện 8/8.
> 6. `require_localhost` cho start/retry/stop/status.
> 7. `startVideoProcessing` tái dùng `buildBackendVideoCfg()` (hết nhân đôi ~70 field).
> 8. Dùng chung `has_sibling_banner`/`sibling_banner`.
> 10. Bỏ nháy màn hình retry (nhánh loading khi `batchId && !batch`).
>
> **Verify sau sửa:** guard atomic ✓ · recover_interrupted (running+pending→error, done giữ nguyên) ✓ · BE import ✓ · FE `tsc` ✓ · 1 finding bị bác (auto_clean text rỗng → an toàn, TTS reject sẵn).

## Mục tiêu
Thay vì đi hết wizard 8 bước cho từng truyện, người dùng:
1. Chọn **1 folder** (mỗi file `.txt`/`.docx` = 1 truyện = 1 video).
2. Đặt **preset + folder clip nền dùng chung** cho cả batch, có thể **override từng truyện**.
3. Bấm 1 nút → **backend tự chạy** cả chuỗi cho từng truyện, chạy nền (đóng cửa sổ vẫn tiếp tục).

## Quyết định sản phẩm (đã chốt)
- **Input**: mỗi file = 1 truyện riêng (batch), mỗi truyện ra 1 video.
- **Preset**: gói đủ **giọng (TTS) + video config + folder clip nền**.
- **Spellcheck**: bỏ qua trong build nhanh.
- **Orchestration**: backend tự chạy toàn bộ (sống sót khi đóng cửa sổ).
- **Cấu hình**: chung cho cả batch + override từng truyện (preset/giọng/tốc độ/clip/banner/phụ đề/clean).
- **Bảng preset**: tách riêng `build_presets` (KHÔNG nhét vào `video_presets`, vì preset video cố tình loại folder/banner/bgm).
- **Auto-clean text**: mức **conservative** (chỉ bỏ dòng rác rõ ràng, không đụng nội dung).
- **Banner per-truyện**: tự nhận theo tên file (`chuong-01.txt` ↔ `chuong-01.jpg`).

## Pipeline (lặp lại chuỗi wizard, bỏ bước review)
```
File .txt → tạo Story + tách chương + merged_content
         → [BỎ spellcheck] [auto-clean nếu bật]
         → TTS (VBEE hoặc OmniVoice) → gộp audio
         → [auto-SRT nếu bật — Phase 3.5]
         → render video (video_cfg + folder clip + banner) → xuất video
         → job tiếp theo
```

## Hàm/luồng tái dùng (đã xác minh trong code)
| Công đoạn | Tái dùng |
|---|---|
| Đọc file → tách chương | `services/chapter_splitter.py`: `read_text_from_file(path)`, `split_chapters(text)` |
| Lưu chương + merged_content | logic `_persist_imported_chapters` (chapters.py) + join content (stories.py:401-408) |
| TTS VBEE (1 file) | `services/tts_processor.py`: `VbeeTTSProcessor(db).process_merged_content(story_id, db, voice_code, audio_type, bitrate, speed)` |
| TTS OmniVoice (1 file) | `services/omnivoice_processor.py`: `OmniVoiceProcessor(db).process_merged_content(story_id, db, config)` |
| Config TTS flatten | tham chiếu `_build_tts_config` (tts.py) — keys: engine, voice_code, audio_type, bitrate, speed, mode, model_key, preset_id, ref_text, instruct, language |
| Lấy audio đã gộp | `MergedAudio` mới nhất của story → `.file_path` |
| Render video | `workers/video_worker.py`: `run_video_task(task_id, story_id, config)` (wrapper sync). Keys config: xem video_worker.py:44-128 |

**Lưu ý quan trọng:** `merged_content` KHÔNG tự lưu khi import — phải tự set `story.merged_content` trước khi TTS (`start-merged` yêu cầu field này). Join: `"".join(ch.content.strip() for ch in chapters if ch.content and ch.content.strip())`.

**Concurrency:** TTS + video đều nặng GPU → orchestrator chạy **tuần tự 1 job/lần** trong 1 background thread.

> ⚠️ **GPU global lock (bắt buộc — review finding #1):** merged-TTS và render **KHÔNG** lấy lock `_active_stories` (lock đó chỉ cho segment-TTS). Nếu user vừa chạy batch vừa render trong wizard → 2 tiến trình NVENC/OmniVoice đụng GPU → OOM. Cần **1 lock/guard toàn cục**: chặn `POST /quick-build/start` khi đang có video task chạy (và wizard render nên kiểm tra batch đang chạy). Triển khai: 1 `threading.Lock` / flag process-wide dùng chung giữa quick_build và video worker.

---

## GIAI ĐOẠN 1 — BuildPreset (model + CRUD + nút lưu)

### 1.1 Model — `backend/app/models.py`
```python
class BuildPreset(Base):
    __tablename__ = "build_presets"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False, unique=True, index=True)
    tts_config = Column(JSON, nullable=False)     # {engine, voice_code, speed, bitrate, preset_id, mode, ...}
    video_cfg  = Column(JSON, nullable=False)     # nguyên khối VideoCfgPreset của FE
    video_folder = Column(Text, nullable=True)    # folder clip nền
    bgm_path   = Column(Text, nullable=True)
    watermark_image = Column(Text, nullable=True)
    banner_mode = Column(String(20), default="by_filename")   # by_filename | none | fixed
    banner_fixed = Column(Text, nullable=True)
    options = Column(JSON, nullable=True)         # {skip_spellcheck, auto_clean, auto_subtitle}
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())
```
> `init_db()` (create_all) tự tạo bảng mới → **không cần migration** (chỉ thêm bảng, không đổi cột bảng cũ).

### 1.2 Schemas — `backend/app/schemas.py`
`BuildPresetCreate / BuildPresetUpdate / BuildPresetResponse` (clone `VideoPreset*` ở schemas.py:523-534).

### 1.3 API — `backend/app/api/build_presets.py`
CRUD y hệt `video_presets.py`. Đăng ký `main.py`: `app.include_router(build_presets.router, prefix="/api/v1/build-presets", tags=["build-presets"])`.

### 1.4 Nút lưu preset trong wizard — `frontend/src/pages/ProcessorPage.tsx`
Nút "💾 Lưu thành Build Preset" → snapshot:
```
{ name, tts_config: ttsConfig, video_cfg: <videoConfig ĐÃ strip>,
  video_folder: videoConfig.folder, bgm_path: videoConfig.bgmPath,
  watermark_image: videoConfig.watermarkImage,
  options: { skip_spellcheck: true, auto_clean: true, auto_subtitle: false } }
```
> **Strip trong `video_cfg` (review finding #3):** set `null` các field per-truyện — `folder`, `audioPath`, `bannerImage`, **`subtitle_srt_path`** (dễ quên → sẽ burn nhầm SRT của truyện khác). Banner xử lý qua `banner_mode`, folder qua `video_folder`. Đảm bảo `tts_config` giữ đúng `voice_code` mà `_build_tts_config` cần (wizard lưu kèm `dbVoiceCode`).

→ `POST /api/v1/build-presets`.

---

## GIAI ĐOẠN 2 — Orchestrator + API batch

### 2.1 Models tracking — `backend/app/models.py`
```python
class BuildBatch(Base):
    __tablename__ = "build_batches"
    id, status(queued|running|done|stopped), total(Integer), created_at

class BuildJob(Base):
    __tablename__ = "build_jobs"
    id, batch_id(FK build_batches, CASCADE), order_index(Integer),
    source_path(Text), title(String),
    story_id(String, nullable), preset_id(String), overrides(JSON),
    stage(String: create|tts|video|done), status(String: pending|running|done|error),
    output_path(Text, nullable), error_message(Text, nullable),
    created_at, updated_at
```

### 2.2 Service — `backend/app/services/build_orchestrator.py`
```python
_running_batches: set
_batch_lock = threading.Lock()

def start_batch_thread(batch_id): ...        # daemon thread → _run_batch
def stop_batch(batch_id): ...                # discard khỏi _running_batches
def is_batch_running(batch_id): ...

def _run_batch(batch_id):
    db = SessionLocal()
    jobs = query BuildJob by batch order_index
    for job in jobs:
        if not is_batch_running(batch_id): break
        try: _run_one_job(db, job)
        except Exception as e:
            job.status='error'; job.error_message=str(e); db.commit()   # cô lập, chạy tiếp
    set batch.status='done'/'stopped'

def _run_one_job(db, job):
    cfg = _resolve_config(db, job)           # merge preset + overrides
    # create
    job.stage='create'; job.status='running'; db.commit()
    story = _create_story_from_file(db, job, cfg)
    # tts
    job.stage='tts'; db.commit()
    _run_tts_sync(db, story, cfg['tts'])
    audio = latest MergedAudio(story).file_path
    if not audio: raise RuntimeError("TTS không tạo được audio")
    # video
    job.stage='video'; db.commit()
    vcfg = _build_video_config(cfg, audio, banner=_auto_banner(job.source_path, cfg))
    task = Task(type='video_processing', story_id=story.id); commit
    result = run_video_task(task.id, story.id, vcfg)
    if not result.get('success'): raise RuntimeError(result.get('error'))
    job.output_path=result['output_path']; job.stage='done'; job.status='done'; db.commit()
```
Helpers:
- `_create_story_from_file(db, job, cfg)`: tạo `Story(title=_nice_title(source_path), url='')`; `read_text_from_file` → `split_chapters` → persist chương; set `story.merged_content` (join); nếu `cfg.options.auto_clean` → `story.merged_content = clean_story_text(...)`.
- `_run_tts_sync(db, story, tts_cfg)`: `loop=asyncio.new_event_loop()`; route VBEE/OmniVoice `process_merged_content`.
- `_build_video_config(cfg, audio, banner)`: đổ `preset.video_cfg` + `video_source_folder=cfg.video_folder` + `audio_path=audio` + `banner_image=banner` + `bgm_path` + `watermark_image` + stickers → đúng keys `process_video_task` đọc.
- `_auto_banner(txt_path, cfg)`: banner_mode `by_filename` → tìm `<basename>.{jpg,jpeg,png,webp}` cạnh file; `fixed` → `banner_fixed`; `none` → None.
- `clean_story_text(text)` (conservative): bỏ dòng chứa url/website/"nguồn:"/"truyện được đăng tại", gộp >2 dòng trống. Không sửa nội dung câu.
- `_nice_title(path)`: tên file, bỏ đuôi, thay `_`/`-` bằng space, title-case nhẹ.
- `_resolve_config(db, job)`: preset gốc + `job.overrides` (preset_id/voice/speed/folder/banner/subtitle/clean).

### 2.3 API — `backend/app/api/quick_build.py`
- `POST /scan-folder` `{path}` → `[{source_path, title, has_banner}]` (reuse browse-files logic; liệt kê .txt/.docx + dò ảnh cùng tên). **Thêm `dependencies=[Depends(require_localhost)]`** (đọc disk — review finding #2).
- `POST /start` `{preset_id, common_overrides, jobs:[{source_path, selected, overrides}]}` → **kiểm tra GPU global lock (không cho start khi có video task chạy)** → tạo `BuildBatch`+`BuildJob`(chỉ selected), `start_batch_thread`, trả `{batch_id}`.
- `GET /{batch_id}/status` → batch + jobs (FE poll 2–3s).
- `POST /{batch_id}/stop` → **ngừng nhận job MỚI; job đang render vẫn chạy hết** (run_video_task blocking, không interrupt được — review finding #4).
- `POST /job/{job_id}/retry` → **tạo Story mới + job mới** (KHÔNG tái dùng story_id cũ, tránh dọn MergedAudio/VideoOutput rác — review finding #4).
Đăng ký prefix `/api/v1/quick-build`.

> **Commit thưa (review finding #5):** orchestrator chỉ `db.commit()` khi đổi stage (create→tts→video→done), không commit mỗi %, tránh "database is locked" với SQLite.

> **Tái dùng cho FE (review finding — đơn giản hoá):** nút "Mở video" ở bảng tiến độ dùng lại `GET /video/result/{story_id}` + `POST /video/reveal-video/{story_id}` — không cần endpoint mới. Story quick-build là Story thật → **tự xuất hiện trong History** (mong muốn, không phải bug).

### 2.4 Startup recovery — `backend/app/startup_recovery.py`
Job `status='running'` khi khởi động lại (app đã đóng giữa chừng) → set `error` = "bị gián đoạn", cho retry. (Giống cơ chế reset task đang chạy hiện có.)

---

## GIAI ĐOẠN 3 — Frontend

### 3.1 `frontend/src/services/quickBuildApi.ts`
Wrap: `scanFolder`, `startBatch`, `getBatchStatus`, `stopBatch`, `retryJob`, `listBuildPresets`.

### 3.2 `frontend/src/pages/QuickBuildPage.tsx` (theo mockup)
- Card 1: chọn folder → `scan-folder` → danh sách truyện.
- Card 2: cấu hình chung — preset dropdown (`GET /build-presets`) + folder clip + toggle (auto-SRT, auto-clean).
- Card 3: bảng truyện — checkbox chọn/bỏ; cột Preset/Clip/Banner mặc định `⟳ Chung`; nút ✎ mở editor inline override từng job; badge RIÊNG cho dòng đã override.
- Nút Build → `POST /start` → chuyển sang chế độ tiến độ (poll `status`): pill xong/đang chạy/chờ/lỗi + nút Mở video / Thử lại.

### 3.3 Điều hướng
- `frontend/src/App.tsx`: `<Route path="/quick-build" element={<QuickBuildPage/>} />`.
- `frontend/src/components/layout/Layout.tsx`: thêm nav `{ to:'/quick-build', label:'Build nhanh', icon: Zap }` vào nhóm **Sản xuất** (dưới Trang chủ).
- `frontend/src/pages/HomePage.tsx`: nút phụ "⚡ Build nhanh" cạnh "Tạo dự án mới".

### 3.4 Modal quản lý preset (list/rename/delete) — nhẹ, có thể gộp cuối GĐ3.

---

## Phase 3.5 (tách riêng) — Auto-SRT
Tự sinh phụ đề burn vào video từ timing TTS.
- OmniVoice: có `duration` per-segment → dựng SRT theo mốc thời gian cộng dồn.
- VBEE merged: không có timing per-câu → cần tách câu + ước lượng, hoặc bỏ.
Mặc định **tắt**; bật qua toggle preset/override.

---

## Ước lượng & rủi ro
- GĐ1 ~½ ngày · GĐ2 ~1–1.5 ngày · GĐ3 ~1 ngày · Phase 3.5 riêng.
- VBEE cần quota, OmniVoice cần GPU — lỗi từng job đã cô lập, batch không dừng.
- Text nguồn bẩn = rủi ro chất lượng chính → `auto_clean` conservative + để người dùng tự chịu trách nhiệm file sạch.

## Thứ tự triển khai
1. GĐ1 → có preset để test.
2. GĐ2 → test orchestrator bằng 1–2 file trước khi làm UI.
3. GĐ3 → trang + nav.
4. Phase 3.5 nếu cần phụ đề.

---

## Review log (đã kiểm chứng với code)
**Đã verify khớp code thật:** `create_all` không cần migration · `check_same_thread=False` (thread ghi DB OK) · VBEE & OmniVoice `process_merged_content` đọc `merged_content` + tạo `MergedAudio` · `split_chapters` không crash với file không heading · `StoryBase` chỉ cần title+url · `run_video_task` blocking (tuần tự tự nhiên).

**5 finding đã vá vào plan:**
1. [CAO] GPU global lock — chặn batch/wizard render đụng nhau (mục Concurrency).
2. [TB] `scan-folder` cần `require_localhost` (mục 2.3).
3. [TB] Strip `subtitle_srt_path`/folder/audioPath/bannerImage khỏi `video_cfg` khi lưu preset (mục 1.4).
4. [TB] Stop = ngừng job mới; Retry = tạo Story mới (mục 2.3).
5. [THẤP] Commit thưa theo stage (mục 2.3).

**Không có lỗi chí mạng.** Chặn trước khi chạy song song wizard: finding #1.
