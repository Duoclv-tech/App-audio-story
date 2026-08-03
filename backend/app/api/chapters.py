from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from loguru import logger
from datetime import datetime
from typing import List, Dict

from app.database import get_db
from app import models, schemas
from app.services.text_checker import TextChecker
from app.services.gemini_service import GeminiService
from app.services.openai_spellcheck import OpenAISpellChecker
from app.services.chapter_splitter import (
    split_chapters,
    read_text_from_file,
    read_folder_as_chapters,
)

router = APIRouter()
text_checker = TextChecker()

@router.get("/{chapter_id}", response_model=schemas.ChapterResponse)
async def get_chapter(chapter_id: str, db: Session = Depends(get_db)):
    """Get chapter by ID"""
    chapter = db.query(models.Chapter).filter(models.Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return chapter

@router.put("/{chapter_id}", response_model=schemas.ChapterResponse)
async def update_chapter(chapter_id: str, chapter_update: schemas.ChapterUpdate, db: Session = Depends(get_db)):
    """Update chapter content"""
    logger.info(f"Updating chapter {chapter_id}")

    # Get chapter from database
    chapter = db.query(models.Chapter).filter(models.Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    # Update fields if provided (allow empty string for title)
    if chapter_update.title is not None:
        chapter.title = chapter_update.title
        logger.debug(f"Updated title to: {chapter_update.title}")

    if chapter_update.content is not None:
        chapter.content = chapter_update.content
        chapter.char_count = len(chapter_update.content)

        # Check for censored words (if needed)
        # You can add logic here to check for censored words
        logger.debug(f"Updated content, new char count: {chapter.char_count}")

    if chapter_update.status is not None:
        chapter.status = chapter_update.status
        logger.debug(f"Updated status to: {chapter_update.status}")

    # Update timestamp
    chapter.updated_at = datetime.utcnow()

    # Save to database
    try:
        db.commit()
        db.refresh(chapter)
        logger.info(f"Chapter {chapter_id} updated successfully")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update chapter {chapter_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update chapter")

    return chapter

@router.delete("/{chapter_id}")
async def delete_chapter(chapter_id: str, db: Session = Depends(get_db)):
    """Delete chapter and related data"""
    logger.info(f"Deleting chapter {chapter_id}")

    # Get chapter from database
    chapter = db.query(models.Chapter).filter(models.Chapter.id == chapter_id).first()
    if not chapter:
        logger.warning(f"Chapter {chapter_id} not found")
        raise HTTPException(status_code=404, detail="Chapter not found")

    # Store chapter info for logging
    chapter_number = chapter.chapter_number
    story_id = chapter.story_id

    try:
        # Delete related audio files if exist
        audio_files = db.query(models.AudioFile).filter(models.AudioFile.chapter_id == chapter_id).all()
        if audio_files:
            for audio in audio_files:
                db.delete(audio)
            logger.info(f"Deleted {len(audio_files)} audio files for chapter {chapter_id}")

        # Delete related censored words if exist
        censored_words = db.query(models.CensoredWord).filter(models.CensoredWord.chapter_id == chapter_id).all()
        if censored_words:
            for word in censored_words:
                db.delete(word)
            logger.info(f"Deleted {len(censored_words)} censored words for chapter {chapter_id}")

        # Delete the chapter
        db.delete(chapter)
        db.commit()

        logger.info(f"Chapter {chapter_number} (ID: {chapter_id}) from story {story_id} deleted successfully")
        return {
            "message": "Chapter deleted successfully",
            "chapter_id": chapter_id,
            "chapter_number": chapter_number
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete chapter {chapter_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete chapter")


@router.post("/batch-update", response_model=List[schemas.ChapterResponse])
async def batch_update_chapters(
    chapter_updates: List[Dict],
    db: Session = Depends(get_db)
):
    """Batch update multiple chapters at once"""
    logger.info(f"Batch updating {len(chapter_updates)} chapters")

    updated_chapters = []
    errors = []

    for update_data in chapter_updates:
        chapter_id = update_data.get("id")
        if not chapter_id:
            errors.append({"error": "Missing chapter ID"})
            continue

        chapter = db.query(models.Chapter).filter(models.Chapter.id == chapter_id).first()
        if not chapter:
            errors.append({"chapter_id": chapter_id, "error": "Chapter not found"})
            continue

        try:
            # Update fields
            if "title" in update_data:
                chapter.title = update_data["title"]
            if "content" in update_data:
                chapter.content = update_data["content"]
                chapter.char_count = len(update_data["content"])
            if "status" in update_data:
                chapter.status = update_data["status"]

            chapter.updated_at = datetime.utcnow()
            updated_chapters.append(chapter)

        except Exception as e:
            errors.append({"chapter_id": chapter_id, "error": str(e)})

    # Commit all changes at once
    if updated_chapters:
        try:
            db.commit()
            for chapter in updated_chapters:
                db.refresh(chapter)
            logger.info(f"Successfully updated {len(updated_chapters)} chapters")
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to batch update chapters: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to batch update chapters")

    if errors:
        logger.warning(f"Batch update had {len(errors)} errors: {errors}")

    return updated_chapters


@router.get("/story/{story_id}/stats")
async def get_story_chapters_stats(story_id: str, db: Session = Depends(get_db)):
    """Get statistics for all chapters of a story"""
    chapters = db.query(models.Chapter).filter(models.Chapter.story_id == story_id).all()

    if not chapters:
        return {
            "story_id": story_id,
            "total_chapters": 0,
            "total_characters": 0,
            "average_characters": 0,
            "chapters_with_censored_words": 0,
            "total_censored_words": 0
        }

    total_chars = sum(ch.char_count for ch in chapters)
    chapters_with_censored = sum(1 for ch in chapters if ch.has_censored_words)
    total_censored = sum(ch.censored_count for ch in chapters)

    return {
        "story_id": story_id,
        "total_chapters": len(chapters),
        "total_characters": total_chars,
        "average_characters": total_chars // len(chapters) if chapters else 0,
        "chapters_with_censored_words": chapters_with_censored,
        "total_censored_words": total_censored,
        "chapters": [
            {
                "id": ch.id,
                "chapter_number": ch.chapter_number,
                "title": ch.title,
                "char_count": ch.char_count,
                "has_censored_words": ch.has_censored_words,
                "censored_count": ch.censored_count,
                "status": ch.status
            }
            for ch in chapters
        ]
    }


@router.get("/{chapter_id}/censored-words")
async def get_chapter_censored_words(chapter_id: str, db: Session = Depends(get_db)):
    """Get all censored words for a specific chapter"""
    logger.info(f"Getting censored words for chapter {chapter_id}")

    # Get chapter from database
    chapter = db.query(models.Chapter).filter(models.Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    # Get censored words from database
    censored_words = db.query(models.CensoredWord).filter(
        models.CensoredWord.chapter_id == chapter_id
    ).all()

    return {
        "chapter_id": chapter_id,
        "chapter_number": chapter.chapter_number,
        "censored_count": len(censored_words),
        "censored_words": [
            {
                "id": word.id,
                "word": word.word,
                "line_number": word.line_number,
                "context": word.context,
                "fixed": word.fixed,
                "word_type": word.word_type if hasattr(word, 'word_type') else 'censored',
                "suggested_replacement": word.suggested_replacement if hasattr(word, 'suggested_replacement') else None
            }
            for word in censored_words
        ]
    }


@router.post("/{chapter_id}/check-grammar")
async def check_chapter_grammar(
    chapter_id: str,
    request: schemas.CheckGrammarRequest,
    db: Session = Depends(get_db)
):
    """Check grammar/censored words for a specific chapter with provided content"""
    logger.info(f"Checking grammar for chapter {chapter_id} with custom content")

    # Get chapter from database to verify it exists
    chapter = db.query(models.Chapter).filter(models.Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    try:
        # Always use content from request body
        content_to_check = request.content

        # Find censored words (including banned words)
        censored_words = text_checker.find_censored_words(content_to_check, db=db)

        # Find stuck Vietnamese words
        stuck_words = text_checker.find_stuck_words(content_to_check)

        # Compile all issues
        all_issues = censored_words + stuck_words

        # Note: We don't save to database when checking custom content
        # This is a temporary check only

        logger.info(f"Found {len(censored_words)} censored words and {len(stuck_words)} stuck words in chapter {chapter_id}")

        total_issues = len(all_issues)
        return {
            "chapter_id": chapter_id,
            "chapter_number": chapter.chapter_number,
            "censored_count": len(censored_words),
            "stuck_words_count": len(stuck_words),
            "total_issues": total_issues,
            "censored_words": censored_words,
            "stuck_words": stuck_words,
            "all_issues": all_issues
        }

    except Exception as e:
        logger.error(f"Failed to check grammar for chapter {chapter_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to check grammar: {str(e)}")


@router.post("/{chapter_id}/check-grammar-save")
async def check_and_save_chapter_grammar(
    chapter_id: str,
    db: Session = Depends(get_db)
):
    """Check grammar and save results to database (for saved content)"""
    logger.info(f"Checking and saving grammar for chapter {chapter_id}")

    # Get chapter from database
    chapter = db.query(models.Chapter).filter(models.Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    try:
        # Delete existing censored words
        db.query(models.CensoredWord).filter(
            models.CensoredWord.chapter_id == chapter_id
        ).delete()

        # Find censored words (including banned words)
        censored_words = text_checker.find_censored_words(chapter.content, db=db)

        # Find stuck Vietnamese words
        stuck_words = text_checker.find_stuck_words(chapter.content)

        # Save censored words to database
        for word_info in censored_words:
            censored = models.CensoredWord(
                chapter_id=chapter_id,
                word=word_info['word'],
                line_number=word_info['line_number'],
                context=word_info['context'],
                word_type=word_info.get('word_type', 'censored'),
                suggested_replacement=word_info.get('suggested_replacement')
            )
            db.add(censored)

        # Save stuck words to database
        for word_info in stuck_words:
            censored = models.CensoredWord(
                chapter_id=chapter_id,
                word=word_info['word'],
                line_number=word_info['line_number'],
                context=word_info['context'],
                word_type='stuck',
                suggested_replacement=word_info['suggested_replacement']
            )
            db.add(censored)

        # Update chapter stats
        total_issues = len(censored_words) + len(stuck_words)
        chapter.censored_count = total_issues
        chapter.has_censored_words = total_issues > 0
        chapter.updated_at = datetime.utcnow()

        db.commit()

        logger.info(f"Saved {len(censored_words)} censored words and {len(stuck_words)} stuck words for chapter {chapter_id}")

        return {
            "chapter_id": chapter_id,
            "chapter_number": chapter.chapter_number,
            "censored_count": len(censored_words),
            "stuck_words_count": len(stuck_words),
            "total_issues": total_issues,
            "message": "Grammar check completed and saved"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to save grammar check for chapter {chapter_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to save grammar check")


@router.post("/story/{story_id}/check-grammar")
async def check_story_grammar(story_id: str, db: Session = Depends(get_db)):
    """Check grammar/censored words for all chapters of a story"""
    logger.info(f"Checking grammar for story {story_id}")

    # Get all chapters
    chapters = db.query(models.Chapter).filter(
        models.Chapter.story_id == story_id
    ).order_by(models.Chapter.chapter_number).all()

    if not chapters:
        raise HTTPException(status_code=404, detail="No chapters found for this story")

    results = {
        "story_id": story_id,
        "total_chapters": len(chapters),
        "chapters_checked": 0,
        "total_censored_words": 0,
        "chapter_results": []
    }

    try:
        for chapter in chapters:
            # Delete existing censored words
            db.query(models.CensoredWord).filter(
                models.CensoredWord.chapter_id == chapter.id
            ).delete()

            # Find censored words (including banned words)
            censored_words = text_checker.find_censored_words(chapter.content, db=db)

            # Save to database
            for word_info in censored_words:
                censored = models.CensoredWord(
                    chapter_id=chapter.id,
                    word=word_info['word'],
                    line_number=word_info['line_number'],
                    context=word_info['context'],
                    word_type=word_info.get('word_type', 'censored'),
                    suggested_replacement=word_info.get('suggested_replacement')
                )
                db.add(censored)

            # Update chapter
            chapter.censored_count = len(censored_words)
            chapter.has_censored_words = len(censored_words) > 0
            chapter.updated_at = datetime.utcnow()

            results["chapters_checked"] += 1
            results["total_censored_words"] += len(censored_words)
            results["chapter_results"].append({
                "chapter_id": chapter.id,
                "chapter_number": chapter.chapter_number,
                "censored_count": len(censored_words)
            })

        db.commit()

        logger.info(f"Checked {len(chapters)} chapters, found {results['total_censored_words']} censored words")

        return results

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to check grammar for story {story_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to check grammar")


@router.post("/story/{story_id}/create-chapter-zero")
async def create_chapter_zero(story_id: str, db: Session = Depends(get_db)):
    """Create Chapter 0 (intro chapter) for a story if it doesn't exist"""
    logger.info(f"Creating Chapter 0 for story {story_id}")

    # Check if story exists
    story = db.query(models.Story).filter(models.Story.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    # Check if Chapter 0 already exists
    existing_chapter = db.query(models.Chapter).filter(
        models.Chapter.story_id == story_id,
        models.Chapter.chapter_number == 0
    ).first()

    if existing_chapter:
        logger.info(f"Chapter 0 already exists for story {story_id}")
        return {
            "success": True,
            "message": "Chapter 0 already exists",
            "chapter": {
                "id": existing_chapter.id,
                "chapter_number": existing_chapter.chapter_number,
                "title": existing_chapter.title,
                "content": existing_chapter.content,
                "char_count": existing_chapter.char_count,
                "status": existing_chapter.status
            }
        }

    try:
        # Create Chapter 0 with empty content
        chapter_zero = models.Chapter(
            story_id=story_id,
            chapter_number=0,
            title="Giới thiệu",
            content="",
            char_count=0,
            has_censored_words=False,
            censored_count=0,
            status="pending"
        )
        db.add(chapter_zero)
        db.commit()
        db.refresh(chapter_zero)

        logger.info(f"Chapter 0 created successfully for story {story_id}")
        return {
            "success": True,
            "message": "Chapter 0 created successfully",
            "chapter": {
                "id": chapter_zero.id,
                "chapter_number": chapter_zero.chapter_number,
                "title": chapter_zero.title,
                "content": chapter_zero.content,
                "char_count": chapter_zero.char_count,
                "status": chapter_zero.status
            }
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create Chapter 0 for story {story_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create Chapter 0")


# --- Import content (paste / file / folder) — replaces the scraper flow ------

def _persist_imported_chapters(db, story, chapters, title=None):
    """Replace a story's chapters with imported ones and advance it to Edit.

    ``chapters`` is a list of dicts: {chapter_number, title, content}. Mirrors
    what the download worker did on a successful scrape (status/current_step).
    """
    chapters = [c for c in chapters if (c.get("content") or "").strip() or c.get("chapter_number") == 0]
    if not chapters:
        raise HTTPException(status_code=400, detail="Không tìm thấy nội dung chương nào để nhập")

    # Fresh import replaces any previous chapters (cascade removes their audio).
    db.query(models.Chapter).filter(models.Chapter.story_id == story.id).delete()

    for ch in chapters:
        content = (ch.get("content") or "")
        db.add(models.Chapter(
            story_id=story.id,
            chapter_number=ch.get("chapter_number", 1),
            title=(ch.get("title") or None),
            content=content,
            char_count=len(content),
            has_censored_words=False,
            censored_count=0,
            status="pending",
        ))

    if title:
        story.title = title
    story.status = "downloaded"
    story.current_step = 3  # move to the Edit step
    db.commit()
    return len(chapters)


def _get_story_or_404(db, story_id):
    story = db.query(models.Story).filter(models.Story.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    return story


@router.post("/story/{story_id}/import")
async def import_chapters(story_id: str, req: schemas.ImportChaptersRequest, db: Session = Depends(get_db)):
    """Import already-split chapters (from pasted text split on the client)."""
    story = _get_story_or_404(db, story_id)
    chapters = [
        {"chapter_number": c.chapter_number, "title": c.title, "content": c.content}
        for c in req.chapters
    ]
    try:
        count = _persist_imported_chapters(db, story, chapters, req.title)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Import chapters failed for story {story_id}: {e}")
        raise HTTPException(status_code=500, detail="Nhập nội dung thất bại")
    return {"success": True, "count": count}


@router.post("/story/{story_id}/import-file")
async def import_from_file(story_id: str, req: schemas.ImportPathRequest, db: Session = Depends(get_db)):
    """Read a .txt/.docx file, split it into chapters, and import."""
    story = _get_story_or_404(db, story_id)
    try:
        text = read_text_from_file(req.path)
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="Không tìm thấy file")
    except Exception as e:
        logger.error(f"Read file failed ({req.path}): {e}")
        raise HTTPException(status_code=400, detail="Không đọc được file (chỉ hỗ trợ .txt, .docx)")

    chapters = split_chapters(text)
    try:
        count = _persist_imported_chapters(db, story, chapters, req.title)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Import file failed for story {story_id}: {e}")
        raise HTTPException(status_code=500, detail="Nhập nội dung thất bại")
    return {"success": True, "count": count}


@router.post("/story/{story_id}/import-folder")
async def import_from_folder(story_id: str, req: schemas.ImportPathRequest, db: Session = Depends(get_db)):
    """Read a folder where each .txt/.docx file is one chapter, and import."""
    story = _get_story_or_404(db, story_id)
    try:
        chapters = read_folder_as_chapters(req.path)
    except NotADirectoryError:
        raise HTTPException(status_code=400, detail="Không tìm thấy thư mục")
    except Exception as e:
        logger.error(f"Read folder failed ({req.path}): {e}")
        raise HTTPException(status_code=400, detail="Không đọc được thư mục")

    if not chapters:
        raise HTTPException(status_code=400, detail="Thư mục không có file .txt hoặc .docx nào")
    try:
        count = _persist_imported_chapters(db, story, chapters, req.title)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Import folder failed for story {story_id}: {e}")
        raise HTTPException(status_code=500, detail="Nhập nội dung thất bại")
    return {"success": True, "count": count}


@router.post("/censored-word/{censored_word_id}/accept")
async def accept_replacement(censored_word_id: str, db: Session = Depends(get_db)):
    """Accept suggested replacement for a censored/banned word"""
    logger.info(f"Accepting replacement for censored word {censored_word_id}")

    # Get censored word
    censored_word = db.query(models.CensoredWord).filter(
        models.CensoredWord.id == censored_word_id
    ).first()

    if not censored_word:
        raise HTTPException(status_code=404, detail="Censored word not found")

    if not censored_word.suggested_replacement:
        raise HTTPException(status_code=400, detail="No suggested replacement available")

    # Get chapter
    chapter = db.query(models.Chapter).filter(
        models.Chapter.id == censored_word.chapter_id
    ).first()

    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    try:
        # Replace the word in chapter content
        old_word = censored_word.word
        new_word = censored_word.suggested_replacement

        # Use case-sensitive replacement
        chapter.content = chapter.content.replace(old_word, new_word)
        chapter.char_count = len(chapter.content)
        chapter.updated_at = datetime.utcnow()

        # Mark censored word as fixed
        censored_word.fixed = True

        # Update censored count
        unfixed_count = db.query(models.CensoredWord).filter(
            models.CensoredWord.chapter_id == chapter.id,
            models.CensoredWord.fixed == False
        ).count()
        chapter.censored_count = unfixed_count
        chapter.has_censored_words = unfixed_count > 0

        db.commit()

        logger.info(f"Replaced '{old_word}' with '{new_word}' in chapter {chapter.id}")

        return {
            "success": True,
            "message": f"Replaced '{old_word}' with '{new_word}'",
            "chapter_id": chapter.id,
            "remaining_censored_count": unfixed_count
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to accept replacement: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to accept replacement")


# ============== AI Grammar Check (OpenAI / Gemini) ==============

def _get_setting_value(db: Session, key: str):
    """Read a raw setting value from the DB (unwrapping JSON-quoted strings)."""
    setting = db.query(models.Setting).filter(models.Setting.setting_key == key).first()
    if setting and setting.setting_value:
        value = setting.setting_value
        if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        return value
    return None


async def run_ai_grammar_check(text: str, db: Session) -> Dict:
    """Run AI grammar/spell check using the configured provider.

    Provider is chosen by the ``AI_GRAMMAR_PROVIDER`` setting (default
    ``openai``). We prefer that provider but fall back to any other provider that
    has a key, so a single configured key always works. DeepSeek is served by the
    OpenAI-compatible ``OpenAISpellChecker`` with a different endpoint/model. All
    providers return the same result shape (see ``OpenAISpellChecker.check_grammar``).
    """
    from app.config import settings as cfg

    provider = (_get_setting_value(db, "AI_GRAMMAR_PROVIDER") or "openai").lower()
    keys = {
        "openai": _get_setting_value(db, "OPENAI_API_KEY") or cfg.OPENAI_API_KEY,
        "gemini": _get_setting_value(db, "GEMINI_API_KEY") or cfg.GEMINI_API_KEY,
        "deepseek": _get_setting_value(db, "DEEPSEEK_API_KEY") or cfg.DEEPSEEK_API_KEY,
    }

    # Priority order: selected provider first, the rest as fallback.
    order = [provider] + [p for p in ("openai", "gemini", "deepseek") if p != provider]

    for name in order:
        key = keys.get(name)
        if not key:
            continue
        if name == "openai":
            return OpenAISpellChecker(api_key=key).check_grammar(text)
        if name == "deepseek":
            checker = OpenAISpellChecker(
                api_key=key,
                model="deepseek-chat",
                base_url="https://api.deepseek.com/chat/completions",
                provider_label="DeepSeek",
            )
            return checker.check_grammar(text)
        if name == "gemini":
            return await GeminiService(api_key=key, db=db).check_grammar(text)

    return {
        "success": False,
        "error": "Chưa cấu hình API key nào (OpenAI / Gemini / DeepSeek). Vào Cài đặt để nhập key.",
    }


@router.post("/{chapter_id}/ai-grammar-check")
async def ai_grammar_check(
    chapter_id: str,
    request: schemas.CheckGrammarRequest,
    db: Session = Depends(get_db)
):
    """Check grammar using the configured AI provider (OpenAI or Gemini)"""
    logger.info(f"AI grammar check for chapter {chapter_id}")

    # Verify chapter exists
    chapter = db.query(models.Chapter).filter(models.Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    try:
        result = await run_ai_grammar_check(request.content, db)

        return {
            "chapter_id": chapter_id,
            "chapter_number": chapter.chapter_number,
            **result
        }

    except Exception as e:
        logger.error(f"AI grammar check failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI grammar check failed: {str(e)}")


@router.post("/{chapter_id}/ai-improve")
async def ai_improve_text(
    chapter_id: str,
    request: schemas.CheckGrammarRequest,
    db: Session = Depends(get_db)
):
    """Improve text using Gemini AI (for TTS readability)"""
    logger.info(f"AI improve text for chapter {chapter_id}")

    # Verify chapter exists
    chapter = db.query(models.Chapter).filter(models.Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    try:
        gemini = GeminiService(db=db)
        result = await gemini.improve_text(request.content)

        return {
            "chapter_id": chapter_id,
            "chapter_number": chapter.chapter_number,
            **result
        }

    except Exception as e:
        logger.error(f"AI improve text failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI improve text failed: {str(e)}")


@router.post("/story/{story_id}/ai-grammar-check")
async def ai_grammar_check_story(
    story_id: str,
    db: Session = Depends(get_db)
):
    """Check grammar for all chapters of a story using Gemini AI"""
    logger.info(f"AI grammar check for story {story_id}")

    # Get all chapters
    chapters = db.query(models.Chapter).filter(
        models.Chapter.story_id == story_id
    ).order_by(models.Chapter.chapter_number).all()

    if not chapters:
        raise HTTPException(status_code=404, detail="No chapters found")

    try:
        results = []
        total_issues = 0

        for chapter in chapters:
            if chapter.content and chapter.content.strip():
                result = await run_ai_grammar_check(chapter.content, db)
                chapter_result = {
                    "chapter_id": chapter.id,
                    "chapter_number": chapter.chapter_number,
                    "title": chapter.title,
                    **result
                }
                results.append(chapter_result)

                if result.get("success") and result.get("total_issues"):
                    total_issues += result["total_issues"]

        return {
            "story_id": story_id,
            "total_chapters": len(chapters),
            "checked_chapters": len(results),
            "total_issues": total_issues,
            "results": results
        }

    except Exception as e:
        logger.error(f"AI grammar check story failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI grammar check failed: {str(e)}")
