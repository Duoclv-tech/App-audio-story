"""
Export API endpoints
Handle document export (Word, etc.)
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from loguru import logger
import os

from app.database import get_db
from app import models, paths
from app.services.word_exporter import WordExporter
from app.services.output_delivery import deliver_final, safe_file_stem

router = APIRouter()


@router.get("/{story_id}/word")
async def export_to_word(story_id: str, db: Session = Depends(get_db)):
    """
    Export story chapters to Word document (.docx)

    Returns the Word file for download
    """
    try:
        # Get story
        story = db.query(models.Story).filter(models.Story.id == story_id).first()
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")

        # Get all chapters ordered by chapter number
        chapters = db.query(models.Chapter).filter(
            models.Chapter.story_id == story_id
        ).order_by(models.Chapter.chapter_number).all()

        if not chapters:
            raise HTTPException(status_code=400, detail="No chapters found to export")

        # Convert chapters to dict format
        chapters_data = [
            {
                'chapter_number': ch.chapter_number,
                'title': ch.title or f'Chương {ch.chapter_number}',
                'content': ch.content or ''
            }
            for ch in chapters
        ]

        # Create exporter and export
        exporter = WordExporter()
        filepath = exporter.export_story(
            story_id=story_id,
            title=story.title,
            chapters=chapters_data,
            author=story.author
        )

        # Check if file was created
        if not os.path.exists(filepath):
            raise HTTPException(status_code=500, detail="Failed to create export file")

        # Move the finished file into the user's configured output folder
        # (same delivery mechanism as audio/video), grouped under the story name.
        _name = safe_file_stem(story.title, story_id[:8])
        delivered = deliver_final(
            filepath, db, filename=f"{_name}.docx", subfolder=_name
        )

        logger.info(f"Exported Word document -> {delivered}")

        return {
            "path": delivered,
            "filename": os.path.basename(delivered),
            "folder": os.path.dirname(delivered),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting to Word: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{story_id}/txt")
async def export_to_txt(story_id: str, db: Session = Depends(get_db)):
    """
    Export story chapters to plain text file (.txt)

    Returns the text file for download
    """
    try:
        # Get story
        story = db.query(models.Story).filter(models.Story.id == story_id).first()
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")

        # Get all chapters ordered by chapter number
        chapters = db.query(models.Chapter).filter(
            models.Chapter.story_id == story_id
        ).order_by(models.Chapter.chapter_number).all()

        if not chapters:
            raise HTTPException(status_code=400, detail="No chapters found to export")

        # Separate Chapter 0 (intro) from other chapters
        intro_chapter = None
        regular_chapters = []
        for ch in chapters:
            if ch.chapter_number == 0:
                intro_chapter = ch
            else:
                regular_chapters.append(ch)

        # Build text content
        lines = []
        lines.append(story.title)
        lines.append("=" * len(story.title))
        if story.author:
            lines.append(f"Tác giả: {story.author}")
        lines.append(f"Số chương: {len(regular_chapters)}")
        lines.append("")

        # Add intro content if available
        if intro_chapter and intro_chapter.content:
            lines.append(intro_chapter.content)
            lines.append("")
        lines.append("")

        for ch in regular_chapters:
            title = ch.title or f'Chương {ch.chapter_number}'
            lines.append(title)
            lines.append("-" * len(title))
            lines.append("")
            if ch.content:
                lines.append(ch.content)
            lines.append("")
            lines.append("")

        content = "\n".join(lines)

        # Write to the internal exports dir first, then deliver to the user's
        # configured output folder (same mechanism as audio/video/Word).
        output_dir = str(paths.EXPORTS_DIR)
        os.makedirs(output_dir, exist_ok=True)

        _name = safe_file_stem(story.title, story_id[:8])
        filename = f"{_name}_{story_id[:8]}.txt"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        delivered = deliver_final(
            filepath, db, filename=f"{_name}.txt", subfolder=_name
        )

        logger.info(f"Exported TXT document -> {delivered}")

        return {
            "path": delivered,
            "filename": os.path.basename(delivered),
            "folder": os.path.dirname(delivered),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting to TXT: {e}")
        raise HTTPException(status_code=500, detail=str(e))
