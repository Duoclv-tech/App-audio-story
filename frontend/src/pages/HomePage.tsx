import { Link, useNavigate } from 'react-router-dom'
import {
  Plus, ArrowRight, ChevronRight, BookOpen, Clock, AudioLines,
  FileText, PenLine, Mic, Video, FolderOpen, Loader2, Zap,
} from 'lucide-react'
import { useState, useEffect } from 'react'
import axios from 'axios'

interface Overview {
  total_projects: number
  total_audio_generated: number
  running_count: number
}

interface RecentStory {
  id: string
  title: string
  author?: string
  start_chapter: number
  end_chapter: number
  status: string
  current_step: number
  updated_at: string
  total_downloaded: number
  total_audio_generated: number
  has_merged_audio: boolean
}

const TOTAL_STEPS = 8 // WORKFLOW_STEPS length in ProcessorPage (step 2 "Tải" is hidden)

// Grouped overview of the real 8-step workflow into 4 human-facing phases
const FLOW = [
  { icon: FileText, title: 'Nhập nội dung', desc: 'Dán văn bản, tải file .txt hoặc chọn cả thư mục truyện.' },
  { icon: PenLine, title: 'Biên tập & kiểm tra', desc: 'Tự tách chương, chỉnh sửa trực tiếp, kiểm duyệt từ ngữ.' },
  { icon: Mic, title: 'Chuyển giọng đọc', desc: 'TTS từng câu (VBEE / OmniVoice), retry riêng rồi ghép 1 file.' },
  { icon: Video, title: 'Dựng video', desc: 'Ghép audio với hình nền, visualizer sóng nhạc, xuất video.' },
]

// Vietnamese status → { label, tailwind classes } (mirrors HistoryPage colors)
const STATUS: Record<string, { label: string; cls: string }> = {
  draft: { label: 'Bản nháp', cls: 'bg-surface-3 text-strong' },
  created: { label: 'Đã tạo', cls: 'bg-primary-100 dark:bg-primary-500/20 text-primary-800 dark:text-primary-300' },
  downloading: { label: 'Đang tải', cls: 'bg-yellow-100 dark:bg-yellow-500/20 text-yellow-800 dark:text-yellow-300' },
  downloaded: { label: 'Đã tải', cls: 'bg-green-100 dark:bg-green-500/20 text-green-800 dark:text-green-300' },
  ready_for_tts: { label: 'Sẵn sàng TTS', cls: 'bg-primary-100 dark:bg-primary-500/20 text-primary-800 dark:text-primary-300' },
  tts_processing: { label: 'Đang đọc TTS', cls: 'bg-orange-100 dark:bg-orange-500/20 text-orange-800 dark:text-orange-300' },
  tts_completed: { label: 'TTS xong', cls: 'bg-teal-100 dark:bg-teal-500/20 text-teal-800 dark:text-teal-300' },
  completed: { label: 'Hoàn tất', cls: 'bg-green-100 dark:bg-green-500/20 text-green-800 dark:text-green-300' },
}

function greeting() {
  const h = new Date().getHours()
  if (h < 11) return 'Chào buổi sáng'
  if (h < 14) return 'Chào buổi trưa'
  if (h < 18) return 'Chào buổi chiều'
  return 'Chào buổi tối'
}

function relativeTime(iso: string) {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const diff = Date.now() - then
  const m = Math.floor(diff / 60000)
  if (m < 1) return 'vừa xong'
  if (m < 60) return `${m} phút trước`
  const hrs = Math.floor(m / 60)
  if (hrs < 24) return `${hrs} giờ trước`
  const d = Math.floor(hrs / 24)
  if (d === 1) return 'hôm qua'
  if (d < 30) return `${d} ngày trước`
  return new Date(iso).toLocaleDateString('vi-VN')
}

export default function HomePage() {
  const navigate = useNavigate()
  const [creating, setCreating] = useState(false)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [recent, setRecent] = useState<RecentStory[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const [ov, rc] = await Promise.all([
          axios.get<Overview>('/api/v1/stories/overview'),
          axios.get<{ data: RecentStory[] }>('/api/v1/stories/with-stats?page=1&page_size=6'),
        ])
        if (!alive) return
        setOverview(ov.data)
        setRecent(rc.data.data)
      } catch (error) {
        console.error('Error loading home data:', error)
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => { alive = false }
  }, [])

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

  const stats = [
    { n: overview?.total_projects ?? '—', label: 'Dự án', cls: '' },
    { n: overview?.total_audio_generated ?? '—', label: 'Audio đã tạo', cls: 'text-green-600 dark:text-green-400' },
    { n: overview?.running_count ?? '—', label: 'Đang chạy', cls: 'text-orange-600 dark:text-orange-400' },
  ]

  return (
    <div className="space-y-6">
      {/* ── Hero: compact, greeting + stats + CTA ── */}
      <div
        className="card p-6 flex flex-wrap items-center gap-6"
        style={{
          backgroundImage:
            'radial-gradient(120% 140% at 100% 0%, var(--accent-soft), transparent 55%)',
        }}
      >
        <div className="flex-1 min-w-[260px]">
          <div className="font-mono text-[11px] tracking-[0.14em] uppercase text-primary-600 dark:text-primary-400 font-semibold">
            Xưởng sản xuất audio truyện
          </div>
          <h2 className="text-2xl font-bold tracking-tight mt-1.5 mb-1 text-balance">
            {greeting()} <span className="inline-block">👋</span>
          </h2>
          <p className="text-dim max-w-xl">
            Nhập nội dung, biên tập, chuyển thành giọng đọc và dựng video — tất cả trong một quy trình.
          </p>
          <div className="flex flex-wrap gap-2.5 mt-4">
            <button
              onClick={handleCreateNewProject}
              disabled={creating}
              className="inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-white text-sm font-semibold transition disabled:opacity-60 disabled:cursor-not-allowed"
              style={{ background: 'var(--accent)', boxShadow: '0 2px 8px var(--accent-line)' }}
            >
              {creating ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
              {creating ? 'Đang tạo...' : 'Tạo dự án mới'}
            </button>
            <Link
              to="/quick-build"
              className="inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold border border-token-strong text-strong hover:bg-surface-2 transition"
            >
              <Zap size={16} style={{ color: 'var(--accent)' }} /> Build Batch
            </Link>
            <Link
              to="/settings"
              className="inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold border border-token-strong text-strong hover:bg-surface-2 transition"
            >
              Xem hướng dẫn
            </Link>
          </div>
        </div>

        {/* Stat tiles */}
        <div className="flex gap-2.5">
          {stats.map((s) => (
            <div key={s.label} className="rounded-xl bg-surface-2 border border-token px-4 py-3 min-w-[92px]">
              <div className={`text-xl font-bold tabular-nums tracking-tight ${s.cls}`}>{s.n}</div>
              <div className="text-faint text-xs mt-0.5">{s.label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Workflow overview (4 phases) ── */}
      <div>
        <div className="flex items-baseline justify-between mb-3 px-0.5">
          <h3 className="text-[15px] font-bold">Quy trình 4 bước</h3>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {FLOW.map(({ icon: Icon, title, desc }, i) => (
            <div key={title} className="card p-4 relative">
              <div
                className="w-6 h-6 rounded-lg grid place-items-center text-xs font-bold mb-2.5"
                style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}
              >
                {i + 1}
              </div>
              <Icon size={20} style={{ color: 'var(--accent)' }} className="mb-2" />
              <h4 className="font-semibold text-sm mb-0.5">{title}</h4>
              <p className="text-faint text-xs leading-snug">{desc}</p>
              {i < FLOW.length - 1 && (
                <ChevronRight
                  size={18}
                  className="hidden lg:block absolute -right-2.5 top-1/2 -translate-y-1/2 text-faint z-10"
                />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* ── Primary CTA banner ── */}
      <button
        onClick={handleCreateNewProject}
        disabled={creating}
        className="w-full text-left rounded-2xl p-5 flex items-center gap-4 text-white transition disabled:opacity-60 disabled:cursor-not-allowed"
        style={{
          background: 'linear-gradient(135deg, var(--accent-bright), var(--accent))',
          boxShadow: '0 8px 24px var(--accent-line)',
        }}
      >
        <div className="shrink-0 w-11 h-11 rounded-xl grid place-items-center bg-white/20">
          <Plus size={22} />
        </div>
        <div className="flex-1">
          <h3 className="text-lg font-semibold">{creating ? 'Đang tạo...' : 'Tạo dự án mới'}</h3>
          <p className="text-white/85 text-sm">Bắt đầu nhập và xử lý một truyện mới từ đầu.</p>
        </div>
        <span className="shrink-0 inline-flex items-center gap-2 bg-white rounded-xl px-4 py-2.5 font-bold text-sm" style={{ color: 'var(--accent)' }}>
          Bắt đầu ngay
          <ArrowRight size={18} />
        </span>
      </button>

      {/* ── Recent projects ── */}
      <div>
        <div className="flex items-baseline justify-between mb-3 px-0.5">
          <h3 className="text-[15px] font-bold">Dự án gần đây</h3>
          <Link to="/history" className="text-sm font-semibold text-primary-600 dark:text-primary-400 hover:underline">
            Xem tất cả trong Lịch sử →
          </Link>
        </div>

        {loading ? (
          <div className="card p-8 text-center text-dim flex items-center justify-center gap-2">
            <Loader2 size={16} className="animate-spin" /> Đang tải…
          </div>
        ) : recent.length === 0 ? (
          <button
            onClick={handleCreateNewProject}
            className="card w-full p-8 border-dashed grid place-items-center gap-2 text-faint hover:text-primary-600 dark:hover:text-primary-400 transition"
          >
            <FolderOpen size={28} />
            <span className="text-sm">Chưa có dự án nào — bấm để tạo dự án đầu tiên.</span>
          </button>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {recent.map((s) => {
              const st = STATUS[s.status] ?? { label: s.status, cls: 'bg-surface-3 text-strong' }
              const pct = Math.max(6, Math.round((Math.min(s.current_step || 1, TOTAL_STEPS) / TOTAL_STEPS) * 100))
              const running = s.status === 'downloading' || s.status === 'tts_processing'
              return (
                <button
                  key={s.id}
                  onClick={() => navigate(`/processor/${s.id}`)}
                  className="card text-left p-0 overflow-hidden hover:-translate-y-0.5 hover:shadow-md transition"
                >
                  <div className="flex items-start gap-3 p-4 pb-3">
                    <div
                      className="shrink-0 w-10 h-10 rounded-lg grid place-items-center"
                      style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}
                    >
                      <BookOpen size={18} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="font-semibold text-sm truncate">{s.title || 'Chưa đặt tên'}</div>
                      <div className="text-faint text-xs mt-0.5 font-mono flex items-center gap-1.5">
                        <AudioLines size={12} /> {s.total_audio_generated} audio
                        <span className="opacity-40">·</span>
                        <Clock size={12} /> {relativeTime(s.updated_at)}
                      </div>
                    </div>
                  </div>
                  <div className="px-4 pb-4">
                    <div className="flex items-center justify-between mb-1.5">
                      <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium ${st.cls}`}>
                        {running && <Loader2 size={11} className="animate-spin" />}
                        {st.label}
                      </span>
                      <span className="text-faint text-xs font-mono">bước {Math.min(s.current_step || 1, TOTAL_STEPS)}/{TOTAL_STEPS}</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-surface-3 overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${pct}%`, background: 'linear-gradient(90deg, var(--accent), #2f8f4e)' }}
                      />
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
