"""Split user-provided text into chapters and read text from files/folders.

This backs the "paste / import file / import folder" input flow that replaced
the (now hidden) TruyenFull scraper. The whole downstream pipeline only needs
Chapter rows with content, so all these helpers do is turn arbitrary text into a
list of ``{chapter_number, title, content}`` dicts.
"""
import re
from pathlib import Path
from typing import List, Dict

# A line that starts a new chapter. Matches (case-insensitive), at the start of a
# line: an optional "Quyển N" prefix, then Chương/Chapter/Hồi, then a number.
#   "Chương 1", "Chương 1: Tựa đề", "Chapter 12 - Title", "Hồi 3", "Quyển 2 Chương 5"
_HEADING_RE = re.compile(
    r'^\s*(?:quyển\s+\d+\s*[-:.]?\s*)?'
    r'(?:chương|chuong|chapter|hồi|hoi)\s*[:.\-]?\s*(\d+)\b.*$',
    re.IGNORECASE,
)

_TEXT_EXTS = (".txt", ".docx")


def split_chapters(text: str) -> List[Dict]:
    """Split a full-story blob into chapters by detecting chapter headings.

    - Text before the first heading becomes an intro (chapter_number 0).
    - If no heading is found at all, the whole text is a single chapter.
    """
    if not text or not text.strip():
        return []

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    chapters: List[Dict] = []
    current: Dict = None
    pre_lines: List[str] = []

    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            if current is not None:
                chapters.append(current)
            current = {
                "chapter_number": int(m.group(1)),
                "title": line.strip(),
                "content_lines": [],
            }
        elif current is not None:
            current["content_lines"].append(line)
        else:
            pre_lines.append(line)

    if current is not None:
        chapters.append(current)

    # No headings detected -> treat the whole thing as one chapter.
    if not chapters:
        return [{"chapter_number": 1, "title": "Chương 1", "content": text.strip()}]

    result: List[Dict] = []
    pre_text = "\n".join(pre_lines).strip()
    if pre_text:
        result.append({"chapter_number": 0, "title": "Giới thiệu", "content": pre_text})
    for ch in chapters:
        result.append({
            "chapter_number": ch["chapter_number"],
            "title": ch["title"],
            "content": "\n".join(ch["content_lines"]).strip(),
        })
    return result


def read_text_from_file(path: str) -> str:
    """Read a .txt or .docx file into plain text."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(path)

    ext = p.suffix.lower()
    if ext == ".docx":
        from docx import Document
        doc = Document(str(p))
        return "\n".join(par.text for par in doc.paragraphs)

    # .txt (and any other text-like file): try a few encodings.
    for enc in ("utf-8", "utf-8-sig", "cp1258", "latin-1"):
        try:
            return p.read_text(encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return p.read_text(encoding="utf-8", errors="ignore")


def _natural_key(name: str):
    """Sort key so 'chuong-2' comes before 'chuong-10'."""
    return [int(tok) if tok.isdigit() else tok.lower() for tok in re.split(r"(\d+)", name)]


def read_folder_as_chapters(path: str) -> List[Dict]:
    """Read a folder where each .txt/.docx file is one chapter (sorted by name)."""
    p = Path(path)
    if not p.is_dir():
        raise NotADirectoryError(path)

    files = sorted(
        [f for f in p.iterdir() if f.is_file() and f.suffix.lower() in _TEXT_EXTS],
        key=lambda f: _natural_key(f.name),
    )
    chapters: List[Dict] = []
    for i, f in enumerate(files, start=1):
        content = read_text_from_file(str(f)).strip()
        chapters.append({"chapter_number": i, "title": f.stem, "content": content})
    return chapters
