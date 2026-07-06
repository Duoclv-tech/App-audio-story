"""
Ollama Spell-Check Service
==========================

Calls a local Ollama instance to detect misspelled Vietnamese words in a
block of text. Returns a list of context-aware entries so callers can do
safe replacement: text.replace(hit["wrong"], hit["correct"]).

Each entry contains:
- wrong:       the error phrase WITH 1-2 surrounding words (from source text)
- correct:     the same phrase with the error fixed
- explanation: model's reasoning (forces it to think, reduces false positives)
- occurrences: how many times `wrong` appears in the full text

Minimal usage:

    from app.services.ollama_spellcheck import OllamaSpellChecker
    checker = OllamaSpellChecker()
    if checker.is_available():
        hits = checker.find_misspelled_words(story_text)
        for h in hits:
            print(f"{h['wrong']} -> {h['correct']}  ({h['explanation']})")
"""
from __future__ import annotations

import json
from typing import List, Dict, Optional

import requests
from loguru import logger


DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "gemma4:26b"
DEFAULT_TIMEOUT = 600          # seconds — local LLM on big text can be slow
DEFAULT_CHUNK_CHARS = 6000     # keep prompt small enough for fast passes

# JSON Schema for structured output. Three fields per entry:
#   wrong       — the error WITH 1-2 surrounding words (copy nguyên văn)
#   correct     — same phrase but with the error fixed
#   explanation — short reasoning why it's wrong (forces model to think)
SPELLCHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "misspelled": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "wrong": {"type": "string"},
                    "correct": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["wrong", "correct", "explanation"],
            },
        }
    },
    "required": ["misspelled"],
}

SYSTEM_PROMPT = (
    "Bạn là công cụ kiểm tra chính tả tiếng Việt cho văn bản truyện.\n\n"

    "NHIỆM VỤ: tìm các từ sai chính tả trong đoạn văn và trả về JSON.\n\n"

    "MỖI LỖI GỒM 3 TRƯỜNG:\n"
    "- wrong: từ sai KÈM 1-2 từ phía trước hoặc phía sau (copy nguyên văn "
    "từ đoạn văn, giữ nguyên dấu câu nếu có)\n"
    "- correct: cụm từ đã sửa đúng (cùng số từ với wrong)\n"
    "- explanation: giải thích ngắn gọn tại sao sai và sửa thành gì\n\n"

    "CÁC LOẠI LỖI CẦN BẮT:\n"
    "- Gõ nhầm, thừa/thiếu chữ cái: \"quaán\" → \"quán\"\n"
    "- Sai dấu thanh: \"aý\" → \"ấy\"\n"
    "- Nhầm từ đồng âm/gần âm theo ngữ cảnh: \"lầm việc\" → \"làm việc\", "
    "\"sử lý\" → \"xử lý\", \"giành dụm\" → \"dành dụm\"\n\n"

    "KHÔNG BẮT (bỏ qua hoàn toàn):\n"
    "- Tên riêng, tên nhân vật, địa danh, môn phái\n"
    "- Thuật ngữ võ hiệp, Hán Việt cổ: chưởng, huynh đệ, kiếm khí...\n"
    "- Xưng hô cổ: ngươi, hắn, nàng, lão, tiểu thư...\n"
    "- Phương ngữ hợp lệ: giời (Bắc), bả (Nam)...\n"
    "- Từ đúng chính tả dù ít gặp\n\n"

    "NẾU KHÔNG CHẮC CHẮN → BỎ QUA. Chỉ báo lỗi khi tự tin ≥90%.\n\n"

    "VÍ DỤ:\n"
    "Input: \"Anh ấy aý đi lầm việc rồi ghé quaán cà phê\"\n"
    "Output:\n"
    "{\"misspelled\": [\n"
    "  {\"wrong\": \"ấy aý đi\", \"correct\": \"ấy ấy đi\", "
    "\"explanation\": \"aý gõ nhầm dấu, đúng là ấy\"},\n"
    "  {\"wrong\": \"đi lầm việc\", \"correct\": \"đi làm việc\", "
    "\"explanation\": \"lầm (nhầm lẫn) sai ngữ cảnh, đúng là làm (lao động)\"},\n"
    "  {\"wrong\": \"ghé quaán cà\", \"correct\": \"ghé quán cà\", "
    "\"explanation\": \"quaán thừa chữ a, đúng là quán\"}\n"
    "]}\n\n"

    "Không có lỗi: {\"misspelled\": []}"
)

USER_PROMPT_TEMPLATE = (
    "Tìm các từ sai chính tả trong đoạn văn truyện sau:\n\n{text}"
)


class OllamaSpellChecker:
    """Thin wrapper around a local Ollama /api/generate endpoint."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    # -------------------------------------------------- availability check

    def is_available(self) -> bool:
        """Return True if Ollama is reachable AND the configured model is
        present in `ollama list`. Does not pull the model automatically.
        """
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            data = resp.json()
            models = {m.get("name", "") for m in data.get("models", [])}
            if self.model in models:
                return True
            # Ollama sometimes reports tags as "gemma4:26b" or bare "gemma4"
            # — accept either form.
            stem = self.model.split(":")[0]
            for name in models:
                if name == self.model or name.startswith(stem + ":"):
                    return True
            logger.warning(
                f"Ollama is up but model '{self.model}' not found. "
                f"Available: {sorted(models)}"
            )
            return False
        except requests.RequestException as e:
            logger.warning(f"Ollama not reachable at {self.base_url}: {e}")
            return False

    # -------------------------------------------------- single-chunk call

    def _generate(self, user_prompt: str) -> str:
        """Low-level /api/chat call — returns the assistant's message content.

        Uses Ollama structured-output: `format` is a JSON Schema so the
        decoder is grammar-constrained to schema-matching output. Chat
        endpoint (not /api/generate) so we can pass a dedicated system
        message, which instruction-tuned models follow more reliably.
        """
        resp = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "format": SPELLCHECK_SCHEMA,
                "options": {
                    # Fully deterministic for spell-check — no exploration.
                    "temperature": 0.0,
                    "top_p": 0.9,
                },
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return (data.get("message") or {}).get("content", "") or ""

    def _check_chunk(self, chunk_text: str) -> List[Dict]:
        """Run a single chunk through the model and parse the JSON reply.
        Returns a list of {wrong, correct, explanation} dicts.
        Malformed replies yield [].
        """
        if not chunk_text or not chunk_text.strip():
            return []

        user_prompt = USER_PROMPT_TEMPLATE.format(text=chunk_text)
        try:
            raw = self._generate(user_prompt)
        except requests.RequestException as e:
            logger.error(f"Ollama request failed: {e}")
            return []

        parsed = _safe_json_loads(raw)
        if parsed is None:
            logger.warning("Ollama returned unparseable JSON despite schema")
            logger.debug(f"raw response: {raw[:500]}")
            return []

        items = parsed.get("misspelled", [])
        if not isinstance(items, list):
            return []

        out: List[Dict] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            wrong = str(it.get("wrong", "")).strip()
            correct = str(it.get("correct", "")).strip()
            explanation = str(it.get("explanation", "")).strip()
            if not wrong or not correct:
                continue
            # Filters:
            # - wrong != correct (identity = no actual error)
            # - wrong phrase must exist in the source text
            # - explanation must be non-empty (forces model to reason)
            if wrong == correct:
                continue
            if wrong not in chunk_text:
                continue
            if not explanation:
                continue
            out.append({
                "wrong": wrong,
                "correct": correct,
                "explanation": explanation,
            })
        return out

    # -------------------------------------------------- public entry point

    def find_misspelled_words(
        self,
        text: str,
        chunk_chars: Optional[int] = DEFAULT_CHUNK_CHARS,
    ) -> List[Dict]:
        """Detect misspelled words in `text`.

        Args:
            text: Vietnamese text of any length.
            chunk_chars: Split text into chunks of at most this many chars
                before calling Ollama. Set to None to send the whole text
                in a single call (only do this if you know the model's
                context window fits it).

        Returns:
            List of {wrong, correct, explanation, occurrences} dicts.
            - wrong:       the error phrase with 1-2 surrounding words
            - correct:     the corrected phrase (same span)
            - explanation: model's reasoning for the correction
            - occurrences: how many times `wrong` appears in full text
            Deduplicated by (wrong, correct) pair.
        """
        if not text or not text.strip():
            return []

        if chunk_chars is None or len(text) <= chunk_chars:
            chunks = [text]
        else:
            chunks = _split_text(text, chunk_chars)

        logger.info(
            f"Ollama spell-check: {len(text):,} chars -> {len(chunks)} chunk(s) "
            f"via {self.model}"
        )

        all_hits: List[Dict] = []
        for i, chunk in enumerate(chunks, 1):
            logger.debug(f"  chunk {i}/{len(chunks)} ({len(chunk):,} chars)")
            hits = self._check_chunk(chunk)
            all_hits.extend(hits)

        # Dedup by (wrong, correct) pair — keep first explanation seen.
        seen = set()
        deduped: List[Dict] = []
        for hit in all_hits:
            key = (hit["wrong"], hit["correct"])
            if key in seen:
                continue
            seen.add(key)
            hit["occurrences"] = text.count(hit["wrong"])
            deduped.append(hit)

        deduped.sort(key=lambda r: r["wrong"])
        return deduped


# ---------------------------------------------------------- context helper

def _extract_context(text: str, word: str, radius: int = 15) -> str:
    """Return a snippet of `text` around the first occurrence of `word`.

    Grabs up to `radius` characters before and after the word, snapping
    to word boundaries so the snippet reads naturally. Used to give
    callers a precise location for context-aware replacement.
    """
    idx = text.find(word)
    if idx == -1:
        return ""
    start = max(0, idx - radius)
    end = min(len(text), idx + len(word) + radius)
    # Snap start forward to a space boundary (don't cut mid-word)
    if start > 0:
        sp = text.find(" ", start)
        if sp != -1 and sp < idx:
            start = sp + 1
    # Snap end backward to a space boundary
    if end < len(text):
        sp = text.rfind(" ", idx + len(word), end)
        if sp != -1:
            end = sp
    snippet = text[start:end].strip()
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


# ---------------------------------------------------------- parse helper

def _safe_json_loads(raw: str) -> Optional[Dict]:
    """Parse JSON forgivingly.

    First tries a direct `json.loads`. If that fails, scans for the first
    balanced top-level `{...}` block and parses that. This catches the
    case where a model spills trailing garbage after an otherwise valid
    JSON object (sometimes happens when the schema constraint relaxes
    near the end of generation).
    """
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Brace-matching scan: find the first '{', then walk forward tracking
    # nesting depth while honoring string literals (so braces inside
    # strings don't mess up the count).
    start = raw.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(raw)):
        c = raw[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                candidate = raw[start:i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    return None
    return None


# ---------------------------------------------------------- chunk helper

def _split_text(text: str, chunk_chars: int) -> List[str]:
    """Split text into <= chunk_chars pieces, preferring paragraph / newline
    boundaries so a single sentence isn't cut in half. Falls back to a hard
    char split if a paragraph itself is larger than chunk_chars.
    """
    if len(text) <= chunk_chars:
        return [text]

    paragraphs = text.split("\n")
    chunks: List[str] = []
    buf: List[str] = []
    buf_len = 0

    for para in paragraphs:
        # +1 for the newline we'll re-insert
        plen = len(para) + 1
        if buf_len + plen > chunk_chars and buf:
            chunks.append("\n".join(buf))
            buf = []
            buf_len = 0
        if plen > chunk_chars:
            # Single paragraph too big — hard-split it.
            if buf:
                chunks.append("\n".join(buf))
                buf = []
                buf_len = 0
            for i in range(0, len(para), chunk_chars):
                chunks.append(para[i:i + chunk_chars])
        else:
            buf.append(para)
            buf_len += plen

    if buf:
        chunks.append("\n".join(buf))

    return chunks
