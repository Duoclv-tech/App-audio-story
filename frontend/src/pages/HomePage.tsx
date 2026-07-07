import { Link, useNavigate } from 'react-router-dom'
import { Plus, History, BookOpen, Download, ScanText, PenLine, Mic, Combine, Activity, ArrowRight } from 'lucide-react'
import { useState } from 'react'
import axios from 'axios'

const FEATURES = [
  { icon: Download, title: 'Tải truyện tự động', desc: 'Tải nhiều chương cùng lúc từ TruyenFull' },
  { icon: ScanText, title: 'Kiểm tra nội dung', desc: 'Phát hiện từ bị che và thống kê' },
  { icon: PenLine, title: 'Chỉnh sửa trực tiếp', desc: 'Editor tích hợp chỉnh sửa nội dung' },
  { icon: Mic, title: 'TTS VBEE', desc: 'Chuyển văn bản thành giọng nói' },
  { icon: Combine, title: 'Nối audio', desc: 'Gộp tất cả chương thành một file' },
  { icon: Activity, title: 'Theo dõi tiến độ', desc: 'Cập nhật trạng thái theo thời gian thực' },
]

const HOSTS = [
  { name: 'TruyenFull.vision', note: 'Nguồn mặc định', primary: true },
  { name: 'TruyenMoiii.org', note: 'Hỗ trợ đầy đủ', primary: false },
  { name: 'TruyenHay.blog', note: 'Nền tảng WordPress', primary: false },
  { name: 'NguyetTruyen.net', note: 'Hỗ trợ đầy đủ', primary: false },
  { name: 'MeTruyen.mobi', note: 'Chống chặn bằng CSS', primary: false },
]

export default function HomePage() {
  const navigate = useNavigate()
  const [creating, setCreating] = useState(false)

  const handleCreateNewProject = async () => {
    setCreating(true)
    try {
      const response = await axios.post('/api/v1/stories/create-process')
      navigate(`/processor/${response.data.id}`)
    } catch (error) {
      console.error('Error creating project:', error)
      alert('Không tạo được dự án mới. Thử lại nhé.')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="space-y-8">
      {/* Welcome / hero */}
      <div className="card p-8">
        <div className="font-mono text-[11px] tracking-[0.14em] uppercase text-primary-600 dark:text-primary-400 font-semibold mb-2">
          Xưởng sản xuất audio truyện
        </div>
        <h2 className="text-3xl font-bold tracking-tight mb-3 text-balance">
          Chào mừng đến với Audio Story
        </h2>
        <p className="text-dim text-lg max-w-2xl">
          Tải truyện, biên tập, chuyển thành giọng đọc và dựng video — tất cả trong một quy trình.
        </p>
      </div>

      {/* Quick actions */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <button
          onClick={handleCreateNewProject}
          disabled={creating}
          className="group text-left rounded-xl p-6 text-white transition disabled:opacity-60 disabled:cursor-not-allowed"
          style={{
            background: 'linear-gradient(150deg, var(--accent-bright), var(--accent))',
            boxShadow: '0 8px 24px var(--accent-line)',
          }}
        >
          <div className="flex items-center justify-between mb-6">
            <Plus size={30} />
            <ArrowRight size={20} className="opacity-60 group-hover:translate-x-1 transition-transform" />
          </div>
          <h3 className="text-xl font-semibold mb-1">
            {creating ? 'Đang tạo...' : 'Tạo dự án mới'}
          </h3>
          <p className="text-white/80 text-sm">Bắt đầu tải và xử lý truyện mới</p>
        </button>

        <Link to="/history" className="card p-6 hover:-translate-y-0.5 transition-transform group">
          <History size={30} className="text-dim mb-6" />
          <h3 className="text-xl font-semibold mb-1 flex items-center gap-2">
            Lịch sử
            <ArrowRight size={18} className="text-faint opacity-0 group-hover:opacity-100 transition-opacity" />
          </h3>
          <p className="text-dim text-sm">Xem các dự án đã xử lý</p>
        </Link>

        <Link to="/settings" className="card p-6 hover:-translate-y-0.5 transition-transform group">
          <BookOpen size={30} className="text-dim mb-6" />
          <h3 className="text-xl font-semibold mb-1 flex items-center gap-2">
            Cấu hình & Hướng dẫn
            <ArrowRight size={18} className="text-faint opacity-0 group-hover:opacity-100 transition-opacity" />
          </h3>
          <p className="text-dim text-sm">Nhập API key và tùy chỉnh mặc định</p>
        </Link>
      </div>

      {/* Features */}
      <div className="card p-8">
        <h3 className="text-lg font-bold mb-6">Tính năng chính</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-8 gap-y-6">
          {FEATURES.map(({ icon: Icon, title, desc }) => (
            <div key={title} className="flex gap-3">
              <div
                className="w-9 h-9 rounded-lg shrink-0 grid place-items-center"
                style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}
              >
                <Icon size={18} />
              </div>
              <div>
                <h4 className="font-semibold text-[14.5px] mb-0.5">{title}</h4>
                <p className="text-dim text-sm">{desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Supported hosts */}
      <div className="card p-6">
        <h3 className="text-base font-bold mb-4">Nguồn được hỗ trợ</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {HOSTS.map((h) => (
            <div key={h.name} className="rounded-lg border border-token p-4 bg-surface-2">
              <div className="flex items-center gap-2 mb-1">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ background: h.primary ? 'var(--accent)' : '#1F9D6B' }}
                />
                <span className="font-semibold text-sm">{h.name}</span>
              </div>
              <p className="text-xs text-dim ml-4">{h.note}</p>
            </div>
          ))}
        </div>
        <p className="text-xs text-faint mt-4">Tự động phát hiện domain và áp dụng bộ selector phù hợp.</p>
      </div>
    </div>
  )
}
