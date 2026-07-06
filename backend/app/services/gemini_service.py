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

        url = f"{self.base_url}/{self.model}:generateContent?key={self.api_key}"

        prompt = f"""Đọc kĩ từng dòng và check chính tả văn bản tiếng Việt.

Nhiệm vụ:
1. Liệt kê các từ sai chính tả và gợi ý chỉnh sửa
2. Tìm các watermark (tên website, nguồn truyện, quảng cáo ẩn trong text) và liệt kê

Trả về kết quả dưới dạng JSON với format:
{{
  "total_issues": <tổng số lỗi chính tả>,
  "spelling_errors": [
    {{
      "original": "<từ sai>",
      "suggestion": "<từ đúng>",
      "context": "<đoạn văn chứa từ sai để dễ tìm>"
    }}
  ],
  "watermarks": [
    {{
      "text": "<nội dung watermark>",
      "context": "<đoạn văn chứa watermark>"
    }}
  ],
  "total_watermarks": <số watermark tìm thấy>,
  "summary": "<tóm tắt ngắn gọn>"
}}

Văn bản cần kiểm tra:
---
{text[:8000]}
---

CHỈ trả về JSON, không có text khác."""

        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 2048
            }
        }

        try:
            logger.debug(f"Checking grammar with Gemini, text length: {len(text)}")
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()

            # Extract text from response
            if "candidates" in result and len(result["candidates"]) > 0:
                content = result["candidates"][0]["content"]["parts"][0]["text"]

                # Parse JSON from response
                # Remove markdown code blocks if present
                content = content.strip()
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

                try:
                    grammar_result = json.loads(content)
                    grammar_result["success"] = True
                    return grammar_result
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse Gemini response as JSON: {content[:200]}")
                    return {
                        "success": True,
                        "total_issues": 0,
                        "issues": [],
                        "overall_quality": "unknown",
                        "summary": content,
                        "raw_response": content
                    }
            else:
                return {"success": False, "error": "No response from Gemini"}

        except requests.exceptions.HTTPError as e:
            logger.error(f"Gemini API error: {e}")
            try:
                error_detail = e.response.json()
                return {"success": False, "error": str(error_detail)}
            except:
                return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"Error calling Gemini API: {e}")
            return {"success": False, "error": str(e)}

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
