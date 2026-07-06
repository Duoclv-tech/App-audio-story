"""
Vietnamese Word Splitter - Tách từ tiếng Việt bị dính
Sử dụng từ điển và thuật toán dynamic programming để tìm cách tách tốt nhất
"""
import re
from typing import List, Tuple, Dict, Set

class VietnameseWordSplitter:
    def __init__(self):
        # Từ điển tiếng Việt phổ biến (có thể mở rộng)
        self.vietnamese_words = {
            # Đại từ
            'tôi', 'bạn', 'anh', 'chị', 'em', 'ông', 'bà', 'cô', 'chú', 'ta', 'mình',
            'họ', 'chúng', 'nó', 'hắn', 'người', 'ai', 'gì', 'nào', 'đâu',
            # Loại bỏ 'y' vì gây tách sai như "bày" -> "bà y"

            # Động từ phổ biến
            'là', 'có', 'được', 'đã', 'đang', 'sẽ', 'làm', 'đi', 'đến', 'về', 'ở',
            'ăn', 'uống', 'ngủ', 'học', 'chơi', 'nói', 'nghe', 'nhìn', 'viết', 'đọc',
            'chạy', 'đứng', 'ngồi', 'nằm', 'cười', 'khóc', 'yêu', 'thích', 'ghét',
            'muốn', 'cần', 'phải', 'nên', 'thể', 'biết', 'hiểu', 'nghĩ', 'nhớ',
            'quên', 'tìm', 'thấy', 'gặp', 'hỏi', 'trả', 'lời', 'giúp', 'làm', 'việc',
            'quay', 'xoay', 'lấy', 'đưa', 'cầm', 'nắm', 'bắt', 'thả', 'ném', 'bỏ',
            'bày', 'bầy', 'dạy', 'tập', 'luyện', 'rèn', 'sắp', 'xếp', 'đặt', 'để',
            'trình', 'diễn', 'trưng', 'giữ', 'cất', 'dọn', 'dẹp', 'lau', 'chùi', 'rửa',

            # Tính từ
            'tốt', 'xấu', 'đẹp', 'xinh', 'cao', 'thấp', 'to', 'nhỏ', 'lớn', 'bé',
            'mới', 'cũ', 'trẻ', 'già', 'nhanh', 'chậm', 'nhiều', 'ít', 'rất', 'quá',
            'vui', 'buồn', 'hay', 'dở', 'khó', 'dễ', 'xa', 'gần', 'sạch', 'bẩn',

            # Danh từ
            'nhà', 'trường', 'lớp', 'bàn', 'ghế', 'cửa', 'sổ', 'đường', 'phố', 'xe',
            'người', 'bạn', 'thầy', 'cô', 'học', 'sinh', 'việc', 'tiền', 'giờ', 'ngày',
            'tháng', 'năm', 'sách', 'vở', 'bút', 'thước', 'túi', 'áo', 'quần', 'giày',
            'mũ', 'tay', 'chân', 'đầu', 'mặt', 'mắt', 'mũi', 'miệng', 'tai', 'tóc',
            'cơm', 'nước', 'bánh', 'kẹo', 'trái', 'cây', 'hoa', 'lá', 'rễ', 'đất',
            'trời', 'mây', 'gió', 'mưa', 'nắng', 'sáng', 'tối', 'đêm', 'sớm', 'muộn',
            'may', 'bay', 'cay', 'hay', 'gay', 'lay', 'say', 'xay', 'vay', 'tây',

            # Giới từ, liên từ
            'và', 'hoặc', 'hay', 'nhưng', 'mà', 'vì', 'để', 'cho', 'của', 'với',
            'trong', 'ngoài', 'trên', 'dưới', 'trước', 'sau', 'giữa', 'bên', 'cạnh',
            'từ', 'đến', 'tới', 'qua', 'lại', 'ra', 'vào', 'lên', 'xuống',

            # Trạng từ
            'rất', 'quá', 'lắm', 'nhiều', 'ít', 'hơn', 'nhất', 'cũng', 'đều', 'cả',
            'chỉ', 'mới', 'đã', 'sẽ', 'đang', 'vẫn', 'còn', 'luôn', 'thường', 'hay',
            'không', 'chưa', 'chẳng', 'đừng', 'đã', 'rồi', 'xong', 'hết',

            # Từ ghép phổ biến (thêm dưới dạng từ đơn để có thể tách)
            'hôm', 'qua', 'nay', 'mai', 'kia', 'ngày', 'đêm', 'tuần', 'tháng', 'năm',
            'ngoái', 'trước', 'sau', 'tới', 'sang',

            # Thêm các từ đơn tiết
            'an', 'ấy', 'khi', 'thì', 'nếu', 'như', 'bị', 'bởi', 'cái', 'con', 'cùng',
            'các', 'này', 'kia', 'ấy', 'đó', 'đây', 'kìa', 'thế', 'vậy', 'sao', 'gì',
            'chi', 'hả', 'ư', 'à', 'ạ', 'ơi', 'nhé', 'nhỉ', 'chứ', 'thôi', 'mãi',
            'cứ', 'hãy', 'đang', 'những', 'mọi', 'mỗi', 'từng', 'vài', 'mấy', 'bao',

            # Số đếm
            'một', 'hai', 'ba', 'bốn', 'năm', 'sáu', 'bảy', 'tám', 'chín', 'mười',
            'trăm', 'nghìn', 'triệu', 'tỷ',

            # Thêm các từ hay bị dính
            'khác', 'cách', 'theo', 'được', 'tập', 'xem', 'kiểm', 'tra', 'bài',
            'chuẩn', 'bị', 'gặp', 'hỏi', 'thăm', 'chăm', 'chỉ', 'cẩn', 'thận',
            'khéo', 'léo', 'xinh', 'xắn', 'rõ', 'ràng', 'tường', 'tận', 'chi', 'tiết',
            'công', 'việc', 'cuộc', 'sống', 'tình', 'yêu', 'bạn', 'thân', 'gia', 'đình',
            'quê', 'hương', 'đất', 'nước', 'dân', 'tộc', 'văn', 'hóa', 'lịch', 'sử',

            # Động từ ghép
            'ở', 'đây', 'đó', 'kia', 'đâu', 'sao', 'thế', 'nào', 'bao', 'nhiêu',
            'khi', 'nào', 'lúc', 'hồi', 'bữa', 'dịp', 'thời', 'buổi', 'tiết',
        }

        # Chuyển thành set để tra cứu nhanh hơn
        self.word_set = set(self.vietnamese_words)

        # Cache để lưu kết quả đã tính
        self.cache: Dict[str, List[str]] = {}

    def is_vietnamese_word(self, word: str) -> bool:
        """Kiểm tra một từ có trong từ điển không"""
        return word.lower() in self.word_set

    def is_valid_word(self, word: str) -> bool:
        """
        Kiểm tra xem một từ có phải là từ tiếng Việt hợp lệ không
        KHÔNG cần tách từ, chỉ kiểm tra trực tiếp

        Args:
            word: Từ cần kiểm tra

        Returns:
            True nếu từ có nghĩa, False nếu không
        """
        # Loại bỏ dấu câu
        clean_word = word.rstrip('.,!?;:""''').lstrip('""''')

        # Kiểm tra trong từ điển
        return self.is_vietnamese_word(clean_word)

    def check_word_validity(self, word: str) -> Dict[str, any]:
        """
        Kiểm tra chi tiết về một từ

        Returns:
            Dict với các thông tin:
            - is_valid: Từ có hợp lệ không
            - is_stuck: Từ có bị dính không
            - suggested_split: Gợi ý tách (nếu bị dính)
            - reason: Lý do
        """
        clean_word = word.rstrip('.,!?;:""''')

        # Kiểm tra từ gốc
        if self.is_vietnamese_word(clean_word):
            return {
                'word': word,
                'is_valid': True,
                'is_stuck': False,
                'suggested_split': None,
                'reason': 'Từ có trong từ điển tiếng Việt'
            }

        # Nếu từ không có trong từ điển, kiểm tra có thể tách không
        segments = self.split_word_dp(clean_word)

        if len(segments) > 1 and all(self.is_vietnamese_word(s.lower()) for s in segments):
            return {
                'word': word,
                'is_valid': False,
                'is_stuck': True,
                'suggested_split': ' '.join(segments),
                'reason': f'Từ bị dính, có thể tách thành: {" ".join(segments)}'
            }

        return {
            'word': word,
            'is_valid': False,
            'is_stuck': False,
            'suggested_split': None,
            'reason': 'Từ không có trong từ điển và không thể tách'
        }

    def split_word_dp(self, text: str) -> List[str]:
        """
        Sử dụng Dynamic Programming để tìm cách tách tốt nhất
        Ưu tiên các từ dài hơn và có nghĩa
        """
        if not text:
            return []

        # Kiểm tra cache
        if text in self.cache:
            return self.cache[text]

        text_lower = text.lower()
        n = len(text)

        # dp[i] = (best_score, split_position)
        # best_score là điểm cao nhất có thể đạt được từ vị trí i đến cuối
        dp = [(-float('inf'), -1) for _ in range(n + 1)]
        dp[n] = (0, -1)  # Base case: end of string

        # Duyệt ngược từ cuối về đầu
        for i in range(n - 1, -1, -1):
            # Thử tất cả các cách cắt từ vị trí i
            for j in range(i + 1, min(i + 15, n + 1)):  # Giới hạn độ dài từ tối đa 15
                word = text_lower[i:j]
                remaining_score = dp[j][0]

                if self.is_vietnamese_word(word):
                    # Từ có trong từ điển - ưu tiên từ dài
                    score = len(word) * 10 + remaining_score
                    if score > dp[i][0]:
                        dp[i] = (score, j)
                elif j == i + 1:
                    # Ký tự đơn - phạt điểm nhưng vẫn cho phép
                    score = -5 + remaining_score
                    if score > dp[i][0]:
                        dp[i] = (score, j)

        # Nếu không tìm được cách tách hợp lý, trả về nguyên văn
        if dp[0][0] == -float('inf'):
            self.cache[text] = [text]
            return [text]

        # Tái tạo kết quả
        result = []
        i = 0
        while i < n:
            j = dp[i][1]
            if j == -1:
                # Không thể tách - lấy ký tự đơn
                result.append(text[i])
                i += 1
            else:
                # Giữ nguyên chữ hoa/thường
                result.append(text[i:j])
                i = j

        self.cache[text] = result
        return result

    def find_stuck_words(self, text: str) -> List[Tuple[str, str]]:
        """
        Tìm các từ bị dính trong văn bản
        Trả về danh sách (từ_gốc, từ_đã_tách)
        """
        stuck_words = []
        words = text.split()

        for word in words:
            # Tách dấu câu cuối
            clean_word = word.rstrip('.,!?;:')
            punctuation = word[len(clean_word):]

            # Bỏ qua từ ngắn hoặc là số
            if len(clean_word) <= 2 or clean_word.isdigit():
                continue

            # QUAN TRỌNG: Kiểm tra xem từ gốc đã có nghĩa chưa
            # Nếu từ gốc đã là từ tiếng Việt hợp lệ -> không phải từ bị dính
            if self.is_vietnamese_word(clean_word.lower()):
                continue

            # Tách từ
            segments = self.split_word_dp(clean_word)

            # Nếu tách được thành nhiều phần có nghĩa
            if len(segments) > 1 and all(self.is_vietnamese_word(s.lower()) for s in segments):
                fixed = ' '.join(segments) + punctuation
                stuck_words.append((word, fixed))

        return stuck_words

    def fix_text(self, text: str) -> str:
        """
        Sửa toàn bộ văn bản, tách các từ bị dính
        """
        words = text.split()
        fixed_words = []

        for word in words:
            # Tách dấu câu cuối
            clean_word = word.rstrip('.,!?;:""''')
            punctuation = word[len(clean_word):]

            # Kiểm tra xem có phải từ bị dính không
            if len(clean_word) > 3 and not self.is_vietnamese_word(clean_word.lower()):
                segments = self.split_word_dp(clean_word)
                if len(segments) > 1:
                    fixed_words.append(' '.join(segments) + punctuation)
                else:
                    fixed_words.append(word)
            else:
                fixed_words.append(word)

        return ' '.join(fixed_words)

    def analyze_chapter(self, content: str) -> Dict:
        """
        Phân tích một chapter, tìm tất cả từ bị dính
        """
        lines = content.split('\n')
        issues = []
        fixed_lines = []
        total_stuck_words = 0

        for line_num, line in enumerate(lines, 1):
            stuck_words = self.find_stuck_words(line)
            fixed_line = line

            if stuck_words:
                total_stuck_words += len(stuck_words)
                for original, fixed in stuck_words:
                    fixed_line = fixed_line.replace(original, fixed)
                    issues.append({
                        'line': line_num,
                        'original': original,
                        'fixed': fixed,
                        'context': line[:100]
                    })

            fixed_lines.append(fixed_line)

        return {
            'total_issues': total_stuck_words,
            'issues': issues,
            'fixed_content': '\n'.join(fixed_lines)
        }


# Test function
if __name__ == "__main__":
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    splitter = VietnameseWordSplitter()

    # Test cases
    test_words = [
        "ởđây",
        "tôilà",
        "đãđến",
        "khôngthể",
        "cónhững",
        "làmviệc",
        "họcsinh",
        "hômqua",
        "ngàymai",
        "anhấy",
        "côấy",
        "chúngtôi",
        "mọingười",
        "thămhỏi",
        "cuộcsống",
        "tìnhyêu"
    ]

    print("Testing Word Splitting:\n" + "="*50)
    for word in test_words:
        segments = splitter.split_word_dp(word)
        print(f"{word:15} -> {' '.join(segments)}")

    print("\n\nTesting Full Text:\n" + "="*50)
    test_text = "Tôi đãđến nhàbạn hômqua để thămhỏi nhưng khôngthể gặpđược bạn. Anhấy đangở nhàmình vàđang làmviệc."

    fixed = splitter.fix_text(test_text)
    print(f"Original: {test_text}")
    print(f"Fixed:    {fixed}")

    stuck = splitter.find_stuck_words(test_text)
    print(f"\nStuck words found: {stuck}")