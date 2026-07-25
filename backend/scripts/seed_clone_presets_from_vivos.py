"""
Seed additional default clone presets from the VIVOS corpus.

VIVOS is a free, open Vietnamese speech corpus (AILAB, VNUHCM) distributed
under CC BY-NC-SA 4.0 — https://creativecommons.org/licenses/by-nc-sa/4.0/
NON-COMMERCIAL USE ONLY. Unlike the VBEE-derived presets (a paid TTS engine's
own catalog), these presets embed real recordings of real people from an
academic corpus; the license terms travel with any audio generated from them.

For each chosen speaker we concatenate their first ``CLIPS_PER_SPEAKER``
sentence recordings (~8-20s combined, in the same ballpark as the VBEE
reference length) and encode to mp3. The transcript (``ref_text``) is the
corpus's own prompts joined together, so audio/text stay in sync exactly like
the VBEE presets need for OmniVoice clone mode.

Usage:
    1. Download the corpus once (~1.4GB), not committed to the repo:
       https://huggingface.co/datasets/AILAB-VNUHCM/vivos/resolve/main/data/vivos.tar.gz
       https://huggingface.co/datasets/AILAB-VNUHCM/vivos/resolve/main/data/prompts-train.txt.gz
    2. Place both files next to this script's ``--data-dir`` (default: a
       sibling ``vivos_data/`` folder, gitignored) and gunzip the prompts file.
    3. python backend/scripts/seed_clone_presets_from_vivos.py
"""
import argparse
import json
import re
import subprocess
import sys
import tarfile
import time
import unicodedata
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import paths  # noqa: E402

LICENSE_NOTE = "CC BY-NC-SA 4.0 (non-commercial) — https://creativecommons.org/licenses/by-nc-sa/4.0/"
CLIPS_PER_SPEAKER = 3

# (speaker_id, display name, gender) — picked to span the corpus' 46 train
# speakers (26 f / 20 m) roughly evenly; extend/replace freely with other
# VIVOSSPKnn ids (see train/genders.txt inside the tarball) for more voices.
SPEAKERS = [
    ("VIVOSSPK01", "Cẩm Tú", "f"),
    ("VIVOSSPK05", "Diễm My", "f"),
    ("VIVOSSPK10", "Gia Hân", "f"),
    ("VIVOSSPK16", "Thùy Dương", "f"),
    ("VIVOSSPK25", "Ánh Tuyết", "f"),
    ("VIVOSSPK34", "Vân Anh", "f"),
    ("VIVOSSPK40", "Ngọc Trâm", "f"),
    ("VIVOSSPK46", "Bảo Trâm", "f"),
    ("VIVOSSPK04", "Duy Khang", "m"),
    ("VIVOSSPK07", "Nhật Minh", "m"),
    ("VIVOSSPK12", "Thanh Sơn", "m"),
    ("VIVOSSPK18", "Vũ Long", "m"),
    ("VIVOSSPK22", "Đăng Khoa", "m"),
    ("VIVOSSPK27", "Chí Thanh", "m"),
    ("VIVOSSPK33", "Phúc Nguyên", "m"),
    ("VIVOSSPK39", "Hồng Sơn", "m"),
]


def _slugify(name: str) -> str:
    nfkd = unicodedata.normalize("NFD", name)
    ascii_ = "".join(c for c in nfkd if not unicodedata.combining(c))
    ascii_ = ascii_.replace("Đ", "D").replace("đ", "d")
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", ascii_.strip()).strip("-").lower()
    return s or "preset"


def _sentence_case(s: str) -> str:
    s = s.strip().lower()
    return s[:1].upper() + s[1:] if s else s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent / "vivos_data",
                     help="folder holding vivos.tar.gz + prompts-train.txt")
    ap.add_argument("--force", action="store_true", help="overwrite existing presets")
    args = ap.parse_args()

    tarball = args.data_dir / "vivos.tar.gz"
    prompts_path = args.data_dir / "prompts-train.txt"
    if not tarball.exists() or not prompts_path.exists():
        print(f"Missing corpus files under {args.data_dir} — see this script's docstring for download links.")
        return 1

    ffmpeg = paths.FFMPEG_BIN_DIR / "ffmpeg.exe"
    out_root = paths.DEFAULT_CLONE_PRESETS_DIR
    out_root.mkdir(parents=True, exist_ok=True)

    prompts = {}
    for line in prompts_path.read_text(encoding="utf-8").splitlines():
        clip_id, _, text = line.partition(" ")
        prompts[clip_id] = text

    tf = tarfile.open(tarball, mode="r:gz")
    ok = 0
    for index, (speaker_id, name, gender) in enumerate(SPEAKERS):
        preset_id = f"vivos-{index:02d}-{_slugify(name)}"
        dest = out_root / preset_id
        if (dest / "meta.json").exists() and not args.force:
            print(f"  [skip] {preset_id} (already exists)")
            ok += 1
            continue

        clip_ids = sorted(cid for cid in prompts if cid.startswith(speaker_id + "_"))[:CLIPS_PER_SPEAKER]
        if len(clip_ids) < CLIPS_PER_SPEAKER:
            print(f"  [FAIL] {speaker_id}: only {len(clip_ids)} clips found in prompts file")
            continue

        dest.mkdir(parents=True, exist_ok=True)
        wav_paths = []
        for cid in clip_ids:
            f = tf.extractfile(f"vivos/train/waves/{speaker_id}/{cid}.wav")
            wav_path = dest / f"_{cid}.wav"
            wav_path.write_bytes(f.read())
            wav_paths.append(wav_path)

        list_file = dest / "_concat.txt"
        list_file.write_text("\n".join(f"file '{p.name}'" for p in wav_paths), encoding="utf-8")
        audio_path = dest / "reference.mp3"
        subprocess.run(
            [str(ffmpeg), "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
             "-ac", "1", "-ar", "22050", "-b:a", "128k", str(audio_path)],
            cwd=str(dest), capture_output=True, check=True,
        )
        for p in wav_paths:
            p.unlink(missing_ok=True)
        list_file.unlink(missing_ok=True)

        ref_text = " ".join(_sentence_case(prompts[cid]) + "." for cid in clip_ids)
        meta = {
            "id": preset_id,
            "name": f"VIVOS - {name}",
            "audio_file": "reference.mp3",
            "ref_text": ref_text,
            "created_at": int(time.time()),
            "source": "vivos",
            "license": LICENSE_NOTE,
            "speaker_id": speaker_id,
            "gender": gender,
        }
        (dest / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [ ok ] {preset_id}  ({audio_path.stat().st_size // 1024} KB)")
        ok += 1

    tf.close()
    print(f"\nDone: {ok}/{len(SPEAKERS)} presets ready in {out_root}")
    return 0 if ok == len(SPEAKERS) else 2


if __name__ == "__main__":
    raise SystemExit(main())
