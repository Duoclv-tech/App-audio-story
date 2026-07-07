"""
Export API endpoints
Handle document export (Word, etc.)
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from loguru import logger
import os

from app.database import get_db
from app import models, paths
from app.services.word_exporter import WordExporter

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

        # Get filename for download
        filename = os.path.basename(filepath)

        logger.info(f"Exporting Word document: {filename}")

        return FileResponse(
            path=filepath,
            filename=filename,
            media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )

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

        # Save to file
        output_dir = str(paths.EXPORTS_DIR)
        os.makedirs(output_dir, exist_ok=True)

        safe_title = "".join(c for c in story.title if c.isalnum() or c in (' ', '-', '_')).strip()[:50]
        filename = f"{safe_title}_{story_id[:8]}.txt"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        logger.info(f"Exporting TXT document: {filename}")

        return FileResponse(
            path=filepath,
            filename=filename,
            media_type='text/plain; charset=utf-8'
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting to TXT: {e}")
        raise HTTPException(status_code=500, detail=str(e))
