import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import axios from 'axios'
import {
  Zap, FolderOpen, Play, Square, RotateCcw, Loader2, CheckCircle2,
  AlertCircle, ChevronDown, ChevronRight, Settings2, Pencil, X, Trash2,
} from 'lucide-react'
import { hasNativeDialogs, pickFolderNative } from '../services/nativeDialog'
import {
  listBuildPresets, deleteBuildPreset, renameBuildPreset,
  scanFolder, startBatch, getBatchStatus, stopBatch, retryJob, cancelJob,
  BuildPreset, ScanItem, JobOverrides, BatchStatus, JobOut,
} from '../services/quickBuildApi'

interface Row extends ScanItem {
  selected: boolean
  expanded: boolean
  overrides: JobOverrides
}

const STAGES = [
  { key: 'create', label: 'Tạo truyện' },
  { key: 'tts', label: 'TTS' },
  { key: 'video', label: 'Render video' },
]

function errMsg(e: any, fallback: string): string {
  const d = e?.response?.data?.detail
  return typeof d === 'string' ? d : fallback
}

const baseName = (p: string) => p.split(/[\\/]/).filter(Boolean).pop() || p

export default function QuickBuildPage() {
  const [presets, setPresets] = useState<BuildPreset[]>([])
  const [presetId, setPresetId] = useState('')
  const [folder, setFolder] = useState('')
  const [rows, setRows] = useState<Row[]>([])
  const [scanning, setScanning] = useState(false)
  const [notice, setNotice] = useState<{ kind: 'err' | 'ok'; text: string } | null>(null)

  // Batch-wide options (apply to every story unless a row overrides them).
  const [commonAutoClean, setCommonAutoClean] = useState(true)
  // Shared clip folder for the whole batch. Empty = use the preset's folder.
  const [commonFolder, setCommonFolder] = useState('')
  // Auto-generate burned subtitles from the TTS timing (estimated). Default off.
  const [commonAutoSubtitle, setCommonAutoSubtitle] = useState(false)
  const [managePresets, setManagePresets] = useState(false)
  const [filesOpen, setFilesOpen] = useState(false)
  const [bulkOpen, setBulkOpen] = useState(false)
  const [bulkDraft, setBulkDraft] = useState<JobOverrides>({})

  const [batchId, setBatchId] = useState<string | null>(null)
  const [batch, setBatch] = useState<BatchStatus | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()

  // Opened from the History tab with ?batch=<id> → jump straight to that batch's
  // progress view (the polling effect below fetches its status). Consume the
  // param so a later reset/refresh doesn't re-open it.
  useEffect(() => {
    const b = searchParams.get('batch')
    if (b) {
      setBatchId(b)
      setBatch(null)
      setTab('run')
      setSearchParams({}, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  // Which tab is showing. Setup ⇄ Run switch freely — the batch keeps polling in
  // the background regardless, so flipping tabs never interrupts a running build.
  const [tab, setTab] = useState<'setup' | 'run'>('setup')

  // ---- load presets -------------------------------------------------------
  const reloadPresets = () =>
    listBuildPresets()
      // Keep the current selection if it still exists; otherwise fall back to the
      // first preset (or none) — guards against a stale id after deleting the
      // selected preset in the Manage modal.
      .then(p => { setPresets(p); setPresetId(cur => (p.some(x => x.id === cur) ? cur : (p[0]?.id ?? ''))) })
      .catch(e => setNotice({ kind: 'err', text: errMsg(e, 'Không tải được danh sách preset') }))
  useEffect(() => { reloadPresets() }, [])

  const selectedPreset = presets.find(p => p.id === presetId) || null
  const selectedCount = rows.filter(r => r.selected).length
  const presetName = (id?: string) => presets.find(p => p.id === id)?.name

  // ---- scan folder --------------------------------------------------------
  const pickFolder = async () => {
    const path = hasNativeDialogs() ? await pickFolderNative() : folder.trim()
    if (!path) return
    setFolder(path)
    await runScan(path)
  }
  const runScan = async (path: string) => {
    setScanning(true); setNotice(null)
    try {
      const items = await scanFolder(path)
      setRows(items.map(it => ({ ...it, selected: true, expanded: false, overrides: {} })))
    } catch (e: any) {
      setRows([])
      setNotice({ kind: 'err', text: errMsg(e, 'Không quét được thư mục') })
    } finally {
      setScanning(false)
    }
  }

  // ---- row helpers --------------------------------------------------------
  const patchRow = (i: number, patch: Partial<Row>) =>
    setRows(rs => rs.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  const patchOverride = (i: number, patch: Partial<JobOverrides>) =>
    setRows(rs => rs.map((r, idx) => (idx === i ? { ...r, overrides: { ...r.overrides, ...patch } } : r)))
  const hasOverride = (o: JobOverrides) => Object.values(o).some(v => v !== undefined && v !== '' && v !== null)

  const applyBulk = () => {
    const clean: JobOverrides = {}
    for (const [k, v] of Object.entries(bulkDraft)) {
      if (v !== undefined && v !== '' && v !== null) (clean as any)[k] = v
    }
    setRows(rs => rs.map(r => (r.selected ? { ...r, overrides: { ...r.overrides, ...clean } } : r)))
    setBulkOpen(false); setBulkDraft({})
  }

  // ---- start / poll -------------------------------------------------------
  const start = async () => {
    if (!presetId) { setNotice({ kind: 'err', text: 'Chưa chọn preset' }); return }
    // A batch is already running. Starting another would swap the polling target and
    // orphan the in-flight one (it keeps rendering on the backend but vanishes from
    // the UI). Block it and point the user at the running batch instead.
    if (batch && (batch.status === 'running' || batch.status === 'queued')) {
      setNotice({ kind: 'err', text: 'Đang chạy một batch — bấm "Dừng" ở tab Chạy build trước khi build mẻ mới.' })
      setTab('run')
      return
    }
    const jobs = rows.filter(r => r.selected).map(r => {
      const ov: JobOverrides = { ...r.overrides }
      // The common Auto-clean / subtitle toggles apply unless the row set its own.
      if (ov.auto_clean === undefined) ov.auto_clean = commonAutoClean
      if (ov.auto_subtitle === undefined) ov.auto_subtitle = commonAutoSubtitle
      // The common clip folder applies unless the row overrides it (a per-row
      // folder wins; empty common folder falls back to the preset on the backend).
      if (!ov.video_folder && commonFolder.trim()) ov.video_folder = commonFolder.trim()
      return { source_path: r.source_path, title: r.title, selected: true, overrides: ov }
    })
    if (!jobs.length) { setNotice({ kind: 'err', text: 'Chưa chọn truyện nào' }); return }
    setNotice(null)
    try {
      const res = await startBatch(presetId, jobs)
      setBatch(null)
      setBatchId(res.batch_id)
      setTab('run')  // jump to the progress tab, but you can flip back to Setup any time
    } catch (e: any) {
      setNotice({ kind: 'err', text: errMsg(e, 'Không bắt đầu được build') })
    }
  }

  useEffect(() => {
    if (!batchId) return
    // `loaded` flips true after the first successful fetch; `fails` counts
    // consecutive errors. A hiccup mid-run is harmless (keep polling), but if we
    // never load the batch at all — e.g. a stale ?batch deep-link to a deleted id
    // that 404s every tick — bail out after a few tries so the Run tab doesn't spin
    // on "Đang tải tiến độ…" forever.
    let loaded = false
    let fails = 0
    const tick = async () => {
      try {
        const s = await getBatchStatus(batchId)
        loaded = true; fails = 0
        setBatch(s)
        if (s.status === 'done' || s.status === 'stopped') {
          if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
        }
      } catch {
        if (!loaded && ++fails >= 3) {
          if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
          setBatchId(null)
          setNotice({ kind: 'err', text: 'Không tìm thấy batch này (có thể đã bị xoá). Hãy build lại từ tab Cấu hình.' })
        }
        /* otherwise keep polling */
      }
    }
    tick()
    pollRef.current = setInterval(tick, 2500)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [batchId])

  const doStop = async () => { if (batchId) { try { await stopBatch(batchId) } catch { /* noop */ } } }
  const doRetry = async (jobId: string) => {
    try { const res = await retryJob(jobId); setBatchId(res.batch_id); setBatch(null) }
    catch (e: any) { setNotice({ kind: 'err', text: errMsg(e, 'Không thử lại được') }) }
  }
  const doCancel = async (jobId: string) => {
    // Optimistic: flip to 'skipped' locally so the row updates before the next poll.
    setBatch(b => b ? { ...b, jobs: b.jobs.map(j => j.id === jobId ? { ...j, status: 'skipped' } : j) } : b)
    try { await cancelJob(jobId) } catch (e: any) { setNotice({ kind: 'err', text: errMsg(e, 'Không bỏ được job') }) }
  }
  const openVideo = async (storyId: string | null) => {
    if (!storyId) return
    try { await axios.post(`/api/v1/video/reveal-video/${storyId}`) } catch { /* noop */ }
  }
  const resetToConfig = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
    setBatchId(null); setBatch(null); setTab('setup')
  }

  // Summary counters for the batch (used by the Run tab badge + its header).
  const batchDone = batch ? batch.jobs.filter(j => j.status === 'done').length : 0
  const batchTotal = batch ? batch.jobs.length : 0
  const batchActive = batch ? (batch.status === 'running' || batch.status === 'queued') : false

  // ======================================================================= //
  //  RUN / PROGRESS tab content
  // ======================================================================= //
  const runContent = () => {
    if (!batchId) {
      return (
        <div className="card p-10 text-center">
          <div className="w-12 h-12 rounded-2xl grid place-items-center mx-auto mb-3" style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}>
            <Play size={22} />
          </div>
          <p className="text-sm font-semibold">Chưa có batch nào đang chạy</p>
          <p className="text-xs text-faint mt-1">Sang tab <b className="text-dim">Cấu hình</b>, chọn truyện rồi bấm <b className="text-dim">Build</b> để bắt đầu.</p>
          <button onClick={() => setTab('setup')}
            className="mt-4 text-sm px-3.5 py-2 rounded border border-token-strong text-dim hover:bg-surface-2 inline-flex items-center gap-2">
            <Settings2 size={14} /> Về cấu hình
          </button>
        </div>
      )
    }
    if (!batch) {
      return (
        <div className="card p-8 text-center text-dim flex items-center justify-center gap-2">
          <Loader2 size={16} className="animate-spin" /> Đang tải tiến độ…
        </div>
      )
    }
    const done = batchDone
    const running = batch.jobs.filter(j => j.status === 'running').length
    const err = batch.jobs.filter(j => j.status === 'error').length
    const pending = batch.jobs.filter(j => j.status === 'pending').length
    const skipped = batch.jobs.filter(j => j.status === 'skipped').length
    const active = batchActive
    return (
        <div className="card p-0 overflow-hidden">
          <div className="flex items-center justify-between gap-3 flex-wrap p-4 border-b border-token">
            <div className="flex items-baseline gap-3">
              <h2 className="text-base font-semibold">Tiến độ batch</h2>
              <span className="text-sm text-dim font-mono">
                <span className="text-green-600 dark:text-green-400">{done} xong</span> ·{' '}
                <span style={{ color: 'var(--accent)' }}>{running} chạy</span> · {pending} chờ
                {err > 0 && <> · <span className="text-red-500">{err} lỗi</span></>}
                {skipped > 0 && <> · <span className="text-faint">{skipped} bỏ</span></>}
              </span>
            </div>
            <div className="flex gap-2">
              {active && (
                <button onClick={doStop}
                  className="text-sm px-3 py-1.5 rounded border border-red-300 text-red-600 hover:bg-red-50 dark:hover:bg-red-500/10 inline-flex items-center gap-1.5">
                  <Square size={14} /> Dừng
                </button>
              )}
              {!active && (
                <button onClick={resetToConfig}
                  className="text-sm px-3 py-1.5 rounded border border-token-strong text-dim hover:bg-surface-2 inline-flex items-center gap-1.5">
                  <ChevronRight size={14} /> Build batch khác
                </button>
              )}
            </div>
          </div>
          <div className="p-4 space-y-2.5">
            {batch.jobs.map(j => <ProgressRow key={j.id} job={j} onOpen={openVideo} onRetry={doRetry} onCancel={doCancel} canCancel={active} />)}
          </div>
          <div className="px-4 pb-4 text-xs text-faint flex items-center gap-2">
            💡 Chạy nền ở backend — đóng cửa sổ vẫn render tiếp, mở lại app để xem tiến độ.
          </div>
        </div>
    )
  }

  // ======================================================================= //
  //  PAGE — Header + tabs, then Setup or Run content
  // ======================================================================= //
  return (
    <div className="space-y-5 max-w-[1120px]">
      <Header />

      {/* Tabs — flip between Setup and Run freely; the batch keeps running. */}
      <div className="flex items-center gap-1 border-b border-token">
        <TabBtn n={1} label="Cấu hình" active={tab === 'setup'} onClick={() => setTab('setup')} />
        <TabBtn n={2} label="Chạy build" active={tab === 'run'} onClick={() => setTab('run')}
          badge={batch ? `${batchDone}/${batchTotal}` : batchId ? '…' : undefined} live={batchActive} />
      </div>

      {notice && (
        <div className={`rounded-lg px-4 py-2.5 text-sm border ${notice.kind === 'err'
          ? 'bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/30 text-red-600 dark:text-red-400'
          : 'bg-green-50 dark:bg-green-500/10 border-green-200 dark:border-green-500/30 text-green-700 dark:text-green-400'}`}>
          {notice.text}
        </div>
      )}

      {tab === 'run' ? runContent() : (
      <>
      {/* 1. Folder */}
      <div className="card p-0 overflow-hidden">
        <div className="p-4 border-b border-token flex items-center justify-between">
          <h2 className="text-base font-semibold flex items-center gap-2"><StepNum n={1} /> Chọn folder truyện</h2>
          <span className="text-xs text-faint">Mỗi file <b className="text-dim">.txt/.docx</b> = 1 truyện = 1 video</span>
        </div>
        <div className="p-4">
          <div className="rounded-xl border border-dashed border-token-strong bg-surface-2 p-4">
            <div className="flex items-center gap-4">
              <div className="w-11 h-11 rounded-xl grid place-items-center shrink-0" style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}>
                <FolderOpen size={22} />
              </div>
              <div className="flex-1 min-w-0">
                {hasNativeDialogs() ? (
                  <div className="font-mono text-sm break-all">{folder || <span className="text-faint">Chưa chọn folder</span>}</div>
                ) : (
                  <>
                    <label className="block text-xs font-semibold text-dim mb-1">Đường dẫn folder (dán vào đây)</label>
                    <input
                      value={folder}
                      onChange={e => setFolder(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter' && folder.trim()) runScan(folder.trim()) }}
                      placeholder="vd: D:\Truyện\thang-7  — rồi Enter hoặc bấm Quét"
                      className="w-full px-3 py-2 text-sm font-mono border border-token-strong rounded bg-surface focus:outline-none focus:ring-2 focus:ring-primary-500"
                    />
                  </>
                )}
                {rows.length ? (
                  <button onClick={() => setFilesOpen(v => !v)}
                    className="text-xs text-dim mt-1 inline-flex items-center gap-1 hover:text-[var(--text)]">
                    {filesOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                    Tìm thấy <b className="text-strong">{rows.length}</b> truyện
                    <span className="text-faint">— {filesOpen ? 'ẩn danh sách' : 'xem danh sách'}</span>
                  </button>
                ) : (
                  <div className="text-xs text-faint mt-1">
                    {hasNativeDialogs()
                      ? 'Chọn folder để quét danh sách truyện'
                      : 'Trình duyệt không mở được hộp thoại — dán đường dẫn folder rồi bấm Quét. (Bản .exe sẽ mở Explorer thật.)'}
                  </div>
                )}
              </div>
              <button onClick={pickFolder} disabled={scanning || (!hasNativeDialogs() && !folder.trim())}
                className="text-sm px-3.5 py-2 rounded border border-token-strong bg-surface hover:bg-surface-2 inline-flex items-center gap-2 disabled:opacity-50 shrink-0">
                {scanning ? <Loader2 size={15} className="animate-spin" /> : <FolderOpen size={15} />}
                {hasNativeDialogs() ? 'Chọn folder' : 'Quét'}
              </button>
            </div>
            {rows.length > 0 && filesOpen && (
              <div className="flex flex-wrap gap-1.5 mt-3 pl-[60px]">
                {rows.map(r => (
                  <span key={r.source_path} className="inline-flex items-center gap-1 text-[11px] font-mono text-dim bg-surface border border-token rounded px-2 py-0.5">
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--accent)' }} />
                    {baseName(r.source_path)}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 2. Common config */}
      <div className="card p-0 overflow-hidden">
        <div className="p-4 border-b border-token flex items-center justify-between">
          <h2 className="text-base font-semibold flex items-center gap-2"><StepNum n={2} /> Cấu hình chung</h2>
          {presets.length > 0 && (
            <button onClick={() => setManagePresets(true)}
              className="text-xs px-2.5 py-1.5 rounded border border-token-strong text-dim hover:bg-surface-2 inline-flex items-center gap-1.5">
              <Settings2 size={13} /> Quản lý preset
            </button>
          )}
        </div>
        <div className="p-4 space-y-3">
          <div className="rounded-xl p-4" style={{ background: 'var(--accent-soft)', border: '1px solid var(--border-strong)' }}>
            <div className="text-xs font-bold uppercase tracking-wide mb-2.5" style={{ color: 'var(--accent)' }}>⚡ Áp dụng cho tất cả truyện</div>
            {presets.length === 0 ? (
              <div className="text-sm text-dim">
                Chưa có Build Preset nào. Vào wizard (Tạo dự án) → bước Video → bấm <b>⚡ Lưu Build Preset</b>.
              </div>
            ) : (
              <div className="space-y-3">
                <div className="flex flex-wrap gap-4 items-end">
                  <label className="flex flex-col gap-1.5">
                    <span className="text-xs text-dim font-semibold">Preset build</span>
                    <select value={presetId} onChange={e => setPresetId(e.target.value)}
                      className="min-w-[240px] px-3 py-2 text-sm font-semibold border border-token-strong rounded bg-surface focus:outline-none focus:ring-2 focus:ring-primary-500">
                      {presets.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1.5 flex-1 min-w-[240px]">
                    <span className="text-xs text-dim font-semibold">Folder clip nền chung <span className="text-faint font-normal">(để trống = theo preset)</span></span>
                    <div className="flex gap-2">
                      <input value={commonFolder} onChange={e => setCommonFolder(e.target.value)}
                        placeholder={selectedPreset?.video_folder || 'Theo preset'}
                        className="flex-1 px-3 py-2 text-sm font-mono border border-token-strong rounded bg-surface focus:outline-none focus:ring-2 focus:ring-primary-500" />
                      {hasNativeDialogs() && (
                        <button type="button" onClick={async () => { const p = await pickFolderNative(); if (p) setCommonFolder(p) }}
                          className="px-3 rounded border border-token-strong text-dim hover:bg-surface-2"><FolderOpen size={15} /></button>
                      )}
                      {commonFolder && (
                        <button type="button" onClick={() => setCommonFolder('')} title="Về theo preset"
                          className="px-2.5 rounded border border-token-strong text-dim hover:bg-surface-2"><RotateCcw size={14} /></button>
                      )}
                    </div>
                  </label>
                </div>
                {selectedPreset && <PresetChips preset={selectedPreset} />}
                <div className="flex flex-wrap gap-5 pt-1">
                  <Toggle on={commonAutoClean} onChange={setCommonAutoClean} label="Auto-clean text"
                    hint="(bỏ dòng rác: nguồn, web, quảng cáo)" />
                  <Toggle on={commonAutoSubtitle} onChange={setCommonAutoSubtitle} label="Tự tạo phụ đề"
                    hint="(sinh từ giọng đọc — canh giờ ước lượng)" />
                </div>
              </div>
            )}
          </div>
          {rows.length > 0 && (
            <p className="text-xs text-faint">💡 Các truyện mặc định <b className="text-dim">dùng chung</b> cấu hình này — chỉ đụng tới truyện nào muốn khác đi (cột có <b className="text-dim">⟳</b>).</p>
          )}
        </div>
      </div>

      {/* 3. Story list */}
      {rows.length > 0 && (
        <div className="card p-0 overflow-hidden">
          <div className="p-4 border-b border-token flex items-center justify-between gap-3 flex-wrap">
            <h3 className="text-sm font-bold">
              Danh sách truyện <span className="text-faint font-normal">· {selectedCount}/{rows.length} chọn</span>
            </h3>
            <div className="flex gap-2">
              <button onClick={() => setRows(rs => rs.map(r => ({ ...r, selected: true })))}
                className="text-xs px-2.5 py-1.5 rounded border border-token-strong text-dim hover:bg-surface-2">Chọn tất cả</button>
              <button onClick={() => setRows(rs => rs.map(r => ({ ...r, selected: false })))}
                className="text-xs px-2.5 py-1.5 rounded border border-token-strong text-dim hover:bg-surface-2">Bỏ chọn</button>
              <button onClick={() => { setBulkDraft({}); setBulkOpen(v => !v) }} disabled={!selectedCount}
                className="text-xs px-2.5 py-1.5 rounded border border-token-strong text-dim hover:bg-surface-2 inline-flex items-center gap-1 disabled:opacity-50">
                <Pencil size={12} /> Sửa hàng loạt
              </button>
            </div>
          </div>

          {bulkOpen && (
            <BulkPanel draft={bulkDraft} setDraft={setBulkDraft} presets={presets}
              count={selectedCount} onApply={applyBulk} onClose={() => setBulkOpen(false)} />
          )}

          <div className="p-4 overflow-x-auto">
            <div className="min-w-[760px] space-y-2">
              <div className="grid grid-cols-[26px_1.5fr_1fr_1fr_120px_34px] gap-3 px-2 text-[11px] font-bold uppercase tracking-wide text-faint">
                <span /><span>Truyện</span><span>Preset</span><span>Clip nền</span><span>Banner</span><span />
              </div>
              {rows.map((r, i) => {
                const ov = r.overrides
                const overridden = hasOverride(ov)
                return (
                  <div key={r.source_path}
                    className={`rounded-xl border ${r.expanded ? 'border-primary-400 ring-2 ring-primary-500/20' : overridden ? 'border-token-strong bg-surface-2' : 'border-token'} px-3 py-2.5`}>
                    <div className="grid grid-cols-[26px_1.5fr_1fr_1fr_120px_34px] gap-3 items-center">
                      <input type="checkbox" checked={r.selected} onChange={e => patchRow(i, { selected: e.target.checked })}
                        className="w-4 h-4 accent-amber-500" />
                      <div className="min-w-0">
                        <div className="text-sm font-semibold truncate flex items-center gap-2">
                          {r.title}
                          {overridden && <span className="text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0" style={{ color: 'var(--accent)', background: 'var(--accent-soft)' }}>RIÊNG</span>}
                        </div>
                        <div className="text-[11px] font-mono text-faint truncate">{baseName(r.source_path)}</div>
                      </div>
                      <Cell overridden={!!ov.preset_id} value={ov.preset_id ? (presetName(ov.preset_id) || 'preset') : null} />
                      <Cell overridden={!!ov.video_folder} value={ov.video_folder ? baseName(ov.video_folder) : null}
                        fallback={baseName((commonFolder || selectedPreset?.video_folder || '').trim()) || undefined} />
                      <Cell overridden={!!ov.banner_mode}
                        value={ov.banner_mode ? (ov.banner_mode === 'none' ? 'Không' : 'Theo tên') : null}
                        fallback={r.has_banner ? '🖼️ theo tên' : 'clip nền'} />
                      <button onClick={() => patchRow(i, { expanded: !r.expanded })}
                        className="w-7 h-7 grid place-items-center rounded border border-token-strong text-dim hover:bg-surface-3 justify-self-center">
                        {r.expanded ? <ChevronDown size={14} /> : <Pencil size={13} />}
                      </button>
                    </div>

                    {r.expanded && (
                      <div className="mt-3 pt-3 border-t border-token grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                        <label className="flex flex-col gap-1 sm:col-span-2 lg:col-span-1">
                          <span className="text-xs font-semibold text-dim">Tên truyện (hiển thị)</span>
                          <input value={r.title} onChange={e => patchRow(i, { title: e.target.value })}
                            className="px-2.5 py-1.5 text-sm border border-token-strong rounded bg-surface" />
                        </label>
                        <label className="flex flex-col gap-1">
                          <span className="text-xs font-semibold text-dim">Preset riêng</span>
                          <select value={ov.preset_id || ''} onChange={e => patchOverride(i, { preset_id: e.target.value || undefined })}
                            className="px-2.5 py-1.5 text-sm border border-token-strong rounded bg-surface">
                            <option value="">⟳ Theo chung</option>
                            {presets.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                          </select>
                        </label>
                        <label className="flex flex-col gap-1">
                          <span className="text-xs font-semibold text-dim">Giọng ghi đè <span className="text-faint font-normal">(voice_code)</span></span>
                          <input value={ov.voice_code || ''} onChange={e => patchOverride(i, { voice_code: e.target.value || undefined })}
                            placeholder="để trống = theo preset" className="px-2.5 py-1.5 text-sm font-mono border border-token-strong rounded bg-surface" />
                        </label>
                        <label className="flex flex-col gap-1">
                          <span className="text-xs font-semibold text-dim">Tốc độ đọc</span>
                          <input type="number" step="0.01" min="0.5" max="2" placeholder="theo chung"
                            value={ov.speed ?? ''} onChange={e => patchOverride(i, { speed: e.target.value ? Number(e.target.value) : undefined })}
                            className="px-2.5 py-1.5 text-sm border border-token-strong rounded bg-surface" />
                        </label>
                        <label className="flex flex-col gap-1">
                          <span className="text-xs font-semibold text-dim">Banner</span>
                          <select value={ov.banner_mode || ''} onChange={e => patchOverride(i, { banner_mode: (e.target.value || undefined) as any })}
                            className="px-2.5 py-1.5 text-sm border border-token-strong rounded bg-surface">
                            <option value="">⟳ Theo chung</option>
                            <option value="by_filename">Theo tên file</option>
                            <option value="none">Không banner</option>
                          </select>
                        </label>
                        <label className="flex flex-col gap-1">
                          <span className="text-xs font-semibold text-dim">Làm sạch text</span>
                          <select value={ov.auto_clean === undefined ? '' : ov.auto_clean ? 'on' : 'off'}
                            onChange={e => patchOverride(i, { auto_clean: e.target.value === '' ? undefined : e.target.value === 'on' })}
                            className="px-2.5 py-1.5 text-sm border border-token-strong rounded bg-surface">
                            <option value="">⟳ Theo chung</option>
                            <option value="on">Bật</option>
                            <option value="off">Tắt</option>
                          </select>
                        </label>
                        <label className="flex flex-col gap-1">
                          <span className="text-xs font-semibold text-dim">Phụ đề</span>
                          <select value={ov.auto_subtitle === undefined ? '' : ov.auto_subtitle ? 'on' : 'off'}
                            onChange={e => patchOverride(i, { auto_subtitle: e.target.value === '' ? undefined : e.target.value === 'on' })}
                            className="px-2.5 py-1.5 text-sm border border-token-strong rounded bg-surface">
                            <option value="">⟳ Theo chung</option>
                            <option value="on">Bật</option>
                            <option value="off">Tắt</option>
                          </select>
                        </label>
                        <label className="flex flex-col gap-1 sm:col-span-2 lg:col-span-3">
                          <span className="text-xs font-semibold text-dim">Folder clip nền riêng (tuỳ chọn)</span>
                          <div className="flex gap-2">
                            <input value={ov.video_folder || ''} onChange={e => patchOverride(i, { video_folder: e.target.value || undefined })}
                              placeholder="Để trống = theo chung" className="flex-1 px-2.5 py-1.5 text-sm font-mono border border-token-strong rounded bg-surface" />
                            {hasNativeDialogs() && (
                              <button onClick={async () => { const p = await pickFolderNative(); if (p) patchOverride(i, { video_folder: p }) }}
                                className="text-xs px-2.5 rounded border border-token-strong text-dim hover:bg-surface-2">📂</button>
                            )}
                          </div>
                        </label>
                        <button onClick={() => patchRow(i, { overrides: {} })}
                          className="text-xs text-dim underline justify-self-start">↺ Về theo chung</button>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          <div className="px-4 pb-4 flex items-center gap-4 flex-wrap">
            <button onClick={start} disabled={!selectedCount || !presetId || batchActive}
              className="px-5 py-2.5 rounded-xl text-white font-semibold inline-flex items-center gap-2 disabled:opacity-50"
              style={{ background: 'var(--accent)' }}>
              <Zap size={17} /> Build {selectedCount} truyện đã chọn
            </button>
            <span className="text-xs text-faint font-mono">
              {batchActive
                ? '⏳ đang chạy một batch — dừng ở tab Chạy build trước'
                : 'tuần tự · ~8–12 phút / video'}
            </span>
          </div>
        </div>
      )}
      </>
      )}

      {managePresets && (
        <ManagePresetsModal presets={presets} onClose={() => setManagePresets(false)}
          onChanged={reloadPresets} />
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- //
function StepNum({ n }: { n: number }) {
  return <span className="w-5 h-5 rounded-full grid place-items-center text-xs font-bold" style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}>{n}</span>
}

// A single tab in the Setup ⇄ Run bar. `badge` shows batch progress (e.g. "2/5"),
// `live` pulses a dot while a batch is actively running.
function TabBtn({ n, label, active, onClick, badge, live }:
  { n: number; label: string; active: boolean; onClick: () => void; badge?: string; live?: boolean }) {
  return (
    <button onClick={onClick}
      className={`relative -mb-px px-4 py-2.5 text-sm font-semibold inline-flex items-center gap-2 border-b-2 transition-colors ${
        active ? 'text-[var(--text)]' : 'border-transparent text-faint hover:text-dim'}`}
      style={active ? { borderColor: 'var(--accent)' } : undefined}>
      <span className="w-5 h-5 rounded-full grid place-items-center text-xs font-bold"
        style={{ background: active ? 'var(--accent)' : 'var(--accent-soft)', color: active ? '#fff' : 'var(--accent)' }}>{n}</span>
      {label}
      {live && <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: 'var(--accent)' }} />}
      {badge && (
        <span className="text-[11px] font-mono px-1.5 py-0.5 rounded-full bg-surface-2 border border-token text-dim">{badge}</span>
      )}
    </button>
  )
}

function Header() {
  return (
    <div>
      <div className="flex items-center gap-3">
        <span className="w-8 h-8 rounded-lg grid place-items-center text-white" style={{ background: 'var(--accent)' }}><Zap size={17} /></span>
        <h1 className="text-xl font-bold tracking-tight">Build nhanh</h1>
      </div>
      <p className="text-sm text-dim mt-1">Đổ cả folder truyện → hàng loạt video. Cấu hình chung + override từng truyện.</p>
    </div>
  )
}

function Toggle({ on, onChange, label, hint, disabled }: { on: boolean; onChange: (v: boolean) => void; label: string; hint?: string; disabled?: boolean }) {
  return (
    <button type="button" disabled={disabled} onClick={() => onChange(!on)}
      className={`inline-flex items-center gap-2 ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}>
      <span className={`w-9 h-5 rounded-full relative transition-colors ${on ? '' : 'bg-gray-300 dark:bg-gray-600'}`} style={on ? { background: 'var(--accent)' } : undefined}>
        <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all ${on ? 'left-[18px]' : 'left-0.5'}`} />
      </span>
      <span className="text-sm font-semibold">{label}{hint && <span className="text-faint font-normal"> {hint}</span>}</span>
    </button>
  )
}

// One "Preset / Clip / Banner" cell: shows the override value, or a faint "⟳ Chung"
// (optionally with what the shared config resolves to, e.g. banner fallback).
function Cell({ overridden, value, fallback }: { overridden: boolean; value: string | null; fallback?: string }) {
  if (overridden && value) {
    return <span className="text-xs font-semibold px-2 py-1 rounded border truncate inline-block max-w-full"
      style={{ color: 'var(--accent)', borderColor: 'var(--accent)', background: 'var(--accent-soft)' }}>{value}</span>
  }
  return (
    <span className="text-xs text-faint inline-flex items-center gap-1 truncate">
      <span>⟳</span> Theo chung{fallback && <span className="opacity-70">· {fallback}</span>}
    </span>
  )
}

function BulkPanel({ draft, setDraft, presets, count, onApply, onClose }:
  { draft: JobOverrides; setDraft: (d: JobOverrides) => void; presets: BuildPreset[]; count: number; onApply: () => void; onClose: () => void }) {
  const set = (patch: Partial<JobOverrides>) => setDraft({ ...draft, ...patch })
  return (
    <div className="mx-4 mt-3 rounded-xl border border-primary-400 bg-surface-2 p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-bold uppercase tracking-wide" style={{ color: 'var(--accent)' }}>✎ Sửa hàng loạt — {count} dòng đã chọn</span>
        <button onClick={onClose} className="text-faint hover:text-dim"><X size={16} /></button>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs font-semibold text-dim">Preset</span>
          <select value={draft.preset_id || ''} onChange={e => set({ preset_id: e.target.value || undefined })}
            className="px-2.5 py-1.5 text-sm border border-token-strong rounded bg-surface">
            <option value="">— giữ nguyên —</option>
            {presets.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-semibold text-dim">Tốc độ</span>
          <input type="number" step="0.01" min="0.5" max="2" value={draft.speed ?? ''}
            onChange={e => set({ speed: e.target.value ? Number(e.target.value) : undefined })}
            placeholder="giữ nguyên" className="px-2.5 py-1.5 text-sm border border-token-strong rounded bg-surface" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-semibold text-dim">Banner</span>
          <select value={draft.banner_mode || ''} onChange={e => set({ banner_mode: (e.target.value || undefined) as any })}
            className="px-2.5 py-1.5 text-sm border border-token-strong rounded bg-surface">
            <option value="">— giữ nguyên —</option>
            <option value="by_filename">Theo tên file</option>
            <option value="none">Không banner</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-semibold text-dim">Làm sạch text</span>
          <select value={draft.auto_clean === undefined ? '' : draft.auto_clean ? 'on' : 'off'}
            onChange={e => set({ auto_clean: e.target.value === '' ? undefined : e.target.value === 'on' })}
            className="px-2.5 py-1.5 text-sm border border-token-strong rounded bg-surface">
            <option value="">— giữ nguyên —</option>
            <option value="on">Bật</option>
            <option value="off">Tắt</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-semibold text-dim">Phụ đề</span>
          <select value={draft.auto_subtitle === undefined ? '' : draft.auto_subtitle ? 'on' : 'off'}
            onChange={e => set({ auto_subtitle: e.target.value === '' ? undefined : e.target.value === 'on' })}
            className="px-2.5 py-1.5 text-sm border border-token-strong rounded bg-surface">
            <option value="">— giữ nguyên —</option>
            <option value="on">Bật</option>
            <option value="off">Tắt</option>
          </select>
        </label>
      </div>
      <div className="flex gap-2 mt-3">
        <button onClick={onApply} className="px-3.5 py-1.5 rounded text-white text-sm font-semibold" style={{ background: 'var(--accent)' }}>
          Áp dụng cho {count} dòng
        </button>
        <button onClick={onClose} className="px-3.5 py-1.5 rounded border border-token-strong text-sm text-dim hover:bg-surface-3">Huỷ</button>
      </div>
    </div>
  )
}

function ManagePresetsModal({ presets, onClose, onChanged }:
  { presets: BuildPreset[]; onClose: () => void; onChanged: () => void }) {
  const [editing, setEditing] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  const doRename = async (id: string) => {
    if (!name.trim()) return
    setBusy(true)
    try { await renameBuildPreset(id, name.trim()); setEditing(null); await onChanged() }
    finally { setBusy(false) }
  }
  const doDelete = async (id: string) => {
    setBusy(true)
    try { await deleteBuildPreset(id); await onChanged() }
    finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-surface rounded-xl w-full max-w-lg" onClick={e => e.stopPropagation()}>
        <div className="p-4 border-b border-token flex items-center justify-between">
          <h3 className="text-base font-semibold">Quản lý Build Preset</h3>
          <button onClick={onClose} className="text-faint hover:text-dim"><X size={18} /></button>
        </div>
        <div className="p-4 space-y-2 max-h-[60vh] overflow-y-auto">
          {presets.length === 0 && <div className="text-sm text-dim text-center py-4">Chưa có preset nào.</div>}
          {presets.map(p => (
            <div key={p.id} className="flex items-center gap-2 rounded-lg border border-token px-3 py-2">
              {editing === p.id ? (
                <>
                  <input autoFocus value={name} onChange={e => setName(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') doRename(p.id) }}
                    className="flex-1 px-2 py-1 text-sm border border-token-strong rounded bg-surface" />
                  <button disabled={busy} onClick={() => doRename(p.id)} className="text-xs px-2.5 py-1.5 rounded text-white font-semibold disabled:opacity-50" style={{ background: 'var(--accent)' }}>Lưu</button>
                  <button onClick={() => setEditing(null)} className="text-xs px-2.5 py-1.5 rounded border border-token-strong text-dim">Huỷ</button>
                </>
              ) : (
                <>
                  <span className="flex-1 text-sm font-medium truncate">{p.name}</span>
                  <button onClick={() => { setEditing(p.id); setName(p.name) }} title="Đổi tên"
                    className="w-7 h-7 grid place-items-center rounded border border-token-strong text-dim hover:bg-surface-2"><Pencil size={13} /></button>
                  <button disabled={busy} onClick={() => doDelete(p.id)} title="Xoá"
                    className="w-7 h-7 grid place-items-center rounded border border-red-300 text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 disabled:opacity-50"><Trash2 size={13} /></button>
                </>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function PresetChips({ preset }: { preset: BuildPreset }) {
  const t = preset.tts_config || {}
  const chip = (label: string, val: any) => (
    <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-surface border border-token">
      <span className="text-faint">{label}</span> <b className="text-strong">{String(val)}</b>
    </span>
  )
  return (
    <div className="flex flex-wrap gap-2">
      {chip('Engine', (t.engine || 'vbee').toUpperCase())}
      {t.voice_code && chip('Giọng', t.voice_code)}
      {t.speed && chip('Tốc độ', `${t.speed}×`)}
      {preset.video_cfg?.resolution && chip('Video', preset.video_cfg.resolution)}
      {preset.video_folder && chip('Clip nền', baseName(preset.video_folder))}
      {preset.bgm_path && chip('Nhạc nền', '✓')}
      <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-surface border border-token opacity-70 line-through">
        <span className="text-faint">Spellcheck</span> <b>bỏ qua</b>
      </span>
    </div>
  )
}

const fmtSize = (b: number | null) =>
  b == null ? '' : b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`
// Backend timestamps are naive UTC (SQLite CURRENT_TIMESTAMP); tag as UTC so the
// browser renders the local wall-clock the render actually finished at.
const fmtTime = (s: string | null) => {
  if (!s) return ''
  const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s.replace(' ', 'T') + 'Z'
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function ProgressRow({ job, onOpen, onRetry, onCancel, canCancel }:
  { job: JobOut; onOpen: (id: string | null) => void; onRetry: (id: string) => void; onCancel: (id: string) => void; canCancel: boolean }) {
  const isRun = job.status === 'running'
  const isErr = job.status === 'error'
  const isDone = job.status === 'done'
  const isPending = job.status === 'pending'
  const isSkipped = job.status === 'skipped'
  const stageLabel = STAGES.find(s => s.key === job.stage)?.label || job.stage
  const stageNo = Math.max(1, STAGES.findIndex(s => s.key === job.stage) + 1)
  const showPct = isRun && job.stage === 'video' && job.progress > 0

  const detail = isDone && job.output_path
    ? `→ ${baseName(job.output_path)}${job.output_size ? ` · ${fmtSize(job.output_size)}` : ''}${fmtTime(job.updated_at) ? ` · ${fmtTime(job.updated_at)}` : ''}`
    : isErr ? <span className="text-red-500">{job.error_message || 'Lỗi'}</span>
    : isSkipped ? 'Đã bỏ khỏi hàng đợi'
    : isRun ? `Đang: ${stageLabel}${showPct ? ` · ${job.progress}%` : ` (${stageNo}/${STAGES.length})`}`
    : 'Trong hàng đợi…'

  return (
    <div className={`rounded-xl border px-3.5 py-3 ${isRun ? 'border-amber-400' : isErr ? 'border-red-300' : isDone ? 'border-green-300 dark:border-green-500/40' : isSkipped ? 'border-token opacity-55' : 'border-token'}`}
      style={isRun ? { background: 'var(--accent-soft)' } : undefined}>
      <div className="flex items-center gap-3">
        <span className="font-mono text-xs text-faint w-6 text-center shrink-0">{String(job.order_index + 1).padStart(2, '0')}</span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold truncate">{job.title || baseName(job.source_path)}</div>
          <div className="text-[11px] font-mono text-faint truncate">{detail}</div>
          {showPct && (
            <div className="mt-1.5 h-1 rounded-full overflow-hidden bg-surface-3">
              <div className="h-full rounded-full transition-[width] duration-500" style={{ width: `${job.progress}%`, background: 'var(--accent)' }} />
            </div>
          )}
        </div>
        <StatusPill status={job.status} label={isRun ? `${stageLabel} (${stageNo}/${STAGES.length})` : undefined} />
        <div className="flex gap-1.5 shrink-0">
          {isDone && (
            <button onClick={() => onOpen(job.story_id)}
              className="text-xs px-2.5 py-1.5 rounded border inline-flex items-center gap-1"
              style={{ color: 'var(--accent)', borderColor: 'var(--accent)', background: 'var(--accent-soft)' }}>
              <Play size={12} /> Mở
            </button>
          )}
          {isErr && (
            <button onClick={() => onRetry(job.id)}
              className="text-xs px-2.5 py-1.5 rounded border border-token-strong text-dim hover:bg-surface-2 inline-flex items-center gap-1">
              <RotateCcw size={12} /> Thử lại
            </button>
          )}
          {isPending && canCancel && (
            <button onClick={() => onCancel(job.id)} title="Bỏ khỏi hàng đợi"
              className="text-xs px-2.5 py-1.5 rounded border border-token-strong text-faint hover:bg-surface-2 hover:text-red-500 inline-flex items-center gap-1">
              <X size={12} /> Bỏ
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function StatusPill({ status, label }: { status: string; label?: string }) {
  if (status === 'done') return <Pill cls="text-green-600 bg-green-50 dark:bg-green-500/10 border-green-300"><CheckCircle2 size={12} /> Hoàn tất</Pill>
  if (status === 'error') return <Pill cls="text-red-600 bg-red-50 dark:bg-red-500/10 border-red-300"><AlertCircle size={12} /> Lỗi</Pill>
  if (status === 'running') return <Pill cls="border-amber-400" style={{ color: 'var(--accent)' }}><Loader2 size={12} className="animate-spin" /> {label || 'Đang chạy'}</Pill>
  if (status === 'skipped') return <Pill cls="text-faint bg-surface-2 border-token">Đã bỏ</Pill>
  return <Pill cls="text-faint bg-surface-2 border-token">Chờ</Pill>
}

function Pill({ children, cls, style }: { children: React.ReactNode; cls: string; style?: React.CSSProperties }) {
  return <span style={style} className={`text-xs font-semibold rounded-full px-3 py-1 border inline-flex items-center gap-1.5 whitespace-nowrap ${cls}`}>{children}</span>
}
