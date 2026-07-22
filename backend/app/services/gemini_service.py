"""
Gemini AI Service
Integration with Google Gemini API for grammar checking
"""
import json
from typing import Optional, List, Dict
import requests
from loguru import logger
from sqlalchemy.orm import Session

from app import models
from app.config import settings
# Reuse OpenAI's spell-check prompt as the single source of truth so both
# providers apply the exact same rules and return the same shape.
from app.services.openai_spellcheck import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE


# Per-request chunk size for grammar checking. Most stories fit in ONE call;
# only longer text is split into 60k-char chunks. Gemini Flash has a large
# context window and 4096 output tokens are enough for a chunk's error list.
GRAMMAR_CHUNK_CHARS = 60000


def _split_text(text: str, chunk_chars: int) -> List[str]:
    """Split ``text`` into <= ``chunk_chars`` pieces along line boundaries."""
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


class GeminiService:
    """Service for interacting with Google Gemini API"""

    def __init__(self, api_key: Optional[str] = None, db: Optional[Session] = None):
        """
        Initialize Gemini service

        Args:
            api_key: Gemini API key (or from settings/db)
            db: Database session to load settings
        """
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        self.model = "models/gemini-3-flash-preview"  # Gemini 3 Flash Preview

        # Load API key from DB first, then .env
        if db:
            db_key = self._get_setting_from_db(db, 'GEMINI_API_KEY')
            self.api_key = api_key or db_key or settings.GEMINI_API_KEY
        else:
            self.api_key = api_key or settings.GEMINI_API_KEY

        if not self.api_key:
            logger.warning("No GEMINI_API_KEY configured!")

    def _get_setting_from_db(self, db: Session, key: str) -> Optional[str]:
        """Get setting value from database"""
        try:
            setting = db.query(models.Setting).filter(models.Setting.setting_key == key).first()
            if setting and setting.setting_value:
                value = setting.setting_value
                # Remove JSON quotes if present
                if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                return value
            return None
        except Exception as e:
            logger.warning(f"Error loading setting {key} from database: {e}")
            return None

    async def check_grammar(self, text: str, language: str = "Vietnamese") -> Dict:
        """
        Check grammar using Gemini AI

        Args:
            text: Text to check
            language: Language of the text

        Returns:
            Dict with grammar issues and suggestions
        """
        if not self.api_key:
            return {"success": False, "error": "GEMINI_API_KEY not configured"}
        if not text or not text.strip():
            return {
                "success": True, "provider": "gemini", "total_issues": 0,
                "spelling_errors": [], "watermarks": [], "total_watermarks": 0,
                "summary": "Không có nội dung để kiểm tra.",
            }

        url = f"{self.base_url}/{self.model}:generateContent?key={self.api_key}"

        # Split the FULL text into chunks so long stories are checked entirely
        # instead of only the first 8000 chars.
        chunks = _split_text(text, GRAMMAR_CHUNK_CHARS)
        logger.info(
            f"Gemini grammar check: {len(text):,} chars -> {len(chunks)} chunk(s) "
            f"via {self.model}"
        )

        spelling_errors: List[Dict] = []
        seen_err = set()
        truncated = False

        for idx, chunk in enumerate(chunks, 1):
            if not chunk or not chunk.strip():
                continue

            # Same prompt as OpenAI: SYSTEM_PROMPT as system instruction,
            # USER_PROMPT_TEMPLATE as the user turn. Output: {"misspelled": [...]}.
            user_prompt = USER_PROMPT_TEMPLATE.format(text=chunk)
            payload = {
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"parts": [{"text": user_prompt}]}],
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": 8192,
                    "responseMimeType": "application/json",
                },
            }

            try:
                logger.debug(f"Gemini grammar chunk {idx}/{len(chunks)}, {len(chunk)} chars")
                response = requests.post(url, json=payload, timeout=120)
                response.raise_for_status()
                result = response.json()
            except requests.exceptions.HTTPError as e:
                try:
                    error_detail = e.response.json()
                except Exception:
                    error_detail = str(e)
                logger.error(f"Gemini API error (chunk {idx}/{len(chunks)}): {error_detail}")
                # Surface deterministic auth/quota errors; keep partial results otherwise.
                if not spelling_errors:
                    return {"success": False, "error": str(error_detail)}
                truncated = True
                break
            except Exception as e:
                logger.error(f"Error calling Gemini API (chunk {idx}): {e}")
                if not spelling_errors:
                    return {"success": False, "error": str(e)}
                truncated = True
                break

            if "candidates" not in result or not result["candidates"]:
                continue

            content = result["candidates"][0]["content"]["parts"][0]["text"].strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse Gemini response as JSON (chunk {idx}): {content[:200]}")
                continue

            # Same output shape as OpenAI: {"misspelled": [{wrong, correct, explanation}]}
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
                # Only trust hits that actually appear in the text (guards against
                # the model paraphrasing instead of copying).
                if wrong not in chunk:
                    continue
                key = (wrong, correct)
                if key in seen_err:
                    continue
                seen_err.add(key)
                spelling_errors.append({
                    "original": wrong,
                    "suggestion": correct,
                    "context": str(it.get("explanation", "")).strip(),
                })

        summary = f"Gemini ({self.model}): tìm thấy {len(spelling_errors)} lỗi chính tả."
        if truncated:
            summary += " (Kiểm tra dừng giữa chừng do lỗi API, kết quả có thể chưa đầy đủ.)"

        return {
            "success": True,
            "provider": "gemini",
            "total_issues": len(spelling_errors),
            "spelling_errors": spelling_errors,
            "watermarks": [],
            "total_watermarks": 0,
            "summary": summary,
        }

    async def improve_text(self, text: str) -> Dict:
        """
        Suggest improvements for text (for TTS readability)

        Args:
            text: Text to improve

        Returns:
            Dict with improved text
        """
        if not self.api_key:
            return {"success": False, "error": "GEMINI_API_KEY not configured"}

        url = f"{self.base_url}/{self.model}:generateContent?key={self.api_key}"

        prompt = f"""Bạn là chuyên gia chỉnh sửa văn bản tiếng Việt cho audio book/TTS.

Hãy cải thiện đoạn văn bản sau để:
1. Sửa lỗi chính tả, ngữ pháp
2. Thêm dấu câu phù hợp để ngắt nghỉ khi đọc
3. Thay thế các từ viết tắt thành từ đầy đủ
4. Đảm bảo câu văn mạch lạc, dễ nghe

Trả về kết quả dưới dạng JSON:
{{
  "improved_text": "<văn bản đã cải thiện>",
  "changes_made": ["<mô tả thay đổi 1>", "<mô tả thay đổi 2>", ...],
  "change_count": <số thay đổi>
}}

Văn bản gốc:
---
{text[:4000]}
---

CHỈ trả về JSON, không có text khác."""

        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 4096
            }
        }

        try:
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()

            if "candidates" in result and len(result["candidates"]) > 0:
                content = result["candidates"][0]["content"]["parts"][0]["text"]

                # Parse JSON
                content = content.strip()
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

                try:
                    improve_result = json.loads(content)
                    improve_result["success"] = True
                    return improve_result
                except json.JSONDecodeError:
                    return {"success": False, "error": "Failed to parse response", "raw": content}
            else:
                return {"success": False, "error": "No response from Gemini"}

        except Exception as e:
            logger.error(f"Error improving text: {e}")
            return {"success": False, "error": str(e)}
