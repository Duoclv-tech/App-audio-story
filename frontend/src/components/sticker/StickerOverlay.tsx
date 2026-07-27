import { useEffect, useRef, useState } from 'react'
import { Sticker, stickerFileUrl } from './sticker'

interface OverlayProps {
  stickers: Sticker[]
  audioRef?: React.RefObject<HTMLAudioElement | null>
  currentTime?: number
  previewFrameW: number
  previewFrameH: number
  outputW: number
  outputH: number
  // When set, this sticker's id is rendered with a selection ring + drag handles.
  selectedId?: string | null
  onSelect?: (id: string) => void
  onDrag?: (id: string, x: number, y: number) => void
  onResize?: (id: string, w: number, h: number) => void
  onRotate?: (id: string, rotation: number) => void
}

// Renders the active stickers on top of the preview frame. Each sticker is a
// plain <img> (so animated GIF/WebP/APNG plays for free without extra wiring).
// Visibility honors start_time / end_time so the FE timing matches what the
// burned-in result will show.
export function StickerOverlay({
  stickers, audioRef, currentTime,
  previewFrameW, previewFrameH, outputW, outputH,
  selectedId, onSelect, onDrag, onResize, onRotate,
}: OverlayProps) {
  // Local rAF tick so we re-evaluate per-sticker visibility against
  // audio.currentTime ~60 Hz (timeupdate fires too slowly).
  const [, force] = useState(0)
  const rafRef = useRef<number>(0)
  useEffect(() => {
    let alive = true
    const tick = () => {
      if (!alive) return
      force(n => (n + 1) & 0xffff)
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => { alive = false; cancelAnimationFrame(rafRef.current) }
  }, [])

  if (!stickers.length) return null

  const t = audioRef?.current
    ? audioRef.current.currentTime
    : (currentTime ?? 0)

  const scaleX = outputW > 0 ? previewFrameW / outputW : 1
  const scaleY = outputH > 0 ? previewFrameH / outputH : 1

  return (
    <>
      {stickers.map(s => {
        const end = s.end_time == null ? Infinity : s.end_time
        // While editing (audio paused at t=0), keep stickers visible so users
        // can position them. Only hide if playback has advanced past end.
        const playing = !!audioRef?.current && !audioRef.current.paused
        const visible = playing
          ? t >= s.start_time && t < end
          : true
        if (!visible) return null

        const isSel = selectedId === s.id
        const rot = s.rotation ?? 0
        const wPx = Math.max(8, s.w * scaleX)
        const hPx = Math.max(8, s.h * scaleY)

        return (
          <div
            key={s.id}
            onMouseDown={(e) => {
              if (!onDrag && !onSelect) return
              e.stopPropagation()
              onSelect?.(s.id)
              if (!onDrag) return
              const frame = (e.currentTarget.parentElement as HTMLElement)
              const rect = frame.getBoundingClientRect()
              const startX = e.clientX
              const startY = e.clientY
              const origX = s.x
              const origY = s.y
              const move = (ev: MouseEvent) => {
                const dx = (ev.clientX - startX) / rect.width
                const dy = (ev.clientY - startY) / rect.height
                onDrag(s.id, Math.max(0, Math.min(1, origX + dx)), Math.max(0, Math.min(1, origY + dy)))
              }
              const up = () => {
                window.removeEventListener('mousemove', move)
                window.removeEventListener('mouseup', up)
              }
              window.addEventListener('mousemove', move)
              window.addEventListener('mouseup', up)
            }}
            style={{
              position: 'absolute',
              left: `${s.x * 100}%`,
              top: `${s.y * 100}%`,
              transform: `translate(-50%, -50%) rotate(${rot}deg)`,
              width: wPx,
              height: hPx,
              opacity: s.opacity,
              cursor: onDrag ? 'move' : 'default',
              outline: isSel ? '2px dashed #C67E15' : 'none',
              outlineOffset: 2,
              userSelect: 'none',
              zIndex: 5,
            }}
          >
            <img
              src={stickerFileUrl(s.image_path)}
              alt=""
              draggable={false}
              /* Backend stretches to exactly w×h (scale=w:h); 'fill' mirrors it. */
              style={{ width: '100%', height: '100%', objectFit: 'fill', pointerEvents: 'none' }}
            />
            {isSel && onResize && (
              <div
                onMouseDown={(e) => {
                  e.stopPropagation()
                  const startX = e.clientX
                  const startY = e.clientY
                  const origW = s.w
                  const origH = s.h
                  const move = (ev: MouseEvent) => {
                    const dx = (ev.clientX - startX) / scaleX
                    const dy = (ev.clientY - startY) / scaleY
                    onResize(s.id, Math.max(16, Math.round(origW + dx)), Math.max(16, Math.round(origH + dy)))
                  }
                  const up = () => {
                    window.removeEventListener('mousemove', move)
                    window.removeEventListener('mouseup', up)
                  }
                  window.addEventListener('mousemove', move)
                  window.addEventListener('mouseup', up)
                }}
                title="Kéo để resize"
                style={{
                  position: 'absolute',
                  right: -8, bottom: -8,
                  width: 16, height: 16,
                  background: '#C67E15', borderRadius: 8,
                  cursor: 'nwse-resize',
                  border: '2px solid white',
                  zIndex: 6,
                }}
              />
            )}
            {isSel && onRotate && (
              <>
                {/* connector line from top-center up to the rotate knob */}
                <div style={{
                  position: 'absolute',
                  left: '50%', top: -24, width: 2, height: 24,
                  background: '#C67E15', transform: 'translateX(-50%)',
                  zIndex: 6, pointerEvents: 'none',
                }} />
                <div
                  onMouseDown={(e) => {
                    e.stopPropagation()
                    const el = e.currentTarget.parentElement as HTMLElement
                    const rect = el.getBoundingClientRect()
                    const cx = rect.left + rect.width / 2
                    const cy = rect.top + rect.height / 2
                    const a0 = Math.atan2(e.clientY - cy, e.clientX - cx)
                    const orig = rot
                    const move = (ev: MouseEvent) => {
                      const a1 = Math.atan2(ev.clientY - cy, ev.clientX - cx)
                      let deg = orig + (a1 - a0) * 180 / Math.PI
                      deg = ((deg % 360) + 360) % 360
                      if (ev.shiftKey) deg = Math.round(deg / 15) * 15
                      onRotate(s.id, deg)
                    }
                    const up = () => {
                      window.removeEventListener('mousemove', move)
                      window.removeEventListener('mouseup', up)
                    }
                    window.addEventListener('mousemove', move)
                    window.addEventListener('mouseup', up)
                  }}
                  title="Kéo để xoay (giữ Shift để snap 15°)"
                  style={{
                    position: 'absolute',
                    left: '50%', top: -32,
                    width: 16, height: 16,
                    transform: 'translateX(-50%)',
                    background: '#C67E15', borderRadius: 8,
                    cursor: 'grab',
                    border: '2px solid white',
                    zIndex: 7,
                  }}
                />
              </>
            )}
          </div>
        )
      })}
    </>
  )
}
