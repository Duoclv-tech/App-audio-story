import { useEffect, useRef, useState } from 'react'
import {
  SubtitleAnimation,
  SubtitleSegment,
  SubtitleStyle,
  findActiveSegment,
} from './srt'

interface OverlayProps {
  segments: SubtitleSegment[] | null
  style: SubtitleStyle
  // Source-of-truth for current playback time. The overlay polls this via rAF
  // for sub-frame smoothness (timeupdate fires only ~4 Hz, too slow for the
  // typewriter effect). Falls back to `currentTime` prop if ref is null.
  audioRef?: React.RefObject<HTMLAudioElement | null>
  currentTime?: number
  // Preview frame size in CSS px and the target output width — used to scale
  // the on-screen font size (and convert drag deltas) so what you see matches
  // the burned-in result.
  previewFrameW: number
  previewFrameH?: number
  outputW: number
  // Direct-manipulation hooks. When provided the subtitle becomes grabbable:
  // click to select, drag the text to move, drag the corner to change font
  // size, drag a side edge to change the wrap-box width (forces line breaks).
  selected?: boolean
  onSelect?: () => void
  onMove?: (x: number, y: number) => void        // 0..1 anchor within frame
  onResizeFont?: (fontSize: number) => void       // output px (16..200)
  onResizeWidth?: (maxWidth: number) => void       // 0..1 fraction of frame
}

// Strip the trailing " (descriptor)" Be Vietnam Pro etc. ship in their key.
function fontFamilyFromKey(key: string): string {
  return key.split(' (')[0]
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * Math.max(0, Math.min(1, t))
}

interface AnimState {
  opacity: number
  scaleX: number
  scaleY: number
  translateY: number  // px (in preview-frame units)
  charsToShow: number
}

function computeAnimState(
  animation: SubtitleAnimation,
  tInSeg: number,
  segDuration: number,
  textLen: number,
): AnimState {
  const base: AnimState = {
    opacity: 1, scaleX: 1, scaleY: 1, translateY: 0, charsToShow: textLen,
  }
  if (animation === 'none') return base

  if (animation === 'fade') {
    const inOp = lerp(0, 1, tInSeg / 0.3)
    const outOp = lerp(0, 1, (segDuration - tInSeg) / 0.3)
    base.opacity = Math.max(0, Math.min(inOp, outOp))
    return base
  }
  if (animation === 'pop') {
    if (tInSeg < 0.25) {
      const k = tInSeg / 0.25
      base.scaleX = base.scaleY = lerp(0.4, 1.0, k)
    }
    const inOp = lerp(0, 1, tInSeg / 0.15)
    const outOp = lerp(0, 1, (segDuration - tInSeg) / 0.2)
    base.opacity = Math.max(0, Math.min(inOp, outOp))
    return base
  }
  if (animation === 'slide_up') {
    if (tInSeg < 0.3) {
      base.translateY = lerp(60, 0, tInSeg / 0.3)
      base.opacity = lerp(0, 1, tInSeg / 0.2)
    }
    return base
  }
  if (animation === 'typewriter') {
    base.charsToShow = Math.max(1, Math.floor(tInSeg / 0.05))
    return base
  }
  return base
}

export function SubtitleOverlay({
  segments, style, audioRef, currentTime,
  previewFrameW, previewFrameH, outputW,
  selected, onSelect, onMove, onResizeFont, onResizeWidth,
}: OverlayProps) {
  // Local ticker — refreshed via rAF whenever audio is playing, so we can
  // recompute animation state at ~display refresh without dragging the parent
  // along. When paused the audio.currentTime stops changing so the rAF still
  // fires but renders are cheap.
  const [, forceRender] = useState(0)
  const rafRef = useRef<number>(0)

  useEffect(() => {
    let running = true
    const tick = () => {
      if (!running) return
      forceRender(n => (n + 1) & 0xffff)
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => {
      running = false
      cancelAnimationFrame(rafRef.current)
    }
  }, [])

  if (!segments || segments.length === 0) return null

  const interactive = !!(onMove || onSelect)

  const t = audioRef?.current
    ? audioRef.current.currentTime
    : (currentTime ?? 0)

  const seg = findActiveSegment(segments, t)
  // Between segments (or paused before the first line) there's no active text.
  // For pure display we render nothing; while editing we keep a dim guide (the
  // first line) so the box stays visible and grabbable for positioning.
  if (!seg && !interactive) return null

  const anim = seg
    ? computeAnimState(style.subtitle_animation, t - seg.start, seg.end - seg.start, seg.text.length)
    : { opacity: 0.4, scaleX: 1, scaleY: 1, translateY: 0, charsToShow: 0 }

  // Scale font size from output px to preview px so on-screen size mirrors the
  // burned-in result.
  const scale = outputW > 0 ? previewFrameW / outputW : 1
  const fontPx = Math.max(8, Math.round(style.subtitle_font_size * scale))
  const outlinePx = Math.max(0, Math.round(style.subtitle_outline_width * scale))
  const frameH = previewFrameH && previewFrameH > 0 ? previewFrameH : previewFrameW

  // Build text-shadow for outline (4 directions, layered for thickness).
  const stroke = (px: number, color: string): string => {
    if (px <= 0) return 'none'
    const offsets: string[] = []
    const steps = Math.max(2, Math.ceil(px))
    for (let i = -steps; i <= steps; i++) {
      for (let j = -steps; j <= steps; j++) {
        if (i === 0 && j === 0) continue
        if (i * i + j * j > steps * steps + 1) continue
        offsets.push(`${i}px ${j}px 0 ${color}`)
      }
    }
    return offsets.join(',')
  }
  // ASS BorderStyle=1 also draws a drop shadow (BackColour ≈ 50% black),
  // offset down-right by the Shadow value. Mirror it so the preview matches.
  const shadowPx = Math.max(0, Math.round(style.subtitle_shadow * scale))
  const outlineShadow = stroke(outlinePx, style.subtitle_outline_color)
  const dropShadow = shadowPx > 0 ? `${shadowPx}px ${shadowPx}px 0 rgba(0,0,0,0.5)` : ''
  const textShadow = [outlineShadow === 'none' ? '' : outlineShadow, dropShadow]
    .filter(Boolean)
    .join(',') || 'none'

  // Anchor: ASS \an4/5/6 = middle-left/center/right. Mirror with translate.
  const tx = style.subtitle_align === 'left' ? '0%'
    : style.subtitle_align === 'right' ? '-100%'
    : '-50%'

  const text = !seg
    ? (segments[0]?.text ?? '')
    : style.subtitle_animation === 'typewriter'
      ? seg.text.slice(0, anim.charsToShow)
      : seg.text

  const fontKey = style.subtitle_font
  const fontFamily = fontKey.includes('system default')
    ? 'Arial, sans-serif'
    : `'${fontFamilyFromKey(fontKey)}', Arial, sans-serif`

  // Wrap-box width in preview px. The browser wraps the text within this; the
  // backend re-wraps to the same fraction of the output width so breaks match.
  const maxWidthFrac = Math.max(0.05, Math.min(1, style.subtitle_max_width ?? 1))
  const boxWidthPx = Math.max(24, maxWidthFrac * previewFrameW)

  // Shared drag lifecycle (mouse). Delta-based so no grab-snap; converts px to
  // fractions/output-px using the known preview/output sizes (no frame rect).
  const startDrag = (
    e: React.MouseEvent,
    onMoveDelta: (dx: number, dy: number) => void,
  ) => {
    e.preventDefault()
    e.stopPropagation()
    const startX = e.clientX
    const startY = e.clientY
    const move = (ev: MouseEvent) => onMoveDelta(ev.clientX - startX, ev.clientY - startY)
    const up = () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }

  const HANDLE = '#C67E15'
  const handleBase: React.CSSProperties = {
    position: 'absolute',
    background: HANDLE,
    border: '2px solid white',
    borderRadius: 8,
    zIndex: 8,
    pointerEvents: 'auto',
  }

  return (
    <div
      style={{
        position: 'absolute',
        left: `${style.subtitle_x * 100}%`,
        top: `${style.subtitle_y * 100}%`,
        transform: `translate(${tx}, -50%)`,
        width: boxWidthPx,
        // The box itself is click-through; only the text + handles grab, so a
        // wide wrap-box doesn't block dragging clips behind the empty margins.
        pointerEvents: 'none',
        userSelect: 'none',
        touchAction: 'none',
        outline: selected ? `2px dashed ${HANDLE}` : 'none',
        outlineOffset: 4,
        zIndex: 6,
      }}
    >
      <div
        onMouseDown={interactive ? (e) => {
          onSelect?.()
          if (!onMove) return
          const ox = style.subtitle_x
          const oy = style.subtitle_y
          startDrag(e, (dx, dy) => {
            const nx = Math.max(0, Math.min(1, ox + dx / previewFrameW))
            const ny = Math.max(0, Math.min(1, oy + dy / frameH))
            onMove(nx, ny)
          })
        } : undefined}
        style={{
          width: '100%',
          transform: `translateY(${anim.translateY}px) scale(${anim.scaleX}, ${anim.scaleY})`,
          transformOrigin: 'center center',
          opacity: anim.opacity * style.subtitle_opacity,
          fontFamily,
          fontSize: fontPx,
          color: style.subtitle_color,
          textShadow,
          fontWeight: style.subtitle_bold ? 700 : 400,
          fontStyle: style.subtitle_italic ? 'italic' : 'normal',
          textAlign: style.subtitle_align as any,
          lineHeight: 1.2,
          whiteSpace: 'pre-line',
          overflowWrap: 'break-word',
          wordBreak: 'break-word',
          pointerEvents: interactive ? 'auto' : 'none',
          cursor: onMove ? 'move' : 'default',
          userSelect: 'none',
          textRendering: 'geometricPrecision',
          padding: '2px 6px',
        }}
      >
        {text}
      </div>

      {selected && onResizeWidth && (
        <>
          {/* Left / right edge handles — drag to change the wrap-box width so
              the text breaks into more or fewer lines. */}
          {(['left', 'right'] as const).map(side => (
            <div
              key={side}
              onMouseDown={(e) => {
                const orig = maxWidthFrac
                const sign = side === 'right' ? 1 : -1
                startDrag(e, (dx) => {
                  // Symmetric about the anchor → moving one edge grows both.
                  const next = orig + sign * 2 * (dx / previewFrameW)
                  onResizeWidth(Math.max(0.1, Math.min(1, next)))
                })
              }}
              title="Kéo để đổi bề rộng (xuống dòng)"
              style={{
                ...handleBase,
                top: '50%',
                [side]: -7,
                marginTop: -7,
                width: 14, height: 14,
                cursor: 'ew-resize',
              }}
            />
          ))}
        </>
      )}

      {selected && onResizeFont && (
        <div
          onMouseDown={(e) => {
            const orig = style.subtitle_font_size
            startDrag(e, (dx, dy) => {
              // Down-right grows; convert avg preview-px delta to output px.
              const deltaOut = ((dx + dy) / 2) / (scale || 1)
              onResizeFont(Math.max(16, Math.min(200, Math.round(orig + deltaOut))))
            })
          }}
          title="Kéo để đổi cỡ chữ"
          style={{
            ...handleBase,
            right: -8, bottom: -8,
            width: 16, height: 16,
            cursor: 'nwse-resize',
          }}
        />
      )}
    </div>
  )
}
