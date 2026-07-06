-- Create voices table
CREATE TABLE IF NOT EXISTS voices (
    id VARCHAR(36) PRIMARY KEY,
    code VARCHAR(100) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    gender VARCHAR(10) NOT NULL,
    locale VARCHAR(20) NOT NULL,
    category VARCHAR(50),
    description TEXT,
    demo_url VARCHAR(500),
    is_active BOOLEAN DEFAULT TRUE,
    `rank` INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_code (code),
    INDEX idx_gender (gender),
    INDEX idx_locale (locale),
    INDEX idx_active (is_active)
);

-- Insert voice data (selected best voices for audiobook)
INSERT INTO voices (id, code, name, gender, locale, category, description, demo_url, is_active, `rank`) VALUES
-- Top female voices
('61947d641c159f3c2c313de2', 'hn_female_ngochuyen_full_48k-fhg', 'HN - Ngọc Huyền', 'female', 'northern', 'review', 'Giọng nữ nổi bật nhất của Vbee, chất giọng truyền cảm, rõ ràng, phù hợp với các nội dung review phim, giải trí, quảng cáo.', 'https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_female_ngochuyen_fast_news_48k-thg.mp3', TRUE, 1),
('62d176ca0eeb959b36831b71', 'sg_female_tuongvy_call_44k-fhg', 'SG - Tường Vy', 'female', 'southern', 'callcenter', 'Giọng nữ thân thiện, dễ nghe, phù hợp cho nội dung hướng dẫn, kể chuyện, quảng cáo nhẹ nhàng hoặc giao tiếp dịch vụ khách hàng.', 'https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_female_tuongvy_call_44k-fhg.mp3', TRUE, 2),
('632c3cbde5a553c69f3207ed', 'sg_female_thaotrinh_full_44k-phg', 'SG - Thảo Trinh', 'female', 'southern', 'callcenter', 'Giọng nữ nhẹ nhàng, chậm rãi, nhấn nhá phù hợp với các nội dung thuyết minh, kể chuyện, podcast, sách nói.', 'https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_female_thaotrinh_full_44k-phg.mp3', TRUE, 3),
('64dca259665065790b992266', 'hn_female_hermer_stor_48k-fhg', 'HN - Ngọc Lan', 'female', 'northern', 'story', 'Giọng nữ nhẹ nhàng, tình cảm, phù hợp với các nội dung sách nói, kể chuyện cho bé', 'https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_female_hermer_stor_48k-fhg.mp3', TRUE, 4),
('61947d641c159f3c2c313de3', 'hn_female_maiphuong_vdts_48k-fhg', 'HN - Mai Phương', 'female', 'northern', 'education', 'Giọng nữ trung niên ấm áp, chững chạc, sâu sắc, phù hợp đọc các bản tin, phóng sự, sách nói', 'https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_female_maiphuong_vdts_48k_cs-thg.mp3', TRUE, 9),
('61947d641c159f3c2c313de4', 'sg_female_lantrinh_vdts_48k-fhg', 'SG - Lan Trinh', 'female', 'southern', 'story', 'Giọng nữ trầm, chững chạc, rõ ràng, phù hợp với các nội dung thuyết minh phim, tổng đài', 'https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_female_lantrinh_fast_vdts_48k_cs-thg.mp3', TRUE, 10),
('61947d641c159f3c2c313de5', 'hue_female_huonggiang_full_48k-fhg', 'Huế - Hương Giang', 'female', 'central', 'callcenter', 'Giọng nữ Huế mang đặc trưng nhẹ nhàng, cảm xúc, ngọt ngào, phù hợp với các hệ thống tổng đài, thuyết minh, quảng cáo, lịch sử địa phương.', 'https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hue_female_huonggiang_news_48k_cs-thg.mp3', TRUE, 8),

-- Top male voices
('6599f16ffe0be226cb42ed24', 'sg_male_chidat_ebook_48k-phg', 'SG - Chí Đạt', 'male', 'southern', 'book', 'Giọng nam truyền cảm, rõ ràng, mang lại cảm giác gần gũi, thân thiện, phù hợp cho các nội dung thuyết minh, kể chuyện, tin tức', 'https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_male_chidat_ebook_48k-phg.wav', TRUE, 3),
('646b478406d76f2addd3cefd', 'hn_male_phuthang_stor80dt_48k-fhg', 'HN - Anh Khôi', 'male', 'northern', 'story', 'Giọng nam trầm, nhấn nhá và đầy truyền cảm, phù hợp với các nội dung kể chuyện, lịch sử, phật pháp', 'https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_male_phuthang_stor80dt_48k-fhg.mp3', TRUE, 4),
('61dceb25ad6e3f747603ba3a', 'hn_male_thanhlong_talk_48k-fhg', 'HN - Thanh Long', 'male', 'northern', 'book', 'Giọng nam nhẹ nhàng, điềm tĩnh, nhịp điệu ổn định, phù hợp với các thể loại kể chuyện thiếu nhi, sách nói, podcast chữa lành', 'https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_male_thanhlong_talk_48k-fhg.mp3', TRUE, 5),
('61947d641c159f3c2c313dea', 'hn_male_manhdung_news_48k-fhg', 'HN - Mạnh Dũng', 'male', 'northern', 'news', 'Giọng nam mạnh mẽ, nhấn nhá linh hoạt, phù hợp với các nội dung quảng cáo, tin tức hoặc thuyết minh', 'https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_male_manhdung_news_48k_cs-thg.mp3', TRUE, 5),
('61947d641c159f3c2c313de7', 'sg_male_trungkien_vdts_48k-fhg', 'SG - Trung Kiên', 'male', 'southern', 'callcenter', 'Giọng nam trầm, nhấn nhá rõ ràng, phù hợp với các nội dung thuyết minh phim, review du lịch, quảng cáo', 'https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_male_trungkien_vdts_48k-fhg.mp3', TRUE, 11),
('61947d641c159f3c2c313de8', 'hue_male_duyphuong_full_48k-fhg', 'Huế - Duy Phương', 'male', 'central', 'book', 'Giọng nam đặc trưng miền Trung, phù hợp với phát thanh và quảng bá cho nội dung địa phương', 'https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_female_duyphuong_fast_news_48k_cs-thg.mp3', TRUE, 12),
('61947d641c159f3c2c313de9', 'sg_male_minhhoang_full_48k-fhg', 'SG - Minh Hoàng', 'male', 'southern', 'education', 'Giọng nam rõ ràng, dễ nghe, phù hợp nội dung giải trí, giáo dục', 'https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_male_minhhoang_fast_news_48k_cs-thg.mp3', TRUE, 13);
