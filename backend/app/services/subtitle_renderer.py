"""SRT -> ASS converter with style + animation support.

Pipeline: parse SRT into segments, build a single-Style ASS file, prefix each
dialogue with override tags for position/anchor + chosen animation. ffmpeg
then burns the ASS via the `subtitles` filter.

Animation presets: none | fade | pop | slide_up | typewriter
"""
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple


ANIMATION_PRESETS = ("none", "fade", "pop", "slide_up", "typewriter")


@dataclass
class SubtitleStyle:
    font_name: str = "Arial"
    font_size: int = 56
    color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_width: int = 3
    shadow: int = 0
    bold: bool = True
    italic: bool = False
    align: str = "center"  # left | center | right
    x: float = 0.5         # center anchor, 0..1 of frame
    y: float = 0.85
    opacity: float = 1.0
    max_width: float = 1.0  # wrap box width as a fraction of frame (0..1)
    font_file: str = ""     # abs path to the TTF, used to measure wrap width


# ASS numpad-style alignment used as anchor when \pos is given.
# 4=ML  5=MC  6=MR — middle row keeps text vertically centered around py.
_ANCHOR_FOR_ALIGN = {"left": 4, "center": 5, "right": 6}

_SRT_TIME_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def parse_srt(srt_path: str) -> List[Tuple[float, float, str]]:
    """Parse SRT file into [(start_sec, end_sec, text), ...]."""
    raw = Path(srt_path).read_text(encoding="utf-8", errors="replace")
    raw = raw.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", raw.strip())
    out: List[Tuple[float, float, str]] = []
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        time_line_idx = -1
        for i, ln in enumerate(lines):
            if _SRT_TIME_RE.search(ln):
                time_line_idx = i
                break
        if time_line_idx < 0:
            continue
        m = _SRT_TIME_RE.search(lines[time_line_idx])
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = m.groups()
        start = int(h1) * 3600 + int(m1) * 60 + int(s1) + int(ms1.ljust(3, "0")) / 1000.0
        end = int(h2) * 3600 + int(m2) * 60 + int(s2) + int(ms2.ljust(3, "0")) / 1000.0
        text = "\n".join(lines[time_line_idx + 1:]).strip()
        # Strip common HTML-ish tags some SRTs include (<b>, <i>, <font ...>)
        text = re.sub(r"<[^>]+>", "", text)
        if text and end > start:
            out.append((start, end, text))
    return out


def _hex_to_ass_color(hex_color: str, opacity: float = 1.0) -> str:
    """#RRGGBB -> &HAABBGGRR (ASS BGR + alpha; alpha 00 = fully opaque)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    alpha = int(round((1.0 - max(0.0, min(1.0, opacity))) * 255))
    return f"&H{alpha:02X}{b.upper()}{g.upper()}{r.upper()}"


def _format_ass_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - h * 3600 - m * 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _escape_ass_text(text: str) -> str:
    """Escape ASS dialogue special chars. Backslash MUST come first."""
    out = text.replace("\\", "\\\\")
    out = out.replace("{", "\\{").replace("}", "\\}")
    out = out.replace("\n", "\\N")
    return out


def _typewriter_body(text: str, step_ms: int = 50) -> str:
    """Reveal text char-by-char via per-char \\alpha override.

    Each char starts invisible (\\alpha&HFF&) and animates to opaque
    (\\alpha&H00&) over `step_ms` starting at its slot. Newlines pass through
    as hard breaks without consuming a slot."""
    parts: List[str] = []
    t = 0
    for ch in text:
        if ch == "\n":
            parts.append("\\N")
            continue
        esc = _escape_ass_text(ch)
        parts.append(
            f"{{\\alpha&HFF&\\t({t},{t + step_ms},\\alpha&H00&)}}{esc}"
        )
        t += step_ms
    return "".join(parts)


def _measure_fn(font_file: str, font_size: int):
    """Return a callable str->width_px. Uses the real TTF via Pillow when
    available; otherwise falls back to a coarse per-char estimate so wrapping
    still happens (just less precisely) when the font can't be loaded."""
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(font_file or "DejaVuSans.ttf", font_size)
        return lambda s: font.getlength(s)
    except Exception:
        # ~0.5em average glyph advance — rough but keeps long lines wrapping.
        avg = font_size * 0.5
        return lambda s: len(s) * avg


def _wrap_text(text: str, font_file: str, font_size: int, max_width_px: int) -> str:
    """Re-wrap `text` so no line exceeds `max_width_px`, preserving any manual
    line breaks already present. Words longer than the limit are left intact
    (overflow) rather than split mid-word."""
    if max_width_px <= 0:
        return text
    measure = _measure_fn(font_file, font_size)
    out_lines: List[str] = []
    for para in text.split("\n"):
        words = para.split(" ")
        line = ""
        for w in words:
            candidate = w if not line else f"{line} {w}"
            if line and measure(candidate) > max_width_px:
                out_lines.append(line)
                line = w
            else:
                line = candidate
        out_lines.append(line)
    return "\n".join(out_lines)


def _build_dialogue_text(
    animation: str, px: int, py: int, anchor: int, text: str
) -> str:
    """Construct the full ASS dialogue Text field (override tags + body)."""
    if animation == "slide_up":
        # Move from (px, py+60) to (px, py) over 0..300ms; fade in 200ms.
        head = (
            f"{{\\an{anchor}\\move({px},{py + 60},{px},{py},0,300)\\fad(200,0)}}"
        )
        return head + _escape_ass_text(text)

    base = f"\\an{anchor}\\pos({px},{py})"
    if animation == "fade":
        head = "{" + base + "\\fad(300,300)}"
        return head + _escape_ass_text(text)
    if animation == "pop":
        head = (
            "{" + base
            + "\\fscx40\\fscy40\\t(0,250,\\fscx100\\fscy100)\\fad(150,200)}"
        )
        return head + _escape_ass_text(text)
    if animation == "typewriter":
        head = "{" + base + "}"
        return head + _typewriter_body(text)
    # "none" or unknown -> position only
    return "{" + base + "}" + _escape_ass_text(text)


def srt_to_ass(
    srt_path: str,
    output_ass_path: str,
    style: SubtitleStyle,
    animation: str,
    play_res_x: int,
    play_res_y: int,
    max_duration: float = 0.0,
) -> Dict[str, Any]:
    """Convert SRT to a single-Style ASS file with the chosen animation.

    `max_duration > 0` truncates dialogues ending past it (lines starting past
    it are dropped). Returns metadata (counts, last_end) for caller to surface
    a warning to the user.
    """
    if animation not in ANIMATION_PRESETS:
        animation = "fade"

    segments = parse_srt(srt_path)
    total_segments = len(segments)
    last_end = max((e for _, e, _ in segments), default=0.0)

    truncated = 0
    if max_duration > 0:
        kept: List[Tuple[float, float, str]] = []
        for s, e, t in segments:
            if s >= max_duration:
                truncated += 1
                continue
            if e > max_duration:
                e = max_duration
                truncated += 1
            kept.append((s, e, t))
        segments = kept

    px = int(round(max(0.0, min(1.0, style.x)) * play_res_x))
    py = int(round(max(0.0, min(1.0, style.y)) * play_res_y))
    anchor = _ANCHOR_FOR_ALIGN.get(style.align, 5)

    # Re-wrap each line to the chosen box width so the burned-in text breaks at
    # the same place the live preview does (browser wraps a max-width box; here
    # we measure with the same font + size and insert hard breaks to match).
    wrap_px = int(round(max(0.05, min(1.0, style.max_width)) * play_res_x))
    segments = [
        (s, e, _wrap_text(t, style.font_file, style.font_size, wrap_px))
        for s, e, t in segments
    ]

    primary = _hex_to_ass_color(style.color, style.opacity)
    outline = _hex_to_ass_color(style.outline_color, 1.0)
    # Secondary (used by karaoke) and Back (shadow) — keep sane defaults.
    secondary = "&H000000FF"
    back = "&H80000000"

    bold_v = -1 if style.bold else 0
    italic_v = -1 if style.italic else 0

    # BorderStyle=1 -> outline+shadow (vs 3 = opaque box).
    # MarginL/R/V are ignored when \pos override is used (always here).
    style_line = (
        f"Style: Default,{style.font_name},{style.font_size},"
        f"{primary},{secondary},{outline},{back},"
        f"{bold_v},{italic_v},0,0,100,100,0,0,"
        f"1,{style.outline_width},{style.shadow},2,30,30,30,1"
    )

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "ScaledBorderAndShadow: yes\n"
        "WrapStyle: 0\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{style_line}\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )

    body_lines: List[str] = [header]
    for start, end, text in segments:
        dialogue_text = _build_dialogue_text(animation, px, py, anchor, text)
        body_lines.append(
            f"Dialogue: 0,{_format_ass_time(start)},{_format_ass_time(end)},"
            f"Default,,0,0,0,,{dialogue_text}\n"
        )

    Path(output_ass_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_ass_path).write_text("".join(body_lines), encoding="utf-8")

    return {
        "output_path": output_ass_path,
        "total_segments": total_segments,
        "kept_segments": len(segments),
        "truncated_count": truncated,
        "last_end": last_end,
    }


def probe_srt(srt_path: str) -> Dict[str, Any]:
    """Lightweight inspect — used by upload endpoint to compute warnings.

    Returns segment count and last_end seconds.
    """
    segments = parse_srt(srt_path)
    return {
        "segment_count": len(segments),
        "last_end": max((e for _, e, _ in segments), default=0.0),
        "first_start": min((s for s, _, _ in segments), default=0.0),
    }
