"""
Story Downloader Service
Refactored from make_story/download_single_chapter.py
"""
import re
import time
import asyncio
from typing import Optional, List, Dict, Tuple, Callable
from urllib.parse import urlparse

import requests
import urllib3
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from loguru import logger
from urllib3.exceptions import InsecureRequestWarning

from app import models
from app.config import settings
from app.services.text_checker import TextChecker


class StoryDownloader:
    """Service for downloading stories from TruyenFull"""

    def __init__(self, base_url: str, auto_remove_numbering: bool = True):
        """
        Initialize downloader with base URL

        Args:
            base_url: Base URL of the story (e.g., https://truyenfull.vision/story-name)
            auto_remove_numbering: If True, automatically remove standalone numbering lines from content
        """
        self.base_url = base_url.rstrip('/')
        self.auto_remove_numbering = auto_remove_numbering
        self.text_checker = TextChecker() if auto_remove_numbering else None
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        # Detect domain and set appropriate selectors
        parsed_url = urlparse(self.base_url)
        self.domain = parsed_url.netloc
        print('self.domain', self.domain)

        # Extract slug from URL path (used by API-based sites like daotruyen.me)
        self.slug = parsed_url.path.strip('/').split('/')[-1] if parsed_url.path.strip('/') else ''

        # Domain-specific configuration
        if 'daotruyen' in self.domain:
            # daotruyen.me uses a JSON API, no HTML scraping needed
            self.use_api = True
            self.api_base = f"https://{self.domain}/api/public/v2"
            self.api_headers = {
                'User-Agent': self.headers['User-Agent'],
                'Accept': 'application/json',
                'Referer': f'https://{self.domain}/',
                'Origin': f'https://{self.domain}'
            }
            # These are not used for API-based sites, but set for compatibility
            self.chapter_content_class = None
            self.chapter_title_class = None
            self.story_title_class = None
            self.url_pattern = None
            print(f"Initialized API-based downloader for domain: {self.domain}, slug: {self.slug}")
            return

        self.use_api = False

        if 'truyenhay.blog' in self.domain:
            self.chapter_content_class = 'entry-content'
            self.chapter_title_class = 'entry-title'
            self.story_title_class = None  # No specific class, extract from URL or meta
            self.url_pattern = 'truyen'  # Has /truyen/ in URL
        elif 'nguyettruyen.net' in self.domain:
            self.chapter_content_class = 'app-content'
            self.chapter_title_class = None  # Use h1 tag directly
            self.story_title_class = None  # Parse from page title
            self.url_pattern = 'truyen'  # Has /truyen/ in URL
        elif 'metruyen.mobi' in self.domain:
            self.chapter_content_class = 'entry-content'
            self.chapter_title_class = None  # Use h1 tag directly
            self.story_title_class = None  # Parse from page title (split by •)
            self.url_pattern = 'truyen'  # Has /truyen/ in URL
        elif 'metruyen.fit' in self.domain:
            self.chapter_content_class = 'reading-content'
            self.chapter_title_class = None  # Use h1 tag directly
            self.story_title_class = None  # Parse from page title (split by •)
            self.url_pattern = 'truyen'  # Has /truyen/ in URL
        elif 'truyenmoiii.org' in self.domain:
            self.chapter_content_class = 'chapter-content'
            self.chapter_title_class = 'chapter-title'
            self.story_title_class = 'truyen-title'
            self.url_pattern = None
        elif 'vivutruyen.net' in self.domain:
            self.chapter_content_class = 'reading'
            self.chapter_title_class = None  # Extract from <title> or og:title
            self.story_title_class = None  # Extract from URL slug
            self.url_pattern = None
        elif 'metruyenhot' in self.domain:  # Supports .me, .vn, etc.
            self.chapter_content_class = 'chapter-c'
            self.chapter_title_class = None  # Use h2 tag directly
            self.story_title_class = None  # Use h1 tag directly
            self.url_pattern = None
        else:
            # Default for truyenfull.vision and similar sites
            self.chapter_content_class = 'chapter-c'
            self.chapter_title_class = 'chapter-title'
            self.story_title_class = 'truyen-title'
            self.url_pattern = None

        print(f"Initialized downloader for domain: {self.domain}, using class: .{self.chapter_content_class}")

    def _sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename"""
        return re.sub(r'[<>:"/\\|?*]', '', filename)

    def _clean_content(self, content: str) -> Tuple[str, int]:
        """
        Clean content by removing numbering lines if enabled.

        Args:
            content: Raw content text

        Returns:
            Tuple of (cleaned_content, removed_count)
        """
        if not self.auto_remove_numbering or not self.text_checker or not content:
            return content, 0

        cleaned_content, removed_lines = self.text_checker.remove_numbering_lines(content)
        return cleaned_content, len(removed_lines)

    def _remove_fake_text_elements(self, soup: BeautifulSoup) -> None:
        """
        Remove fake text elements used for anti-scraping (all hosts)
        These are <span class="fake" data-before="word"></span> elements
        that display text via CSS but contain no actual text content.
        Safe to run on all sites - won't affect sites that don't use this technique.
        """
        fake_spans = soup.find_all('span', class_='fake')
        if fake_spans:
            logger.info(f"Removing {len(fake_spans)} fake text elements")
            for span in fake_spans:
                span.decompose()

    def _parse_css_before_rules(self, soup: BeautifulSoup) -> dict:
        """
        Parse CSS ::before pseudo-element rules from <style> tags (all hosts)
        Returns dict mapping class names to their content or attribute name.
        Safe to run on all sites - returns empty dict if no rules found.

        Handles two patterns:
        1. .class:before { content: "text"; } -> returns {"class": "text"}
        2. .class::before { content: attr(attrname); } -> returns {"class": ("attr", "attrname")}
        """
        css_rules = {}
        style_tags = soup.find_all('style')

        for style in style_tags:
            css_text = style.string
            if css_text and ':before' in css_text:
                # Pattern 1: .class-name:before { content: "text"; }
                # For sites like vivutruyen.net
                pattern1 = r'\.([a-z]-[a-f0-9]+):before\s*\{\s*content:\s*"([^"]*)"\s*;?\s*\}'
                matches1 = re.findall(pattern1, css_text, re.IGNORECASE)
                for class_name, content in matches1:
                    css_rules[class_name] = content

                # Pattern 2: .classname::before { content: attr(attrname); }
                # For sites like metruyenhot.me with random class names
                pattern2 = r'\.([a-zA-Z0-9]+)::?before\s*\{\s*content:\s*attr\(([a-zA-Z0-9]+)\)\s*;?\s*\}'
                matches2 = re.findall(pattern2, css_text, re.IGNORECASE)
                for class_name, attr_name in matches2:
                    css_rules[class_name] = ('attr', attr_name)

        if css_rules:
            logger.info(f"Parsed {len(css_rules)} CSS ::before rules")

        return css_rules

    def _get_text_with_css(self, element, css_rules: dict) -> str:
        """
        Extract text from element, replacing tags with CSS ::before content
        Handles anti-scraping technique where text is hidden in CSS pseudo-elements

        Supports two types of css_rules values:
        1. String: direct content from content: "text"
        2. Tuple ('attr', 'attrname'): get content from element's attribute

        Handles two placement patterns:
        1. CSS class on <span> inside <p> (vivutruyen.net style)
        2. CSS class directly on <p> tag itself (metruyenhot.me style)
        """
        # First check if the element itself has a matching CSS class (metruyenhot.me style)
        # where content is in attribute on the <p> tag itself
        classes = element.get('class', [])
        if classes:
            for class_name in classes:
                css_content = css_rules.get(class_name)
                if css_content:
                    if isinstance(css_content, tuple) and css_content[0] == 'attr':
                        # Get content from element's own attribute
                        attr_name = css_content[1]
                        attr_value = element.get(attr_name, '')
                        if attr_value:
                            return attr_value
                    elif isinstance(css_content, str):
                        # Direct CSS content on the element itself
                        return css_content

        # Otherwise, process children (vivutruyen.net style with spans)
        result = []

        for child in element.children:
            if isinstance(child, str):
                # Plain text node
                result.append(child)
            elif child.name == 'span':
                # Check if span has CSS ::before content
                child_classes = child.get('class', [])
                if child_classes:
                    class_name = child_classes[0]
                    css_content = css_rules.get(class_name)
                    if css_content:
                        if isinstance(css_content, tuple) and css_content[0] == 'attr':
                            # Get content from element's attribute (metruyenhot.me style)
                            attr_name = css_content[1]
                            attr_value = child.get(attr_name, '')
                            result.append(attr_value)
                        else:
                            # Use direct CSS content (vivutruyen.net style)
                            result.append(css_content)
                    else:
                        # Fallback to span's text
                        result.append(child.get_text())
                else:
                    result.append(child.get_text())
            else:
                # Other tags (like <strong>, <em>, etc.), process recursively
                result.append(self._get_text_with_css(child, css_rules))

        return ''.join(result)

    def _remove_chapter_header(self, content: str) -> str:
        """Remove 'CHƯƠNG {number}' text from content"""
        patterns = [
            r'CHƯƠNG\s+\d+[\s:.\-]*',  # CHƯƠNG 1: or CHƯƠNG 1. or CHƯƠNG 1 -
            r'Chương\s+\d+[\s:.\-]*',  # Chương 1: (lowercase)
            r'CHUONG\s+\d+[\s:.\-]*',  # CHUONG 1 (no diacritics)
            r'Chuong\s+\d+[\s:.\-]*',  # Chuong 1 (no diacritics, lowercase)
        ]

        lines = content.split('\n')
        cleaned_lines = []

        for line in lines:
            cleaned_line = line
            # Apply all patterns to remove chapter headers
            for pattern in patterns:
                cleaned_line = re.sub(pattern, '', cleaned_line, flags=re.IGNORECASE)

            # Remove excess whitespace
            cleaned_line = cleaned_line.strip()

            # Only add line if there's content after cleaning
            if cleaned_line:
                cleaned_lines.append(cleaned_line)

        return '\n'.join(cleaned_lines)

    def _extract_content(self, soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Extract content from BeautifulSoup object

        Returns:
            Tuple of (story_title, chapter_title, content)
        """
        # Debug: Print all elements with class containing 'chapter' or 'content'
        logger.debug("=== DEBUG: Looking for chapter content ===")
        logger.debug(f"Target class: {self.chapter_content_class}")

        # Try to find all elements that might contain chapter content
        potential_elements = soup.find_all(class_=lambda x: x and ('chapter' in x or 'content' in x))
        logger.debug(f"Found {len(potential_elements)} elements with 'chapter' or 'content' in class")
        for elem in potential_elements[:5]:  # Show first 5
            logger.debug(f"  - {elem.name} class={elem.get('class')}")

        # Find chapter content using domain-specific class (can be div or article)
        chapter_content = soup.find(class_=self.chapter_content_class)
        if not chapter_content:
            logger.warning(f"Chapter content element with class '.{self.chapter_content_class}' not found")

            # Try alternative selectors
            logger.debug("Trying alternative selectors...")
            chapter_content = soup.find('article', class_='chapter-content')
            if chapter_content:
                logger.info("Found with selector: article.chapter-content")
            else:
                chapter_content = soup.find('div', class_='chapter-content')
                if chapter_content:
                    logger.info("Found with selector: div.chapter-content")

        if not chapter_content:
            logger.error(f"Failed to find chapter content with any selector")
            return None, None, None

        # Parse CSS ::before rules (for anti-scraping sites)
        css_before_rules = self._parse_css_before_rules(soup)

        # Remove fake text elements (for anti-scraping sites)
        # Always run for all hosts - won't affect sites that don't use this technique
        self._remove_fake_text_elements(chapter_content)

        # Get story title (domain-specific)
        if self.story_title_class:
            story_title_elem = soup.find('a', class_=self.story_title_class)
            story_title = story_title_elem.text.strip() if story_title_elem else "Unknown Story"
        else:
            # Extract from URL or page title for sites without story_title_class (like truyenhay.blog, nguyettruyen.net, metruyen.mobi)
            page_title = soup.find('title')
            if page_title:
                # Different formats:
                # - "Story Name - Chapter X - Site Name" (hyphen/em dash)
                # - "Story Name • Site Name" (bullet)
                title_text = page_title.text

                # Try bullet first (for metruyen.mobi)
                if '•' in title_text:
                    title_parts = title_text.split('•')
                # Then try em dash (–) or hyphen (-)
                else:
                    title_parts = title_text.split('–') if '–' in title_text else title_text.split('-')

                if len(title_parts) >= 2:
                    story_title = title_parts[0].strip()
                else:
                    story_title = "Unknown Story"
            else:
                story_title = "Unknown Story"

        # Get chapter title (domain-specific)
        if hasattr(self, 'chapter_title_class') and self.chapter_title_class:
            # Try <a> tag first (truyenfull style)
            chapter_title_elem = soup.find('a', class_=self.chapter_title_class)
            if not chapter_title_elem:
                # Try <h1> tag (WordPress/truyenhay.blog style)
                chapter_title_elem = soup.find('h1', class_=self.chapter_title_class)
            chapter_title = chapter_title_elem.text.strip() if chapter_title_elem else "Unknown Chapter"
        else:
            # For sites without chapter_title_class (like nguyettruyen.net), find h1 directly
            chapter_title_elem = soup.find('h1')
            if not chapter_title_elem:
                # Fallback to default chapter-title class
                chapter_title_elem = soup.find('a', class_='chapter-title')
            chapter_title = chapter_title_elem.text.strip() if chapter_title_elem else "Unknown Chapter"

        # Extract text content
        paragraphs = chapter_content.find_all('p')
        content_lines = []

        if paragraphs:
            # If there are <p> tags, get content from them
            for p in paragraphs:
                # Use _get_text_with_css to handle CSS ::before content in <span> tags
                if css_before_rules:
                    text = self._get_text_with_css(p, css_before_rules)
                else:
                    text = p.get_text()  # Keep whitespace, don't strip

                # Check if text has actual content (not just whitespace)
                if text.strip() and text.strip() != 'DTV':  # Skip empty lines and 'DTV'
                    content_lines.append(text)
        else:
            # If no <p> tags, process full content with <br> handling
            html_content = str(chapter_content)
            html_content = html_content.replace('<br/>', '\n').replace('<br>', '\n')

            # Re-parse with BeautifulSoup to get clean text
            temp_soup = BeautifulSoup(html_content, 'html.parser')

            # Remove script, style and ad elements
            for element in temp_soup(['script', 'style', 'div']):
                if element.name == 'div' and element.get('class'):
                    # Remove ad divs
                    if any('ads' in cls or 'ad' in cls for cls in element.get('class', [])):
                        element.decompose()

            # Get text and split by lines
            text_content = temp_soup.get_text()
            lines = text_content.split('\n')

            for line in lines:
                line = line.strip()
                if line and line != 'DTV' and not line.startswith('visible-'):
                    content_lines.append(line)

        full_content = '\n\n'.join(content_lines)

        # Remove chapter headers from content
        full_content = self._remove_chapter_header(full_content)

        return story_title, chapter_title, full_content

    def _get_story_slug(self) -> str:
        """Extract story slug from base URL for fallback URL patterns"""
        # Example: https://vivutruyen.net/chong-toi-bo-lai-toi-mot-minh-trong-dam-chay
        # Returns: chong-toi-bo-lai-toi-mot-minh-trong-dam-chay
        path = urlparse(self.base_url).path.strip('/')
        # Get the last part of the path (story slug)
        return path.split('/')[-1] if path else ''

    def _api_get(self, url: str) -> requests.Response:
        """GET a JSON API URL, retrying daotruyen cert-chain failures."""
        try:
            return requests.get(url, headers=self.api_headers, timeout=30)
        except requests.exceptions.SSLError as e:
            if "CERTIFICATE_VERIFY_FAILED" not in str(e):
                raise
            logger.warning(f"SSL certificate verification failed for {url}; retrying without verification")
            urllib3.disable_warnings(category=InsecureRequestWarning)
            return requests.get(url, headers=self.api_headers, timeout=30, verify=False)

    def _download_chapter_api(self, chapter_num: int) -> Dict:
        """
        Download a chapter using JSON API (for daotruyen.me)

        API: GET /api/public/v2/{slug}/{chapterNumber}
        Response: { story: {name, id, url}, chapter: {chapterNumber, paragraph, title, ...} }
        """
        url = f"{self.api_base}/{self.slug}/{chapter_num}"
        try:
            response = self._api_get(url)
            response.raise_for_status()
            data = response.json()

            story_data = data.get('story', {})
            chapter_data = data.get('chapter', {})

            content = chapter_data.get('paragraph', '')
            if not content:
                return {
                    "success": False,
                    "chapter_num": chapter_num,
                    "error": "No content found in API response"
                }

            # Clean content (remove numbering lines if enabled)
            content, numbering_removed = self._clean_content(content)
            if numbering_removed > 0:
                logger.info(f"Removed {numbering_removed} numbering lines from chapter {chapter_num}")

            # Remove chapter headers
            content = self._remove_chapter_header(content)

            char_count = len(content.replace(' ', '').replace('\n', ''))

            chapter_title = chapter_data.get('title') or f"Chương {chapter_num}"
            story_title = story_data.get('name', 'Unknown Story')

            return {
                "success": True,
                "chapter_num": chapter_num,
                "story_title": story_title,
                "chapter_title": chapter_title,
                "content": content,
                "char_count": char_count,
                "numbering_removed": numbering_removed,
                "url": url
            }

        except requests.RequestException as e:
            logger.error(f"API error downloading chapter {chapter_num}: {e}")
            return {
                "success": False,
                "chapter_num": chapter_num,
                "error": str(e)
            }
        except Exception as e:
            logger.error(f"Unexpected error for chapter {chapter_num}: {e}")
            return {
                "success": False,
                "chapter_num": chapter_num,
                "error": str(e)
            }

    def _get_story_info_api(self) -> Dict:
        """Get story info using JSON API (for daotruyen.me)"""
        url = f"{self.api_base}/{self.slug}"
        try:
            response = self._api_get(url)
            response.raise_for_status()
            data = response.json()

            story_data = data.get('story', {})
            chapters = data.get('chapters', [])
            translate = data.get('translate', {})

            return {
                "title": story_data.get('name', 'Unknown'),
                "author": story_data.get('authorName', translate.get('translatorName', 'Unknown')),
                "description": story_data.get('description', ''),
                "total_chapters": len(chapters),
                "url": self.base_url
            }
        except Exception as e:
            logger.error(f"Error getting story info from API: {e}")
            return {
                "title": "Unknown",
                "author": "Unknown",
                "description": "",
                "total_chapters": 0,
                "url": self.base_url
            }

    async def download_chapter(
        self,
        chapter_num: int,
        progress_callback: Optional[Callable] = None
    ) -> Dict:
        """
        Download a single chapter

        Args:
            chapter_num: Chapter number to download
            progress_callback: Optional callback for progress updates

        Returns:
            Dictionary with chapter data or error info
        """
        # Use API for daotruyen.me
        if self.use_api:
            if progress_callback:
                progress_callback(f"Downloading chapter {chapter_num}...")
            return self._download_chapter_api(chapter_num)

        # Build chapter URL based on domain pattern
        # For truyenhay.blog: base_url already includes /truyen/story-name
        # Just append /chuong-X/
        url = f"{self.base_url}/chuong-{chapter_num}/"

        # Build alternative URL patterns for fallback (applies to all domains)
        story_slug = self._get_story_slug()
        fallback_urls = []
        if story_slug:
            # Pattern: /chuong-{number}-{story-slug}/
            fallback_urls.append(f"{self.base_url}/chuong-{chapter_num}-{story_slug}/")

        try:
            if progress_callback:
                progress_callback(f"Downloading chapter {chapter_num}...")

            response = requests.get(url, headers=self.headers, timeout=settings.SCRAPE_HTTP_TIMEOUT)
            response.raise_for_status()
            response.encoding = 'utf-8'

            soup = BeautifulSoup(response.text, 'html.parser')
            story_title, chapter_title, content = self._extract_content(soup)

            # If no content found, try fallback URLs
            if not content and fallback_urls:
                for fallback_url in fallback_urls:
                    logger.info(f"Trying fallback URL: {fallback_url}")
                    try:
                        response = requests.get(fallback_url, headers=self.headers, timeout=settings.SCRAPE_HTTP_TIMEOUT)
                        response.raise_for_status()
                        response.encoding = 'utf-8'

                        soup = BeautifulSoup(response.text, 'html.parser')
                        story_title, chapter_title, content = self._extract_content(soup)

                        if content:
                            url = fallback_url  # Update URL to the one that worked
                            logger.info(f"Fallback URL worked: {fallback_url}")
                            break
                    except requests.RequestException as e:
                        logger.warning(f"Fallback URL failed: {fallback_url} - {e}")
                        continue

            if not content:
                logger.warning(f"No content found for chapter {chapter_num}")
                return {
                    "success": False,
                    "chapter_num": chapter_num,
                    "error": "No content found"
                }

            # Clean content (remove numbering lines if enabled)
            content, numbering_removed = self._clean_content(content)
            if numbering_removed > 0:
                logger.info(f"Removed {numbering_removed} numbering lines from chapter {chapter_num}")

            # Count characters
            char_count = len(content.replace(' ', '').replace('\n', ''))

            return {
                "success": True,
                "chapter_num": chapter_num,
                "story_title": story_title,
                "chapter_title": chapter_title,
                "content": content,
                "char_count": char_count,
                "numbering_removed": numbering_removed,
                "url": url
            }

        except requests.RequestException as e:
            # If main URL fails, try fallback URLs
            if fallback_urls:
                for fallback_url in fallback_urls:
                    logger.info(f"Main URL failed, trying fallback: {fallback_url}")
                    try:
                        response = requests.get(fallback_url, headers=self.headers, timeout=settings.SCRAPE_HTTP_TIMEOUT)
                        response.raise_for_status()
                        response.encoding = 'utf-8'

                        soup = BeautifulSoup(response.text, 'html.parser')
                        story_title, chapter_title, content = self._extract_content(soup)

                        if content:
                            # Clean content (remove numbering lines if enabled)
                            content, numbering_removed = self._clean_content(content)
                            if numbering_removed > 0:
                                logger.info(f"Removed {numbering_removed} numbering lines from chapter {chapter_num}")

                            char_count = len(content.replace(' ', '').replace('\n', ''))
                            return {
                                "success": True,
                                "chapter_num": chapter_num,
                                "story_title": story_title,
                                "chapter_title": chapter_title,
                                "content": content,
                                "char_count": char_count,
                                "numbering_removed": numbering_removed,
                                "url": fallback_url
                            }
                    except requests.RequestException:
                        continue

            logger.error(f"Error downloading chapter {chapter_num}: {e}")
            return {
                "success": False,
                "chapter_num": chapter_num,
                "error": str(e)
            }
        except Exception as e:
            logger.error(f"Unexpected error for chapter {chapter_num}: {e}")
            return {
                "success": False,
                "chapter_num": chapter_num,
                "error": str(e)
            }

    async def download_chapter_from_url(
        self,
        url: str,
        chapter_num: int,
        progress_callback: Optional[Callable] = None
    ) -> Dict:
        """
        Download a single chapter from a specific URL (for custom/manual URLs)

        Args:
            url: Full URL of the chapter
            chapter_num: Chapter number (for labeling)
            progress_callback: Optional callback for progress updates

        Returns:
            Dictionary with chapter data or error info
        """
        try:
            if progress_callback:
                progress_callback(f"Downloading chapter {chapter_num} from custom URL...")

            response = requests.get(url, headers=self.headers, timeout=settings.SCRAPE_HTTP_TIMEOUT)
            response.raise_for_status()
            response.encoding = 'utf-8'

            soup = BeautifulSoup(response.text, 'html.parser')
            story_title, chapter_title, content = self._extract_content(soup)

            if not content:
                logger.warning(f"No content found for chapter {chapter_num} at {url}")
                return {
                    "success": False,
                    "chapter_num": chapter_num,
                    "error": "No content found"
                }

            # Clean content (remove numbering lines if enabled)
            content, numbering_removed = self._clean_content(content)
            if numbering_removed > 0:
                logger.info(f"Removed {numbering_removed} numbering lines from chapter {chapter_num}")

            # Count characters
            char_count = len(content.replace(' ', '').replace('\n', ''))

            return {
                "success": True,
                "chapter_num": chapter_num,
                "story_title": story_title,
                "chapter_title": chapter_title,
                "content": content,
                "char_count": char_count,
                "numbering_removed": numbering_removed,
                "url": url
            }

        except requests.RequestException as e:
            logger.error(f"Error downloading chapter {chapter_num} from {url}: {e}")
            return {
                "success": False,
                "chapter_num": chapter_num,
                "error": str(e)
            }
        except Exception as e:
            logger.error(f"Unexpected error for chapter {chapter_num} from {url}: {e}")
            return {
                "success": False,
                "chapter_num": chapter_num,
                "error": str(e)
            }

    async def download_chapters_range(
        self,
        start: int,
        end: int,
        story_id: str,
        db: Session,
        task_id: Optional[str] = None,
        max_concurrent: int = 3,
        custom_chapter_urls: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Download multiple chapters with parallel execution

        Args:
            start: Start chapter number
            end: End chapter number
            story_id: Story ID in database
            db: Database session
            task_id: Optional task ID for progress tracking
            max_concurrent: Maximum concurrent downloads
            custom_chapter_urls: Optional list of custom URLs for each chapter

        Returns:
            List of download results
        """
        results = []
        semaphore = asyncio.Semaphore(max_concurrent)

        # Determine if using custom URLs
        use_custom_urls = custom_chapter_urls and len(custom_chapter_urls) > 0

        def _bump_progress():
            """Count one chapter as done and refresh the task's percent."""
            if not task_id:
                return
            task = db.query(models.Task).filter(models.Task.id == task_id).first()
            if task:
                task.completed_items = (task.completed_items or 0) + 1
                if task.total_items:
                    task.progress = int((task.completed_items / task.total_items) * 100)
                try:
                    db.commit()
                except Exception as e:
                    logger.error(f"Error updating progress for chapter: {e}")
                    db.rollback()

        async def download_with_limit(chapter_num, custom_url=None):
            async with semaphore:
                # Idempotent resume: startup recovery re-runs the whole
                # start..end range, so if this chapter is already saved for the
                # story, skip both the re-fetch and the insert — otherwise every
                # previously-downloaded chapter would be duplicated (and the
                # content re-scraped). Still counts toward progress so a resumed
                # task can reach 100%.
                existing = db.query(models.Chapter).filter(
                    models.Chapter.story_id == story_id,
                    models.Chapter.chapter_number == chapter_num,
                ).first()
                if existing:
                    _bump_progress()
                    return {"success": True, "chapter_num": chapter_num, "skipped": True}

                # Use custom URL if provided, otherwise use pattern-based URL
                if custom_url:
                    result = await self.download_chapter_from_url(custom_url, chapter_num)
                else:
                    result = await self.download_chapter(chapter_num)

                # Save to database if successful
                if result["success"]:
                    chapter = models.Chapter(
                        story_id=story_id,
                        chapter_number=chapter_num,
                        title=result["chapter_title"],
                        content=result["content"],
                        char_count=result["char_count"]
                    )
                    db.add(chapter)

                    try:
                        db.commit()
                    except Exception as e:
                        logger.error(f"Error saving chapter {chapter_num}: {e}")
                        db.rollback()
                    else:
                        # Only count a successfully-committed chapter.
                        _bump_progress()

                # Add small delay to avoid overwhelming server
                await asyncio.sleep(1)
                return result

        # Create tasks for all chapters
        if use_custom_urls:
            # Use custom URLs - each URL corresponds to a chapter
            tasks = [
                download_with_limit(i + 1, custom_chapter_urls[i])
                for i in range(len(custom_chapter_urls))
            ]
        else:
            # Use pattern-based URLs
            tasks = [download_with_limit(i) for i in range(start, end + 1)]

        # Execute downloads
        results = await asyncio.gather(*tasks)

        # Update task status if all complete
        if task_id:
            task = db.query(models.Task).filter(models.Task.id == task_id).first()
            if task:
                successful = sum(1 for r in results if r["success"])
                failed = len(results) - successful

                if failed == 0:
                    task.status = "completed"
                    task.progress = 100
                else:
                    task.status = "completed_with_errors"
                    task.error_message = f"{failed} chapters failed to download"

                db.commit()

        return results

    def get_story_info(self) -> Dict:
        """
        Get basic story information from the main page

        Returns:
            Dictionary with story info
        """
        # Use API for daotruyen.me
        if self.use_api:
            return self._get_story_info_api()

        try:
            response = requests.get(self.base_url, headers=self.headers, timeout=settings.SCRAPE_HTTP_TIMEOUT)
            response.raise_for_status()
            response.encoding = 'utf-8'

            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract story title
            title_elem = soup.find('h3', class_='title')
            title = title_elem.text.strip() if title_elem else "Unknown"

            # Extract author
            author_elem = soup.find('div', class_='info').find('a') if soup.find('div', class_='info') else None
            author = author_elem.text.strip() if author_elem else "Unknown"

            # Extract description
            desc_elem = soup.find('div', class_='desc-text')
            description = desc_elem.text.strip() if desc_elem else ""

            # Count total chapters
            chapter_links = soup.find_all('a', href=re.compile(r'/chuong-\d+/'))
            total_chapters = len(chapter_links) if chapter_links else 0

            return {
                "title": title,
                "author": author,
                "description": description,
                "total_chapters": total_chapters,
                "url": self.base_url
            }

        except Exception as e:
            logger.error(f"Error getting story info: {e}")
            return {
                "title": "Unknown",
                "author": "Unknown",
                "description": "",
                "total_chapters": 0,
                "url": self.base_url
            }
