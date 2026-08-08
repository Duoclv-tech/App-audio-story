# Supported Hosts - Web Story Downloader

## Danh sách các host được hỗ trợ

Downloader (`backend/app/services/downloader.py`) tự nhận diện domain từ URL và chọn CSS selector (hoặc JSON API) phù hợp. Hiện hỗ trợ **9 nguồn**:

| # | Domain | Content selector | Cách lấy nội dung |
|---|--------|------------------|-------------------|
| 1 | `truyenfull.vision` / `.vn` (default) | `.chapter-c` | scrape HTML |
| 2 | `truyenmoiii.org` | `.chapter-content` (article) | scrape HTML |
| 3 | `truyenhay.blog` | `.entry-content` | scrape HTML (WordPress) |
| 4 | `nguyettruyen.net` | `.app-content` | scrape HTML |
| 5 | `metruyen.mobi` | `.entry-content` | scrape HTML |
| 6 | `metruyen.fit` | `.reading-content` | scrape HTML |
| 7 | `vivutruyen.net` | `.reading` | scrape HTML |
| 8 | `metruyenhot` (.me/.vn…) | `.chapter-c` | scrape HTML |
| 9 | `daotruyen.me` | — | **JSON API** (`/api/public/v2`) |

> Nguồn nào không khớp domain nào ở trên sẽ dùng cấu hình **mặc định** (giống truyenfull.vision: `.chapter-c` / `.chapter-title` / `.truyen-title`).

Ngoài tải từ web, còn có thể **import trực tiếp** nội dung (dán text / upload `.txt`/`.docx` / chọn folder) — xem `backend/app/api/chapters.py` (`import`, `import-file`, `import-folder`) và service `chapter_splitter.py`.

---

### 1. TruyenFull.vision (Default)

**Domain**: `truyenfull.vision`, `truyenfull.vn`, và các domain tương tự

**CSS Selectors**: content `.chapter-c` · chapter title `.chapter-title` · story title `.truyen-title`

```python
from app.services.downloader import StoryDownloader

downloader = StoryDownloader("https://truyenfull.vision/tieu-thu-nha-giau")
result = await downloader.download_chapter(1)
```

### 2. TruyenMoiii.org

**Domain**: `truyenmoiii.org`

**CSS Selectors**: content `.chapter-content` (dùng `<article>`, fallback `<div>`) · chapter title `.chapter-title` · story title `.truyen-title`

### 3. TruyenHay.blog

**Domain**: `truyenhay.blog` — WordPress (GeneratePress)

**CSS Selectors**: content `.entry-content` · chapter title `.entry-title` (`<h1>`) · story title parse từ `<title>` (format "Story – Chapter – Site"). URL có prefix `/truyen/`.

### 4. NguyetTruyen.net

**Domain**: `nguyettruyen.net`

**CSS Selectors**: content `.app-content` · chapter title dùng thẻ `<h1>` trực tiếp · story title parse từ page title. URL có prefix `/truyen/`.

### 5. MeTruyen.mobi

**Domain**: `metruyen.mobi`

**CSS Selectors**: content `.entry-content` · chapter title dùng `<h1>` · story title parse từ page title (tách theo `•`). URL có prefix `/truyen/`.

### 6. MeTruyen.fit

**Domain**: `metruyen.fit`

**CSS Selectors**: content `.reading-content` · chapter title dùng `<h1>` · story title parse từ page title (tách theo `•`). URL có prefix `/truyen/`.

### 7. VivuTruyen.net

**Domain**: `vivutruyen.net`

**CSS Selectors**: content `.reading` · chapter title trích từ `<title>`/og:title · story title trích từ URL slug.

### 8. MeTruyenHot (.me / .vn / …)

**Domain**: chứa `metruyenhot`

**CSS Selectors**: content `.chapter-c` · chapter title dùng `<h2>` · story title dùng `<h1>`.

### 9. DaoTruyen.me (JSON API)

**Domain**: chứa `daotruyen`

Không scrape HTML — gọi **JSON API** tại `https://<domain>/api/public/v2`. Downloader lấy `slug` từ path URL và đặt các header `Accept: application/json`, `Referer`, `Origin` phù hợp. Các CSS selector không dùng cho nguồn này.

---

## Cơ chế tự động phát hiện domain

Downloader tự động phát hiện domain từ URL và áp dụng cấu hình phù hợp (trích `backend/app/services/downloader.py` `__init__`):

```python
parsed_url = urlparse(self.base_url)
self.domain = parsed_url.netloc
self.slug = parsed_url.path.strip('/').split('/')[-1]  # dùng cho site API

if 'daotruyen' in self.domain:
    self.use_api = True                       # JSON API, không scrape
    self.api_base = f"https://{self.domain}/api/public/v2"
    return

self.use_api = False
if 'truyenhay.blog' in self.domain:
    self.chapter_content_class = 'entry-content'; self.chapter_title_class = 'entry-title'
elif 'nguyettruyen.net' in self.domain:
    self.chapter_content_class = 'app-content'
elif 'metruyen.mobi' in self.domain:
    self.chapter_content_class = 'entry-content'
elif 'metruyen.fit' in self.domain:
    self.chapter_content_class = 'reading-content'
elif 'truyenmoiii.org' in self.domain:
    self.chapter_content_class = 'chapter-content'; self.chapter_title_class = 'chapter-title'; self.story_title_class = 'truyen-title'
elif 'vivutruyen.net' in self.domain:
    self.chapter_content_class = 'reading'
elif 'metruyenhot' in self.domain:            # .me, .vn, ...
    self.chapter_content_class = 'chapter-c'
else:                                          # default: truyenfull.vision
    self.chapter_content_class = 'chapter-c'; self.chapter_title_class = 'chapter-title'; self.story_title_class = 'truyen-title'
```

---

## Thêm hỗ trợ cho host mới

### 1. Phân tích cấu trúc HTML
Truy cập trang chương và xác định: CSS class của content wrapper, chapter title, story title, và URL pattern.

### 2. Cập nhật `__init__` trong `downloader.py`
```python
elif 'newdomain.com' in self.domain:
    self.chapter_content_class = 'your-content-class'
    self.chapter_title_class = 'your-title-class'   # or None → dùng <h1>
    self.story_title_class = 'your-story-class'     # or None → parse page title
```

### 3. Test với một chương
```python
downloader = StoryDownloader("https://newdomain.com/story-name")
result = await downloader.download_chapter(1)
print(result)
```

### 4. Cập nhật tài liệu
Thêm nguồn mới vào bảng đầu file này.

---

## Troubleshooting

### Không tìm thấy nội dung chương
**Lỗi**: `Failed to find chapter content with any selector`
1. Kiểm tra CSS class trong HTML source.
2. Thêm log debug để xem elements tìm được.
3. Cập nhật selector trong domain configuration.

### Title bị trích xuất sai
Với các site parse title từ page title (truyenhay.blog, metruyen.*), kiểm tra ký tự phân tách (`–`, `•`) trong logic `_extract_content`.

### URL pattern không đúng
`base_url` nên là URL truyện, **không** kèm chương:
- ✅ Đúng: `https://truyenhay.blog/truyen/story-name`
- ❌ Sai: `https://truyenhay.blog/truyen/story-name/chuong-1/`

---

## Changelog

### Version 1.6 - 2026-08-08
- ✅ Bổ sung tài liệu đầy đủ **9 nguồn** (trước đây chỉ ghi 3): thêm daotruyen.me (JSON API), nguyettruyen.net, metruyen.mobi, vivutruyen.net, metruyenhot.
- ✅ Cập nhật đoạn code domain-detection cho khớp `downloader.py` hiện tại.

### Version 1.4 - 2026-01-03
- ✅ Thêm hỗ trợ cho **metruyen.fit**

### Version 1.3 - 2025-11-19
- ✅ Thêm hỗ trợ cho **truyenhay.blog** (WordPress) + cải thiện domain detection

### Version 1.2
- ✅ Thêm hỗ trợ cho **truyenmoiii.org** + fallback selectors (article → div)

### Version 1.1
- ✅ Hỗ trợ **truyenfull.vision** (default)
