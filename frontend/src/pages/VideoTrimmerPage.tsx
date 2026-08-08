import { useEffect, useMemo, useRef, useState } from 'react'
import axios from 'axios'
import { Scissors, Play, RotateCcw, Plus, Trash2, Upload, X, FolderOpen } from 'lucide-react'
import UploadZone from '../components/trim/UploadZone'
import VideoPreview from '../components/trim/VideoPreview'
import Waveform from '../components/trim/Waveform'
import Timeline from '../components/trim/Timeline'
import TimeInput from '../components/trim/TimeInput'
import ExportSettings from '../components/trim/ExportSettings'
import SubtitleTrimPanel from '../components/trim/SubtitleTrimPanel'
import { DEFAULT_SUBTITLE_STYLE, type SubtitleStyle } from '../components/subtitle/srt'
import {
  uploadVideo,
  importVideoFromPath,
  fetchWaveform,
  startTrim,
  openProgressStream,
  revealOutput,
  getVideoUrl,
  checkFileExists,
  clearTemp,
  defaultWatermark,
  isVideoFile,
  validateVideoFolder,
  generateFromFolder,
  type AspectRatioParams,
  type FolderValidation,
  type TrimUploadResponse,
  type WatermarkParams,
} from '../services/trimApi'
import { pickFolderNative } from '../services/nativeDialog'

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
  srtPath: string | null
  subtitleStyle: SubtitleStyle
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

interface VideoTrimmerPageProps {
  /** Server-side path of a video (e.g. the long video just produced by the
   *  pipeline). When set, an "import from server" field appears at the top of
   *  the upload section so the video can be trimmed without re-uploading. */
  sourceVideoPath?: string
}

export default function VideoTrimmerPage({ sourceVideoPath }: VideoTrimmerPageProps = {}) {
  const persistedInitial = useMemo(() => loadPersisted(), [])
  const skipFilenameEffectRef = useRef(!!persistedInitial)

  // Import-from-server-path (long video produced upstream)
  const [importPath, setImportPath] = useState(sourceVideoPath ?? '')

  // In-app confirm dialog (replaces native window.confirm)
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean
    title: string
    message: string
    confirmText: string
    variant: 'danger' | 'primary'
    onConfirm: () => void
  }>({ isOpen: false, title: '', message: '', confirmText: 'OK', variant: 'primary', onConfirm: () => {} })

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
  // Drag-over highlight for the compact "replace current video" drop target
  const [dragOverReplace, setDragOverReplace] = useState(false)

  // ── Video Source Folder (override current video with a random shuffle-concat
  //    of clips from a folder, cut to the imported video's exact duration) ──
  const [sourceFolder, setSourceFolder] = useState('')
  const [folderValidation, setFolderValidation] = useState<FolderValidation | null>(null)
  const [clipOrder, setClipOrder] = useState<'shuffle' | 'name'>('shuffle')
  // Mute the audio of clips pulled from the folder (default on). This only
  // affects the folder-generated video — the original imported video's audio
  // (kept via the Export "mute" toggle) is untouched.
  const [folderMuteAudio, setFolderMuteAudio] = useState(true)
  // Mute the ORIGINAL imported video's audio when generating from folder.
  // Default off => the original narration is muxed onto the folder background
  // so the folder clips act purely as visuals.
  const [muteOriginalAudio, setMuteOriginalAudio] = useState(false)
  const [folderBusy, setFolderBusy] = useState(false)
  // The target length to fill — captured from the ORIGINAL imported video so it
  // stays fixed across re-shuffles (the generated clip replaces `metadata`).
  const [folderTargetDuration, setFolderTargetDuration] = useState<number | null>(null)

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

  // Subtitle (SRT) burn — optional. srtPath is server-side, scoped to the
  // current trim file_id; it's cleared whenever the video changes.
  const [srtPath, setSrtPath] = useState<string | null>(persistedInitial?.srtPath ?? null)
  const [subtitleStyle, setSubtitleStyle] = useState<SubtitleStyle>(
    persistedInitial?.subtitleStyle ?? DEFAULT_SUBTITLE_STYLE
  )
  const [availableFonts, setAvailableFonts] = useState<string[]>([
    'Be Vietnam Pro (Vietnamese)',
  ])
  const [subtitleCardOpen, setSubtitleCardOpen] = useState(false)

  // Processing
  const [jobId, setJobId] = useState<string | null>(null)
  const [processProgress, setProcessProgress] = useState(0)
  const [processStatus, setProcessStatus] = useState<'idle' | 'running' | 'completed' | 'failed'>(
    'idle'
  )
  const [processError, setProcessError] = useState<string | null>(null)
  const [savedPath, setSavedPath] = useState<string | null>(null)
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
      setSrtPath(null)
    })
    return () => {
      cancelled = true
    }
  }, [persistedInitial])

  // Keep the import field in sync with the upstream long-video path
  useEffect(() => {
    if (sourceVideoPath) setImportPath(sourceVideoPath)
  }, [sourceVideoPath])

  // Fonts available for subtitle burning (same registry as the story pipeline).
  useEffect(() => {
    axios
      .get<string[]>('/api/v1/video/fonts')
      .then((r) => {
        if (Array.isArray(r.data) && r.data.length > 0) setAvailableFonts(r.data)
      })
      .catch(() => {})
  }, [])

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
      srtPath, subtitleStyle,
    })
  }, [
    metadata, fileSizeBytes, startSec, endSec, segments,
    quality, customBitrate, aspectRatio, cropMode,
    mute, volume, speed, exactFrame, fade, watermark, outputFilename, waveform,
    srtPath, subtitleStyle,
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

  // Output canvas height in px — mirrors backend video_trimmer.py: quality maps
  // to a fixed height (else source height for original/custom). The watermark
  // overlay uses this to scale font_size/margin (both output-pixel units).
  const outputHeight = useMemo(() => {
    const map: Record<string, number> = { '1080p': 1080, '720p': 720, '480p': 480 }
    return map[quality] ?? metadata?.height ?? 1080
  }, [quality, metadata])

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
    setSrtPath(null)
    setFolderTargetDuration(null)
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

  // Replace the current video from the compact card (button or drag-drop),
  // keeping the video-type guard the UploadZone enforces on first load.
  const handleReplaceFile = (f: File | null | undefined) => {
    if (!f || uploading || folderBusy) return
    if (!isVideoFile(f)) {
      alert('File không phải định dạng video hợp lệ')
      return
    }
    handleFileSelected(f)
  }

  const handleImportPath = async (path: string) => {
    const p = path.trim()
    if (!p) return
    if (metadata) clearTemp(metadata.file_id).catch(() => {})
    if (esRef.current) { esRef.current.close(); esRef.current = null }
    if (fileUrl.startsWith('blob:')) URL.revokeObjectURL(fileUrl)
    clearPersisted()

    setFile(null)
    setFileSizeBytes(null)
    setMetadata(null)
    setFileUrl('')
    setWaveform([])
    setStartSec(0)
    setEndSec(0)
    setSegments([])
    setSrtPath(null)
    setFolderTargetDuration(null)
    setJobId(null)
    setProcessProgress(0)
    setProcessStatus('idle')
    setProcessError(null)

    setUploading(true)
    setUploadProgress(0)
    try {
      const meta = await importVideoFromPath(p)
      setMetadata(meta)
      setFileUrl(getVideoUrl(meta.file_id))
      setStartSec(0)
      setEndSec(meta.duration)
      fetchWaveform(meta.file_id).then(setWaveform).catch(() => setWaveform([]))
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      alert(`Nạp video thất bại: ${msg}`)
    } finally {
      setUploading(false)
    }
  }

  const handleBrowseFolder = async () => {
    const picked = await pickFolderNative(sourceFolder || '')
    if (picked) {
      setSourceFolder(picked)
      setFolderValidation(null)
    }
  }

  const handleValidateFolder = async () => {
    const folder = sourceFolder.trim()
    if (!folder) return
    try {
      const v = await validateVideoFolder(folder)
      setFolderValidation(v)
      if (!v.valid) alert(v.error || 'Thư mục không hợp lệ')
    } catch {
      setFolderValidation({
        valid: false, video_count: 0, total_duration: 0,
        total_duration_formatted: '', error: 'Không kiểm tra được thư mục',
      })
    }
  }

  // Build a source video from the folder that fills the original imported
  // video's duration, then swap it in as the current trim video. Each call in
  // shuffle mode uses a fresh random order, so clicking again gives a new mix.
  const handleGenerateFromFolder = async () => {
    const folder = sourceFolder.trim()
    if (!folder) { alert('Nhập đường dẫn thư mục video'); return }
    if (!metadata) { alert('Cần import/upload video gốc trước để lấy thời lượng đích'); return }

    const target = folderTargetDuration ?? metadata.duration
    const width = metadata.width
    const height = metadata.height
    const seed = clipOrder === 'shuffle' ? Math.floor(Math.random() * 1_000_000_000) : null

    const prevFileId = metadata.file_id
    setFolderBusy(true)
    try {
      const meta = await generateFromFolder({
        folder,
        target_duration: target,
        width,
        height,
        clip_order: clipOrder,
        clip_seed: seed,
        mute_audio: folderMuteAudio,
        // Carry the currently-loaded video's audio onto the new background so
        // the original narration survives (unless the user chose to mute it).
        // On re-shuffles prevFileId already holds the muxed narration, so it
        // keeps flowing through each regeneration.
        original_file_id: prevFileId,
        mute_original_audio: muteOriginalAudio,
      })
      if (fileUrl.startsWith('blob:')) URL.revokeObjectURL(fileUrl)
      setFolderTargetDuration(target)
      setFile(null)
      setFileSizeBytes(null)
      setMetadata(meta)
      setFileUrl(getVideoUrl(meta.file_id))
      setStartSec(0)
      setEndSec(meta.duration)
      setSegments([])
      setSrtPath(null)
      setWaveform([])
      setJobId(null)
      setProcessProgress(0)
      setProcessStatus('idle')
      setProcessError(null)
      fetchWaveform(meta.file_id).then(setWaveform).catch(() => setWaveform([]))
      if (prevFileId && prevFileId !== meta.file_id) clearTemp(prevFileId).catch(() => {})
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      const msg = detail || (err instanceof Error ? err.message : String(err))
      alert(`Tạo video từ folder thất bại: ${msg}`)
    } finally {
      setFolderBusy(false)
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
    setSavedPath(null)

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
        subtitle: {
          enabled: !!srtPath,
          srt_path: srtPath,
          animation: subtitleStyle.subtitle_animation,
          font: subtitleStyle.subtitle_font,
          font_size: subtitleStyle.subtitle_font_size,
          color: subtitleStyle.subtitle_color,
          outline_color: subtitleStyle.subtitle_outline_color,
          outline_width: subtitleStyle.subtitle_outline_width,
          shadow: subtitleStyle.subtitle_shadow,
          bold: subtitleStyle.subtitle_bold,
          italic: subtitleStyle.subtitle_italic,
          align: subtitleStyle.subtitle_align,
          x: subtitleStyle.subtitle_x,
          y: subtitleStyle.subtitle_y,
          opacity: subtitleStyle.subtitle_opacity,
          max_width: subtitleStyle.subtitle_max_width,
        },
        output_filename: outputFilename,
      })
      setJobId(newJobId)

      esRef.current = openProgressStream(newJobId, (pct, status, error, outputPath) => {
        // NaN pct signals a transient SSE reconnect — keep the bar where it is.
        if (!Number.isNaN(pct)) setProcessProgress(pct)
        if (status === 'completed') {
          setProcessStatus('completed')
          // The server already saved the file into the configured output folder
          // (Downloads by default) — show where instead of forcing a browser download.
          setSavedPath(outputPath || null)
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

  const doReset = () => {
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
    setSrtPath(null)
    setSubtitleStyle(DEFAULT_SUBTITLE_STYLE)
    setSubtitleCardOpen(false)
    setSourceFolder('')
    setFolderValidation(null)
    setFolderTargetDuration(null)
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
    setSavedPath(null)
  }

  const resetAll = () => {
    if (processStatus === 'running') {
      setConfirmDialog({
        isOpen: true,
        title: 'Xoá tất cả?',
        message: 'Đang xử lý video, xoá tất cả bây giờ?',
        confirmText: 'Xoá tất cả',
        variant: 'danger',
        onConfirm: doReset,
      })
      return
    }
    doReset()
  }

  // Clear only this trim section (video + segments + settings). Leaves the
  // upstream "Nạp video dài vừa tạo" import field untouched.
  const clearVideoSelection = () => {
    setConfirmDialog({
      isOpen: true,
      title: 'Xóa video này?',
      message:
        processStatus === 'running'
          ? 'Đang xử lý video. Gỡ video và xoá các lựa chọn cắt ở phần này?'
          : 'Gỡ video này và xoá các đoạn/cài đặt đã chọn? (Không ảnh hưởng ô "Nạp video dài vừa tạo" ở trên.)',
      confirmText: 'Xóa video',
      variant: 'danger',
      onConfirm: doReset,
    })
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

        {/* Import long video produced upstream (Shorts/TikTok workflow) */}
        {sourceVideoPath && (
          <div className="mb-4 p-3 rounded-md border border-primary-300 dark:border-primary-500/30 bg-primary-50 dark:bg-primary-500/10 space-y-2">
            <div className="text-sm font-medium text-strong">
              Nạp video dài vừa tạo (cắt ra clip ngắn cho Short/TikTok)
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={importPath}
                onChange={(e) => setImportPath(e.target.value)}
                placeholder="Đường dẫn video trên máy (điền sẵn từ video dài vừa tạo)"
                className="flex-1 px-3 py-2 border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                disabled={uploading}
              />
              <button
                type="button"
                onClick={() => handleImportPath(importPath)}
                disabled={!importPath.trim() || uploading}
                className="px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition whitespace-nowrap"
              >
                Nạp video này
              </button>
            </div>
            <p className="text-xs text-dim">
              Cắt trực tiếp video dài — khỏi phải tải file lên lại. Hoặc chọn file khác bên dưới.
            </p>
          </div>
        )}

        {/* Before a video is loaded (or while uploading) show the drop zone;
            once loaded, collapse it into a compact card to reduce clutter. */}
        {!metadata ? (
          <UploadZone
            onFileSelected={handleFileSelected}
            uploading={uploading}
            uploadProgress={uploadProgress}
          />
        ) : (
          <div
            onDragOver={(e) => {
              e.preventDefault()
              if (!uploading && !folderBusy) setDragOverReplace(true)
            }}
            onDragLeave={() => setDragOverReplace(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragOverReplace(false)
              handleReplaceFile(e.dataTransfer.files?.[0])
            }}
            className={`flex items-center justify-between gap-3 p-4 border rounded-lg bg-surface-2 transition ${
              dragOverReplace ? 'border-primary-500 bg-primary-50 dark:bg-primary-500/10' : 'border-token'
            }`}
          >
            <div className="min-w-0 text-sm text-dim space-y-0.5">
              <div className="truncate">
                <b className="text-strong">File:</b> {metadata.original_filename}
                {fileSizeBytes !== null && (
                  <> · <b>Kích thước:</b> {(fileSizeBytes / 1024 / 1024).toFixed(1)} MB</>
                )}
              </div>
              <div>
                <b>Thời lượng:</b> {metadata.duration.toFixed(1)}s · <b>Độ phân giải:</b>{' '}
                {metadata.width}×{metadata.height} · <b>Codec:</b> {metadata.video_codec}
                {metadata.audio_codec && ` / ${metadata.audio_codec}`}
              </div>
              <div className="text-xs text-faint">Kéo thả video khác vào đây để đổi</div>
            </div>
            <label
              className={`shrink-0 flex items-center gap-2 px-3 py-1.5 text-sm border border-token rounded transition ${
                uploading || folderBusy ? 'opacity-50 cursor-not-allowed' : 'hover:bg-surface cursor-pointer'
              }`}
              title="Chọn file video khác thay thế"
            >
              <Upload size={16} /> Đổi video khác
              <input
                type="file"
                accept=".mp4,.mov,.mkv,.avi,.webm,video/*"
                className="hidden"
                disabled={uploading || folderBusy}
                onChange={(e) => {
                  handleReplaceFile(e.target.files?.[0])
                  e.target.value = ''
                }}
              />
            </label>
          </div>
        )}
      </section>

      {metadata && fileUrl && (
        <>
          {/* Step 2: Preview + selection */}
          <section className="bg-surface p-6 rounded-lg shadow space-y-4">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-semibold">2. Xem trước & chọn đoạn</h2>
              <button
                type="button"
                onClick={clearVideoSelection}
                className="flex items-center gap-1.5 px-2.5 py-1.5 text-sm text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-500/10 rounded transition"
                title="Gỡ video này và xoá các đoạn/cài đặt đã chọn"
              >
                <X size={16} /> Xóa video này
              </button>
            </div>
            <VideoPreview
              ref={videoRef}
              src={fileUrl}
              outputAspect={outputAspect}
              aspectMode={aspectRatio.mode}
              cropMode={cropMode}
              speed={speed}
              mute={mute}
              volume={volume}
              watermark={watermark}
              outputHeight={outputHeight}
            />
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

          {/* Video Source Folder — override the current video with a random
              shuffle-concat of clips from a folder, cut to the original duration. */}
          <section className="bg-surface p-6 rounded-lg shadow space-y-3">
            <div>
              <h2 className="text-lg font-semibold">Nguồn từ thư mục (tuỳ chọn)</h2>
              <p className="text-sm text-dim mt-1">
                Chọn ngẫu nhiên các video trong thư mục, nối lại và cắt đúng{' '}
                <b>{(folderTargetDuration ?? metadata.duration).toFixed(1)}s</b>{' '}
                (thời lượng video gốc) làm <b>nền hình</b> — mặc định vẫn giữ{' '}
                <b>tiếng của video gốc</b>.
              </p>
            </div>

            <div>
              <label className="block text-sm text-dim mb-1">Video Source Folder</label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={sourceFolder}
                  onChange={(e) => {
                    setSourceFolder(e.target.value)
                    setFolderValidation(null)
                  }}
                  placeholder="D:\path\to\video\folder"
                  className="flex-1 px-3 py-1.5 border rounded bg-surface text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                  disabled={folderBusy}
                />
                <button
                  type="button"
                  onClick={handleBrowseFolder}
                  disabled={folderBusy}
                  className="px-3 py-1.5 text-sm bg-gray-600 text-white rounded hover:bg-gray-700 disabled:opacity-50"
                >
                  Browse
                </button>
                <button
                  type="button"
                  onClick={handleValidateFolder}
                  disabled={!sourceFolder.trim() || folderBusy}
                  className="px-3 py-1.5 text-sm bg-primary-500 text-white rounded hover:bg-primary-600 disabled:opacity-50"
                >
                  Validate
                </button>
              </div>
              {folderValidation && (
                <div
                  className={`mt-1 text-xs ${
                    folderValidation.valid
                      ? 'text-green-600 dark:text-green-400'
                      : 'text-red-600 dark:text-red-400'
                  }`}
                >
                  {folderValidation.valid
                    ? `✓ ${folderValidation.video_count} video (${folderValidation.total_duration_formatted})`
                    : folderValidation.error || 'Thư mục không hợp lệ'}
                </div>
              )}
            </div>

            <div className="flex items-center gap-4 flex-wrap">
              <span className="text-sm text-dim">Cách chọn clip:</span>
              <label className="flex items-center gap-1.5 text-sm text-dim cursor-pointer select-none">
                <input
                  type="radio"
                  name="trim_clip_order"
                  checked={clipOrder === 'shuffle'}
                  onChange={() => setClipOrder('shuffle')}
                  disabled={folderBusy}
                />
                Ngẫu nhiên (mặc định)
              </label>
              <label className="flex items-center gap-1.5 text-sm text-dim cursor-pointer select-none">
                <input
                  type="radio"
                  name="trim_clip_order"
                  checked={clipOrder === 'name'}
                  onChange={() => setClipOrder('name')}
                  disabled={folderBusy}
                />
                Theo thứ tự tên (A→Z)
              </label>
            </div>

            <label className="flex items-center gap-2 text-sm text-dim cursor-pointer select-none">
              <input
                type="checkbox"
                checked={folderMuteAudio}
                onChange={(e) => setFolderMuteAudio(e.target.checked)}
                disabled={folderBusy}
              />
              Tắt tiếng các video lấy từ thư mục (chỉ dùng làm nền hình)
            </label>

            <label className="flex items-center gap-2 text-sm text-dim cursor-pointer select-none">
              <input
                type="checkbox"
                checked={muteOriginalAudio}
                onChange={(e) => setMuteOriginalAudio(e.target.checked)}
                disabled={folderBusy}
              />
              Tắt âm thanh của video gốc import (mặc định giữ tiếng gốc, ghép vào nền mới)
            </label>

            <div className="flex items-center gap-3 flex-wrap">
              <button
                type="button"
                onClick={handleGenerateFromFolder}
                disabled={folderBusy || !sourceFolder.trim()}
                className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50"
              >
                <Scissors size={16} />
                {folderBusy ? 'Đang tạo…' : 'Tạo video từ folder'}
              </button>
              {clipOrder === 'shuffle' && folderTargetDuration !== null && !folderBusy && (
                <span className="text-xs text-dim">Bấm lại để tạo bản ngẫu nhiên khác cùng thời lượng.</span>
              )}
            </div>
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

          {/* Phụ đề (SRT) — tuỳ chọn: burn phụ đề re-based lên clip cắt */}
          <section className="bg-surface p-6 rounded-lg shadow">
            <button
              type="button"
              onClick={() => setSubtitleCardOpen((o) => !o)}
              className="w-full flex items-center justify-between gap-2"
            >
              <span className="flex items-center gap-2">
                <span className="text-lg font-semibold">Phụ đề (SRT)</span>
                <span className="text-sm text-dim font-normal">— tuỳ chọn</span>
                {srtPath && (
                  <span className="text-[11px] px-1.5 py-0.5 rounded bg-green-100 dark:bg-green-500/15 text-green-700 dark:text-green-400">
                    đã gắn ({subtitleStyle.subtitle_animation})
                  </span>
                )}
              </span>
              <span className="text-faint text-xs">{subtitleCardOpen ? '▲ ẩn' : '▼ hiện'}</span>
            </button>
            {subtitleCardOpen && (
              <div className="mt-4">
                <SubtitleTrimPanel
                  fileId={metadata.file_id}
                  style={subtitleStyle}
                  onChange={(patch) => setSubtitleStyle((prev) => ({ ...prev, ...patch }))}
                  srtPath={srtPath}
                  onSrtUploaded={(info) => setSrtPath(info?.srt_path ?? null)}
                  availableFonts={availableFonts}
                />
              </div>
            )}
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
                  {processStatus === 'completed' && ' Xong — đã lưu vào thư mục xuất'}
                  {processStatus === 'failed' && ` Lỗi: ${processError || 'Không xác định'}`}
                </p>
                {processStatus === 'completed' && savedPath && (
                  <p className="text-sm text-dim mt-1 break-all">
                    Đã lưu vào: <span className="font-mono text-strong">{savedPath}</span>
                  </p>
                )}
                {processStatus === 'completed' && jobId && (
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        await revealOutput(jobId)
                      } catch (e: any) {
                        alert(e?.response?.data?.detail || 'Không mở được thư mục chứa file.')
                      }
                    }}
                    className="mt-2 flex items-center gap-2 text-sm text-primary-600 dark:text-primary-400 hover:underline"
                  >
                    <FolderOpen size={16} />
                    Mở thư mục chứa file
                  </button>
                )}
              </div>
            )}
          </section>
        </>
      )}

      {/* Confirm Dialog */}
      {confirmDialog.isOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-surface rounded-lg w-full max-w-md flex flex-col">
            <div className="p-4 border-b flex items-center justify-between">
              <h3 className="text-lg font-semibold">{confirmDialog.title}</h3>
              <button
                onClick={() => setConfirmDialog(prev => ({ ...prev, isOpen: false }))}
                className="text-faint hover:text-dim text-xl"
              >
                ×
              </button>
            </div>
            <div className="p-4">
              <p className="text-sm text-dim whitespace-pre-line">{confirmDialog.message}</p>
            </div>
            <div className="p-4 border-t flex gap-2 justify-end">
              <button
                onClick={() => setConfirmDialog(prev => ({ ...prev, isOpen: false }))}
                className="px-4 py-2 bg-gray-200 dark:bg-gray-700 rounded-md hover:bg-gray-300 dark:hover:bg-gray-600 transition text-sm"
              >
                Hủy
              </button>
              <button
                onClick={() => {
                  const cb = confirmDialog.onConfirm
                  setConfirmDialog(prev => ({ ...prev, isOpen: false }))
                  cb()
                }}
                className={`px-4 py-2 text-white rounded-md transition text-sm font-semibold ${
                  confirmDialog.variant === 'danger'
                    ? 'bg-red-500 hover:bg-red-600'
                    : 'bg-primary-500 hover:bg-primary-600'
                }`}
              >
                {confirmDialog.confirmText}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
