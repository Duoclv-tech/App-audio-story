"""
FFmpeg-based video trimmer service
"""
import json
import os
import struct
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from loguru import logger

from app import paths

STORAGE_BASE = paths.STORAGE_DIR
TRIM_TEMP_DIR = paths.TRIM_TEMP_DIR
FONT_PATH = paths.default_font_path()


def _ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def probe(input_path: str) -> dict:
    """Run ffprobe and return duration, width, height, codecs."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", input_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    data = json.loads(result.stdout)
    duration = float(data.get("format", {}).get("duration", 0))
    width = height = 0
    video_codec = audio_codec = None

    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and not video_codec:
            video_codec = stream.get("codec_name")
            width = stream.get("width", 0)
            height = stream.get("height", 0)
        elif stream.get("codec_type") == "audio" and not audio_codec:
            audio_codec = stream.get("codec_name")

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "video_codec": video_codec or "unknown",
        "audio_codec": audio_codec,
    }


def generate_waveform(input_path: str, samples: int = 500) -> list:
    """Extract normalized waveform peak values [0..1] from audio."""
    cmd = [
        "ffmpeg", "-v", "quiet", "-i", input_path,
        "-ac", "1", "-ar", "8000",
        "-map", "0:a", "-c:a", "pcm_s16le", "-f", "s16le", "-"
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0 or not result.stdout:
        return [0.0] * samples

    raw = result.stdout
    n_samples = len(raw) // 2
    values = struct.unpack(f"<{n_samples}h", raw)

    bucket_size = max(1, n_samples // samples)
    peaks = []
    for i in range(samples):
        start = i * bucket_size
        end = min(start + bucket_size, n_samples)
        if start >= n_samples:
            peaks.append(0.0)
        else:
            bucket = values[start:end]
            peak = max(abs(v) for v in bucket) if bucket else 0
            peaks.append(peak / 32768.0)

    return peaks


def _escape_drawtext(text: str) -> str:
    """Escape special chars for FFmpeg drawtext filter."""
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "\\'")
    text = text.replace(":", "\\:")
    return text


def _escape_fontfile(path) -> str:
    """Escape a filesystem path for a drawtext ``fontfile='...'`` value.

    On Windows a raw path like ``C:\\WINDOWS\\Fonts\\arialbd.ttf`` breaks the
    filtergraph parser: backslashes are escape chars and the ``C:`` colon is an
    option separator, so ffmpeg fails with "Invalid argument". Use forward
    slashes and escape the drive-letter colon (the value is wrapped in single
    quotes by the caller, so spaces are fine).
    """
    p = str(path).replace("\\", "/")
    p = p.replace(":", "\\:")
    return p


_WM_POSITION_MAP = {
    "top-left":      ("{m}",              "{m}"),
    "top-center":    ("(w-text_w)/2",     "{m}"),
    "top-right":     ("w-text_w-{m}",     "{m}"),
    "middle-left":   ("{m}",              "(h-text_h)/2"),
    "center":        ("(w-text_w)/2",     "(h-text_h)/2"),
    "middle-right":  ("w-text_w-{m}",     "(h-text_h)/2"),
    "bottom-left":   ("{m}",              "h-text_h-{m}"),
    "bottom-center": ("(w-text_w)/2",     "h-text_h-{m}"),
    "bottom-right":  ("w-text_w-{m}",     "h-text_h-{m}"),
}


def _hex_to_ffmpeg(color: str) -> str:
    """Normalize a color string to FFmpeg '0xRRGGBB' form. Falls back to named color."""
    c = (color or "").strip()
    if not c:
        return "0xFFFFFF"
    if c.startswith("#"):
        c = c[1:]
    if c.lower().startswith("0x"):
        c = c[2:]
    if len(c) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in c):
        return f"0x{c.upper()}"
    # Named colors like "white", "black" — pass through
    return color


def _drawtext_expr(wm: dict) -> str:
    """Build a 'drawtext=...' filter expression from watermark params."""
    text = wm.get("text", "") or ""
    escaped = _escape_drawtext(text)
    font_size = int(wm.get("font_size", 36))
    color_ff = _hex_to_ffmpeg(wm.get("color") or "#FFFFFF")
    opacity = max(0.0, min(1.0, float(wm.get("opacity", 0.85))))
    position = wm.get("position", "bottom-center")
    margin = int(wm.get("margin", 20))
    border_enabled = bool(wm.get("border_enabled", True))
    border_color_ff = _hex_to_ffmpeg(wm.get("border_color") or "#000000")
    border_width = int(wm.get("border_width", 2))

    if position == "custom":
        cx = max(0.0, min(1.0, float(wm.get("custom_x", 0.5))))
        cy = max(0.0, min(1.0, float(wm.get("custom_y", 0.5))))
        x_expr = f"(w-text_w)*{cx:.4f}"
        y_expr = f"(h-text_h)*{cy:.4f}"
    else:
        x_tpl, y_tpl = _WM_POSITION_MAP.get(position, _WM_POSITION_MAP["bottom-center"])
        x_expr = x_tpl.format(m=margin)
        y_expr = y_tpl.format(m=margin)

    parts = [
        f"fontfile='{_escape_fontfile(FONT_PATH)}'",
        f"text='{escaped}'",
        f"fontsize={font_size}",
        f"fontcolor={color_ff}@{opacity:.2f}",
        f"x={x_expr}",
        f"y={y_expr}",
    ]
    if border_enabled and border_width > 0:
        border_alpha = min(opacity + 0.1, 1.0)
        parts.append(f"borderw={border_width}")
        parts.append(f"bordercolor={border_color_ff}@{border_alpha:.2f}")
    return "drawtext=" + ":".join(parts)


def _watermark_active(params: dict) -> tuple[bool, int]:
    """Return (enabled, rotation) for the watermark."""
    wm = params.get("watermark") or {}
    enabled = bool(wm.get("enabled")) and bool((wm.get("text") or "").strip())
    rotation = int(wm.get("rotation", 0)) if enabled else 0
    return enabled, rotation


def _build_atempo(speed: float) -> list[str]:
    """Chain atempo filters (each limited to [0.5, 2.0])."""
    filters: list[str] = []
    s = speed
    if s >= 1.0:
        while s > 2.0:
            filters.append("atempo=2.0")
            s /= 2.0
        filters.append(f"atempo={s:.4f}")
    else:
        while s < 0.5:
            filters.append("atempo=0.5")
            s *= 2.0
        filters.append(f"atempo={s:.4f}")
    return filters


def _quality_encode_args(params: dict) -> list[str]:
    """libx264 rate-control args for the chosen quality / custom bitrate.

    Mirrors the mapping the main trim pass uses so the subtitle 2nd pass honours
    the user's quality choice instead of a fixed CRF.
    """
    quality = params.get("quality", "original")
    if quality == "custom" and params.get("custom_bitrate_kbps"):
        return ["-b:v", f"{params['custom_bitrate_kbps']}k"]
    crf_map = {"original": 12, "1080p": 18, "720p": 23, "480p": 28}
    preset_map = {"original": "slow", "1080p": "medium", "720p": "medium", "480p": "fast"}
    return ["-crf", str(crf_map.get(quality, 23)), "-preset", preset_map.get(quality, "medium")]


def needs_reencode(params: dict) -> bool:
    """Return True if re-encoding is required (cannot use stream copy)."""
    if len(params.get("segments", [])) > 1:
        return True
    # A subtitle burn re-bases timings assuming the clip starts EXACTLY at
    # start_sec. Stream copy keyframe-snaps the start (extra leading frames), so
    # the burn would be shifted by up to one GOP — force a frame-accurate
    # re-encode when subtitles are requested.
    sub = params.get("subtitle") or {}
    if sub.get("enabled") and sub.get("srt_path"):
        return True
    if params.get("exact_frame"):
        return True
    if params.get("quality", "original") != "original":
        return True
    if params.get("aspect_ratio", {}).get("mode", "original") != "original":
        return True
    wm_enabled, _ = _watermark_active(params)
    if wm_enabled:
        return True
    if params.get("fade"):
        return True
    if params.get("mute"):
        return True
    if params.get("volume", 1.0) != 1.0:
        return True
    if params.get("speed", 1.0) != 1.0:
        return True
    return False


def build_filter_chain(params: dict, video_w: int, video_h: int, output_duration: float = 0.0, speed: float = 1.0):
    """
    Build the -vf filter string (or filter_complex for blur / rotated watermark).
    Returns (filter_str, use_filter_complex).
    output_duration: duration of the output video (trim_duration / speed).
    """
    quality = params.get("quality", "original")
    target_h = {"1080p": 1080, "720p": 720, "480p": 480}.get(quality)

    ar_mode = params.get("aspect_ratio", {}).get("mode", "original")
    crop_mode = params.get("crop_mode", "crop")
    duration = output_duration

    wm_enabled, wm_rotation = _watermark_active(params)
    needs_wm_overlay = wm_enabled and wm_rotation != 0

    # --- aspect-ratio target dims ---
    target_w, target_h_ar = None, None
    if ar_mode not in ("original", None):
        if ar_mode == "custom":
            cw = params["aspect_ratio"].get("custom_w", 1) or 1
            ch = params["aspect_ratio"].get("custom_h", 1) or 1
            ratio = cw / ch
        else:
            ratio_map = {
                "16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0,
                "4:3": 4 / 3, "4:5": 4 / 5, "21:9": 21 / 9,
                "16:10": 16 / 10, "3:4": 3 / 4,
            }
            ratio = ratio_map.get(ar_mode, video_w / video_h)
        target_h_ar = target_h if target_h else video_h
        target_w = int(target_h_ar * ratio)
        if target_w % 2 != 0:
            target_w += 1

    # Final output canvas (for overlay source sizing)
    if target_w and target_h_ar:
        canvas_w, canvas_h = target_w, target_h_ar
    elif target_h:
        canvas_h = target_h
        canvas_w = (video_w * target_h) // video_h
        if canvas_w % 2 != 0:
            canvas_w -= 1
    else:
        canvas_w, canvas_h = video_w, video_h

    # --- build main video processing ---
    use_filter_complex = False
    filter_complex_str = None
    main_filters: list[str] = []

    if ar_mode not in ("original", None):
        if crop_mode == "blur":
            use_filter_complex = True
            scale_fg = f"scale={target_w}:{target_h_ar}:force_original_aspect_ratio=decrease:flags=lanczos"
            scale_bg = f"scale={target_w}:{target_h_ar}:force_original_aspect_ratio=increase:flags=lanczos"
            filter_complex_str = (
                f"[0:v]split=2[fg][bg];"
                f"[bg]{scale_bg},crop={target_w}:{target_h_ar},gblur=sigma=20[blurred];"
                f"[fg]{scale_fg}[scaled];"
                f"[blurred][scaled]overlay=(W-w)/2:(H-h)/2[outmain]"
            )
        elif crop_mode == "letterbox":
            main_filters.append(
                f"scale={target_w}:{target_h_ar}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={target_w}:{target_h_ar}:(ow-iw)/2:(oh-ih)/2:color=black"
            )
        else:  # center-crop
            main_filters.append(
                f"scale={target_w}:{target_h_ar}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={target_w}:{target_h_ar}"
            )
    elif target_h:
        main_filters.append(f"scale=-2:{target_h}:flags=lanczos")

    # speed → setpts before fade/watermark so they operate on output timeline
    if speed != 1.0:
        main_filters.append(f"setpts=1/{speed:.4f}*PTS")

    # fade and non-rotated watermark live in the main chain
    if params.get("fade") and duration > 2:
        main_filters.append(f"fade=t=in:st=0:d=1,fade=t=out:st={duration - 1:.2f}:d=1")
    if wm_enabled and not needs_wm_overlay:
        main_filters.append(_drawtext_expr(params["watermark"]))

    # --- no rotated watermark: return early ---
    if not needs_wm_overlay:
        if use_filter_complex:
            if main_filters:
                extras = ",".join(main_filters)
                filter_complex_str = filter_complex_str.replace(
                    "[outmain]", f"[ovpre];[ovpre]{extras}[outv]"
                )
            else:
                filter_complex_str = filter_complex_str.replace("[outmain]", "[outv]")
            return filter_complex_str, True
        return ",".join(main_filters), False

    # --- rotated watermark: always filter_complex with overlay ---
    if not use_filter_complex:
        base = ",".join(main_filters) if main_filters else "null"
        filter_complex_str = f"[0:v]{base}[outmain]"
        use_filter_complex = True
    elif main_filters:
        extras = ",".join(main_filters)
        filter_complex_str = filter_complex_str.replace(
            "[outmain]", f"[ovpre];[ovpre]{extras}[outmain]"
        )

    drawtext = _drawtext_expr(params["watermark"])
    rot_rad = f"{wm_rotation}*PI/180"
    overlay_fc = (
        f";color=c=black@0:s={canvas_w}x{canvas_h}:d={duration}[wmbg];"
        f"[wmbg]{drawtext}[wmtxt];"
        f"[wmtxt]rotate={rot_rad}:c=none[wmrot];"
        f"[outmain][wmrot]overlay=0:0[outv]"
    )
    filter_complex_str = filter_complex_str + overlay_fc
    return filter_complex_str, True


def _build_multiseg_filter_complex(params: dict, segments: list, video_w: int, video_h: int) -> tuple[str, Optional[str], float]:
    """
    Build filter_complex for multi-segment concat with all effects applied.
    Returns (filter_complex_str, audio_out_label_or_None, total_output_duration).
    Video output label is always [outv].
    """
    quality = params.get("quality", "original")
    target_h_map = {"1080p": 1080, "720p": 720, "480p": 480}
    target_h = target_h_map.get(quality)
    ar_mode = params.get("aspect_ratio", {}).get("mode", "original")
    crop_mode = params.get("crop_mode", "crop")
    speed = params.get("speed", 1.0)
    mute = params.get("mute", False)
    volume = params.get("volume", 1.0)
    fade = params.get("fade", False)
    wm_enabled, wm_rotation = _watermark_active(params)

    # --- compute output canvas size ---
    canvas_w, canvas_h = video_w, video_h
    seg_v_filters: list[str] = []

    if ar_mode not in ("original", None):
        if ar_mode == "custom":
            cw = params["aspect_ratio"].get("custom_w", 1) or 1
            ch = params["aspect_ratio"].get("custom_h", 1) or 1
            ratio = cw / ch
        else:
            ratio_map = {
                "16:9": 16/9, "9:16": 9/16, "1:1": 1.0,
                "4:3": 4/3, "4:5": 4/5, "21:9": 21/9,
                "16:10": 16/10, "3:4": 3/4,
            }
            ratio = ratio_map.get(ar_mode, video_w / video_h)
        th = target_h if target_h else video_h
        tw = int(th * ratio)
        if tw % 2 != 0:
            tw += 1
        canvas_w, canvas_h = tw, th

        if crop_mode == "letterbox":
            seg_v_filters.append(
                f"scale={tw}:{th}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color=black"
            )
        elif crop_mode == "blur":
            # blur per-segment is complex; use letterbox as practical fallback
            seg_v_filters.append(
                f"scale={tw}:{th}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color=black"
            )
        else:  # crop
            seg_v_filters.append(
                f"scale={tw}:{th}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={tw}:{th}"
            )
    elif target_h:
        cw = (video_w * target_h) // video_h
        if cw % 2 != 0:
            cw -= 1
        canvas_w, canvas_h = cw, target_h
        seg_v_filters.append(f"scale=-2:{target_h}:flags=lanczos")

    if speed != 1.0:
        seg_v_filters.append(f"setpts=1/{speed:.4f}*PTS")

    seg_a_filters = _build_atempo(speed) if speed != 1.0 else []

    raw_duration = sum(s["end_sec"] - s["start_sec"] for s in segments)
    total_output_duration = raw_duration / speed

    n = len(segments)
    fc_parts: list[str] = []

    # split inputs so the same stream can be referenced N times
    fc_parts.append(f"[0:v]split={n}" + "".join(f"[vsrc{i}]" for i in range(n)))
    if not mute:
        fc_parts.append(f"[0:a]asplit={n}" + "".join(f"[asrc{i}]" for i in range(n)))

    concat_inputs = ""
    for i, seg in enumerate(segments):
        s, e = seg["start_sec"], seg["end_sec"]

        vf = f"trim=start={s}:end={e},setpts=PTS-STARTPTS"
        if seg_v_filters:
            vf += "," + ",".join(seg_v_filters)
        fc_parts.append(f"[vsrc{i}]{vf}[vseg{i}]")
        concat_inputs += f"[vseg{i}]"

        if not mute:
            af = f"atrim=start={s}:end={e},asetpts=PTS-STARTPTS"
            if seg_a_filters:
                af += "," + ",".join(seg_a_filters)
            fc_parts.append(f"[asrc{i}]{af}[aseg{i}]")
            concat_inputs += f"[aseg{i}]"

    if mute:
        fc_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=0[vc]")
        cur_v, cur_a = "vc", None
    else:
        fc_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[vc][ac]")
        cur_v, cur_a = "vc", "ac"
        # Volume must live inside the complex graph — a simple `-af` filter on a
        # complex-graph output is rejected by ffmpeg ("Invalid argument").
        if volume != 1.0:
            fc_parts.append(f"[{cur_a}]volume={volume:.3f}[avol]")
            cur_a = "avol"

    if fade and total_output_duration > 2:
        fc_parts.append(
            f"[{cur_v}]fade=t=in:st=0:d=1,"
            f"fade=t=out:st={total_output_duration - 1:.2f}:d=1[vfade]"
        )
        cur_v = "vfade"

    if wm_enabled:
        drawtext = _drawtext_expr(params["watermark"])
        if wm_rotation == 0:
            fc_parts.append(f"[{cur_v}]{drawtext}[outv]")
        else:
            rot_rad = f"{wm_rotation}*PI/180"
            fc_parts.append(
                f"color=c=black@0:s={canvas_w}x{canvas_h}:d={total_output_duration:.2f}[wmbg];"
                f"[wmbg]{drawtext}[wmtxt];"
                f"[wmtxt]rotate={rot_rad}:c=none[wmrot];"
                f"[{cur_v}][wmrot]overlay=0:0[outv]"
            )
    else:
        fc_parts.append(f"[{cur_v}]null[outv]")

    return ";".join(fc_parts), cur_a, total_output_duration


def _run_ffmpeg_with_progress(cmd: list, target_duration: float, progress_cb: Optional[Callable]) -> tuple[int, str]:
    """Run ffmpeg, parse -progress pipe output, call progress_cb(percent).

    Drains stderr via a background thread to avoid pipe-buffer deadlock on
    long/complex videos. Returns (returncode, stderr_tail).
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stderr_chunks: list[str] = []

    def _drain_stderr():
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_chunks.append(line)
            # Keep only the most recent ~64KB to bound memory
            if sum(len(c) for c in stderr_chunks) > 64 * 1024:
                # drop oldest half
                total = 0
                cutoff = 0
                for i, c in enumerate(stderr_chunks):
                    total += len(c)
                    if total > 32 * 1024:
                        cutoff = i
                        break
                del stderr_chunks[:cutoff]

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_ms="):
                try:
                    out_time_us = int(line.split("=", 1)[1])
                    if target_duration > 0 and progress_cb:
                        percent = min(99.0, out_time_us / (target_duration * 1_000_000) * 100)
                        progress_cb(percent)
                except ValueError:
                    pass
            elif line == "progress=end" and progress_cb:
                progress_cb(100.0)
    finally:
        proc.wait()
        t.join(timeout=5)

    stderr_tail = "".join(stderr_chunks)
    if proc.returncode != 0:
        logger.error(f"FFmpeg error (rc={proc.returncode}): {stderr_tail[-2000:]}")
    return proc.returncode, stderr_tail


def _burn_subtitle(video_path: str, params: dict, progress_cb: Optional[Callable] = None) -> Optional[str]:
    """Burn a re-based SRT onto the finished (already-trimmed) clip in a 2nd pass.

    Runs only when ``params["subtitle"]`` is enabled with a valid ``srt_path``.
    The SRT is still on the SOURCE timeline, so it is re-based against the cut
    ``segments`` + ``speed`` and rendered against the OUTPUT canvas (probed from
    ``video_path``) so position/size match the shortened, resized clip. Rewrites
    ``video_path`` in place. Returns an error string on failure, else ``None``
    (also ``None`` when there is nothing to burn).
    """
    sub = params.get("subtitle") or {}
    if not sub.get("enabled") or not sub.get("srt_path"):
        return None
    srt_path = sub["srt_path"]
    if not Path(srt_path).exists():
        return f"SRT not found: {srt_path}"

    from app.services import subtitle_renderer
    from app.services.fonts import ensure_font, FONTS_DIR

    try:
        meta = probe(video_path)
    except Exception as e:
        return f"Cannot probe clip for subtitle: {e}"
    play_w = meta.get("width") or 1920
    play_h = meta.get("height") or 1080

    # Resolve (and auto-download) the chosen font; "" => system default.
    font_name, font_file = ensure_font(sub.get("font", "") or "")
    style = subtitle_renderer.SubtitleStyle(
        font_name=font_name,
        font_size=int(sub.get("font_size", 56)),
        color=sub.get("color", "#FFFFFF"),
        outline_color=sub.get("outline_color", "#000000"),
        outline_width=int(sub.get("outline_width", 3)),
        shadow=int(sub.get("shadow", 0)),
        bold=bool(sub.get("bold", True)),
        italic=bool(sub.get("italic", False)),
        align=sub.get("align", "center"),
        x=float(sub.get("x", 0.5)),
        y=float(sub.get("y", 0.85)),
        opacity=float(sub.get("opacity", 1.0)),
        max_width=float(sub.get("max_width", 0.9)),
        font_file=font_file,
    )

    cut_segments = [(s["start_sec"], s["end_sec"]) for s in params.get("segments", [])]
    speed = params.get("speed", 1.0) or 1.0

    d = Path(video_path).parent
    ass_path = str(d / "subtitle.ass")
    try:
        subtitle_renderer.rebase_srt_to_ass(
            srt_path=srt_path,
            output_ass_path=ass_path,
            style=style,
            animation=sub.get("animation", "fade"),
            play_res_x=play_w,
            play_res_y=play_h,
            cut_segments=cut_segments,
            speed=speed,
        )
    except Exception as e:
        return f"SRT→ASS failed: {e}"

    vf = subtitle_renderer.build_subtitles_vf(ass_path, str(FONTS_DIR))

    tmp_out = str(d / "subtitled.mp4")
    # Honour the user's export quality on this 2nd encode too (else a small-bitrate
    # request would balloon back up at a fixed CRF).
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", vf,
        "-map", "0:v", "-map", "0:a?",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        *_quality_encode_args(params),
        "-c:a", "copy",
        "-movflags", "+faststart",
        tmp_out,
    ]
    logger.info(f"[trim] burning subtitle onto clip ({play_w}x{play_h}): {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    except subprocess.TimeoutExpired:
        return "Subtitle burn timed out"
    finally:
        try:
            if os.path.exists(ass_path):
                os.remove(ass_path)
        except Exception:
            pass

    if proc.returncode != 0 or not os.path.exists(tmp_out):
        tail = (proc.stderr or "").strip().splitlines()
        last = tail[-1] if tail else "unknown error"
        return f"Subtitle burn failed: {last[:300]}"

    os.replace(tmp_out, video_path)
    if progress_cb:
        progress_cb(100.0)
    return None


def trim(input_path: str, output_path: str, params: dict, progress_cb: Optional[Callable] = None) -> dict:
    """
    Run FFmpeg trim. Returns {success, duration, file_size, error?}.
    Handles single-segment (stream copy or re-encode) and multi-segment concat.
    """
    segments = params.get("segments") or []
    if not segments:
        return {"success": False, "error": "No segments provided"}

    quality = params.get("quality", "original")
    mute = params.get("mute", False)
    speed = params.get("speed", 1.0)
    volume = params.get("volume", 1.0)

    meta = probe(input_path)
    video_w = meta.get("width", 1920)
    video_h = meta.get("height", 1080)

    # --- encoding quality args ---
    if quality == "custom" and params.get("custom_bitrate_kbps"):
        video_bitrate_args = ["-b:v", f"{params['custom_bitrate_kbps']}k"]
        crf_args: list[str] = []
    else:
        crf_map = {"original": 12, "1080p": 18, "720p": 23, "480p": 28}
        preset_map = {"original": "slow", "1080p": "medium", "720p": "medium", "480p": "fast"}
        crf_args = ["-crf", str(crf_map.get(quality, 23)), "-preset", preset_map.get(quality, "medium")]
        video_bitrate_args = []

    # --- audio filters (volume + speed) ---
    audio_filters: list[str] = []
    if not mute:
        if volume != 1.0:
            audio_filters.append(f"volume={volume:.3f}")
        if speed != 1.0:
            audio_filters.extend(_build_atempo(speed))

    # When a subtitle burn (2nd pass) will follow, keep the 1st pass inside
    # 0..90% so the progress bar doesn't hit 100% and appear stuck while the
    # burn re-encodes.
    sub_cfg = params.get("subtitle") or {}
    will_burn = bool(sub_cfg.get("enabled") and sub_cfg.get("srt_path"))
    if will_burn and progress_cb:
        _outer_cb = progress_cb
        trim_cb: Optional[Callable] = lambda p: _outer_cb(min(90.0, p * 0.9))
    else:
        trim_cb = progress_cb

    # -----------------------------------------------------------------------
    # MULTI-SEGMENT path
    # -----------------------------------------------------------------------
    if len(segments) > 1:
        fc_str, audio_out_label, output_duration = _build_multiseg_filter_complex(
            params, segments, video_w, video_h
        )
        cmd = ["ffmpeg", "-y", "-i", input_path,
               "-filter_complex", fc_str, "-map", "[outv]"]

        if mute:
            cmd += ["-an"]
        else:
            if audio_out_label:
                cmd += ["-map", f"[{audio_out_label}]"]
            # NOTE: volume + speed (atempo) are applied INSIDE the complex graph
            # (per-segment atempo, post-concat volume). A simple `-af` here would
            # target a complex-graph output, which ffmpeg rejects. So no -af.
            cmd += ["-c:a", "aac", "-b:a", "192k"]

        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        cmd += crf_args + video_bitrate_args
        cmd += ["-avoid_negative_ts", "make_zero", "-movflags", "+faststart"]
        cmd += ["-progress", "pipe:1", "-nostats"]
        cmd.append(output_path)

        logger.info(f"FFmpeg multi-segment: {' '.join(cmd)}")
        rc, stderr_tail = _run_ffmpeg_with_progress(cmd, output_duration, trim_cb)

    # -----------------------------------------------------------------------
    # SINGLE-SEGMENT path
    # -----------------------------------------------------------------------
    else:
        seg = segments[0]
        start = seg["start_sec"]
        trim_duration = seg["end_sec"] - seg["start_sec"]
        output_duration = trim_duration / speed

        re_encode = needs_reencode(params)

        if re_encode:
            filter_str, use_fc = build_filter_chain(
                params, video_w, video_h, output_duration=output_duration, speed=speed
            )

            cmd = ["ffmpeg", "-y", "-ss", str(start), "-i", input_path, "-t", str(trim_duration)]

            if use_fc:
                cmd += ["-filter_complex", filter_str, "-map", "[outv]"]
                if not mute:
                    cmd += ["-map", "0:a?"]
            elif filter_str:
                cmd += ["-vf", filter_str]

            cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
            cmd += crf_args + video_bitrate_args

            if mute:
                cmd += ["-an"]
            else:
                if audio_filters:
                    cmd += ["-af", ",".join(audio_filters)]
                cmd += ["-c:a", "aac", "-b:a", "192k"]

            cmd += ["-avoid_negative_ts", "make_zero", "-movflags", "+faststart"]
            cmd += ["-progress", "pipe:1", "-nostats"]
            cmd.append(output_path)

            logger.info(f"FFmpeg re-encode: {' '.join(cmd)}")
            rc, stderr_tail = _run_ffmpeg_with_progress(cmd, output_duration, trim_cb)

        else:
            # Stream copy (fast path — no audio/video filters)
            cmd = [
                "ffmpeg", "-y", "-ss", str(start), "-i", input_path, "-t", str(trim_duration),
                "-c", "copy", "-avoid_negative_ts", "make_zero", "-movflags", "+faststart",
                "-progress", "pipe:1", "-nostats",
                output_path,
            ]
            logger.info(f"FFmpeg stream copy: {' '.join(cmd)}")
            rc, stderr_tail = _run_ffmpeg_with_progress(cmd, output_duration, trim_cb)

            if rc != 0:
                logger.warning("Stream copy failed, falling back to audio re-encode")
                cmd = [
                    "ffmpeg", "-y", "-ss", str(start), "-i", input_path, "-t", str(trim_duration),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-avoid_negative_ts", "make_zero", "-movflags", "+faststart",
                    "-progress", "pipe:1", "-nostats",
                    output_path,
                ]
                rc, stderr_tail = _run_ffmpeg_with_progress(cmd, output_duration, trim_cb)

    # -----------------------------------------------------------------------
    # Result
    # -----------------------------------------------------------------------
    if rc != 0:
        last_line = next(
            (ln for ln in reversed(stderr_tail.splitlines()) if ln.strip()),
            "FFmpeg encoding failed",
        )
        return {"success": False, "error": last_line[:300]}

    out = Path(output_path)
    if not out.exists():
        return {"success": False, "error": "Output file not created"}

    # 2nd pass: burn a re-based SRT onto the finished clip (no-op if disabled).
    if will_burn and progress_cb:
        progress_cb(92.0)
    sub_err = _burn_subtitle(output_path, params, progress_cb)
    if sub_err:
        return {"success": False, "error": sub_err}

    if progress_cb:
        progress_cb(100.0)

    return {
        "success": True,
        "duration": output_duration,
        "file_size": out.stat().st_size,
    }
