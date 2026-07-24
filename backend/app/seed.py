"""
Seed default data into an empty database.

When we dropped Docker/MySQL, the SQL init scripts
(``docker/mysql/01_init.sql``, ``02_init_voices.sql``) stopped running, so the
VBEE voices and the default settings would never exist. ``init_db()`` only
creates empty tables — this module fills them on first run.

Idempotent: skips rows that already exist, so it's safe to call every startup.
"""
from loguru import logger
from sqlalchemy.orm import Session

from app import models

# (code, name, gender, locale, category, description, demo_url, rank)
# Full Vietnamese VBEE catalog (25 voices) pulled from the public voice list
# GET https://vbee.vn/api/v1/voices, filtered to provider=vbee + language vi-VN,
# ordered by VBEE's own ``rank`` (1 = most prominent). Superseded the original
# 14 ported from docker/mysql/02_init_voices.sql.
_VOICES = [
    ("hn_female_ngochuyen_full_24k-st", "Ngọc Huyền 2.0", "female", "northern", "review", "Giọng nữ nổi bật của Vbee, giọng đọc nhấn nhá, truyền cảm, bay bổng, tự nhiên như người thật. Phù hợp với các nội dung đọc thơ, đọc truyện truyền cảm.", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_female_ngochuyen_full_24k-st.mp3", 1),
    ("hn_female_ngochuyen_full_48k-fhg", "HN - Ngọc Huyền", "female", "northern", "review", "Giọng nữ nổi bật nhất của Vbee, chất giọng truyền cảm, rõ ràng, phù hợp với các nội dung review phim, giải trí, quảng cáo.", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_female_ngochuyen_fast_news_48k-thg.mp3", 1),
    ("hn_male_manhdung_full_24k-st", "Mạnh Dũng 2.0 (Beta)", "male", "northern", "advertise", "Giọng nam mạnh mẽ, nhấn nhá linh hoạt, phù hợp với các nội dung quảng cáo, tin tức hoặc thuyết minh", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_male_manhdung_full_24k-st.mp3", 1),
    ("hn_male_minhquan_yt_24k-pre", "Minh Quân Pro (Beta)", "male", "northern", "advertise", "Giọng nam tự nhiên, trẻ trung, phát âm rõ ràng, có khả năng chuyển đổi mượt mà giữa tiếng Việt và tiếng Anh (code-switching), phù hợp với các nội dung podcast, thể thao, giải trí, công nghệ và video dành cho giới trẻ.", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_male_minhquan_yt_24k-pre.mp3", 1),
    ("hn_female_nganha_child_22k-vc", "HN - Ngân Hà", "female", "northern", "children", "Giọng bé gái trong trẻo, dễ thương, phù hợp với các nội dung giáo dục, sách nói, truyện cổ tích, video học tập.", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_female_nganha_child_22k-vc.mp3", 2),
    ("hn_male_minhquan_yt-stable", "HN - Minh Quân", "male", "northern", "advertise", "Giọng nam trẻ trung, nhấn nhá, phù hợp với các nội dung tin tức giải trí, quảng cáo, khoa học công nghệ.", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_male_minhquan_yt-stable.mp3", 2),
    ("hn_male_vietbach_child_22k-vc", "HN - Việt Bách", "male", "northern", "children", "Giọng bé trai trong sáng, dễ thương, tự nhiên và gần gũi, phù hợp cho các nội dung thiếu nhi, sách nói, truyện cổ tích, giáo dục cho bé", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_male_vietbach_child_22k-vc.mp3", 2),
    ("sg_female_tuongvy_call_44k-fhg", "SG - Tường Vy", "female", "southern", "callcenter", "Giọng nữ thân thiện, dễ nghe, phù hợp cho nội dung hướng dẫn, kể chuyện, quảng cáo nhẹ nhàng hoặc giao tiếp dịch vụ khách hàng.", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_female_tuongvy_call_44k-fhg.mp3", 2),
    ("hn_female_hachi_book_22k-vc", "HN - Hà Chi", "female", "northern", "story", "Giọng nữ chậm rãi, nhấn nhá tự nhiên, phù hợp cho thuyết minh, đọc tin tức hoặc trình bày nội dung chuyên nghiệp", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_female_hachi_book_22k-vc.mp3", 3),
    ("sg_female_thaotrinh_full_44k-phg", "SG - Thảo Trinh", "female", "southern", "callcenter", "Giọng nữ nhẹ nhàng, chậm rãi, nhấn nhá phù hợp với các nội dung thuyết minh, kể chuyện, podcast, sách nói.", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_female_thaotrinh_full_44k-phg.mp3", 3),
    ("sg_male_chidat_ebook_48k-phg", "SG - Chí Đạt", "male", "southern", "book", "Giọng nam truyền cảm, rõ ràng, mang lại cảm giác gần gũi, thân thiện, phù hợp cho các nội dung thuyết minh, kể chuyện, tin tức", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_male_chidat_ebook_48k-phg.wav", 3),
    ("hn_female_hermer_stor_48k-fhg", "HN - Ngọc Lan", "female", "northern", "story", "Giọng nữ nhẹ nhàng, tình cảm, phù hợp với các nội dung sách nói, kể chuyện cho bé", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_female_hermer_stor_48k-fhg.mp3", 4),
    ("hn_female_lenka_stor_48k-phg", "HN - Nguyệt Dương", "female", "northern", "story", "Giọng nữ nhẹ nhàng, thân thiện, phù hợp chăm sóc khách hàng hoặc thuyết minh/tài liệu.", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_female_lenka_stor_48k-phg.wav", 4),
    ("hn_male_phuthang_stor80dt_48k-fhg", "HN - Anh Khôi", "male", "northern", "story", "Giọng nam trầm, nhấn nhá và đầy truyền cảm, phù hợp với các nội dung kể chuyện, lịch sử, phật pháp", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_male_phuthang_stor80dt_48k-fhg.mp3", 4),
    ("hn_male_manhdung_news_48k-fhg", "HN - Mạnh Dũng", "male", "northern", "news", "Giọng nam mạnh mẽ, nhấn nhá linh hoạt, phù hợp với các nội dung quảng cáo, tin tức hoặc thuyết minh", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_male_manhdung_news_48k_cs-thg.mp3", 5),
    ("hn_male_thanhlong_talk_48k-fhg", "HN - Thanh Long", "male", "northern", "book", "Giọng nam nhẹ nhàng, điềm tĩnh, nhịp điệu ổn định, phù hợp với các thể loại kể chuyện thiếu nhi, sách nói, podcast chữa lành", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_male_thanhlong_talk_48k-fhg.mp3", 5),
    ("sg_female_thaotrinh_full_48k-fhg", "SG - Thảo Trinh", "female", "southern", "book", "Giọng nữ nhẹ nhàng, chậm rãi, nhấn nhá phù hợp với các nội dung thuyết minh, kể chuyện, podcast, sách nói, tổng đài", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_female_thaotrinh_fast_news_48k_cs-thg.mp3", 6),
    ("hn_male_phuthang_news65dt_44k-fhg", "HN - Anh Khôi", "male", "northern", "news", "Giọng nam trầm, nhấn nhá và đầy truyền cảm, phù hợp với các nội dung kể chuyện, lịch sử, phật pháp", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_male_phuthang_news65dt_44k-fhg.mp3", 7),
    ("hue_female_huonggiang_full_48k-fhg", "Huế - Hương Giang", "female", "central", "callcenter", "Giọng nữ Huế mang đặc trưng nhẹ nhàng, cảm xúc, ngọt ngào, phù hợp với các hệ thống tổng đài, thuyết minh, quảng cáo, lịch sử địa phương.", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hue_female_huonggiang_news_48k_cs-thg.mp3", 8),
    ("hn_female_maiphuong_vdts_48k-fhg", "HN - Mai Phương", "female", "northern", "education", "Giọng nữ trung niên ấm áp, chững chạc, sâu sắc, phù hợp đọc các bản tin, phóng sự, sách nói", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_female_maiphuong_vdts_48k_cs-thg.mp3", 9),
    ("sg_female_lantrinh_vdts_48k-fhg", "SG - Lan Trinh", "female", "southern", "story", "Giọng nữ trầm, chững chạc, rõ ràng, phù hợp với các nội dung thuyết minh phim, tổng đài", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_female_lantrinh_fast_vdts_48k_cs-thg.mp3", 10),
    ("sg_male_trungkien_vdts_48k-fhg", "SG - Trung Kiên", "male", "southern", "callcenter", "Giọng nam trầm, nhấn nhá rõ ràng, phù hợp với các nội dung thuyết minh phim, review du lịch, quảng cáo", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_male_trungkien_vdts_48k-fhg.mp3", 11),
    ("hue_male_duyphuong_full_48k-fhg", "Huế - Duy Phương", "male", "central", "book", "Giọng nam đặc trưng miền Trung, phù hợp với phát thanh và quảng bá cho nội dung địa phương", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_female_duyphuong_fast_news_48k_cs-thg.mp3", 12),
    ("sg_male_minhhoang_full_48k-fhg", "SG - Minh Hoàng", "male", "southern", "education", "Giọng nam rõ ràng, dễ nghe, phù hợp nội dung giải trí, giáo dục", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_male_minhhoang_fast_news_48k_cs-thg.mp3", 13),
    ("hn_male_manhdung_news_48k-phg", "HN - Mạnh Dũng", "male", "northern", "advertise", "Giọng nam mạnh mẽ, nhấn nhá linh hoạt, phù hợp với các nội dung quảng cáo, tin tức hoặc thuyết minh", "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_male_manhdung_news_48k-phg.mp3", 14),
]

# setting_key -> default value (native Python; stored in a JSON column)
# Ported from docker/mysql/01_init.sql
_SETTINGS = {
    "tts_voice": "hn_female_ngochuyen_full_48k-fhg",
    "tts_speed": 1.0,
    "tts_volume": 100,
    "auto_check_grammar": True,
    "auto_run_tts": False,
    "audio_format": "mp3",
    "audio_bitrate": "192k",
    # AI grammar/spell-check provider: "openai" (preferred) or "gemini".
    "AI_GRAMMAR_PROVIDER": "openai",
    # Where finished files (video/audio/word) are delivered. Empty = the OS
    # Downloads folder (resolved at runtime in output_delivery.get_output_folder).
    "output_folder": "",
}


def _seed_voices(db: Session) -> int:
    existing = {code for (code,) in db.query(models.Voice.code).all()}
    added = 0
    for code, name, gender, locale, category, description, demo_url, rank in _VOICES:
        if code in existing:
            continue
        db.add(models.Voice(
            code=code, name=name, gender=gender, locale=locale,
            category=category, description=description, demo_url=demo_url,
            is_active=True, rank=rank,
        ))
        added += 1
    return added


def _seed_settings(db: Session) -> int:
    existing = {k for (k,) in db.query(models.Setting.setting_key).all()}
    added = 0
    for key, value in _SETTINGS.items():
        if key in existing:
            continue
        db.add(models.Setting(setting_key=key, setting_value=value))
        added += 1
    return added


def seed_defaults() -> None:
    """Populate voices + settings if missing. Safe to call on every startup."""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        v = _seed_voices(db)
        s = _seed_settings(db)
        if v or s:
            db.commit()
            logger.info(f"Seeded defaults: {v} voices, {s} settings")
        else:
            logger.info("Seed: defaults already present, nothing to add")
    except Exception as e:
        db.rollback()
        logger.error(f"Seeding failed: {e}")
    finally:
        db.close()
