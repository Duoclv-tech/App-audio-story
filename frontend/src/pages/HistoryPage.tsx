import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import {
  ChevronRight, ChevronDown, Zap, Trash2, ExternalLink,
} from 'lucide-react'
import {
  historyFeed, deleteBatch,
  type FeedEntry, type HistStory, type HistBatch, type HistBatchJob,
  type HistBatchConfig, type FeedMeta,
} from '../services/historyApi'

const baseName = (p: string) => p.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || p

// AI Voice local picks its voice by mode, not a voice_code; label it for humans.
const localModeLabel = (mode: string | null | undefined) =>
  mode === 'design' ? 'thiết kế' : mode === 'clone' ? 'clone' : 'mặc định'

export default function HistoryPage() {
  const navigate = useNavigate()
  const listRef = useRef<HTMLDivElement>(null)
  const [entries, setEntries] = useState<FeedEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [favoriteOnly, setFavoriteOnly] = useState(false)
  const [currentPage, setCurrentPage] = useState(1)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [meta, setMeta] = useState<FeedMeta>({ total: 0, page: 1, page_size: 20, total_pages: 0 })
  const [delStory, setDelStory] = useState<HistStory | null>(null)
  const [delBatch, setDelBatch] = useState<HistBatch | null>(null)
  const [busy, setBusy] = useState(false)
  const [exporting, setExporting] = useState<string | null>(null)
  const [notice, setNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  useEffect(() => { loadFeed(currentPage) }, [currentPage, favoriteOnly])

  const flash = (type: 'success' | 'error', text: string) => {
    setNotice({ type, text })
    setTimeout(() => setNotice(null), 5000)
  }

  const loadFeed = async (page = 1) => {
    try {
      setLoading(true)
      const res = await historyFeed(page, favoriteOnly)
      setEntries(res.data)
      setMeta(res.meta)
    } catch (e) {
      console.error('Error loading history feed:', e)
    } finally {
      setLoading(false)
    }
  }

  const toggleExpand = (batchId: string) =>
    setExpanded(prev => {
      const next = new Set(prev)
      next.has(batchId) ? next.delete(batchId) : next.add(batchId)
      return next
    })

  const handleExport = async (storyId: string, fmt: 'word' | 'txt') => {
    setExporting(`${storyId}:${fmt}`)
    try {
      const r = await axios.get(`/api/v1/export/${storyId}/${fmt}`)
      flash('success', `Đã lưu ${fmt.toUpperCase()} vào: ${r.data.folder}`)
    } catch (e: any) {
      flash('error', e.response?.data?.detail || `Lỗi khi xuất file ${fmt.toUpperCase()}`)
    } finally {
      setExporting(null)
    }
  }

  const handleToggleFavorite = async (storyId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      const r = await axios.post(`/api/v1/stories/${storyId}/toggle-favorite`)
      setEntries(prev => prev.map(en =>
        en.kind === 'story' && en.story.id === storyId
          ? { ...en, story: { ...en.story, is_favorite: r.data.is_favorite } }
          : en))
    } catch (e) {
      console.error('Error toggling favorite:', e)
    }
  }

  const confirmDeleteStory = async () => {
    if (!delStory) return
    try {
      setBusy(true)
      await axios.delete(`/api/v1/stories/${delStory.id}`)
      setDelStory(null)
      await reloadAfterDelete()
    } catch (e) {
      flash('error', 'Xoá truyện thất bại')
    } finally { setBusy(false) }
  }

  const confirmDeleteBatch = async () => {
    if (!delBatch) return
    try {
      setBusy(true)
      await deleteBatch(delBatch.id)
      setDelBatch(null)
      await reloadAfterDelete()
    } catch (e: any) {
      flash('error', e.response?.data?.detail || 'Xoá mẻ build thất bại')
    } finally { setBusy(false) }
  }

  const reloadAfterDelete = async () => {
    if (entries.length === 1 && currentPage > 1) setCurrentPage(currentPage - 1)
    else await loadFeed(currentPage)
  }

  const handlePageChange = (p: number) => {
    if (p >= 1 && p <= meta.total_pages) {
      setCurrentPage(p)
      listRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }

  // ---- search filter (client-side, within the current page) ---------------
  const term = searchTerm.trim().toLowerCase()
  const matchStory = (s: HistStory) =>
    s.title.toLowerCase().includes(term) ||
    s.url.toLowerCase().includes(term) ||
    (s.author?.toLowerCase().includes(term) ?? false)
  const matchBatch = (b: HistBatch) =>
    (b.folder_label?.toLowerCase().includes(term) ?? false) ||
    (b.preset_name?.toLowerCase().includes(term) ?? false) ||
    b.jobs.some(j => (j.title || '').toLowerCase().includes(term))
  const visible = entries.filter(en =>
    !term || (en.kind === 'story' ? matchStory(en.story) : matchBatch(en.batch)))

  const storyCount = entries.filter(e => e.kind === 'story').length
  const batchCount = entries.filter(e => e.kind === 'batch').length

  if (loading) {
    return (
      <div className="bg-surface rounded-lg shadow-sm p-8">
        <div className="text-center text-dim">Đang tải lịch sử...</div>
      </div>
    )
  }

  return (
    <div className="h-[calc(100vh-3rem)]">
      {notice && (
        <div className={`fixed bottom-6 right-6 z-50 max-w-md px-4 py-3 rounded-lg shadow-lg text-sm break-all ${
          notice.type === 'success'
            ? 'bg-green-50 dark:bg-green-500/10 border border-green-200 dark:border-green-500/30 text-green-800 dark:text-green-300'
            : 'bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 text-red-800 dark:text-red-300'
        }`}>{notice.text}</div>
      )}

      <div className="bg-surface rounded-lg shadow-sm p-8 h-full flex flex-col">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold">Lịch Sử</h2>
          <button
            onClick={() => loadFeed(currentPage)}
            className="text-sm text-primary-600 dark:text-primary-400 hover:text-primary-800 dark:hover:text-primary-300 underline"
          >Làm mới</button>
        </div>

        {/* Search + filters */}
        <div className="mb-6 space-y-3">
          <input
            type="text"
            placeholder="Tìm theo tên truyện, URL, tác giả, hoặc tên folder/preset..."
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
            className="w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
          <label className="flex items-center gap-2 cursor-pointer w-fit">
            <input
              type="checkbox"
              checked={favoriteOnly}
              onChange={e => { setFavoriteOnly(e.target.checked); setCurrentPage(1) }}
              className="w-4 h-4 text-primary-600 border-token rounded focus:ring-primary-500"
            />
            <span className="flex items-center gap-1 text-sm text-dim">
              <svg className="w-4 h-4 text-yellow-500 fill-current" viewBox="0 0 24 24">
                <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
              </svg>
              Chỉ hiển thị truyện yêu thích
            </span>
          </label>
        </div>

        {/* Summary */}
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-primary-50 dark:bg-primary-500/10 p-4 rounded-lg">
            <div className="text-2xl font-bold text-primary-600 dark:text-primary-400">{meta.total}</div>
            <div className="text-sm text-dim">Tổng số mục</div>
          </div>
          <div className="bg-green-50 dark:bg-green-500/10 p-4 rounded-lg">
            <div className="text-2xl font-bold text-green-600 dark:text-green-400">{storyCount}</div>
            <div className="text-sm text-dim">Truyện lẻ (trang này)</div>
          </div>
          <div className="bg-orange-50 dark:bg-orange-500/10 p-4 rounded-lg">
            <div className="text-2xl font-bold text-orange-600 dark:text-orange-400">{batchCount}</div>
            <div className="text-sm text-dim">Mẻ Build Batch (trang này)</div>
          </div>
        </div>

        {/* Feed */}
        <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto -mx-8 px-8">
          {visible.length === 0 ? (
            <div className="text-center text-dim py-12">
              {term ? 'Không tìm thấy mục nào' : 'Chưa có gì trong lịch sử'}
            </div>
          ) : (
            <div className="space-y-4">
              {visible.map(en => en.kind === 'story' ? (
                <StoryRow
                  key={`s-${en.story.id}`}
                  story={en.story}
                  exporting={exporting}
                  onOpen={() => navigate(`/processor/${en.story.id}`)}
                  onExport={handleExport}
                  onToggleFav={handleToggleFavorite}
                  onDelete={() => setDelStory(en.story)}
                />
              ) : (
                <BatchGroup
                  key={`b-${en.batch.id}`}
                  batch={en.batch}
                  open={expanded.has(en.batch.id)}
                  onToggle={() => toggleExpand(en.batch.id)}
                  onOpenBatch={() => navigate(`/quick-build?batch=${en.batch.id}`)}
                  onDelete={() => setDelBatch(en.batch)}
                />
              ))}
            </div>
          )}
        </div>

        {/* Pagination */}
        {meta.total_pages > 1 && (
          <div className="mt-6 flex items-center justify-between border-t pt-6">
            <div className="text-sm text-dim">
              Trang {currentPage} / {meta.total_pages} · tổng {meta.total} mục
            </div>
            <div className="flex items-center gap-2">
              <button onClick={() => handlePageChange(1)} disabled={currentPage === 1}
                className="px-3 py-2 rounded-md border disabled:opacity-50 hover:bg-surface-2">««</button>
              <button onClick={() => handlePageChange(currentPage - 1)} disabled={currentPage === 1}
                className="px-3 py-2 rounded-md border disabled:opacity-50 hover:bg-surface-2">«</button>
              <div className="flex items-center gap-1">
                {Array.from({ length: Math.min(5, meta.total_pages) }, (_, i) => {
                  let n: number
                  if (meta.total_pages <= 5) n = i + 1
                  else if (currentPage <= 3) n = i + 1
                  else if (currentPage >= meta.total_pages - 2) n = meta.total_pages - 4 + i
                  else n = currentPage - 2 + i
                  return (
                    <button key={n} onClick={() => handlePageChange(n)}
                      className={`px-4 py-2 rounded-md border ${currentPage === n ? 'bg-primary-500 text-white border-primary-500' : 'hover:bg-surface-2'}`}>{n}</button>
                  )
                })}
              </div>
              <button onClick={() => handlePageChange(currentPage + 1)} disabled={currentPage === meta.total_pages}
                className="px-3 py-2 rounded-md border disabled:opacity-50 hover:bg-surface-2">»</button>
              <button onClick={() => handlePageChange(meta.total_pages)} disabled={currentPage === meta.total_pages}
                className="px-3 py-2 rounded-md border disabled:opacity-50 hover:bg-surface-2">»»</button>
            </div>
          </div>
        )}
      </div>

      {/* Delete story dialog */}
      {delStory && (
        <ConfirmDialog
          title="Xác nhận xoá truyện"
          body={<>Bạn có chắc muốn xoá truyện:<span className="block mt-2 font-medium text-strong">"{delStory.title}"</span></>}
          warn="Hành động này xoá tất cả chapters, audio files và không thể hoàn tác."
          busy={busy}
          onCancel={() => setDelStory(null)}
          onConfirm={confirmDeleteStory}
        />
      )}

      {/* Delete batch dialog */}
      {delBatch && (
        <ConfirmDialog
          title="Xác nhận xoá mẻ build"
          body={<>Xoá cả mẻ <span className="font-medium text-strong">Build Batch · {delBatch.folder_label || '—'}</span> ({delBatch.total} truyện)?</>}
          warn="Xoá toàn bộ truyện + audio trung gian của mẻ. File video đã xuất ở thư mục Downloads KHÔNG bị xoá."
          busy={busy}
          onCancel={() => setDelBatch(null)}
          onConfirm={confirmDeleteBatch}
        />
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- //
//  Standalone (wizard) story row — unchanged layout from the old flat history
// --------------------------------------------------------------------------- //
function StoryRow({ story, exporting, onOpen, onExport, onToggleFav, onDelete }: {
  story: HistStory
  exporting: string | null
  onOpen: () => void
  onExport: (id: string, fmt: 'word' | 'txt') => void
  onToggleFav: (id: string, e: React.MouseEvent) => void
  onDelete: () => void
}) {
  return (
    <div className="border rounded-lg p-4 hover:bg-surface-2 transition-colors">
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-2">
            <button onClick={e => onToggleFav(story.id, e)} className="flex-shrink-0 hover:scale-110 transition-transform"
              title={story.is_favorite ? 'Bỏ yêu thích' : 'Yêu thích'}>
              {story.is_favorite ? (
                <svg className="w-6 h-6 text-yellow-500 fill-current" viewBox="0 0 24 24">
                  <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                </svg>
              ) : (
                <svg className="w-6 h-6 text-faint hover:text-yellow-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
                </svg>
              )}
            </button>
            <h3 className="text-lg font-semibold truncate">{story.title}</h3>
            <StatusBadge status={story.status} />
          </div>
          <div className="text-sm text-dim space-y-1">
            {story.author && <div><span className="font-medium">Tác giả:</span> {story.author}</div>}
            <div className="flex items-center gap-4">
              <span>{story.total_downloaded} chương</span>
              <span>{story.total_audio_generated} audio</span>
              {story.has_merged_audio && <span className="text-primary-600 dark:text-primary-400">File merge sẵn sàng</span>}
            </div>
            <div className="text-xs">Cập nhật: {new Date(story.updated_at).toLocaleString('vi-VN')}</div>
          </div>
        </div>
        <div className="flex items-center gap-2 ml-4 flex-shrink-0">
          <button onClick={onOpen} className="px-4 py-2 bg-primary-500 text-white rounded-md hover:bg-primary-600 text-sm font-medium">Mở</button>
          {story.total_downloaded > 0 && (
            <>
              <button onClick={() => onExport(story.id, 'word')} disabled={exporting === `${story.id}:word`}
                className="px-3 py-2 bg-primary-500 text-white rounded-md hover:bg-primary-600 text-sm font-medium disabled:opacity-60">
                {exporting === `${story.id}:word` ? '...' : 'Word'}</button>
              <button onClick={() => onExport(story.id, 'txt')} disabled={exporting === `${story.id}:txt`}
                className="px-3 py-2 bg-gray-500 text-white rounded-md hover:bg-gray-600 text-sm font-medium disabled:opacity-60">
                {exporting === `${story.id}:txt` ? '...' : 'TXT'}</button>
            </>
          )}
          <button onClick={onDelete} className="px-4 py-2 bg-red-500 text-white rounded-md hover:bg-red-600 text-sm font-medium">Xóa</button>
        </div>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- //
//  Quick Build batch group — collapsed header + compact child rows
// --------------------------------------------------------------------------- //
function BatchGroup({ batch, open, onToggle, onOpenBatch, onDelete }: {
  batch: HistBatch
  open: boolean
  onToggle: () => void
  onOpenBatch: () => void
  onDelete: () => void
}) {
  const running = batch.status === 'running' || batch.status === 'queued'
  return (
    <div className="border rounded-lg overflow-hidden">
      {/* Header — expand toggles the status list; actions live in Build Batch */}
      <div className="flex items-center gap-3 p-4 bg-surface-2/50 hover:bg-surface-2 cursor-pointer" onClick={onToggle}>
        {open ? <ChevronDown className="w-5 h-5 text-dim flex-shrink-0" /> : <ChevronRight className="w-5 h-5 text-dim flex-shrink-0" />}
        <div className="w-9 h-9 rounded-lg bg-orange-500 flex items-center justify-center flex-shrink-0">
          <Zap className="w-5 h-5 text-white" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold truncate">Build Batch · {batch.folder_label || '—'}</span>
            <BatchBadge status={batch.status} />
          </div>
          <div className="text-sm text-dim">
            {batch.done_count}/{batch.total} xong
            {batch.error_count > 0 && <span className="text-red-500"> · {batch.error_count} lỗi</span>}
            {batch.preset_name && <span> · preset: {batch.preset_name}</span>}
            <span> · {new Date(batch.updated_at).toLocaleString('vi-VN')}</span>
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0" onClick={e => e.stopPropagation()}>
          <button
            onClick={onOpenBatch}
            className="px-3 py-1.5 text-sm rounded-md bg-orange-500 text-white hover:bg-orange-600 inline-flex items-center gap-1.5"
            title="Mở mẻ này trong tab Build Batch để thao tác"
          ><ExternalLink className="w-4 h-4" /> Mở trong Build Batch</button>
          {!running && (
            <button onClick={onDelete} className="p-2 text-dim hover:text-red-500" title="Xoá mẻ build">
              <Trash2 className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Children — config chips (frozen at build time) then status-only rows */}
      {open && (
        <div>
          {batch.config && <ConfigChips config={batch.config} />}
          <div className="divide-y">
            {batch.jobs.map(job => (
              <BatchJobRow key={job.id} job={job} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// Frozen build config, mirroring the chip row on the Quick Build setup screen.
function ConfigChips({ config: c }: { config: HistBatchConfig }) {
  const chip = (label: string, val: string, strike = false) => (
    <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-surface-2 border ${strike ? 'opacity-70 line-through' : ''}`}>
      <span className="text-faint">{label}</span> <b className="text-strong">{val}</b>
    </span>
  )
  return (
    <div className="flex flex-wrap gap-2 px-4 py-3 pl-14 bg-surface-2/30 border-b">
      {chip('Engine', (c.engine || 'vbee').toUpperCase())}
      {c.engine === 'ai_voice_local'
        ? chip('Giọng', c.clone_preset_name || localModeLabel(c.mode))
        : c.voice_code && chip('Giọng', c.voice_code)}
      {c.speed != null && chip('Tốc độ', `${c.speed}×`)}
      {c.resolution && chip('Video', c.resolution)}
      {c.video_folder && chip('Clip nền', baseName(c.video_folder))}
      {c.has_bgm && chip('Nhạc nền', '✓')}
      {c.skip_spellcheck && chip('Spellcheck', 'bỏ qua', true)}
      {c.auto_clean && chip('Auto-clean', '✓')}
      {c.auto_subtitle && chip('Phụ đề', '✓')}
    </div>
  )
}

function BatchJobRow({ job }: { job: HistBatchJob }) {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 pl-14">
      <span className="text-xs text-faint tabular-nums w-6 flex-shrink-0">
        {String(job.order_index + 1).padStart(2, '0')}
      </span>
      <span className="flex-1 min-w-0 truncate text-sm">{job.title || 'Truyện'}</span>
      <JobStatus status={job.status} />
    </div>
  )
}

// --------------------------------------------------------------------------- //
//  Small presentational bits
// --------------------------------------------------------------------------- //
function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    completed: 'bg-green-100 dark:bg-green-500/20 text-green-800 dark:text-green-300',
    tts_processing: 'bg-orange-100 dark:bg-orange-500/20 text-orange-800 dark:text-orange-300',
    downloaded: 'bg-green-100 dark:bg-green-500/20 text-green-800 dark:text-green-300',
  }
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${colors[status] || 'bg-surface-3 text-strong'}`}>
      {status}
    </span>
  )
}

function BatchBadge({ status }: { status: string }) {
  const map: Record<string, [string, string]> = {
    running: ['Đang chạy', 'bg-orange-100 dark:bg-orange-500/20 text-orange-700 dark:text-orange-300'],
    queued: ['Đang chờ', 'bg-yellow-100 dark:bg-yellow-500/20 text-yellow-700 dark:text-yellow-300'],
    done: ['Hoàn tất', 'bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-300'],
    stopped: ['Đã dừng', 'bg-surface-3 text-dim'],
  }
  const [label, cls] = map[status] || [status, 'bg-surface-3 text-dim']
  return <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}>{label}</span>
}

function JobStatus({ status }: { status: string }) {
  const map: Record<string, [string, string]> = {
    done: ['✓ xong', 'text-green-600 dark:text-green-400'],
    error: ['✗ lỗi', 'text-red-500'],
    running: ['⟳ đang chạy', 'text-orange-500'],
    pending: ['· chờ', 'text-faint'],
    skipped: ['– đã bỏ', 'text-faint'],
  }
  const [label, cls] = map[status] || [status, 'text-dim']
  return <span className={`text-xs font-medium flex-shrink-0 ${cls}`}>{label}</span>
}

function ConfirmDialog({ title, body, warn, busy, onCancel, onConfirm }: {
  title: string
  body: React.ReactNode
  warn: string
  busy: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-surface rounded-lg max-w-md w-full p-6">
        <h3 className="text-xl font-semibold mb-4">{title}</h3>
        <p className="text-dim mb-4">{body}</p>
        <p className="text-sm text-red-600 dark:text-red-400 mb-6">{warn}</p>
        <div className="flex justify-end gap-3">
          <button onClick={onCancel} disabled={busy} className="px-4 py-2 text-dim hover:text-strong">Hủy</button>
          <button onClick={onConfirm} disabled={busy}
            className="px-6 py-2 bg-red-500 text-white rounded-md hover:bg-red-600 disabled:bg-gray-400">
            {busy ? 'Đang xoá...' : 'Xóa'}</button>
        </div>
      </div>
    </div>
  )
}
