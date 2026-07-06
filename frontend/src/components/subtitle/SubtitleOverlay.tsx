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
  // Preview frame width in CSS px and the target output width — used to scale
  // the on-screen font size so what you see matches the burned-in result.
  previewFrameW: number
  outputW: number
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
  segments, style, audioRef, currentTime, previewFrameW, outputW,
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

  const t = audioRef?.current
    ? audioRef.current.currentTime
    : (currentTime ?? 0)

  const seg = findActiveSegment(segments, t)
  if (!seg) return null

  const tInSeg = t - seg.start
  const segDuration = seg.end - seg.start
  const anim = computeAnimState(style.subtitle_animation, tInSeg, segDuration, seg.text.length)

  // Scale font size from output px to preview px so on-screen size mirrors the
  // burned-in result.
  const scale = outputW > 0 ? previewFrameW / outputW : 1
  const fontPx = Math.max(8, Math.round(style.subtitle_font_size * scale))
  const outlinePx = Math.max(0, Math.round(style.subtitle_outline_width * scale))

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
  const textShadow = stroke(outlinePx, style.subtitle_outline_color)

  // Anchor: ASS \an4/5/6 = middle-left/center/right. Mirror with translate.
  const tx = style.subtitle_align === 'left' ? '0%'
    : style.subtitle_align === 'right' ? '-100%'
    : '-50%'

  const text = style.subtitle_animation === 'typewriter'
    ? seg.text.slice(0, anim.charsToShow)
    : seg.text

  const fontKey = style.subtitle_font
  const fontFamily = fontKey.includes('system default')
    ? 'Arial, sans-serif'
    : `'${fontFamilyFromKey(fontKey)}', Arial, sans-serif`

  return (
    <div
      style={{
        position: 'absolute',
        left: `${style.subtitle_x * 100}%`,
        top: `${style.subtitle_y * 100}%`,
        transform: `translate(${tx}, -50%) translateY(${anim.translateY}px) scale(${anim.scaleX}, ${anim.scaleY})`,
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
        pointerEvents: 'none',
        userSelect: 'none',
        textRendering: 'geometricPrecision',
        // Outline preview hint (subtle border; doesn't affect the burned output).
        padding: '2px 6px',
      }}
    >
      {text}
    </div>
  )
}
