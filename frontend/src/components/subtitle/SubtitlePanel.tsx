import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import {
  SubtitleAnimation,
  SubtitleStyle,
  SubtitleSegment,
  parseSRT,
} from './srt'

interface UploadResponse {
  srt_path: string
  filename: string
  segment_count: number
  last_end: number
  first_start: number
  audio_duration: number | null
  warning: string | null
}

interface PanelProps {
  storyId: string
  audioPath: string
  audioDuration: number  // seconds (post-speedup not necessary; warning is informational)
  audioSpeed: number     // for warning calculation
  style: SubtitleStyle
  onChange: (patch: Partial<SubtitleStyle>) => void
  // Position is part of style but driven externally via the preview-frame drag.
  srtPath: string | null  // currently uploaded SRT path (server-side)
  onSrtUploaded: (info: UploadResponse | null, segments: SubtitleSegment[] | null) => void
  availableFonts: string[]
}

const ANIMATION_LABELS: Record<SubtitleAnimation, string> = {
  none: 'Không hiệu ứng',
  fade: 'Fade in/out',
  pop: 'Pop (bật vào)',
  slide_up: 'Slide up (trượt từ dưới)',
  typewriter: 'Typewriter (gõ chữ)',
}

export function SubtitlePanel({
  storyId, audioPath, audioDuration, audioSpeed,
  style, onChange,
  srtPath, onSrtUploaded,
  availableFonts,
}: PanelProps) {
  const [uploading, setUploading] = useState(false)
  const [uploadInfo, setUploadInfo] = useState<UploadResponse | null>(null)
  const [warning, setWarning] = useState<string | null>(null)
  const [filename, setFilename] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  // Inject @font-face for the chosen subtitle font (mirrors what the watermark
  // text panel does so the preview displays the right glyphs).
  useEffect(() => {
    const id = 'subtitle-font-face'
    document.getElementById(id)?.remove()
    const key = style.subtitle_font
    if (!key || key.includes('system default')) return
    const fontCssName = key.split(' (')[0]
    const node = document.createElement('style')
    node.id = id
    node.textContent = `@font-face{font-family:'${fontCssName}';src:url('/api/v1/video/fonts/${encodeURIComponent(key)}/file') format('truetype');font-display:swap;}`
    document.head.appendChild(node)
    return () => { document.getElementById(id)?.remove() }
  }, [style.subtitle_font])

  const handleUpload = async (file: File) => {
    if (!storyId) {
      setWarning('Cần story_id (mở từ trang Story).')
      return
    }
    setUploading(true)
    setWarning(null)
    try {
      const fd = new FormData()
      fd.append('story_id', storyId)
      if (audioPath) fd.append('audio_path', audioPath)
      fd.append('file', file)
      const r = await axios.post<UploadResponse>('/api/v1/video/upload-srt', fd)
      setUploadInfo(r.data)
      setFilename(r.data.filename)

      // Pull raw text back to drive the live preview overlay.
      const c = await axios.get<{ content: string }>('/api/v1/video/srt-content',
        { params: { path: r.data.srt_path } })
      const segments = parseSRT(c.data.content)
      onSrtUploaded(r.data, segments)

      // Compute a sped-aware warning since BE only knows raw audio duration.
      // After speed-up the audio is shorter; SRT longer than that gets cut.
      const effectiveAudioDur = audioDuration > 0 && audioSpeed > 0
        ? audioDuration / audioSpeed
        : (r.data.audio_duration ?? 0) / Math.max(audioSpeed, 0.01)
      if (effectiveAudioDur > 0 && r.data.last_end > effectiveAudioDur + 0.5) {
        setWarning(
          `SRT dài ${r.data.last_end.toFixed(1)}s, vượt quá audio sau speed-up `
          + `(${effectiveAudioDur.toFixed(1)}s) — các dòng dư sẽ bị cắt.`
        )
      } else if (r.data.warning) {
        setWarning(r.data.warning)
      }
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || 'Upload thất bại'
      setWarning(msg)
      onSrtUploaded(null, null)
    } finally {
      setUploading(false)
    }
  }

  const handleClear = () => {
    setUploadInfo(null)
    setFilename(null)
    setWarning(null)
    onSrtUploaded(null, null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) handleUpload(f)
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    const f = e.dataTransfer.files?.[0]
    if (f) handleUpload(f)
  }

  // When the parent wipes srtPath (e.g. via "Reset story" in the page header),
  // sync local upload-state back to empty so the panel doesn't show a stale
  // filename or warning.
  useEffect(() => {
    if (srtPath === null) {
      setUploadInfo(null)
      setFilename(null)
      setWarning(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }, [srtPath])

  const inputCls = 'w-full px-2 py-1.5 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500'

  return (
    <div className="space-y-3">
      <div className="text-xs text-gray-600 leading-relaxed">
        Upload .SRT để in phụ đề trực tiếp lên video. Style + animation áp dụng cho toàn bộ file.
      </div>

      {/* Upload area */}
      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        className="border-2 border-dashed border-gray-300 rounded-md p-3 text-center bg-gray-50"
      >
        {srtPath ? (
          <div className="text-xs">
            <div className="font-mono break-all mb-1 text-green-700">{filename ?? srtPath.split(/[\\/]/).pop()}</div>
            {uploadInfo && (
              <div className="text-gray-500">
                {uploadInfo.segment_count} dòng · {uploadInfo.first_start.toFixed(1)}s → {uploadInfo.last_end.toFixed(1)}s
              </div>
            )}
            <button
              type="button"
              onClick={handleClear}
              className="mt-2 text-red-600 hover:text-red-700 underline text-xs"
            >Bỏ phụ đề</button>
          </div>
        ) : (
          <>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="px-3 py-1.5 bg-primary-500 hover:bg-primary-600 disabled:opacity-50 rounded text-xs text-white"
            >{uploading ? 'Đang upload…' : 'Chọn file SRT'}</button>
            <div className="text-[11px] text-gray-500 mt-1">hoặc kéo thả vào đây</div>
          </>
        )}
        <input
          ref={fileInputRef}
          type="file"
          accept=".srt"
          onChange={onFileChange}
          className="hidden"
        />
      </div>

      {warning && (
        <div className="text-xs text-yellow-800 bg-yellow-50 border border-yellow-200 rounded px-2 py-1.5">
          ⚠ {warning}
        </div>
      )}

      {/* Animation */}
      <Field label="Hiệu ứng">
        <select
          value={style.subtitle_animation}
          onChange={(e) => onChange({ subtitle_animation: e.target.value as SubtitleAnimation })}
          className={inputCls}
        >
          {(Object.keys(ANIMATION_LABELS) as SubtitleAnimation[]).map(a => (
            <option key={a} value={a}>{ANIMATION_LABELS[a]}</option>
          ))}
        </select>
      </Field>

      {/* Font */}
      <Field label="Font">
        <select
          value={style.subtitle_font}
          onChange={(e) => onChange({ subtitle_font: e.target.value })}
          className={inputCls}
        >
          {availableFonts.map(f => <option key={f} value={f}>{f}</option>)}
        </select>
      </Field>

      <div className="grid grid-cols-2 gap-2">
        <Field label={`Size: ${style.subtitle_font_size}px`}>
          <input
            type="range" min={16} max={200} step={2}
            value={style.subtitle_font_size}
            onChange={(e) => onChange({ subtitle_font_size: parseInt(e.target.value) })}
            className="w-full"
          />
        </Field>
        <Field label={`Độ mờ: ${Math.round(style.subtitle_opacity * 100)}%`}>
          <input
            type="range" min={0.1} max={1} step={0.05}
            value={style.subtitle_opacity}
            onChange={(e) => onChange({ subtitle_opacity: parseFloat(e.target.value) })}
            className="w-full"
          />
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Field label="Màu chữ">
          <input
            type="color"
            value={style.subtitle_color}
            onChange={(e) => onChange({ subtitle_color: e.target.value })}
            className="w-full h-8 rounded border cursor-pointer"
          />
        </Field>
        <Field label="Màu viền">
          <input
            type="color"
            value={style.subtitle_outline_color}
            onChange={(e) => onChange({ subtitle_outline_color: e.target.value })}
            className="w-full h-8 rounded border cursor-pointer"
          />
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Field label="Độ dày viền (px)">
          <input
            type="number" min={0} max={10}
            value={style.subtitle_outline_width}
            onChange={(e) => onChange({ subtitle_outline_width: parseInt(e.target.value) || 0 })}
            className={inputCls}
          />
        </Field>
        <Field label="Bóng đổ (px)">
          <input
            type="number" min={0} max={10}
            value={style.subtitle_shadow}
            onChange={(e) => onChange({ subtitle_shadow: parseInt(e.target.value) || 0 })}
            className={inputCls}
          />
        </Field>
      </div>

      <div className="flex items-center gap-3 text-xs text-gray-700">
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox" checked={style.subtitle_bold}
            onChange={(e) => onChange({ subtitle_bold: e.target.checked })}
          />
          <b>Bold</b>
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox" checked={style.subtitle_italic}
            onChange={(e) => onChange({ subtitle_italic: e.target.checked })}
          />
          <i>Italic</i>
        </label>
        <div className="flex-1" />
        <div className="flex border border-gray-300 rounded overflow-hidden">
          {(['left', 'center', 'right'] as const).map(a => (
            <button
              key={a}
              type="button"
              onClick={() => onChange({ subtitle_align: a })}
              className={`px-2 py-0.5 ${style.subtitle_align === a ? 'bg-primary-500 text-white' : 'bg-white text-gray-600 hover:bg-gray-100'}`}
              title={`Căn ${a}`}
            >{a === 'left' ? '⇤' : a === 'right' ? '⇥' : '⇔'}</button>
          ))}
        </div>
      </div>

      <div className="text-[11px] text-gray-500">
        Vị trí: X {Math.round(style.subtitle_x * 100)}% · Y {Math.round(style.subtitle_y * 100)}%
        <span className="ml-1 text-primary-500">(kéo phụ đề trên preview để chỉnh)</span>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs text-gray-600 mb-1">{label}</label>
      {children}
    </div>
  )
}
