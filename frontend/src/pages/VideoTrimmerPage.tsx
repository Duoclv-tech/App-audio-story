import { useEffect, useMemo, useRef, useState } from 'react'
import { Scissors, Play, RotateCcw, Plus, Trash2 } from 'lucide-react'
import UploadZone from '../components/trim/UploadZone'
import VideoPreview from '../components/trim/VideoPreview'
import Waveform from '../components/trim/Waveform'
import Timeline from '../components/trim/Timeline'
import TimeInput from '../components/trim/TimeInput'
import ExportSettings from '../components/trim/ExportSettings'
import {
  uploadVideo,
  fetchWaveform,
  startTrim,
  openProgressStream,
  getDownloadUrl,
  getVideoUrl,
  checkFileExists,
  clearTemp,
  defaultWatermark,
  type AspectRatioParams,
  type TrimUploadResponse,
  type WatermarkParams,
} from '../services/trimApi'

// ─── types ───────────────────────────────────────────────────────────────────

interface Segment {
  id: string
  start: number
  end: number
}

// ─── helpers ─────────────────────────────────────────────────────────────────

function fmtSec(sec: number): string {
  const h = Math.floor(sec / 3600).toString().padStart(2, '0')
  const m = Math.floor((sec % 3600) / 60).toString().padStart(2, '0')
  const s = Math.floor(sec % 60).toString().padStart(2, '0')
  return `${h}:${m}:${s}`
}

function fmtHMS(sec: number): string {
  return fmtSec(sec).replace(/:/g, '')
}

function buildDefaultFilename(original: string, startSec: number, endSec: number): string {
  const base = original.replace(/\.[^/.]+$/, '')
  return `${base}_cut_${fmtHMS(startSec)}_${fmtHMS(endSec)}.mp4`
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

// ─── persistence ─────────────────────────────────────────────────────────────

const STORAGE_KEY = 'videoTrimmer.state.v3'
const LEGACY_KEYS = ['videoTrimmer.state.v2', 'videoTrimmer.state.v1']

interface PersistedState {
  metadata: TrimUploadResponse
  fileSizeBytes: number | null
  startSec: number
  endSec: number
  segments: Segment[]
  quality: string
  customBitrate: number
  aspectRatio: AspectRatioParams
  cropMode: string
  mute: boolean
  volume: number
  speed: number
  exactFrame: boolean
  fade: boolean
  watermark: WatermarkParams
  outputFilename: string
  waveform: number[]
}

function loadPersisted(): PersistedState | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw) as PersistedState
    return null
  } catch {
    return null
  }
}

function savePersisted(s: PersistedState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(s))
  } catch {
    // quota error — ignore
  }
}

function clearPersisted() {
  try {
    localStorage.removeItem(STORAGE_KEY)
    LEGACY_KEYS.forEach((k) => localStorage.removeItem(k))
  } catch {
    // ignore
  }
}

// ─── component ───────────────────────────────────────────────────────────────

export default function VideoTrimmerPage() {
  const persistedInitial = useMemo(() => loadPersisted(), [])
  const skipFilenameEffectRef = useRef(!!persistedInitial)

  // Upload state
  const [file, setFile] = useState<File | null>(null)
  const [fileUrl, setFileUrl] = useState<string>(
    persistedInitial ? getVideoUrl(persistedInitial.metadata.file_id) : ''
  )
  const [fileSizeBytes, setFileSizeBytes] = useState<number | null>(
    persistedInitial?.fileSizeBytes ?? null
  )
  const [metadata, setMetadata] = useState<TrimUploadResponse | null>(
    persistedInitial?.metadata ?? null
  )
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [waveform, setWaveform] = useState<number[]>(persistedInitial?.waveform ?? [])

  // Trim selection (current timeline selection)
  const [startSec, setStartSec] = useState(persistedInitial?.startSec ?? 0)
  const [endSec, setEndSec] = useState(persistedInitial?.endSec ?? 0)

  // Multi-segment list
  const [segments, setSegments] = useState<Segment[]>(persistedInitial?.segments ?? [])

  // Export settings
  const [quality, setQuality] = useState(persistedInitial?.quality ?? '720p')
  const [customBitrate, setCustomBitrate] = useState(persistedInitial?.customBitrate ?? 5000)
  const [aspectRatio, setAspectRatio] = useState<AspectRatioParams>(
    persistedInitial?.aspectRatio ?? { mode: 'original' }
  )
  const [cropMode, setCropMode] = useState(persistedInitial?.cropMode ?? 'crop')
  const [mute, setMute] = useState(persistedInitial?.mute ?? false)
  const [volume, setVolume] = useState(persistedInitial?.volume ?? 1.0)
  const [speed, setSpeed] = useState(persistedInitial?.speed ?? 1.0)
  const [exactFrame, setExactFrame] = useState(persistedInitial?.exactFrame ?? true)
  const [fade, setFade] = useState(persistedInitial?.fade ?? false)
  const [watermark, setWatermark] = useState<WatermarkParams>(
    persistedInitial?.watermark ?? defaultWatermark()
  )
  const [outputFilename, setOutputFilename] = useState(
    persistedInitial?.outputFilename ?? 'output.mp4'
  )

  // Processing
  const [jobId, setJobId] = useState<string | null>(null)
  const [processProgress, setProcessProgress] = useState(0)
  const [processStatus, setProcessStatus] = useState<'idle' | 'running' | 'completed' | 'failed'>(
    'idle'
  )
  const [processError, setProcessError] = useState<string | null>(null)
  const esRef = useRef<EventSource | null>(null)

  const videoRef = useRef<HTMLVideoElement>(null)
  const previewPauseAtRef = useRef<number | null>(null)

  // Verify persisted file_id still exists on backend
  useEffect(() => {
    if (!persistedInitial) return
    let cancelled = false
    checkFileExists(persistedInitial.metadata.file_id).then((ok) => {
      if (cancelled || ok) return
      clearPersisted()
      setMetadata(null)
      setFileUrl('')
      setFileSizeBytes(null)
      setWaveform([])
      setStartSec(0)
      setEndSec(0)
      setSegments([])
    })
    return () => {
      cancelled = true
    }
  }, [persistedInitial])

  // Auto-update default output filename when file first loads
  useEffect(() => {
    if (skipFilenameEffectRef.current) {
      skipFilenameEffectRef.current = false
      return
    }
    if (metadata) {
      setOutputFilename(buildDefaultFilename(metadata.original_filename, startSec, endSec))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metadata])

  // Persist state to localStorage
  useEffect(() => {
    if (!metadata) return
    savePersisted({
      metadata, fileSizeBytes, startSec, endSec, segments,
      quality, customBitrate, aspectRatio, cropMode,
      mute, volume, speed, exactFrame, fade, watermark, outputFilename, waveform,
    })
  }, [
    metadata, fileSizeBytes, startSec, endSec, segments,
    quality, customBitrate, aspectRatio, cropMode,
    mute, volume, speed, exactFrame, fade, watermark, outputFilename, waveform,
  ])

  // Preview pause handler
  useEffect(() => {
    const vid = videoRef.current
    if (!vid) return
    const handler = () => {
      if (previewPauseAtRef.current !== null && vid.currentTime >= previewPauseAtRef.current) {
        vid.pause()
        previewPauseAtRef.current = null
      }
    }
    vid.addEventListener('timeupdate', handler)
    return () => vid.removeEventListener('timeupdate', handler)
  }, [fileUrl])

  // Cleanup on unmount / file change
  useEffect(() => {
    return () => {
      if (fileUrl) URL.revokeObjectURL(fileUrl)
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
      }
    }
  }, [fileUrl])

  // ─── derived ─────────────────────────────────────────────────────────────

  // Segments to highlight on waveform (fall back to current selection if list empty)
  const waveformSegments = useMemo(() => {
    if (segments.length > 0) return segments.map((s) => ({ start: s.start, end: s.end }))
    return [{ start: startSec, end: endSec }]
  }, [segments, startSec, endSec])

  // Total raw trim duration
  const totalTrimDuration = useMemo(() => {
    if (segments.length > 0) return segments.reduce((sum, s) => sum + (s.end - s.start), 0)
    return endSec - startSec
  }, [segments, startSec, endSec])

  // Output duration after speed
  const outputDuration = useMemo(
    () => (speed > 0 ? totalTrimDuration / speed : totalTrimDuration),
    [totalTrimDuration, speed]
  )

  // Estimated output file size
  const estimatedBytes = useMemo(() => {
    if (!metadata || !fileSizeBytes || totalTrimDuration <= 0) return null
    if (quality === 'original') {
      return (fileSizeBytes / metadata.duration) * outputDuration
    }
    const kbpsMap: Record<string, number> = { '1080p': 4200, '720p': 2200, '480p': 1000 }
    const kbps = quality === 'custom' ? customBitrate + 192 : (kbpsMap[quality] ?? 2200)
    return (kbps * 1000 / 8) * outputDuration
  }, [metadata, fileSizeBytes, totalTrimDuration, outputDuration, quality, customBitrate])

  const outputAspect = useMemo(() => {
    const fallback = metadata ? metadata.width / metadata.height : 16 / 9
    const mode = aspectRatio.mode
    if (!mode || mode === 'original') return fallback
    if (mode === 'custom') return (aspectRatio.custom_w || 16) / (aspectRatio.custom_h || 9)
    const map: Record<string, number> = {
      '16:9': 16 / 9, '9:16': 9 / 16, '1:1': 1,
      '4:3': 4 / 3, '4:5': 4 / 5, '21:9': 21 / 9,
      '16:10': 16 / 10, '3:4': 3 / 4,
    }
    return map[mode] ?? fallback
  }, [metadata, aspectRatio])

  const validationError = useMemo(() => {
    if (!metadata) return 'Chưa upload video'
    if (segments.length === 0) {
      if (startSec >= endSec) return 'Điểm bắt đầu phải nhỏ hơn điểm kết thúc'
      if (endSec > metadata.duration + 0.1) return 'Điểm kết thúc vượt thời lượng video'
      if (endSec - startSec < 0.1) return 'Đoạn cắt phải dài hơn 0.1 giây'
    }
    if (aspectRatio.mode === 'custom') {
      if (!aspectRatio.custom_w || !aspectRatio.custom_h) return 'Nhập tỉ lệ tuỳ chỉnh'
    }
    if (quality === 'custom' && (customBitrate < 100 || customBitrate > 50000)) {
      return 'Bitrate phải 100-50000 kbps'
    }
    if (!outputFilename.trim()) return 'Nhập tên file xuất'
    return null
  }, [metadata, segments, startSec, endSec, aspectRatio, quality, customBitrate, outputFilename])

  const showStreamCopyWarning = useMemo(() => {
    if (!metadata || segments.length > 0) return false
    if (quality !== 'original' || exactFrame) return false
    if (aspectRatio.mode !== 'original') return false
    if ((watermark.enabled && watermark.text.trim()) || fade || mute) return false
    if (speed !== 1.0 || volume !== 1.0) return false
    return true
  }, [metadata, segments, quality, exactFrame, aspectRatio.mode, watermark, fade, mute, speed, volume])

  // ─── actions ─────────────────────────────────────────────────────────────

  const handleFileSelected = async (f: File) => {
    if (metadata) clearTemp(metadata.file_id).catch(() => {})
    if (esRef.current) { esRef.current.close(); esRef.current = null }
    if (fileUrl) URL.revokeObjectURL(fileUrl)
    clearPersisted()

    setFile(f)
    setFileSizeBytes(f.size)
    setFileUrl(URL.createObjectURL(f))
    setMetadata(null)
    setWaveform([])
    setStartSec(0)
    setEndSec(0)
    setSegments([])
    setJobId(null)
    setProcessProgress(0)
    setProcessStatus('idle')
    setProcessError(null)

    setUploading(true)
    setUploadProgress(0)
    try {
      const meta = await uploadVideo(f, setUploadProgress)
      setMetadata(meta)
      setStartSec(0)
      setEndSec(meta.duration)
      fetchWaveform(meta.file_id).then(setWaveform).catch(() => setWaveform([]))
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      alert(`Upload thất bại: ${msg}`)
    } finally {
      setUploading(false)
    }
  }

  const addSegment = () => {
    if (!metadata || endSec - startSec < 0.1) return
    setSegments((prev) => [
      ...prev,
      { id: crypto.randomUUID(), start: startSec, end: endSec },
    ])
  }

  const removeSegment = (id: string) => {
    setSegments((prev) => prev.filter((s) => s.id !== id))
  }

  const startProcess = async () => {
    if (!metadata || validationError) return
    setProcessStatus('running')
    setProcessProgress(0)
    setProcessError(null)

    const segsToSend =
      segments.length > 0
        ? segments.map((s) => ({ start_sec: s.start, end_sec: s.end }))
        : [{ start_sec: startSec, end_sec: endSec }]

    try {
      const newJobId = await startTrim({
        file_id: metadata.file_id,
        segments: segsToSend,
        quality,
        custom_bitrate_kbps: quality === 'custom' ? customBitrate : undefined,
        aspect_ratio: aspectRatio,
        crop_mode: cropMode,
        mute,
        volume,
        speed,
        exact_frame: exactFrame,
        fade,
        watermark,
        output_filename: outputFilename,
      })
      setJobId(newJobId)

      esRef.current = openProgressStream(newJobId, (pct, status, error) => {
        setProcessProgress(pct)
        if (status === 'completed') {
          setProcessStatus('completed')
          const a = document.createElement('a')
          a.href = getDownloadUrl(newJobId)
          a.download = outputFilename
          document.body.appendChild(a)
          a.click()
          a.remove()
        } else if (status === 'failed') {
          setProcessStatus('failed')
          setProcessError(error || 'Xử lý thất bại')
        }
      })
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setProcessStatus('failed')
      setProcessError(msg || 'Lỗi khi bắt đầu xử lý')
    }
  }

  const previewSelection = () => {
    const vid = videoRef.current
    if (!vid || !metadata) return
    vid.currentTime = startSec
    previewPauseAtRef.current = endSec
    vid.play()
  }

  const resetAll = () => {
    if (processStatus === 'running') {
      if (!window.confirm('Đang xử lý video, xoá tất cả bây giờ?')) return
    }
    if (metadata) clearTemp(metadata.file_id).catch(() => {})
    if (esRef.current) { esRef.current.close(); esRef.current = null }
    if (fileUrl) URL.revokeObjectURL(fileUrl)
    previewPauseAtRef.current = null
    clearPersisted()

    setFile(null)
    setFileUrl('')
    setFileSizeBytes(null)
    setMetadata(null)
    setUploading(false)
    setUploadProgress(0)
    setWaveform([])
    setStartSec(0)
    setEndSec(0)
    setSegments([])
    setQuality('720p')
    setCustomBitrate(5000)
    setAspectRatio({ mode: 'original' })
    setCropMode('crop')
    setMute(false)
    setVolume(1.0)
    setSpeed(1.0)
    setExactFrame(true)
    setFade(false)
    setWatermark(defaultWatermark())
    setOutputFilename('output.mp4')
    setJobId(null)
    setProcessProgress(0)
    setProcessStatus('idle')
    setProcessError(null)
  }

  // ─── render ──────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Scissors size={28} className="text-primary-600 dark:text-primary-400" />
          <h1 className="text-3xl font-bold text-strong">Cắt video</h1>
        </div>
        <button
          type="button"
          onClick={resetAll}
          disabled={!file && !metadata && !fileUrl && processStatus === 'idle'}
          className="flex items-center gap-2 px-3 py-1.5 text-sm border border-token rounded hover:bg-surface-2 disabled:opacity-40 disabled:cursor-not-allowed transition"
          title="Xoá video và cài đặt, reset tab"
        >
          <RotateCcw size={16} /> Xoá tất cả
        </button>
      </div>

      {/* Step 1: Upload */}
      <section className="bg-surface p-6 rounded-lg shadow">
        <h2 className="text-lg font-semibold mb-4">1. Tải video lên</h2>
        <UploadZone
          onFileSelected={handleFileSelected}
          uploading={uploading}
          uploadProgress={uploadProgress}
        />
        {metadata && (
          <div className="mt-3 text-sm text-dim space-y-0.5">
            <div>
              <b>File:</b> {metadata.original_filename}
              {fileSizeBytes !== null && (
                <> · <b>Kích thước:</b> {(fileSizeBytes / 1024 / 1024).toFixed(1)} MB</>
              )}
            </div>
            <div>
              <b>Thời lượng:</b> {metadata.duration.toFixed(1)}s · <b>Độ phân giải:</b>{' '}
              {metadata.width}×{metadata.height} · <b>Codec:</b> {metadata.video_codec}
              {metadata.audio_codec && ` / ${metadata.audio_codec}`}
            </div>
          </div>
        )}
      </section>

      {metadata && fileUrl && (
        <>
          {/* Step 2: Preview + selection */}
          <section className="bg-surface p-6 rounded-lg shadow space-y-4">
            <h2 className="text-lg font-semibold">2. Xem trước & chọn đoạn</h2>
            <VideoPreview ref={videoRef} src={fileUrl} />
            <Waveform
              peaks={waveform}
              duration={metadata.duration}
              segments={waveformSegments}
            />
            <Timeline
              duration={metadata.duration}
              startSec={startSec}
              endSec={endSec}
              onChange={(s, e) => {
                setStartSec(s)
                setEndSec(e)
              }}
            />
          </section>

          {/* Step 3: Precise time + segment management */}
          <section className="bg-surface p-6 rounded-lg shadow space-y-4">
            <h2 className="text-lg font-semibold">3. Thời gian chính xác</h2>
            <div className="flex flex-wrap gap-6">
              <TimeInput
                label="Bắt đầu từ"
                valueSec={startSec}
                maxSec={metadata.duration}
                onChange={(s) => setStartSec(Math.min(s, endSec - 0.1))}
                onSetFromPlayer={() => {
                  const t = videoRef.current?.currentTime ?? 0
                  setStartSec(Math.min(t, endSec - 0.1))
                }}
              />
              <TimeInput
                label="Kết thúc tại"
                valueSec={endSec}
                maxSec={metadata.duration}
                onChange={(s) => setEndSec(Math.max(s, startSec + 0.1))}
                onSetFromPlayer={() => {
                  const t = videoRef.current?.currentTime ?? 0
                  setEndSec(Math.max(t, startSec + 0.1))
                }}
              />
              <div className="self-end">
                <div className="text-sm text-dim mb-1">Đoạn hiện tại</div>
                <div className="text-lg font-mono font-semibold text-primary-700 dark:text-primary-400">
                  {(endSec - startSec).toFixed(2)}s
                </div>
              </div>
              <div className="self-end flex gap-2">
                <button
                  type="button"
                  onClick={previewSelection}
                  className="flex items-center gap-2 px-3 py-1.5 border rounded hover:bg-surface-2"
                >
                  <Play size={16} /> Xem trước
                </button>
                <button
                  type="button"
                  onClick={addSegment}
                  disabled={endSec - startSec < 0.1}
                  className="flex items-center gap-2 px-3 py-1.5 border border-primary-400 dark:border-primary-500/30 text-primary-700 dark:text-primary-400 rounded hover:bg-primary-50 dark:hover:bg-primary-500/15 disabled:opacity-40 disabled:cursor-not-allowed transition"
                  title="Thêm đoạn này vào danh sách ghép"
                >
                  <Plus size={16} /> Thêm đoạn
                </button>
              </div>
            </div>

            {/* Segment list */}
            {segments.length > 0 && (
              <div className="space-y-1">
                <div className="text-sm font-medium text-dim">
                  Danh sách đoạn ({segments.length}) — sẽ ghép theo thứ tự:
                </div>
                {segments.map((seg, idx) => (
                  <div
                    key={seg.id}
                    className="flex items-center gap-3 px-3 py-1.5 bg-primary-50 dark:bg-primary-500/10 border border-primary-200 dark:border-primary-500/30 rounded text-sm"
                  >
                    <span className="text-primary-400 font-mono text-xs w-4 text-right">{idx + 1}</span>
                    <span className="font-mono text-strong">
                      {fmtSec(seg.start)} {fmtSec(seg.end)}
                    </span>
                    <span className="text-faint">({(seg.end - seg.start).toFixed(2)}s)</span>
                    <button
                      type="button"
                      onClick={() => removeSegment(seg.id)}
                      className="ml-auto text-red-400 hover:text-red-600 transition"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
                <div className="text-xs text-dim pt-1">
                  Tổng: {totalTrimDuration.toFixed(2)}s
                  {speed !== 1.0 && (
                    <> sau tốc độ {speed}x: <b>{outputDuration.toFixed(2)}s</b></>
                  )}
                </div>
              </div>
            )}
          </section>

          {/* Step 4: Export settings */}
          <section className="bg-surface p-6 rounded-lg shadow">
            <h2 className="text-lg font-semibold mb-4">4. Cài đặt xuất file</h2>
            <ExportSettings
              quality={quality} setQuality={setQuality}
              customBitrate={customBitrate} setCustomBitrate={setCustomBitrate}
              aspectRatio={aspectRatio} setAspectRatio={setAspectRatio}
              cropMode={cropMode} setCropMode={setCropMode}
              mute={mute} setMute={setMute}
              volume={volume} setVolume={setVolume}
              speed={speed} setSpeed={setSpeed}
              exactFrame={exactFrame} setExactFrame={setExactFrame}
              fade={fade} setFade={setFade}
              watermark={watermark} setWatermark={setWatermark}
              previewAspect={outputAspect}
              outputFilename={outputFilename} setOutputFilename={setOutputFilename}
            />
          </section>

          {/* Step 5: Process */}
          <section className="bg-surface p-6 rounded-lg shadow space-y-3">
            <h2 className="text-lg font-semibold">5. Xuất file</h2>

            {showStreamCopyWarning && (
              <div className="bg-yellow-50 dark:bg-yellow-500/10 border border-yellow-300 dark:border-yellow-500/30 text-yellow-900 dark:text-yellow-300 text-sm p-3 rounded">
                 <b>Stream copy</b> — điểm cắt có thể lệch ±2s do keyframe. Tick "Cắt chính xác
                theo frame" để frame-accurate.
              </div>
            )}

            {estimatedBytes !== null && (
              <div className="text-sm text-dim">
                Ước tính dung lượng:{' '}
                <span className="font-semibold text-strong">~{formatBytes(estimatedBytes)}</span>
                {speed !== 1.0 && (
                  <span className="text-faint ml-2">
                    (sau {speed}x tốc độ {outputDuration.toFixed(1)}s)
                  </span>
                )}
              </div>
            )}

            {validationError && (
              <div className="bg-red-50 dark:bg-red-500/10 border border-red-300 dark:border-red-500/30 text-red-800 dark:text-red-300 text-sm p-3 rounded">
                {validationError}
              </div>
            )}

            <button
              type="button"
              onClick={startProcess}
              disabled={!!validationError || processStatus === 'running'}
              className="flex items-center gap-2 px-5 py-2.5 bg-primary-600 text-white rounded-lg font-medium hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
            >
              <Scissors size={18} />
              {segments.length > 1 ? `Cắt & ghép ${segments.length} đoạn` : 'Bắt đầu cắt video'}
            </button>

            {processStatus !== 'idle' && (
              <div>
                <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2.5">
                  <div
                    className={`h-2.5 rounded-full transition-all ${
                      processStatus === 'failed' ? 'bg-red-500' : 'bg-primary-600'
                    }`}
                    style={{ width: `${processProgress}%` }}
                  />
                </div>
                <p className="text-sm text-dim mt-2">
                  {processStatus === 'running' && `Đang xử lý… ${processProgress.toFixed(1)}%`}
                  {processStatus === 'completed' && ' Xong — file đang tải về trình duyệt'}
                  {processStatus === 'failed' && ` Lỗi: ${processError || 'Không xác định'}`}
                </p>
                {processStatus === 'completed' && jobId && (
                  <a
                    href={getDownloadUrl(jobId)}
                    className="text-sm text-primary-600 dark:text-primary-400 hover:underline"
                  >
                    Tải lại file
                  </a>
                )}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}
