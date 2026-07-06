"""
Seed script to populate voices table with TTS voice data
Usage: python seed_voices.py
"""

from app.database import SessionLocal
from app.models import Voice
import uuid

# Voice data - selected best 15 voices for audiobook
VOICES_DATA = [
    # Top female voices
    {
        "id": "61947d641c159f3c2c313de2",
        "code": "hn_female_ngochuyen_full_48k-fhg",
        "name": "HN - Ngọc Huyền",
        "gender": "female",
        "locale": "northern",
        "category": "review",
        "description": "Giọng nữ nổi bật nhất của Vbee, chất giọng truyền cảm, rõ ràng, phù hợp với các nội dung review phim, giải trí, quảng cáo.",
        "demo_url": "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_female_ngochuyen_fast_news_48k-thg.mp3",
        "is_active": True,
        "rank": 1
    },
    {
        "id": "62d176ca0eeb959b36831b71",
        "code": "sg_female_tuongvy_call_44k-fhg",
        "name": "SG - Tường Vy",
        "gender": "female",
        "locale": "southern",
        "category": "callcenter",
        "description": "Giọng nữ thân thiện, dễ nghe, phù hợp cho nội dung hướng dẫn, kể chuyện, quảng cáo nhẹ nhàng hoặc giao tiếp dịch vụ khách hàng.",
        "demo_url": "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_female_tuongvy_call_44k-fhg.mp3",
        "is_active": True,
        "rank": 2
    },
    {
        "id": "632c3cbde5a553c69f3207ed",
        "code": "sg_female_thaotrinh_full_44k-phg",
        "name": "SG - Thảo Trinh",
        "gender": "female",
        "locale": "southern",
        "category": "callcenter",
        "description": "Giọng nữ nhẹ nhàng, chậm rãi, nhấn nhá phù hợp với các nội dung thuyết minh, kể chuyện, podcast, sách nói.",
        "demo_url": "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_female_thaotrinh_full_44k-phg.mp3",
        "is_active": True,
        "rank": 3
    },
    {
        "id": "64dca259665065790b992266",
        "code": "hn_female_hermer_stor_48k-fhg",
        "name": "HN - Ngọc Lan",
        "gender": "female",
        "locale": "northern",
        "category": "story",
        "description": "Giọng nữ nhẹ nhàng, tình cảm, phù hợp với các nội dung sách nói, kể chuyện cho bé",
        "demo_url": "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_female_hermer_stor_48k-fhg.mp3",
        "is_active": True,
        "rank": 4
    },
    {
        "id": "61947d641c159f3c2c313de3",
        "code": "hn_female_maiphuong_vdts_48k-fhg",
        "name": "HN - Mai Phương",
        "gender": "female",
        "locale": "northern",
        "category": "education",
        "description": "Giọng nữ trung niên ấm áp, chững chạc, sâu sắc, phù hợp đọc các bản tin, phóng sự, sách nói",
        "demo_url": "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_female_maiphuong_vdts_48k_cs-thg.mp3",
        "is_active": True,
        "rank": 9
    },
    {
        "id": "61947d641c159f3c2c313de4",
        "code": "sg_female_lantrinh_vdts_48k-fhg",
        "name": "SG - Lan Trinh",
        "gender": "female",
        "locale": "southern",
        "category": "story",
        "description": "Giọng nữ trầm, chững chạc, rõ ràng, phù hợp với các nội dung thuyết minh phim, tổng đài",
        "demo_url": "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_female_lantrinh_fast_vdts_48k_cs-thg.mp3",
        "is_active": True,
        "rank": 10
    },
    {
        "id": "61947d641c159f3c2c313de5",
        "code": "hue_female_huonggiang_full_48k-fhg",
        "name": "Huế - Hương Giang",
        "gender": "female",
        "locale": "central",
        "category": "callcenter",
        "description": "Giọng nữ Huế mang đặc trưng nhẹ nhàng, cảm xúc, ngọt ngào, phù hợp với các hệ thống tổng đài, thuyết minh, quảng cáo, lịch sử địa phương.",
        "demo_url": "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hue_female_huonggiang_news_48k_cs-thg.mp3",
        "is_active": True,
        "rank": 8
    },
    # Top male voices
    {
        "id": "6599f16ffe0be226cb42ed24",
        "code": "sg_male_chidat_ebook_48k-phg",
        "name": "SG - Chí Đạt",
        "gender": "male",
        "locale": "southern",
        "category": "book",
        "description": "Giọng nam truyền cảm, rõ ràng, mang lại cảm giác gần gũi, thân thiện, phù hợp cho các nội dung thuyết minh, kể chuyện, tin tức",
        "demo_url": "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_male_chidat_ebook_48k-phg.wav",
        "is_active": True,
        "rank": 3
    },
    {
        "id": "646b478406d76f2addd3cefd",
        "code": "hn_male_phuthang_stor80dt_48k-fhg",
        "name": "HN - Anh Khôi",
        "gender": "male",
        "locale": "northern",
        "category": "story",
        "description": "Giọng nam trầm, nhấn nhá và đầy truyền cảm, phù hợp với các nội dung kể chuyện, lịch sử, phật pháp",
        "demo_url": "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_male_phuthang_stor80dt_48k-fhg.mp3",
        "is_active": True,
        "rank": 4
    },
    {
        "id": "61dceb25ad6e3f747603ba3a",
        "code": "hn_male_thanhlong_talk_48k-fhg",
        "name": "HN - Thanh Long",
        "gender": "male",
        "locale": "northern",
        "category": "book",
        "description": "Giọng nam nhẹ nhàng, điềm tĩnh, nhịp điệu ổn định, phù hợp với các thể loại kể chuyện thiếu nhi, sách nói, podcast chữa lành",
        "demo_url": "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_male_thanhlong_talk_48k-fhg.mp3",
        "is_active": True,
        "rank": 5
    },
    {
        "id": "61947d641c159f3c2c313dea",
        "code": "hn_male_manhdung_news_48k-fhg",
        "name": "HN - Mạnh Dũng",
        "gender": "male",
        "locale": "northern",
        "category": "news",
        "description": "Giọng nam mạnh mẽ, nhấn nhá linh hoạt, phù hợp với các nội dung quảng cáo, tin tức hoặc thuyết minh",
        "demo_url": "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/hn_male_manhdung_news_48k_cs-thg.mp3",
        "is_active": True,
        "rank": 5
    },
    {
        "id": "61947d641c159f3c2c313de7",
        "code": "sg_male_trungkien_vdts_48k-fhg",
        "name": "SG - Trung Kiên",
        "gender": "male",
        "locale": "southern",
        "category": "callcenter",
        "description": "Giọng nam trầm, nhấn nhá rõ ràng, phù hợp với các nội dung thuyết minh phim, review du lịch, quảng cáo",
        "demo_url": "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_male_trungkien_vdts_48k-fhg.mp3",
        "is_active": True,
        "rank": 11
    },
    {
        "id": "61947d641c159f3c2c313de8",
        "code": "hue_male_duyphuong_full_48k-fhg",
        "name": "Huế - Duy Phương",
        "gender": "male",
        "locale": "central",
        "category": "book",
        "description": "Giọng nam đặc trưng miền Trung, phù hợp với phát thanh và quảng bá cho nội dung địa phương",
        "demo_url": "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_female_duyphuong_fast_news_48k_cs-thg.mp3",
        "is_active": True,
        "rank": 12
    },
    {
        "id": "61947d641c159f3c2c313de9",
        "code": "sg_male_minhhoang_full_48k-fhg",
        "name": "SG - Minh Hoàng",
        "gender": "male",
        "locale": "southern",
        "category": "education",
        "description": "Giọng nam rõ ràng, dễ nghe, phù hợp nội dung giải trí, giáo dục",
        "demo_url": "https://vbee.s3.ap-southeast-1.amazonaws.com/audios/demo/vbee/sg_male_minhhoang_fast_news_48k_cs-thg.mp3",
        "is_active": True,
        "rank": 13
    },
]


def seed_voices():
    """Seed voices data to database"""
    db = SessionLocal()
    try:
        print("Starting voice seeding...")

        # Check if voices already exist
        existing_count = db.query(Voice).count()
        if existing_count > 0:
            print(f"Found {existing_count} existing voices. Skipping seed.")
            response = input("Do you want to clear and reseed? (y/n): ")
            if response.lower() != 'y':
                print("Seed cancelled.")
                return

            # Clear existing voices
            db.query(Voice).delete()
            db.commit()
            print("Cleared existing voices.")

        # Insert new voices
        for voice_data in VOICES_DATA:
            voice = Voice(**voice_data)
            db.add(voice)

        db.commit()
        print(f"Successfully seeded {len(VOICES_DATA)} voices!")

        # Print summary
        print("\nVoice summary:")
        print(f"  Female voices: {sum(1 for v in VOICES_DATA if v['gender'] == 'female')}")
        print(f"  Male voices: {sum(1 for v in VOICES_DATA if v['gender'] == 'male')}")
        print(f"  Northern locale: {sum(1 for v in VOICES_DATA if v['locale'] == 'northern')}")
        print(f"  Southern locale: {sum(1 for v in VOICES_DATA if v['locale'] == 'southern')}")
        print(f"  Central locale: {sum(1 for v in VOICES_DATA if v['locale'] == 'central')}")

    except Exception as e:
        print(f"Error seeding voices: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    seed_voices()
