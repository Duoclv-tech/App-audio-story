import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { SubtitleAnimation, SubtitleStyle } from '../subtitle/srt'
import { uploadTrimSrt, type TrimSrtUploadResponse } from '../../services/trimApi'
import { hasNativeDialogs } from '../../services/nativeDialog'

interface Props {
  /** trim file_id the SRT is scoped to (trim_temp/<file_id>/subtitle.srt). */
  fileId: string
  style: SubtitleStyle
  onChange: (patch: Partial<SubtitleStyle>) => void
  srtPath: string | null
  onSrtUploaded: (info: TrimSrtUploadResponse | null) => void
  availableFonts: string[]
}

const ANIMATION_LABELS: Record<SubtitleAnimation, string> = {
  none: 'Không hiệu ứng',
  fade: 'Fade in/out',
  pop: 'Pop (bật vào)',
  slide_up: 'Slide up (trượt từ dưới)',
  typewriter: 'Typewriter (gõ chữ)',
}

/**
 * Standalone SRT panel for the Cắt video tab. Mirrors the story-pipeline
 * SubtitlePanel's controls but is decoupled from story_id/audio_path: it uploads
 * against a trim file_id and the burned subtitle timings are re-based to the cut
 * segments server-side.
 */
export default function SubtitleTrimPanel({
  fileId, style, onChange, srtPath, onSrtUploaded, availableFonts,
}: Props) {
  const [uploading, setUploading] = useState(false)
  const [info, setInfo] = useState<TrimSrtUploadResponse | null>(null)
  const [filename, setFilename] = useState<string | null>(null)
  const [warning, setWarning] = useState<string | null>(null)
  const [savingSample, setSavingSample] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  // Inject @font-face for the chosen subtitle font so the label preview renders
  // with the right glyphs (unique id so it doesn't clash with SubtitlePanel).
  useEffect(() => {
    const id = 'trim-subtitle-font-face'
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

  // Parent wiped the SRT (e.g. reset / changed video) — clear local state.
  useEffect(() => {
    if (srtPath === null) {
      setInfo(null)
      setFilename(null)
      setWarning(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }, [srtPath])

  const handleUpload = async (file: File) => {
    if (!fileId) {
      setWarning('Cần upload/nạp video trước khi thêm phụ đề.')
      return
    }
    if (!file.name.toLowerCase().endsWith('.srt')) {
      setWarning('Chỉ nhận file .srt')
      return
    }
    setUploading(true)
    setWarning(null)
    try {
      const data = await uploadTrimSrt(fileId, file)
      setInfo(data)
      setFilename(data.filename)
      onSrtUploaded(data)
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || 'Upload thất bại'
      setWarning(msg)
      onSrtUploaded(null)
    } finally {
      setUploading(false)
    }
  }

  const handleClear = () => {
    setInfo(null)
    setFilename(null)
    setWarning(null)
    onSrtUploaded(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handleDownloadSample = async () => {
    if (hasNativeDialogs()) {
      setSavingSample(true)
      try {
        await axios.post('/api/v1/video/sample-srt/save')
        setWarning('Đã lưu phu-de-mau.srt vào thư mục Downloads (đã mở Explorer).')
      } catch (e: any) {
        setWarning(e?.response?.data?.detail || 'Không lưu được file mẫu.')
      } finally {
        setSavingSample(false)
      }
    } else {
      const a = document.createElement('a')
      a.href = '/api/v1/video/sample-srt'
      a.download = 'phu-de-mau.srt'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
    }
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

  const inputCls = 'w-full px-2 py-1.5 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500'

  return (
    <div className="space-y-3">
      <div className="text-xs text-dim leading-relaxed">
        Upload .SRT để in phụ đề trực tiếp lên <b>clip đã cắt</b>. Thời gian phụ đề được
        canh lại theo đoạn cắt (và tốc độ) nên khớp với clip ngắn.
      </div>

      {/* Upload area */}
      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        className="border-2 border-dashed border-token rounded-md p-3 text-center bg-surface-2"
      >
        {srtPath ? (
          <div className="text-xs">
            <div className="font-mono break-all mb-1 text-green-700 dark:text-green-400">
              {filename ?? srtPath.split(/[\\/]/).pop()}
            </div>
            {info && (
              <div className="text-dim">
                {info.segment_count} dòng · {info.first_start.toFixed(1)}s → {info.last_end.toFixed(1)}s
              </div>
            )}
            <button
              type="button"
              onClick={handleClear}
              className="mt-2 text-red-600 dark:text-red-400 hover:text-red-700 underline text-xs"
            >Bỏ phụ đề</button>
          </div>
        ) : (
          <>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading || !fileId}
              className="px-3 py-1.5 bg-primary-500 hover:bg-primary-600 disabled:opacity-50 rounded text-xs text-white"
            >{uploading ? 'Đang upload…' : 'Chọn file SRT'}</button>
            <div className="text-[11px] text-dim mt-1">hoặc kéo thả vào đây</div>
            <button
              type="button"
              onClick={handleDownloadSample}
              disabled={savingSample}
              className="mt-2 text-[11px] text-primary-500 dark:text-primary-400 hover:underline disabled:opacity-50"
            >{savingSample ? 'Đang lưu…' : '⬇ Tải SRT mẫu'}</button>
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
        <div className="text-xs text-yellow-800 dark:text-yellow-300 bg-yellow-50 dark:bg-yellow-500/10 border border-yellow-200 dark:border-yellow-500/30 rounded px-2 py-1.5">
          ⚠ {warning}
        </div>
      )}

      {srtPath && (
        <>
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

          <div className="flex items-center gap-3 text-xs text-dim">
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
            <div className="flex border border-token rounded overflow-hidden">
              {(['left', 'center', 'right'] as const).map(a => (
                <button
                  key={a}
                  type="button"
                  onClick={() => onChange({ subtitle_align: a })}
                  className={`px-2 py-0.5 ${style.subtitle_align === a ? 'bg-primary-500 text-white' : 'bg-surface text-dim hover:bg-surface-3'}`}
                  title={`Căn ${a}`}
                >{a === 'left' ? '⬅' : a === 'right' ? '➡' : '⬍'}</button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2">
            <Field label={`Vị trí X: ${Math.round(style.subtitle_x * 100)}%`}>
              <input
                type="range" min={0} max={1} step={0.01}
                value={style.subtitle_x}
                onChange={(e) => onChange({ subtitle_x: parseFloat(e.target.value) })}
                className="w-full"
              />
            </Field>
            <Field label={`Vị trí Y: ${Math.round(style.subtitle_y * 100)}%`}>
              <input
                type="range" min={0} max={1} step={0.01}
                value={style.subtitle_y}
                onChange={(e) => onChange({ subtitle_y: parseFloat(e.target.value) })}
                className="w-full"
              />
            </Field>
            <Field label={`Rộng: ${Math.round(style.subtitle_max_width * 100)}%`}>
              <input
                type="range" min={0.2} max={1} step={0.05}
                value={style.subtitle_max_width}
                onChange={(e) => onChange({ subtitle_max_width: parseFloat(e.target.value) })}
                className="w-full"
              />
            </Field>
          </div>
        </>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs text-dim mb-1">{label}</label>
      {children}
    </div>
  )
}
