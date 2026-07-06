# ✂️ Video Trimmer — Tài liệu đặc tả tính năng

> Ứng dụng cắt video chính xác theo giờ · phút · giây, chạy hoàn toàn trên trình duyệt, không upload dữ liệu lên server.

---

## 1. Tổng quan

| Thuộc tính | Mô tả |
|---|---|
| Tên app | Video Trimmer |
| Nền tảng | Web (trình duyệt) |
| Xử lý | Client-side — FFmpeg.wasm |
| Dữ liệu | Không rời khỏi máy người dùng |
| Ngôn ngữ UI | Tiếng Việt |

---

## 2. Luồng sử dụng (User Flow)

```
Upload video → Xem trước + chọn đoạn → Nhập thời gian chính xác → Cài đặt xuất → Bắt đầu cắt → Tải file về
```

---

## 3. Chi tiết từng bước

### Bước 1 — Tải video lên

- Kéo thả file vào vùng upload **hoặc** nhấn để mở file picker
- Định dạng hỗ trợ: `MP4`, `MOV`, `MKV`, `AVI`, `WebM`
- Giới hạn kích thước: tối đa **2 GB**
- Sau khi chọn, hiển thị: tên file · thời lượng tổng · dung lượng

---

### Bước 2 — Xem trước & chọn đoạn cắt

**Video player:**
- Phát / tạm dừng
- Hiển thị timecode hiện tại góc phải

**Waveform âm thanh:**
- Trực quan hoá dạng sóng theo toàn bộ thời lượng
- Vùng đã chọn được highlight màu xanh
- Giúp dễ xác định điểm cắt theo âm thanh

**Thanh timeline:**
- Kéo handle trái để đặt điểm bắt đầu
- Kéo handle phải để đặt điểm kết thúc
- Hiển thị thời lượng đoạn chọn ở giữa

---

### Bước 3 — Nhập thời gian chính xác

Hai ô nhập độc lập: **Bắt đầu từ** và **Kết thúc tại**

- Mỗi ô gồm 3 trường: `Giờ` : `Phút` : `Giây`
- Nút **"↙ lấy vị trí hiện tại"** — đồng bộ từ video player
- Tính toán và hiển thị **thời lượng đoạn cắt** tự động
- Nút **"▶ Xem trước đoạn này"** — phát thử đoạn đã chọn

---

### Bước 4 — Cài đặt xuất file

#### 4a. Định dạng đầu ra

| Định dạng | Ghi chú |
|---|---|
| MP4 (H.264) | Mặc định, tương thích cao nhất |
| MP4 (H.265) | Nén tốt hơn, file nhỏ hơn |
| MOV | Dành cho hệ sinh thái Apple |
| MKV | Hỗ trợ nhiều track audio/subtitle |
| WebM | Tối ưu cho web |
| GIF | Video ngắn, không âm thanh |

#### 4b. Chất lượng video

- Gốc (không nén)
- Cao · 1080p *(mặc định)*
- Trung bình · 720p
- Thấp · 480p
- Tuỳ chỉnh (nhập bitrate thủ công)

#### 4c. Tỉ lệ khung hình (Aspect Ratio)

| Tỉ lệ | Mô tả |
|---|---|
| 16:9 | Ngang — YouTube, TV *(mặc định)* |
| 9:16 | Dọc — TikTok, Reels, Shorts |
| 1:1 | Vuông — Instagram feed |
| 4:3 | Cổ điển |
| 4:5 | Instagram portrait |
| 21:9 | Cinematic / rạp chiếu |
| 16:10 | Màn hình laptop |
| 3:4 | Portrait |
| Gốc | Giữ nguyên như file gốc |
| Tuỳ chỉnh | Nhập tay — ví dụ: 2:1, 5:4... |

Khi chọn tỉ lệ **khác gốc**, chọn thêm chế độ xử lý:
- **Crop giữa** — cắt bỏ phần thừa, giữ trung tâm
- **Letterbox** — thêm viền đen (pillarbox/letterbox)
- **Blur background** — làm mờ phần thừa làm nền

#### 4d. Tuỳ chọn thêm

| Option | Mặc định | Ghi chú |
|---|---|---|
| Giữ nguyên âm thanh | ✅ Bật | |
| Tắt tiếng (mute) | ☐ Tắt | |
| Cắt chính xác theo frame | ✅ Bật | |
| Thêm fade in / fade out | ☐ Tắt | |
| Chèn watermark | ☐ Tắt | Khi bật → hiện ô nhập text watermark |

#### 4e. Thư mục & tên file xuất ra

**Thư mục lưu:**
- Mặc định: cùng thư mục với file gốc
- Có thể thay đổi bằng nút "📂 Đổi thư mục"

**Tên file:**
- Có thể sửa tay trực tiếp
- 3 nút nhanh:
  - `⟳ Tự động đặt tên` — theo tên gốc + timestamp cắt
  - `# Thêm ngày giờ` — thêm ngày export vào tên
  - `+ Thêm hậu tố _cut` — đơn giản, ngắn gọn

---

### Bước 5 — Xuất file

- Hiển thị thông tin tóm tắt: định dạng · chất lượng · dung lượng ước tính
- Nút **"✂️ Bắt đầu cắt video"**
- Thanh tiến trình xử lý (%)
- Sau khi xong: tự động tải file về, hoặc mở thư mục chứa
- Ghi chú bảo mật: *"Video xử lý hoàn toàn trên trình duyệt — không upload lên server"*

---

## 4. Yêu cầu kỹ thuật

| Hạng mục | Giải pháp đề xuất |
|---|---|
| Xử lý video | FFmpeg.wasm (chạy trong browser) |
| Đọc file | File API + Web Workers |
| Waveform | Web Audio API |
| UI framework | Vanilla HTML/CSS/JS hoặc React |
| Lưu file | File System Access API (hoặc download blob) |
| Hỗ trợ trình duyệt | Chrome 90+, Edge 90+, Firefox 90+, Safari 15.4+ |

---

## 5. Xác nhận tính năng

| # | Hạng mục | Quyết định |
|---|---|---|
| 1 | Multi-clip (cắt nhiều đoạn cùng lúc) | ❌ Không cần |
| 2 | Nơi xử lý video | — Không quan tâm |
| 3 | Watermark | ✅ Có — khi tích chọn, hiện ô nhập **text watermark** |
| 4 | Phạm vi nền tảng | — Không quan tâm |

**Chi tiết watermark:**
- Mặc định: tắt
- Khi người dùng tick vào option "Chèn watermark" → xuất hiện ô nhập text (ví dụ: `© Tên kênh`, `@handle`, v.v.)
- Vị trí, font size, opacity có thể bổ sung sau nếu cần

---

## 6. UI Mockup (HTML)

> Mở file `video_trimmer_mockup.html` trong cùng thư mục để xem UI mockup tương tác.

```
video_trimmer_spec.md        ← file này
video_trimmer_mockup.html    ← UI mockup (mở bằng trình duyệt)
```

Mockup bao gồm đầy đủ 5 bước, interactive: có thể click chọn tỉ lệ khung hình, chọn định dạng, đổi tên file, v.v.

---

*Tài liệu này được tạo ngày 23/04/2026 — phiên bản review UI v1.*
