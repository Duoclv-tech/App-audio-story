# Supported Hosts - Web Story Downloader

## Danh sách các host được hỗ trợ

Dự án hiện hỗ trợ tải truyện từ 3 nguồn chính:

### 1. TruyenFull.vision (Default)

**Domain**: `truyenfull.vision`, `truyenfull.vn`, và các domain tương tự

**URL Pattern**:
```
https://truyenfull.vision/ten-truyen/
https://truyenfull.vision/ten-truyen/chuong-1/
```

**CSS Selectors**:
- Content wrapper: `.chapter-c`
- Chapter title: `.chapter-title`
- Story title: `.truyen-title`

**Ví dụ sử dụng**:
```python
from app.services.downloader import StoryDownloader

downloader = StoryDownloader("https://truyenfull.vision/tieu-thu-nha-giau")
result = await downloader.download_chapter(1)
```

---

### 2. TruyenMoiii.org

**Domain**: `truyenmoiii.org`

**URL Pattern**:
```
https://truyenmoiii.org/truyen-ten-truyen/
https://truyenmoiii.org/truyen-ten-truyen/chuong-1/
```

**CSS Selectors**:
- Content wrapper: `.chapter-content` (sử dụng `<article>` tag)
- Chapter title: `.chapter-title`
- Story title: `.truyen-title`

**Đặc điểm**:
- Sử dụng `<article class="chapter-content">` thay vì `<div>`
- Có fallback tự động sang `div.chapter-content` nếu không tìm thấy article

**Ví dụ sử dụng**:
```python
downloader = StoryDownloader("https://truyenmoiii.org/truyen-co-vo-ngot-ngao")
result = await downloader.download_chapter(1)
```

---

### 3. TruyenHay.blog ⭐ MỚI

**Domain**: `truyenhay.blog`

**URL Pattern**:
```
https://truyenhay.blog/truyen/vach-mat-thien-kim-gia/
https://truyenhay.blog/truyen/vach-mat-thien-kim-gia/chuong-1/
```

**Platform**: WordPress với theme GeneratePress

**CSS Selectors**:
- Content wrapper: `.entry-content`
- Chapter title: `.entry-title` (thẻ `<h1>`)
- Story title: Trích xuất từ `<title>` tag (format: "Story Name – Chapter X – Site Name")

**Đặc điểm**:
- Sử dụng WordPress semantic markup
- URL có thêm `/truyen/` prefix
- Story title được parse từ page title thay vì CSS selector
- Nội dung trong thẻ `<div class="entry-content" itemprop="text">`

**Cấu trúc HTML**:
```html
<article class="post-26847 truyen type-truyen">
    <div class="inside-article">
        <header class="entry-header">
            <h1 class="entry-title" itemprop="headline">
                Vạch Mặt Thiên Kim Giả – Chương 1
            </h1>
        </header>

        <div class="entry-content" itemprop="text">
            <p>Nội dung chương 1...</p>
            <p>Đoạn văn tiếp theo...</p>
        </div>
    </div>
</article>
```

**Ví dụ sử dụng**:
```python
downloader = StoryDownloader("https://truyenhay.blog/truyen/vach-mat-thien-kim-gia")
result = await downloader.download_chapter(1)

# Result format
{
    "success": True,
    "chapter_num": 1,
    "story_title": "Vạch Mặt Thiên Kim Giả",
    "chapter_title": "Vạch Mặt Thiên Kim Giả – Chương 1",
    "content": "1.\n\nTôi xuyên thành nữ phụ độc ác...",
    "char_count": 12540,
    "url": "https://truyenhay.blog/truyen/vach-mat-thien-kim-gia/chuong-1/"
}
```

---

## Cơ chế tự động phát hiện domain

Downloader tự động phát hiện domain từ URL và áp dụng CSS selectors phù hợp:

```python
# File: app/services/downloader.py
def __init__(self, base_url: str):
    parsed_url = urlparse(self.base_url)
    self.domain = parsed_url.netloc

    # Domain-specific configuration
    if 'truyenhay.blog' in self.domain:
        self.chapter_content_class = 'entry-content'
        self.chapter_title_class = 'entry-title'
        self.story_title_class = None
    elif 'truyenmoiii.org' in self.domain:
        self.chapter_content_class = 'chapter-content'
        self.chapter_title_class = 'chapter-title'
        self.story_title_class = 'truyen-title'
    else:
        # Default: truyenfull.vision
        self.chapter_content_class = 'chapter-c'
        self.chapter_title_class = 'chapter-title'
        self.story_title_class = 'truyen-title'
```

---

## Thêm hỗ trợ cho host mới

Để thêm hỗ trợ cho một host mới, làm theo các bước sau:

### 1. Phân tích cấu trúc HTML

Truy cập trang chương truyện và xác định:
- CSS class của content wrapper (div/article chứa nội dung)
- CSS class của chapter title
- CSS class của story title
- URL pattern

### 2. Cập nhật `__init__` method

Thêm điều kiện mới trong `downloader.py`:

```python
elif 'newdomain.com' in self.domain:
    self.chapter_content_class = 'your-content-class'
    self.chapter_title_class = 'your-title-class'
    self.story_title_class = 'your-story-class'  # or None
```

### 3. Test với một chương

```python
downloader = StoryDownloader("https://newdomain.com/story-name")
result = await downloader.download_chapter(1)
print(result)
```

### 4. Cập nhật tài liệu

Thêm thông tin vào file này (SUPPORTED_HOSTS.md)

---

## Troubleshooting

### Không tìm thấy nội dung chương

**Lỗi**: `Failed to find chapter content with any selector`

**Giải pháp**:
1. Kiểm tra CSS class trong HTML source
2. Thêm log debug để xem các elements được tìm thấy
3. Cập nhật selector trong domain configuration

### Title bị trích xuất sai

**Trường hợp truyenhay.blog**: Story title được parse từ page title với format "Story – Chapter – Site"

Nếu format khác, cần update logic trong `_extract_content`:

```python
# Customize title extraction
title_parts = page_title.text.split('–')
story_title = title_parts[0].strip()
```

### URL pattern không đúng

Kiểm tra `base_url` có đúng format không:
- ✅ Đúng: `https://truyenhay.blog/truyen/story-name`
- ❌ Sai: `https://truyenhay.blog/truyen/story-name/chuong-1/` (không nên có chapter trong base_url)

---

## Testing

Test với 3 domains:

```bash
# Test TruyenFull
curl -X POST http://localhost:8000/api/v1/stories \
  -H "Content-Type: application/json" \
  -d '{"url": "https://truyenfull.vision/tieu-thu-nha-giau", "start_chapter": 1, "end_chapter": 3}'

# Test TruyenMoiii
curl -X POST http://localhost:8000/api/v1/stories \
  -H "Content-Type: application/json" \
  -d '{"url": "https://truyenmoiii.org/truyen-co-vo", "start_chapter": 1, "end_chapter": 3}'

# Test TruyenHay.blog
curl -X POST http://localhost:8000/api/v1/stories \
  -H "Content-Type: application/json" \
  -d '{"url": "https://truyenhay.blog/truyen/vach-mat-thien-kim-gia", "start_chapter": 1, "end_chapter": 3}'
```

---

## Changelog

### Version 1.4 - 2026-01-03
- ✅ Thêm hỗ trợ cho **metruyen.fit** (Manga/Manhua platform)

### Version 1.3 - 2025-11-19
- ✅ Thêm hỗ trợ cho **truyenhay.blog** (WordPress platform)
- ✅ Cải thiện domain detection logic
- ✅ Thêm fallback cho story title extraction

### Version 1.2
- ✅ Thêm hỗ trợ cho **truyenmoiii.org**
- ✅ Thêm fallback selectors (article → div)

### Version 1.1
- ✅ Hỗ trợ **truyenfull.vision** (default)
