"""
Text Checker Service
Service for checking text content quality and finding censored words
"""
import re
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from sqlalchemy.orm import Session
from loguru import logger

from app import models


class TextChecker:
    """Service for checking text quality and censored words"""

    # Common Vietnamese banned/sensitive words that might be censored
    BANNED_WORDS = [
        "chết", "giết", "đánh", "đập", "máu", "xác", "thây", "thi thể",
        "khốn", "đểu", "mẹ", "bố", "cha", "cặc", "lồn", "đít", "cứt",
        "dâm", "dục", "sex", "nude", "porn", "fuck", "shit", "damn",
        "chính trị", "cộng sản", "đảng", "nhà nước", "cách mạng",
        "ma túy", "heroin", "cocaine", "cần sa", "thuốc phiện"
    ]

    def __init__(self):
        """Initialize text checker"""
        # Pattern to find censored words (e.g., t* c*ng, m*t, etc.)
        self.censored_pattern = re.compile(r'\b\w*\*+\w*\b')

        # Pattern to find special characters that might indicate censoring
        self.special_chars_pattern = re.compile(r'[#@$%&*]+')

    def find_censored_words(self, text: str, db: Session = None) -> List[Dict]:
        """
        Find censored words and banned words in text

        Args:
            text: Text content to check
            db: Database session for checking banned words

        Returns:
            List of dictionaries containing censored word info
        """
        censored_words = []
        lines = text.split('\n')

        for line_num, line in enumerate(lines, 1):
            # Find words with asterisks
            matches = self.censored_pattern.finditer(line)
            for match in matches:
                word = match.group()
                start = max(0, match.start() - 20)
                end = min(len(line), match.end() + 20)
                context = line[start:end]

                censored_words.append({
                    'word': word,
                    'line_number': line_num,
                    'position': match.start(),
                    'context': f"...{context}...",
                    'word_type': 'censored',
                    'suggested_replacement': None
                })

            # Find suspicious special character sequences
            special_matches = self.special_chars_pattern.finditer(line)
            for match in special_matches:
                # Check if it's likely a censored word (surrounded by letters)
                if match.start() > 0 and match.end() < len(line):
                    before = line[match.start() - 1] if match.start() > 0 else ''
                    after = line[match.end()] if match.end() < len(line) else ''

                    if before.isalpha() or after.isalpha():
                        word = line[max(0, match.start() - 5):min(len(line), match.end() + 5)]
                        start = max(0, match.start() - 20)
                        end = min(len(line), match.end() + 20)
                        context = line[start:end]

                        censored_words.append({
                            'word': word.strip(),
                            'line_number': line_num,
                            'position': match.start(),
                            'context': f"...{context}...",
                            'word_type': 'censored',
                            'suggested_replacement': None
                        })

        # Check for banned words from database
        if db:
            banned_words_list = self.find_banned_words(text, db)
            censored_words.extend(banned_words_list)

        return censored_words

    def find_banned_words(self, text: str, db: Session) -> List[Dict]:
        """
        Find banned words from database in text

        Args:
            text: Text content to check
            db: Database session

        Returns:
            List of dictionaries containing banned word info
        """
        banned_words_found = []
        lines = text.split('\n')

        # Get all active banned words from database
        banned_words = db.query(models.BannedWord).filter(
            models.BannedWord.is_active == True
        ).all()

        for banned in banned_words:
            # Search for this banned word in text (case-insensitive)
            pattern = re.compile(re.escape(banned.banned_word), re.IGNORECASE)

            for line_num, line in enumerate(lines, 1):
                matches = pattern.finditer(line)
                for match in matches:
                    word = match.group()
                    start = max(0, match.start() - 20)
                    end = min(len(line), match.end() + 20)
                    context = line[start:end]

                    banned_words_found.append({
                        'word': word,
                        'line_number': line_num,
                        'position': match.start(),
                        'context': f"...{context}...",
                        'word_type': 'banned',
                        'suggested_replacement': banned.replacement_word
                    })

        return banned_words_found

    def find_stuck_words(self, text: str) -> List[Dict]:
        """
        Find Vietnamese words that are stuck together (missing spaces)

        Args:
            text: Text content to check

        Returns:
            List of dictionaries containing stuck word info
        """
        stuck_words = []
        lines = text.split('\n')

        # Common Vietnamese stuck word patterns
        # These are common cases where words might be stuck together
        stuck_patterns = [
            # Common stuck patterns with pronouns
            (r'(tôilà|tôiđang|tôiđã|tôisẽ)', 'tôi là|tôi đang|tôi đã|tôi sẽ'),
            (r'(anhấy|anhta|anhlà|anhđang)', 'anh ấy|anh ta|anh là|anh đang'),
            (r'(cônhấy|côta|côlà|côđang)', 'cô ấy|cô ta|cô là|cô đang'),
            (r'(nólà|nóđang|nóđã|nósẽ)', 'nó là|nó đang|nó đã|nó sẽ'),

            # Common stuck patterns with verbs
            (r'(đãlà|đãđi|đãvề|đãđến)', 'đã là|đã đi|đã về|đã đến'),
            (r'(đanglà|đangđi|đangvề|đanglàm)', 'đang là|đang đi|đang về|đang làm'),
            (r'(sẽlà|sẽđi|sẽvề|sẽđến)', 'sẽ là|sẽ đi|sẽ về|sẽ đến'),

            # Common stuck patterns with conjunctions
            (r'(vàlà|vàđang|vàđã|vàsẽ)', 'và là|và đang|và đã|và sẽ'),
            (r'(nhưnglà|nhưngđang|nhưngđã)', 'nhưng là|nhưng đang|nhưng đã'),
            (r'(nênlà|nênđi|nênvề)', 'nên là|nên đi|nên về'),

            # Common stuck patterns with question words
            (r'(saođang|saolà|saođi)', 'sao đang|sao là|sao đi'),
            (r'(thếnào|thếlà|thếđấy)', 'thế nào|thế là|thế đấy'),

            # Numbers stuck with words
            (r'(\d+người|\d+cái|\d+con|\d+chiếc)', r'\1 người|\1 cái|\1 con|\1 chiếc'),

            # Common Vietnamese word combinations that should be separated
            (r'(khônghiểu|khôngbiết|khôngthể)', 'không hiểu|không biết|không thể'),
            (r'(cũngkhông|cũngchẳng|cũngđã)', 'cũng không|cũng chẳng|cũng đã'),
            (r'(rấtlà|rấtnhiều|rấtít)', 'rất là|rất nhiều|rất ít'),
            (r'(quálà|quánhiều|quáít)', 'quá là|quá nhiều|quá ít'),
        ]

        for line_num, line in enumerate(lines, 1):
            # Check for each stuck pattern
            for pattern, suggestion in stuck_patterns:
                matches = re.finditer(pattern, line, re.IGNORECASE)
                for match in matches:
                    word = match.group()
                    start = max(0, match.start() - 20)
                    end = min(len(line), match.end() + 20)
                    context = line[start:end]

                    # Get suggested replacement
                    suggested = suggestion
                    if '|' in suggestion:
                        # Pick the first suggestion if multiple are given
                        suggested = suggestion.split('|')[0]

                    stuck_words.append({
                        'word': word,
                        'line_number': line_num,
                        'position': match.start(),
                        'context': f"...{context}...",
                        'word_type': 'stuck',
                        'suggested_replacement': suggested
                    })

            # Also check for very long words that might be stuck words
            # Vietnamese words are typically 1-7 characters, longer might be stuck
            long_word_pattern = re.compile(r'\b[a-zàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]{8,}\b', re.IGNORECASE)
            long_matches = long_word_pattern.finditer(line)
            for match in long_matches:
                word = match.group()
                # Skip if it's likely an English word or proper noun
                if not any(c in word.lower() for c in 'àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ'):
                    continue

                start = max(0, match.start() - 20)
                end = min(len(line), match.end() + 20)
                context = line[start:end]

                stuck_words.append({
                    'word': word,
                    'line_number': line_num,
                    'position': match.start(),
                    'context': f"...{context}...",
                    'word_type': 'stuck',
                    'suggested_replacement': None  # No automatic suggestion for long words
                })

        return stuck_words

    def check_text_quality(self, text: str) -> Dict:
        """
        Check overall text quality

        Args:
            text: Text to analyze

        Returns:
            Dictionary with quality metrics
        """
        lines = text.split('\n')
        words = text.split()
        chars_no_space = text.replace(' ', '').replace('\n', '')

        # Calculate metrics
        metrics = {
            'total_characters': len(chars_no_space),
            'total_words': len(words),
            'total_lines': len(lines),
            'avg_line_length': len(chars_no_space) / len(lines) if lines else 0,
            'has_minimum_content': len(chars_no_space) >= 9500,  # Standard chapter should have 9500+ chars
            'empty_lines': sum(1 for line in lines if not line.strip()),
            'duplicate_lines': self._count_duplicate_lines(lines),
            'quality_score': 0  # Will be calculated
        }

        # Calculate quality score (0-100)
        score = 100

        # Deduct for low content
        if metrics['total_characters'] < 9500:
            score -= 20

        # Deduct for too many empty lines
        empty_ratio = metrics['empty_lines'] / metrics['total_lines'] if metrics['total_lines'] > 0 else 0
        if empty_ratio > 0.3:
            score -= 10

        # Deduct for duplicate content
        if metrics['duplicate_lines'] > 5:
            score -= 15

        metrics['quality_score'] = max(0, score)
        return metrics

    def _count_duplicate_lines(self, lines: List[str]) -> int:
        """Count number of duplicate lines"""
        seen = set()
        duplicates = 0

        for line in lines:
            line_clean = line.strip()
            if line_clean and line_clean in seen:
                duplicates += 1
            seen.add(line_clean)

        return duplicates

    def check_chapter(self, chapter_id: str, db: Session) -> Dict:
        """
        Check a single chapter for quality and censored words

        Args:
            chapter_id: Chapter ID to check
            db: Database session

        Returns:
            Dictionary with check results
        """
        try:
            # Get chapter from database
            chapter = db.query(models.Chapter).filter(models.Chapter.id == chapter_id).first()
            if not chapter:
                logger.error(f"Chapter {chapter_id} not found")
                return {"error": "Chapter not found"}

            # Find censored words (including banned words from database)
            censored_words = self.find_censored_words(chapter.content, db=db)

            # Find numbering lines (standalone numbers)
            numbering_lines = self.find_numbering_lines(chapter.content)

            # Check text quality
            quality_metrics = self.check_text_quality(chapter.content)

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

            # Update chapter with check results
            chapter.censored_count = len(censored_words)
            chapter.has_censored_words = len(censored_words) > 0

            db.commit()

            return {
                "chapter_id": chapter_id,
                "chapter_number": chapter.chapter_number,
                "censored_count": len(censored_words),
                "censored_words": censored_words,
                "numbering_lines": numbering_lines,
                "numbering_count": len(numbering_lines),
                "quality_metrics": quality_metrics,
                "status": "completed"
            }

        except Exception as e:
            logger.error(f"Error checking chapter {chapter_id}: {e}")
            db.rollback()
            return {"error": str(e), "status": "failed"}

    async def check_story(self, story_id: str, db: Session) -> Dict:
        """
        Check all chapters of a story

        Args:
            story_id: Story ID to check
            db: Database session

        Returns:
            Dictionary with overall check results
        """
        try:
            # Get all chapters for the story
            chapters = db.query(models.Chapter).filter(
                models.Chapter.story_id == story_id
            ).order_by(models.Chapter.chapter_number).all()

            if not chapters:
                return {"error": "No chapters found for story", "status": "failed"}

            results = {
                'total_chapters': len(chapters),
                'chapters_over_9500': 0,
                'chapters_with_censored': 0,
                'total_censored_words': 0,
                'chapter_results': [],
                'low_quality_chapters': []
            }

            # Check each chapter
            for chapter in chapters:
                check_result = self.check_chapter(chapter.id, db)

                if "error" not in check_result:
                    # Update counters
                    if check_result['quality_metrics']['total_characters'] >= 9500:
                        results['chapters_over_9500'] += 1

                    if check_result['censored_count'] > 0:
                        results['chapters_with_censored'] += 1
                        results['total_censored_words'] += check_result['censored_count']

                    if check_result['quality_metrics']['quality_score'] < 70:
                        results['low_quality_chapters'].append({
                            'chapter_number': chapter.chapter_number,
                            'score': check_result['quality_metrics']['quality_score']
                        })

                    results['chapter_results'].append({
                        'chapter_number': chapter.chapter_number,
                        'censored_count': check_result['censored_count'],
                        'quality_score': check_result['quality_metrics']['quality_score']
                    })

            # Update story statistics
            story = db.query(models.Story).filter(models.Story.id == story_id).first()
            if story:
                # Note: These fields may not exist in Story model
                # story.total_censored_words = results['total_censored_words']
                # story.chapters_checked = len(chapters)
                # story.last_checked = datetime.utcnow()
                db.commit()

            return results

        except Exception as e:
            logger.error(f"Error checking story {story_id}: {e}")
            db.rollback()
            return {"error": str(e), "status": "failed"}

    def auto_fix_censored(self, chapter_id: str, db: Session) -> int:
        """
        Attempt to automatically fix censored words

        Args:
            chapter_id: Chapter ID to fix
            db: Database session

        Returns:
            Number of words fixed
        """
        try:
            # Get chapter
            chapter = db.query(models.Chapter).filter(models.Chapter.id == chapter_id).first()
            if not chapter:
                return 0

            # Get censored words for this chapter
            censored_words = db.query(models.CensoredWord).filter(
                models.CensoredWord.chapter_id == chapter_id
            ).all()

            fixed_count = 0
            content = chapter.content

            # Common replacements for censored words
            replacements = {
                't*': 'tôi',
                'm*y': 'mày',
                'n*': 'nó',
                'ch*t': 'chết',
                'c*n': 'còn',
                'kh*ng': 'không',
                'đ*': 'đã',
                'v*': 'vẫn',
                'l*': 'là',
                'th*': 'thì',
                # Add more common replacements
            }

            for word in censored_words:
                # Try to match with known replacements
                for pattern, replacement in replacements.items():
                    if re.match(pattern.replace('*', r'\*'), word.word):
                        # Replace in content
                        content = content.replace(word.word, replacement)
                        fixed_count += 1

                        # Mark as fixed in database
                        word.fixed = True
                        word.fixed_word = replacement
                        break

            if fixed_count > 0:
                # Update chapter content
                chapter.content = content
                chapter.censored_count = chapter.censored_count - fixed_count
                db.commit()

                logger.info(f"Fixed {fixed_count} censored words in chapter {chapter_id}")

            return fixed_count

        except Exception as e:
            logger.error(f"Error auto-fixing chapter {chapter_id}: {e}")
            db.rollback()
            return 0

    def find_numbering_lines(self, text: str) -> List[Dict]:
        """
        Find lines that only contain numbering markers (standalone numbers on a line).

        Patterns detected:
        - Plain numbers: 1, 2, 3, ... or 01, 02, 03, ...
        - Numbers with dot: 1., 2., 3., ...
        - Numbers with comma: 1, 2, 3, ... (standalone)
        - Numbers in parentheses: (1), (2), (3), ...
        - Numbers in brackets: [1], [2], [3], ...
        - Numbers with hash: #1, #2, #3, ...
        - Numbers with slash: 1/, 2/, 3/, ...
        - Roman numerals: I, II, III, IV, ...

        Args:
            text: Text content to check

        Returns:
            List of dictionaries containing numbering line info
        """
        numbering_lines = []
        lines = text.split('\n')

        # Pattern to match various numbering formats on a standalone line
        # ^\\s* - start with optional whitespace
        # (...) - the number pattern
        # \\s*$ - end with optional whitespace
        numbering_patterns = [
            # Plain numbers: 1, 2, 3, ... or 01, 02, 03, ...
            (r'^\s*(\d{1,4})\s*$', 'plain_number'),
            # Numbers with dot: 1., 2., 3., ...
            (r'^\s*(\d{1,4})\.\s*$', 'number_dot'),
            # Numbers in parentheses: (1), (2), (3), ...
            (r'^\s*\((\d{1,4})\)\s*$', 'parentheses'),
            # Numbers with closing paren only: 1), 2), 3), ...
            (r'^\s*(\d{1,4})\)\s*$', 'closing_paren'),
            # Numbers in brackets: [1], [2], [3], ...
            (r'^\s*\[(\d{1,4})\]\s*$', 'brackets'),
            # Numbers with hash: #1, #2, #3, ...
            (r'^\s*#(\d{1,4})\s*$', 'hash_number'),
            # Numbers with slash: 1/, 2/, 3/, ...
            (r'^\s*(\d{1,4})/\s*$', 'number_slash'),
            # Numbers with colon: 1:, 2:, 3:, ...
            (r'^\s*(\d{1,4}):\s*$', 'number_colon'),
            # Numbers with dash: 1-, 2-, 3-, ...
            (r'^\s*(\d{1,4})-\s*$', 'number_dash'),
            # Numbers with comma: 1, 2, 3, ... (standalone on a line)
            (r'^\s*(\d{1,4}),\s*$', 'number_comma'),
            # Roman numerals (common ones): I, II, III, IV, V, VI, VII, VIII, IX, X
            (r'^\s*(I{1,3}|IV|VI{0,3}|IX|XI{0,3}|X{1,3})\s*$', 'roman'),
            # Roman numerals with dot: I., II., III., ...
            (r'^\s*(I{1,3}|IV|VI{0,3}|IX|XI{0,3}|X{1,3})\.\s*$', 'roman_dot'),
        ]

        for line_num, line in enumerate(lines, 1):
            # Skip empty lines
            if not line.strip():
                continue

            for pattern, num_type in numbering_patterns:
                match = re.match(pattern, line, re.IGNORECASE)
                if match:
                    number_value = match.group(1)
                    numbering_lines.append({
                        'line_number': line_num,
                        'content': line.strip(),
                        'number_value': number_value,
                        'number_type': num_type,
                        'word_type': 'numbering'
                    })
                    break  # Only match one pattern per line

        return numbering_lines

    def remove_numbering_lines(self, text: str) -> Tuple[str, List[Dict]]:
        """
        Remove all standalone numbering lines from text.

        Args:
            text: Text content to clean

        Returns:
            Tuple of (cleaned_text, removed_lines)
            - cleaned_text: Text with numbering lines removed
            - removed_lines: List of removed line info
        """
        # Find all numbering lines first
        numbering_lines = self.find_numbering_lines(text)

        if not numbering_lines:
            return text, []

        # Get line numbers to remove
        lines_to_remove = set(item['line_number'] for item in numbering_lines)

        # Split text into lines and filter out numbering lines
        lines = text.split('\n')
        cleaned_lines = []

        for line_num, line in enumerate(lines, 1):
            if line_num not in lines_to_remove:
                cleaned_lines.append(line)

        # Join back
        cleaned_text = '\n'.join(cleaned_lines)

        # Remove excessive blank lines (more than 2 consecutive)
        cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)

        return cleaned_text, numbering_lines

    def remove_numbering_lines_from_chapter(self, chapter_id: str, db: Session) -> Dict:
        """
        Remove numbering lines from a chapter in database.

        Args:
            chapter_id: Chapter ID to clean
            db: Database session

        Returns:
            Dictionary with results
        """
        try:
            # Get chapter from database
            chapter = db.query(models.Chapter).filter(models.Chapter.id == chapter_id).first()
            if not chapter:
                logger.error(f"Chapter {chapter_id} not found")
                return {"error": "Chapter not found", "status": "failed"}

            # Remove numbering lines
            cleaned_content, removed_lines = self.remove_numbering_lines(chapter.content)

            if not removed_lines:
                return {
                    "chapter_id": chapter_id,
                    "chapter_number": chapter.chapter_number,
                    "removed_count": 0,
                    "removed_lines": [],
                    "status": "no_changes"
                }

            # Update chapter content
            original_length = len(chapter.content)
            chapter.content = cleaned_content
            new_length = len(cleaned_content)

            db.commit()

            logger.info(f"Removed {len(removed_lines)} numbering lines from chapter {chapter_id}")

            return {
                "chapter_id": chapter_id,
                "chapter_number": chapter.chapter_number,
                "removed_count": len(removed_lines),
                "removed_lines": removed_lines,
                "original_length": original_length,
                "new_length": new_length,
                "status": "completed"
            }

        except Exception as e:
            logger.error(f"Error removing numbering lines from chapter {chapter_id}: {e}")
            db.rollback()
            return {"error": str(e), "status": "failed"}

    def suggest_fixes(self, censored_word: str) -> List[str]:
        """
        Suggest possible fixes for a censored word

        Args:
            censored_word: The censored word (e.g., "t*")

        Returns:
            List of suggested replacements
        """
        suggestions = []

        # Common Vietnamese word patterns
        patterns = {
            't*': ['tôi', 'ta', 'tao', 'tớ', 'tui'],
            'm*y': ['mày', 'may', 'mấy'],
            'n*': ['nó', 'nà', 'nè', 'này', 'nọ'],
            'ch*t': ['chết', 'chất', 'chút', 'chắt'],
            'c*n': ['còn', 'cần', 'cũng', 'của'],
            'đ*': ['đã', 'đi', 'đó', 'để', 'đây'],
            'kh*ng': ['không', 'khung', 'khẳng'],
            'v*': ['vì', 'về', 'vẫn', 'và', 'vậy'],
            'l*': ['là', 'lại', 'lấy', 'làm', 'lên'],
            'th*': ['thì', 'thế', 'thôi', 'thấy', 'theo']
        }

        # Clean the word (remove extra spaces)
        word_clean = censored_word.strip().lower()

        # Try to match with patterns
        for pattern, words in patterns.items():
            if re.match(pattern.replace('*', r'\*'), word_clean):
                suggestions.extend(words)

        # If no pattern matches, try to guess based on word length
        if not suggestions:
            word_len = len(word_clean)
            # Add logic to suggest words based on length and context
            pass

        return suggestions[:5]  # Return top 5 suggestions