"""
Seed default clone presets from the VBEE catalog.

For each VBEE voice we ask the VBEE cloud engine to read ONE fixed reference
paragraph, download the resulting mp3, and write it as an OmniVoice clone preset
under ``paths.DEFAULT_CLONE_PRESETS_DIR``. Because we control the text we send,
the transcript (``ref_text`` in meta.json) is guaranteed to match the audio —
which is exactly what OmniVoice clone mode needs.

These bundled presets get copied into the writable ``clone_presets`` dir on the
user's first run (see ``clone_preset_store.seed_default_presets``), so every user
gets ~25 ready-made cloned voices without recording anything.

Usage (run from the repo root or backend/):
    python backend/scripts/seed_clone_presets_from_vbee.py            # all voices
    python backend/scripts/seed_clone_presets_from_vbee.py --limit 2  # test first 2
    python backend/scripts/seed_clone_presets_from_vbee.py --only hn_female_ngochuyen_full_48k-fhg
    python backend/scripts/seed_clone_presets_from_vbee.py --force    # overwrite existing

Credentials are read the same way the app reads them: from the settings table in
app.db (primary) with the .env values as fallback.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# Make ``app`` importable when run as a plain script.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import paths                                    # noqa: E402
from app import seed as app_seed                          # noqa: E402
from app.database import SessionLocal                    # noqa: E402
from app.services.clone_preset_store import _slugify      # noqa: E402
from app.services.tts_processor import VbeeTTSProcessor  # noqa: E402

# One fixed, neutral paragraph (~13s of speech) used as the clone reference for
# EVERY voice. Clean single-speaker narration is what makes a good reference.
REF_TEXT = (
    "Xin chào, đây là giọng đọc mẫu. Hôm nay trời trong xanh, "
    "gió nhẹ thổi qua hàng cây bên đường. Tôi đang thử chất lượng giọng nói "
    "để đọc truyện và thuyết minh nội dung một cách tự nhiên."
)

# (voice_code, display name) — the full 25-voice VN catalog.
#
# The codes are the authoritative catalog in app/seed.py (_VOICES); we deliberately
# keep an EXPLICIT list here (not derived) because several seed.py voices share a
# display name (two "SG - Thảo Trinh", two "HN - Anh Khôi", …) and we disambiguate
# them here so the clone dropdown shows unique labels and preset ids stay stable.
# ``_check_catalog_drift`` cross-checks these codes against app/seed.py so a code
# renamed there fails loudly instead of silently generating the wrong voice.
VOICES = [
    ("hn_female_ngochuyen_full_24k-st", "Ngọc Huyền 2.0"),
    ("hn_female_ngochuyen_full_48k-fhg", "HN - Ngọc Huyền"),
    ("hn_male_manhdung_full_24k-st", "Mạnh Dũng 2.0 (Beta)"),
    ("hn_male_minhquan_yt_24k-pre", "Minh Quân Pro (Beta)"),
    ("hn_female_nganha_child_22k-vc", "HN - Ngân Hà"),
    ("hn_male_minhquan_yt-stable", "HN - Minh Quân"),
    ("hn_male_vietbach_child_22k-vc", "HN - Việt Bách"),
    ("sg_female_tuongvy_call_44k-fhg", "SG - Tường Vy"),
    ("hn_female_hachi_book_22k-vc", "HN - Hà Chi"),
    ("sg_female_thaotrinh_full_44k-phg", "SG - Thảo Trinh"),
    ("sg_male_chidat_ebook_48k-phg", "SG - Chí Đạt"),
    ("hn_female_hermer_stor_48k-fhg", "HN - Ngọc Lan"),
    ("hn_female_lenka_stor_48k-phg", "HN - Nguyệt Dương"),
    ("hn_male_phuthang_stor80dt_48k-fhg", "HN - Anh Khôi"),
    ("hn_male_manhdung_news_48k-fhg", "HN - Mạnh Dũng"),
    ("hn_male_thanhlong_talk_48k-fhg", "HN - Thanh Long"),
    ("sg_female_thaotrinh_full_48k-fhg", "SG - Thảo Trinh (sách)"),
    ("hn_male_phuthang_news65dt_44k-fhg", "HN - Anh Khôi (tin tức)"),
    ("hue_female_huonggiang_full_48k-fhg", "Huế - Hương Giang"),
    ("hn_female_maiphuong_vdts_48k-fhg", "HN - Mai Phương"),
    ("sg_female_lantrinh_vdts_48k-fhg", "SG - Lan Trinh"),
    ("sg_male_trungkien_vdts_48k-fhg", "SG - Trung Kiên"),
    ("hue_male_duyphuong_full_48k-fhg", "Huế - Duy Phương"),
    ("sg_male_minhhoang_full_48k-fhg", "SG - Minh Hoàng"),
    ("hn_male_manhdung_news_48k-phg", "HN - Mạnh Dũng (QC)"),
]


def _check_catalog_drift() -> None:
    """Fail loudly if a voice code here no longer exists in app/seed.py."""
    seed_codes = {v[0] for v in app_seed._VOICES}
    missing = [code for code, _ in VOICES if code not in seed_codes]
    if missing:
        raise SystemExit(
            "voice codes not found in app/seed.py (catalog drift): " + ", ".join(missing))


async def seed_one(proc: VbeeTTSProcessor, index: int, code: str, name: str,
                   out_root: Path, force: bool) -> str:
    # Stable, collision-free id (some display names repeat across voices).
    preset_id = f"vbee-{index:02d}-{_slugify(name)}"
    dest = out_root / preset_id
    meta_path = dest / "meta.json"
    audio_path = dest / "reference.mp3"

    if meta_path.exists() and audio_path.exists() and not force:
        print(f"  [skip] {preset_id} (already exists)")
        return "skip"

    print(f"  [gen ] {preset_id}  voice={code}")
    tts = await proc.text_to_speech(
        text=REF_TEXT, voice_code=code, audio_type="mp3", bitrate=128, speed=1.0,
    )
    if not tts or not tts.get("request_id"):
        print(f"  [FAIL] {preset_id}: no request_id from VBEE")
        return "fail"

    link = await proc.get_audio_link(tts["request_id"])
    if not link:
        print(f"  [FAIL] {preset_id}: no audio link (timeout/failure)")
        return "fail"

    dest.mkdir(parents=True, exist_ok=True)
    if not await proc.download_audio(link, str(audio_path)):
        print(f"  [FAIL] {preset_id}: download failed")
        return "fail"

    meta = {
        "id": preset_id,
        "name": name,
        "audio_file": "reference.mp3",
        "ref_text": REF_TEXT,
        "created_at": int(time.time()),
        "source": "vbee",
        "voice_code": code,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [ ok ] {preset_id}  ({audio_path.stat().st_size // 1024} KB)")
    return "ok"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only seed the first N voices")
    ap.add_argument("--only", type=str, default=None, help="only seed this voice_code")
    ap.add_argument("--force", action="store_true", help="overwrite existing presets")
    args = ap.parse_args()

    _check_catalog_drift()

    out_root = paths.DEFAULT_CLONE_PRESETS_DIR
    out_root.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {out_root}")

    voices = list(enumerate(VOICES))
    if args.only:
        voices = [(i, v) for i, v in voices if v[0] == args.only]
        if not voices:
            print(f"No voice with code {args.only}")
            return 1
    elif args.limit is not None:
        voices = voices[: args.limit]

    db = SessionLocal()
    try:
        proc = VbeeTTSProcessor(db=db)
        if not proc.bearer_token or not proc.app_id:
            print("ERROR: VBEE credentials missing (VBEE_APP_ID / VBEE_BEARER_TOKEN).")
            return 1

        ok = 0
        for pos, (index, (code, name)) in enumerate(voices):
            status = "fail"
            try:
                status = await seed_one(proc, index, code, name, out_root, args.force)
            except Exception as e:  # keep going on a single-voice failure
                print(f"  [FAIL] index={index} code={code}: {e}")
            if status in ("ok", "skip"):
                ok += 1
            # Only rate-limit between ACTUAL VBEE calls — skips make none, and the
            # last voice has nothing after it to throttle against.
            if status == "ok" and pos < len(voices) - 1:
                await asyncio.sleep(2)

        print(f"\nDone: {ok}/{len(voices)} presets ready in {out_root}")
        return 0 if ok == len(voices) else 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
