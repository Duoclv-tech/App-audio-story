import { forwardRef, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import type { WatermarkParams, WatermarkPosition } from '../../services/trimApi'

interface Props {
  src: string
  /** Target output aspect ratio (w/h). Falls back to source ratio for "Gốc". */
  outputAspect?: number
  /** 'original' | '16:9' | '9:16' | ... — when 'original' no crop/letterbox is applied. */
  aspectMode?: string
  /** 'crop' | 'letterbox' | 'blur' — how the source fits the target aspect. */
  cropMode?: string
  speed?: number
  mute?: boolean
  volume?: number
  /** Live watermark overlay — mirrors what the export bakes in. */
  watermark?: WatermarkParams
  /**
   * Height (px) of the final output canvas. `font_size`/`margin` are expressed
   * in output pixels, so the overlay scales by (boxHeightPx / outputHeight).
   */
  outputHeight?: number
}

const VideoPreview = forwardRef<HTMLVideoElement, Props>(
  (
    {
      src,
      outputAspect = 16 / 9,
      aspectMode = 'original',
      cropMode = 'crop',
      speed = 1.0,
      mute = false,
      volume = 1.0,
      watermark,
      outputHeight = 1080,
    },
    ref,
  ) => {
    const [currentTime, setCurrentTime] = useState(0)
    const bgRef = useRef<HTMLVideoElement>(null)
    const boxRef = useRef<HTMLDivElement>(null)
    const [boxHeight, setBoxHeight] = useState(0)

    const reshaping = aspectMode !== 'original'
    const showBlurBg = reshaping && cropMode === 'blur'
    // crop → fill & clip; letterbox/blur/original → fit inside (black or blurred bars)
    const objectFit: 'cover' | 'contain' =
      reshaping && cropMode === 'crop' ? 'cover' : 'contain'

    const getEl = () => (ref as React.RefObject<HTMLVideoElement>).current

    // Track the rendered box height so the watermark can scale from output px.
    // The box always carries aspectRatio=outputAspect, so it IS the output frame
    // (bars included) — a uniform boxHeight/outputHeight maps px 1:1 to the export.
    useLayoutEffect(() => {
      const box = boxRef.current
      if (!box) return
      const measure = () => setBoxHeight(box.getBoundingClientRect().height)
      measure()
      const ro = new ResizeObserver(measure)
      ro.observe(box)
      return () => ro.disconnect()
    }, [outputAspect])

    // Track playhead for the timecode badge
    useEffect(() => {
      const el = getEl()
      if (!el) return
      const handler = () => setCurrentTime(el.currentTime)
      el.addEventListener('timeupdate', handler)
      return () => el.removeEventListener('timeupdate', handler)
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ref, src])

    // Reflect playback options live so the preview matches the export
    useEffect(() => {
      const el = getEl()
      if (el) el.playbackRate = speed > 0 ? speed : 1.0
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ref, src, speed])

    useEffect(() => {
      const el = getEl()
      if (el) el.muted = mute
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ref, src, mute])

    useEffect(() => {
      const el = getEl()
      // <video>.volume is capped at 1.0; >100% boost can't be previewed natively.
      if (el) el.volume = Math.max(0, Math.min(1, volume))
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ref, src, volume])

    // Keep the blurred background layer in sync with the main video
    useEffect(() => {
      const main = getEl()
      const bg = bgRef.current
      if (!main || !bg || !showBlurBg) return
      const sync = () => {
        if (Math.abs(bg.currentTime - main.currentTime) > 0.3) {
          bg.currentTime = main.currentTime
        }
      }
      const onPlay = () => { bg.play().catch(() => {}) }
      const onPause = () => bg.pause()
      const onRate = () => { bg.playbackRate = main.playbackRate }
      main.addEventListener('timeupdate', sync)
      main.addEventListener('seeked', sync)
      main.addEventListener('play', onPlay)
      main.addEventListener('pause', onPause)
      main.addEventListener('ratechange', onRate)
      bg.playbackRate = main.playbackRate
      if (!main.paused) bg.play().catch(() => {})
      return () => {
        main.removeEventListener('timeupdate', sync)
        main.removeEventListener('seeked', sync)
        main.removeEventListener('play', onPlay)
        main.removeEventListener('pause', onPause)
        main.removeEventListener('ratechange', onRate)
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ref, src, showBlurBg])

    const fmt = (s: number) => {
      const h = Math.floor(s / 3600)
      const m = Math.floor((s % 3600) / 60)
      const sec = Math.floor(s % 60)
      return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${sec
        .toString()
        .padStart(2, '0')}`
    }

    // Portrait targets are sized by height so they don't blow up the layout;
    // landscape/square fill the available width.
    const isPortrait = outputAspect < 1
    const boxStyle: React.CSSProperties = isPortrait
      ? { aspectRatio: String(outputAspect), height: 'min(70vh, 640px)' }
      : { aspectRatio: String(outputAspect), width: '100%', maxHeight: '70vh' }

    const wmActive = !!(watermark?.enabled && watermark.text.trim())

    return (
      <div className="flex justify-center">
        <div
          ref={boxRef}
          className="relative rounded-lg overflow-hidden bg-black"
          style={boxStyle}
        >
          {showBlurBg && (
            <video
              ref={bgRef}
              src={src}
              muted
              playsInline
              className="absolute inset-0 w-full h-full"
              style={{ objectFit: 'cover', filter: 'blur(20px)', transform: 'scale(1.1)' }}
            />
          )}
          <video
            ref={ref}
            src={src}
            controls
            className="absolute inset-0 w-full h-full"
            style={{ objectFit }}
          />
          {wmActive && boxHeight > 0 && (
            <WatermarkOverlay
              wm={watermark!}
              scale={boxHeight / (outputHeight || 1080)}
            />
          )}
          <div className="absolute top-2 right-2 bg-black/60 text-white text-xs font-mono px-2 py-1 rounded pointer-events-none">
            {fmt(currentTime)}
          </div>
        </div>
      </div>
    )
  },
)

/**
 * Non-interactive watermark overlay that mirrors the ffmpeg drawtext the export
 * bakes in (position map, custom (w-text_w)*cx anchoring, margin, rotation,
 * border, opacity). `scale` converts output px → preview px. Kept in sync with
 * backend `_drawtext_expr` / `_WM_POSITION_MAP` in video_trimmer.py and with
 * the config-panel preview in WatermarkEditor.tsx.
 */
function WatermarkOverlay({ wm, scale }: { wm: WatermarkParams; scale: number }) {
  const margin = wm.margin * scale
  const isCustom = wm.position === 'custom'

  const base: CSSProperties = {
    position: 'absolute',
    color: wm.color,
    opacity: wm.opacity,
    // No min floor: the overlay must scale 1:1 with the export (boxHeight /
    // outputHeight). A floor would inflate the watermark on a short preview box
    // and mislead sizing/positioning vs the baked-in result.
    fontSize: `${wm.font_size * scale}px`,
    fontWeight: 700,
    // Match the export font so text width (which anchors center/right/custom
    // positions) lines up with ffmpeg. The trim export uses
    // paths.default_font_path(); on Windows that resolves to arialbd.ttf, the
    // very same file the browser loads for `Arial` @ weight 700 — so glyph
    // advances (and thus text_w) match. `fontKerning: none` mirrors ffmpeg
    // drawtext, which does not apply kerning.
    // NOTE: if a bundled DejaVuSans-Bold.ttf is ever shipped (see
    // DESKTOP_APP_PLAN.md TODO), default_font_path() would prefer it — then
    // this stack must embed DejaVu via @font-face to stay accurate.
    fontFamily: 'Arial, "Helvetica Neue", Helvetica, sans-serif',
    fontKerning: 'none',
    whiteSpace: 'nowrap',
    userSelect: 'none',
    pointerEvents: 'none', // never block the native video controls
  }

  const bw = wm.border_width
  const bc = wm.border_color
  if (wm.border_enabled && bw > 0) {
    const b = bw * scale
    base.textShadow = [
      `-${b}px -${b}px 0 ${bc}`,
      `${b}px -${b}px 0 ${bc}`,
      `-${b}px ${b}px 0 ${bc}`,
      `${b}px ${b}px 0 ${bc}`,
      `0 -${b}px 0 ${bc}`,
      `0 ${b}px 0 ${bc}`,
      `-${b}px 0 0 ${bc}`,
      `${b}px 0 0 ${bc}`,
    ].join(',')
  }

  // Anchor placement only — NO rotation here. The export draws the text at this
  // anchor on a full canvas-sized layer, then rotates that whole layer about the
  // frame center; we mirror that by rotating a full-box wrapper below (not the
  // text about its own anchor).
  const presetStyles: Record<Exclude<WatermarkPosition, 'custom'>, CSSProperties> = {
    'top-left': { top: margin, left: margin },
    'top-center': { top: margin, left: '50%', transform: 'translateX(-50%)' },
    'top-right': { top: margin, right: margin },
    'middle-left': { top: '50%', left: margin, transform: 'translateY(-50%)' },
    'center': { top: '50%', left: '50%', transform: 'translate(-50%,-50%)' },
    'middle-right': { top: '50%', right: margin, transform: 'translateY(-50%)' },
    'bottom-left': { bottom: margin, left: margin },
    'bottom-center': { bottom: margin, left: '50%', transform: 'translateX(-50%)' },
    'bottom-right': { bottom: margin, right: margin },
  }

  // Mirror FFmpeg `x=(w-text_w)*cx`: element's right edge touches the frame's
  // right edge at cx=1, regardless of text width.
  const customStyle: CSSProperties = {
    left: `${wm.custom_x * 100}%`,
    top: `${wm.custom_y * 100}%`,
    transform: `translate(${-wm.custom_x * 100}%, ${-wm.custom_y * 100}%)`,
  }

  const posStyle = isCustom
    ? customStyle
    : presetStyles[wm.position as Exclude<WatermarkPosition, 'custom'>]

  const text = <span style={{ ...base, ...posStyle }}>{wm.text}</span>
  if (!wm.rotation) return text
  // Rotate the whole frame-sized layer about its center, exactly like the
  // export's `rotate=` on the canvas layer.
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        transform: `rotate(${wm.rotation}deg)`,
        transformOrigin: 'center',
        pointerEvents: 'none',
      }}
    >
      {text}
    </div>
  )
}

VideoPreview.displayName = 'VideoPreview'
export default VideoPreview
