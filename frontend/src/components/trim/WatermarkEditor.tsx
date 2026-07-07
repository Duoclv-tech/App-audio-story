import { useRef, useState } from 'react'
import type { CSSProperties, PointerEvent as ReactPointerEvent } from 'react'
import type { WatermarkParams, WatermarkPosition } from '../../services/trimApi'

interface Props {
  value: WatermarkParams
  onChange: (v: WatermarkParams) => void
  previewAspect?: number
}

const POSITIONS: { value: WatermarkPosition; label: string; title: string }[] = [
  { value: 'top-left', label: '', title: 'Trên trái' },
  { value: 'top-center', label: '', title: 'Trên giữa' },
  { value: 'top-right', label: '', title: 'Trên phải' },
  { value: 'middle-left', label: '', title: 'Giữa trái' },
  { value: 'center', label: '●', title: 'Chính giữa' },
  { value: 'middle-right', label: '', title: 'Giữa phải' },
  { value: 'bottom-left', label: '', title: 'Dưới trái' },
  { value: 'bottom-center', label: '', title: 'Dưới giữa' },
  { value: 'bottom-right', label: '', title: 'Dưới phải' },
]

export default function WatermarkEditor({ value, onChange, previewAspect = 16 / 9 }: Props) {
  const update = (patch: Partial<WatermarkParams>) => onChange({ ...value, ...patch })
  const isCustom = value.position === 'custom'

  return (
    <div className="space-y-4 border border-token rounded-lg p-4 bg-surface-2">
      <div>
        <label className="block text-sm text-dim mb-1">Nội dung watermark</label>
        <input
          type="text"
          maxLength={100}
          placeholder="© Kênh của bạn"
          value={value.text}
          onChange={(e) => update({ text: e.target.value })}
          className="w-full px-3 py-1.5 border rounded bg-surface"
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm text-dim mb-1">
            Cỡ chữ: <span className="font-mono">{value.font_size}px</span>
          </label>
          <input
            type="range"
            min={12}
            max={120}
            value={value.font_size}
            onChange={(e) => update({ font_size: parseInt(e.target.value, 10) })}
            className="w-full"
          />
        </div>

        <div>
          <label className="block text-sm text-dim mb-1">
            Độ mờ: <span className="font-mono">{Math.round(value.opacity * 100)}%</span>
          </label>
          <input
            type="range"
            min={10}
            max={100}
            value={Math.round(value.opacity * 100)}
            onChange={(e) => update({ opacity: parseInt(e.target.value, 10) / 100 })}
            className="w-full"
          />
        </div>

        <div>
          <label className="block text-sm text-dim mb-1">Màu chữ</label>
          <div className="flex gap-2">
            <input
              type="color"
              value={value.color}
              onChange={(e) => update({ color: e.target.value })}
              className="h-9 w-12 border rounded cursor-pointer bg-surface"
            />
            <input
              type="text"
              value={value.color}
              onChange={(e) => update({ color: e.target.value })}
              className="flex-1 px-2 py-1 border rounded font-mono text-sm bg-surface"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm text-dim mb-1">
            Khoảng cách lề: <span className="font-mono">{value.margin}px</span>
            {isCustom && <span className="text-faint"> (không dùng ở chế độ tự do)</span>}
          </label>
          <input
            type="range"
            min={0}
            max={120}
            value={value.margin}
            onChange={(e) => update({ margin: parseInt(e.target.value, 10) })}
            disabled={isCustom}
            className="w-full disabled:opacity-50"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
        <div>
          <label className="block text-sm text-dim mb-1">Vị trí</label>
          <div className="grid grid-cols-3 w-36 gap-1 border rounded p-1 bg-surface">
            {POSITIONS.map((p) => (
              <button
                key={p.value}
                type="button"
                onClick={() => update({ position: p.value })}
                title={p.title}
                className={`aspect-square rounded flex items-center justify-center text-base transition ${
                  value.position === p.value
                    ? 'bg-primary-600 text-white'
                    : 'bg-surface-3 hover:bg-gray-200 dark:hover:bg-gray-700 text-dim'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => update({ position: 'custom' })}
            className={`mt-2 w-36 text-xs px-2 py-1.5 border rounded transition ${
              isCustom
                ? 'bg-primary-600 text-white border-primary-600'
                : 'bg-surface hover:bg-surface-3 border-token'
            }`}
            title="Kéo watermark trong khung xem trước để đặt vị trí tự do"
          >
             Kéo tự do
          </button>
          {isCustom && (
            <p className="text-xs text-dim mt-1 font-mono">
              x: {(value.custom_x * 100).toFixed(1)}% · y: {(value.custom_y * 100).toFixed(1)}%
            </p>
          )}
        </div>

        <div>
          <label className="block text-sm text-dim mb-1">
            Xoay: <span className="font-mono">{value.rotation}°</span>
          </label>
          <input
            type="range"
            min={-180}
            max={180}
            value={value.rotation}
            onChange={(e) => update({ rotation: parseInt(e.target.value, 10) })}
            className="w-full"
          />
          <div className="flex gap-1 mt-1 flex-wrap">
            {[-90, -45, -15, 0, 15, 45, 90].map((a) => (
              <button
                key={a}
                type="button"
                onClick={() => update({ rotation: a })}
                className={`text-xs px-2 py-0.5 border rounded transition ${
                  value.rotation === a ? 'bg-primary-100 dark:bg-primary-500/20 border-primary-400 dark:border-primary-500/30' : 'hover:bg-surface-3'
                }`}
              >
                {a}°
              </button>
            ))}
          </div>
          {value.rotation !== 0 && (
            <p className="text-xs text-dim mt-1">
              Lưu ý: khi xoay, watermark quay quanh tâm khung hình nên vị trí có thể bị dịch so với neo đã chọn.
            </p>
          )}
        </div>
      </div>

      <div>
        <label className="flex items-center gap-2 text-sm text-dim mb-2">
          <input
            type="checkbox"
            checked={value.border_enabled}
            onChange={(e) => update({ border_enabled: e.target.checked })}
          />
          Viền chữ (dễ đọc trên nền sáng/tối)
        </label>
        {value.border_enabled && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pl-6">
            <div>
              <label className="block text-xs text-dim mb-1">Màu viền</label>
              <div className="flex gap-2">
                <input
                  type="color"
                  value={value.border_color}
                  onChange={(e) => update({ border_color: e.target.value })}
                  className="h-8 w-10 border rounded cursor-pointer bg-surface"
                />
                <input
                  type="text"
                  value={value.border_color}
                  onChange={(e) => update({ border_color: e.target.value })}
                  className="flex-1 px-2 py-1 border rounded font-mono text-xs bg-surface"
                />
              </div>
            </div>
            <div>
              <label className="block text-xs text-dim mb-1">
                Độ dày: <span className="font-mono">{value.border_width}px</span>
              </label>
              <input
                type="range"
                min={1}
                max={8}
                value={value.border_width}
                onChange={(e) => update({ border_width: parseInt(e.target.value, 10) })}
                className="w-full"
              />
            </div>
          </div>
        )}
      </div>

      <div>
        <div className="text-xs text-dim mb-1">
          Xem trước (xấp xỉ)
          {isCustom && (
            <span className="ml-2 text-primary-600 dark:text-primary-400">— kéo chữ để đặt vị trí</span>
          )}
        </div>
        <WatermarkPreview
          wm={value}
          aspect={previewAspect}
          onDrag={(cx, cy) => onChange({ ...value, position: 'custom', custom_x: cx, custom_y: cy })}
        />
      </div>
    </div>
  )
}

const PREVIEW_MAX_W = 640
const PREVIEW_MAX_H = 360

interface PreviewProps {
  wm: WatermarkParams
  aspect: number
  onDrag: (cx: number, cy: number) => void
}

function WatermarkPreview({ wm, aspect, onDrag }: PreviewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const textRef = useRef<HTMLDivElement>(null)
  const dragOffsetRef = useRef({ x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)

  const scale = 0.5
  const margin = wm.margin * scale
  const sizeByHeight = PREVIEW_MAX_W / aspect > PREVIEW_MAX_H
  const isCustom = wm.position === 'custom'

  const base: CSSProperties = {
    position: 'absolute',
    color: wm.color,
    opacity: wm.opacity,
    fontSize: `${Math.max(10, wm.font_size * scale)}px`,
    fontWeight: 700,
    whiteSpace: 'nowrap',
    userSelect: 'none',
    touchAction: 'none',
    cursor: isCustom ? (dragging ? 'grabbing' : 'grab') : 'default',
    pointerEvents: isCustom ? 'auto' : 'none',
  }

  const bw = wm.border_width
  const bc = wm.border_color
  if (wm.border_enabled && bw > 0) {
    base.textShadow = [
      `-${bw}px -${bw}px 0 ${bc}`,
      `${bw}px -${bw}px 0 ${bc}`,
      `-${bw}px ${bw}px 0 ${bc}`,
      `${bw}px ${bw}px 0 ${bc}`,
      `0 -${bw}px 0 ${bc}`,
      `0 ${bw}px 0 ${bc}`,
      `-${bw}px 0 0 ${bc}`,
      `${bw}px 0 0 ${bc}`,
    ].join(',')
  }

  const rot = wm.rotation
  const rotExpr = rot ? `rotate(${rot}deg)` : ''

  const presetStyles: Record<Exclude<WatermarkPosition, 'custom'>, CSSProperties> = {
    'top-left': { top: margin, left: margin, transform: rotExpr, transformOrigin: 'top left' },
    'top-center': { top: margin, left: '50%', transform: `translateX(-50%) ${rotExpr}`, transformOrigin: 'top center' },
    'top-right': { top: margin, right: margin, transform: rotExpr, transformOrigin: 'top right' },
    'middle-left': { top: '50%', left: margin, transform: `translateY(-50%) ${rotExpr}`, transformOrigin: 'center left' },
    'center': { top: '50%', left: '50%', transform: `translate(-50%,-50%) ${rotExpr}`, transformOrigin: 'center' },
    'middle-right': { top: '50%', right: margin, transform: `translateY(-50%) ${rotExpr}`, transformOrigin: 'center right' },
    'bottom-left': { bottom: margin, left: margin, transform: rotExpr, transformOrigin: 'bottom left' },
    'bottom-center': { bottom: margin, left: '50%', transform: `translateX(-50%) ${rotExpr}`, transformOrigin: 'bottom center' },
    'bottom-right': { bottom: margin, right: margin, transform: rotExpr, transformOrigin: 'bottom right' },
  }

  // Match FFmpeg semantics `x=(w-text_w)*cx`: element's right edge touches parent's
  // right edge when cx=1, regardless of text width.
  const customTranslate = `translate(${-wm.custom_x * 100}%, ${-wm.custom_y * 100}%)`
  const customStyle: CSSProperties = {
    left: `${wm.custom_x * 100}%`,
    top: `${wm.custom_y * 100}%`,
    transform: rotExpr ? `${customTranslate} ${rotExpr}` : customTranslate,
    transformOrigin: 'top left',
  }

  const posStyle = isCustom ? customStyle : presetStyles[wm.position as Exclude<WatermarkPosition, 'custom'>]

  const handlePointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!isCustom) return
    e.preventDefault()
    const textRect = textRef.current!.getBoundingClientRect()
    dragOffsetRef.current = {
      x: e.clientX - textRect.left,
      y: e.clientY - textRect.top,
    }
    setDragging(true)
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }

  const handlePointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragging || !containerRef.current || !textRef.current) return
    const cRect = containerRef.current.getBoundingClientRect()
    // offsetWidth/Height give pre-transform dimensions (ignore rotation bbox expansion)
    const textW = textRef.current.offsetWidth
    const textH = textRef.current.offsetHeight
    let newLeft = e.clientX - cRect.left - dragOffsetRef.current.x
    let newTop = e.clientY - cRect.top - dragOffsetRef.current.y
    newLeft = Math.max(0, Math.min(cRect.width - textW, newLeft))
    newTop = Math.max(0, Math.min(cRect.height - textH, newTop))
    const spanX = cRect.width - textW
    const spanY = cRect.height - textH
    const cx = spanX > 0 ? newLeft / spanX : 0
    const cy = spanY > 0 ? newTop / spanY : 0
    onDrag(cx, cy)
  }

  const handlePointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragging) return
    setDragging(false)
    ;(e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId)
  }

  return (
    <div className="flex justify-center">
      <div
        ref={containerRef}
        className={`relative bg-gradient-to-br from-gray-700 to-gray-900 rounded overflow-hidden ${
          isCustom ? 'ring-2 ring-primary-400' : ''
        }`}
        style={{
          aspectRatio: `${aspect}`,
          ...(sizeByHeight
            ? { height: PREVIEW_MAX_H, width: 'auto' }
            : { width: '100%', maxWidth: PREVIEW_MAX_W, height: 'auto' }),
          maxWidth: '100%',
        }}
      >
        <div
          className="absolute inset-0 opacity-20"
          style={{
            backgroundImage:
              'repeating-linear-gradient(45deg, #fff 0, #fff 1px, transparent 1px, transparent 18px)',
          }}
        />
        {wm.text && (
          <div
            ref={textRef}
            style={{ ...base, ...posStyle }}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerUp}
          >
            {wm.text}
          </div>
        )}
      </div>
    </div>
  )
}
