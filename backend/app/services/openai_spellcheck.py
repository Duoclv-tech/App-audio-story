"""
OpenAI Spell-Check Service
===========================

Calls OpenAI API (gpt-4o-mini) to detect misspelled Vietnamese words.

Each entry contains:
- wrong:       the error phrase WITH 1-2 surrounding words
- correct:     the same phrase with the error fixed
- explanation: model's reasoning
- occurrences: how many times `wrong` appears in the full text

Usage:
    from app.services.openai_spellcheck import OpenAISpellChecker
    checker = OpenAISpellChecker()
    hits = checker.find_misspelled_words(story_text)
    for h in hits:
        print(f"{h['wrong']} -> {h['correct']}")
"""
from __future__ import annotations

import json
from typing import List, Dict, Optional

import requests
from loguru import logger


DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT = 120
DEFAULT_CHUNK_CHARS = 60000  # most stories fit in ONE call; longer text is split into 60k chunks

SYSTEM_PROMPT = (
    "Bạn là công cụ kiểm tra chính tả tiếng Việt cho văn bản truyện.\n\n"

    "NHIỆM VỤ: tìm các từ sai chính tả trong đoạn văn và trả về JSON.\n\n"

    "MỖI LỖI GỒM 3 TRƯỜNG:\n"
    "- wrong: CHỈ từ/cụm từ sai chính tả (copy nguyên văn từ đoạn văn, "
    "KHÔNG thêm từ xung quanh)\n"
    "- correct: từ/cụm từ đúng thay thế\n"
    "- explanation: giải thích ngắn gọn tại sao sai\n\n"

    "CÁC LOẠI LỖI CẦN BẮT:\n"
    "- Gõ nhầm, thừa/thiếu chữ cái: \"quaán\" → \"quán\"\n"
    "- Sai dấu thanh: \"aý\" → \"ấy\"\n"
    "- Nhầm từ đồng âm/gần âm theo ngữ cảnh: \"lầm việc\" → \"làm việc\", "
    "\"sử lý\" → \"xử lý\", \"giành dụm\" → \"dành dụm\"\n"
    "- Dính chữ thiếu dấu cách: \"kiếmtiền\" → \"kiếm tiền\"\n"
    "- Thừa ký tự lạ trong từ: \"d-ưng\" → \"dưng\", "
    "\"k.h.ỏ.a\" → \"khỏa\", \"đ..ĩ\" → \"đĩ\"\n"
    "- Từ không tồn tại trong tiếng Việt: \"hẵng\", \"chec\" → "
    "xem ngữ cảnh để gợi ý từ đúng\n\n"

    "KHÔNG BẮT (bỏ qua hoàn toàn):\n"
    "- Tên riêng, tên nhân vật, địa danh, môn phái\n"
    "- Thuật ngữ võ hiệp, Hán Việt cổ: chưởng, huynh đệ, kiếm khí...\n"
    "- Xưng hô cổ: ngươi, hắn, nàng, lão, tiểu thư...\n"
    "- Phương ngữ hợp lệ: giời (Bắc), bả (Nam)...\n"
    "- Từ đúng chính tả dù ít gặp\n"
    "- KHÔNG sửa ngữ pháp, cách dùng từ, hay thay từ đồng nghĩa. "
    "Chỉ sửa lỗi CHÍNH TẢ (gõ sai, thừa/thiếu ký tự, ký tự lạ).\n"
    "- KHÔNG xóa hay thêm từ. Số từ trong wrong và correct phải bằng nhau.\n\n"

    "NẾU KHÔNG CHẮC CHẮN → BỎ QUA. Chỉ báo lỗi khi tự tin ≥90%.\n\n"

    "VÍ DỤ:\n"
    "Input: \"Anh ấy aý đi lầm việc rồi ghé quaán cà phê. "
    "Tôi gõ cửa nhà hẵng còn đang ngủ. Tự d-ưng tôi nhớ.\"\n"
    "Output:\n"
    "{\"misspelled\": [\n"
    "  {\"wrong\": \"aý\", \"correct\": \"ấy\", "
    "\"explanation\": \"gõ nhầm dấu, đúng là ấy\"},\n"
    "  {\"wrong\": \"lầm việc\", \"correct\": \"làm việc\", "
    "\"explanation\": \"lầm (nhầm lẫn) sai ngữ cảnh, đúng là làm (lao động)\"},\n"
    "  {\"wrong\": \"quaán\", \"correct\": \"quán\", "
    "\"explanation\": \"thừa chữ a, đúng là quán\"},\n"
    "  {\"wrong\": \"hẵng\", \"correct\": \"hắn\", "
    "\"explanation\": \"hẵng không phải từ TV, ngữ cảnh đúng là hắn\"},\n"
    "  {\"wrong\": \"d-ưng\", \"correct\": \"dưng\", "
    "\"explanation\": \"thừa dấu gạch ngang, đúng là dưng\"}\n"
    "]}\n\n"

    "Không có lỗi: {\"misspelled\": []}"
)

USER_PROMPT_TEMPLATE = (
    "Tìm các từ sai chính tả trong đoạn văn truyện sau:\n\n{text}"
)


class OpenAISpellChecker:
    """Calls OpenAI chat completions API for Vietnamese spell-check."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        timeout: int = DEFAULT_TIMEOUT,
        base_url: str = "https://api.openai.com/v1/chat/completions",
        provider_label: str = "OpenAI",
    ):
        if api_key:
            self.api_key = api_key
        else:
            from app.config import settings
            self.api_key = settings.OPENAI_API_KEY
        self.model = model
        self.timeout = timeout
        # Endpoint + label let this class also drive OpenAI-compatible APIs
        # (e.g. DeepSeek) without duplicating the request/parse logic.
        self.base_url = base_url
        self.provider_label = provider_label

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _call_api(self, user_prompt: str) -> str:
        resp = requests.post(
            self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def _check_chunk(self, chunk_text: str) -> List[Dict]:
        if not chunk_text or not chunk_text.strip():
            return []

        user_prompt = USER_PROMPT_TEMPLATE.format(text=chunk_text)
        try:
            raw = self._call_api(user_prompt)
        except requests.RequestException as e:
            logger.error(f"OpenAI request failed: {e}")
            return []

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"OpenAI returned invalid JSON: {raw[:300]}")
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

    def find_misspelled_words(
        self,
        text: str,
        chunk_chars: Optional[int] = DEFAULT_CHUNK_CHARS,
    ) -> List[Dict]:
        if not text or not text.strip():
            return []

        if chunk_chars is None or len(text) <= chunk_chars:
            chunks = [text]
        else:
            chunks = _split_text(text, chunk_chars)

        logger.info(
            f"OpenAI spell-check: {len(text):,} chars -> {len(chunks)} chunk(s) "
            f"via {self.model}"
        )

        all_hits: List[Dict] = []
        for i, chunk in enumerate(chunks, 1):
            logger.debug(f"  chunk {i}/{len(chunks)} ({len(chunk):,} chars)")
            hits = self._check_chunk(chunk)
            all_hits.extend(hits)

        # Dedup by (wrong, correct) pair
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

    def check_grammar(self, text: str) -> Dict:
        """Spell-check ``text`` and return a result in the SAME shape as
        ``GeminiService.check_grammar`` so both providers can feed the exact
        same UI panel (fields: success, total_issues, spelling_errors[{original,
        suggestion, context}], watermarks, total_watermarks, summary).

        Unlike ``find_misspelled_words`` (which swallows API errors and returns
        an empty list for batch robustness), this surfaces auth/rate errors so
        the interactive Grammar-Check panel can show a real message instead of a
        misleading "0 lỗi".
        """
        if not self.api_key:
            return {"success": False, "error": f"{self.provider_label} API key not configured"}
        if not text or not text.strip():
            return {
                "success": True, "provider": self.provider_label.lower(), "total_issues": 0,
                "spelling_errors": [], "watermarks": [], "total_watermarks": 0,
                "summary": "Không có nội dung để kiểm tra.",
            }

        # Split the FULL text into chunks so long stories are checked entirely
        # instead of only the first slice.
        chunks = _split_text(text, DEFAULT_CHUNK_CHARS)
        logger.info(
            f"{self.provider_label} grammar check: {len(text):,} chars -> {len(chunks)} chunk(s) "
            f"via {self.model}"
        )

        spelling_errors: List[Dict] = []
        seen = set()
        truncated = False  # a chunk failed after we already had results

        for i, chunk in enumerate(chunks, 1):
            if not chunk or not chunk.strip():
                continue
            user_prompt = USER_PROMPT_TEMPLATE.format(text=chunk)
            try:
                raw = self._call_api(user_prompt)
            except requests.RequestException as e:
                detail = None
                resp = getattr(e, "response", None)
                if resp is not None:
                    try:
                        detail = resp.json()
                    except Exception:
                        detail = resp.text
                logger.error(f"{self.provider_label} grammar check failed (chunk {i}/{len(chunks)}): {detail or e}")
                # Surface auth/rate errors (which fail deterministically on the
                # first chunk) instead of a misleading "0 lỗi". If we already
                # gathered hits from earlier chunks, return them and flag partial.
                if not spelling_errors:
                    return {"success": False, "error": f"{self.provider_label} API error: {detail or e}"}
                truncated = True
                break

            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(f"OpenAI returned invalid JSON (chunk {i}): {raw[:200]}")
                continue

            items = parsed.get("misspelled", [])
            if not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                wrong = str(it.get("wrong", "")).strip()
                correct = str(it.get("correct", "")).strip()
                if not wrong or not correct or wrong == correct:
                    continue
                key = (wrong, correct)
                if key in seen:
                    continue
                seen.add(key)
                spelling_errors.append({
                    "original": wrong,
                    "suggestion": correct,
                    "context": str(it.get("explanation", "")).strip(),
                })

        summary = f"{self.provider_label} ({self.model}): tìm thấy {len(spelling_errors)} lỗi chính tả."
        if truncated:
            summary += " (Kiểm tra dừng giữa chừng do lỗi API, kết quả có thể chưa đầy đủ.)"

        return {
            "success": True,
            "provider": self.provider_label.lower(),
            "total_issues": len(spelling_errors),
            "spelling_errors": spelling_errors,
            "watermarks": [],
            "total_watermarks": 0,
            "summary": summary,
        }


def _split_text(text: str, chunk_chars: int) -> List[str]:
    if len(text) <= chunk_chars:
        return [text]

    paragraphs = text.split("\n")
    chunks: List[str] = []
    buf: List[str] = []
    buf_len = 0

    for para in paragraphs:
        plen = len(para) + 1
        if buf_len + plen > chunk_chars and buf:
            chunks.append("\n".join(buf))
            buf = []
            buf_len = 0
        if plen > chunk_chars:
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
