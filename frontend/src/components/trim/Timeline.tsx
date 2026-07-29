import { useCallback, useEffect, useRef, useState } from 'react'

interface Props {
  duration: number
  startSec: number
  endSec: number
  onChange: (start: number, end: number) => void
}

type Drag = 'start' | 'end' | null

export default function Timeline({ duration, startSec, endSec, onChange }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<Drag>(null)

  // Latest values kept in refs so the pointer-move listener never reads stale
  // state and the effect can depend only on `drag` (no listener churn mid-drag).
  const startRef = useRef(startSec)
  const endRef = useRef(endSec)
  const onChangeRef = useRef(onChange)
  startRef.current = startSec
  endRef.current = endSec
  onChangeRef.current = onChange

  const pctStart = duration > 0 ? (startSec / duration) * 100 : 0
  const pctEnd = duration > 0 ? (endSec / duration) * 100 : 100

  const toSec = useCallback(
    (clientX: number): number => {
      const el = ref.current
      if (!el) return 0
      const r = el.getBoundingClientRect()
      const pct = Math.max(0, Math.min(1, (clientX - r.left) / r.width))
      return pct * duration
    },
    [duration]
  )

  useEffect(() => {
    if (!drag) return

    const onMove = (e: PointerEvent) => {
      const sec = toSec(e.clientX)
      if (drag === 'start') {
        onChangeRef.current(Math.min(sec, endRef.current - 0.1), endRef.current)
      } else {
        onChangeRef.current(startRef.current, Math.max(sec, startRef.current + 0.1))
      }
    }
    const onUp = () => setDrag(null)

    // Pointer events unify mouse/touch/pen; window-level so the drag keeps
    // tracking even when the pointer moves off the (thin) handle.
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
    }
  }, [drag, toSec])

  const beginDrag = (which: Exclude<Drag, null>) => (e: React.PointerEvent) => {
    e.preventDefault()
    e.stopPropagation()
    // Capture so this element receives the pointer stream for the whole gesture.
    try {
      ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
    } catch {
      /* setPointerCapture unsupported — window listeners still cover it */
    }
    setDrag(which)
  }

  // Click/tap on the track (not on a handle) → move the nearer handle there.
  const onTrackPointerDown = (e: React.PointerEvent) => {
    if (drag) return
    const sec = toSec(e.clientX)
    const which: Exclude<Drag, null> =
      Math.abs(sec - startSec) <= Math.abs(sec - endSec) ? 'start' : 'end'
    if (which === 'start') onChange(Math.min(sec, endSec - 0.1), endSec)
    else onChange(startSec, Math.max(sec, startSec + 0.1))
    setDrag(which)
    try {
      ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
    } catch {
      /* ignore */
    }
  }

  const selectionDuration = endSec - startSec
  const fmt = (s: number) => {
    const m = Math.floor(s / 60)
    const sec = (s % 60).toFixed(1)
    return `${m}m ${sec}s`
  }

  return (
    <div className="relative select-none">
      <div
        ref={ref}
        onPointerDown={onTrackPointerDown}
        className="relative h-12 bg-gray-200 dark:bg-gray-700 rounded cursor-pointer"
        style={{ touchAction: 'none' }}
      >
        {/* Selection highlight (transparent to pointer so the track/handles get events) */}
        <div
          className="absolute top-0 bottom-0 bg-primary-200/70 border-x-2 border-primary-500 pointer-events-none"
          style={{ left: `${pctStart}%`, width: `${pctEnd - pctStart}%` }}
        >
          <div className="absolute inset-0 flex items-center justify-center text-xs font-medium text-primary-900 dark:text-primary-300">
            {fmt(selectionDuration)}
          </div>
        </div>

        {/* Start handle — wide invisible hit area, thin visible grip inside */}
        <div
          onPointerDown={beginDrag('start')}
          className="absolute top-0 bottom-0 w-6 -ml-3 flex justify-center cursor-ew-resize"
          style={{ left: `${pctStart}%`, touchAction: 'none' }}
          title="Điểm bắt đầu"
        >
          <div className="w-1.5 h-full bg-primary-700 rounded pointer-events-none" />
        </div>
        {/* End handle */}
        <div
          onPointerDown={beginDrag('end')}
          className="absolute top-0 bottom-0 w-6 -ml-3 flex justify-center cursor-ew-resize"
          style={{ left: `${pctEnd}%`, touchAction: 'none' }}
          title="Điểm kết thúc"
        >
          <div className="w-1.5 h-full bg-primary-700 rounded pointer-events-none" />
        </div>
      </div>
      <div className="flex justify-between text-xs text-dim mt-1 font-mono">
        <span>00:00:00</span>
        <span>
          {Math.floor(duration / 3600)
            .toString()
            .padStart(2, '0')}
          :
          {Math.floor((duration % 3600) / 60)
            .toString()
            .padStart(2, '0')}
          :
          {Math.floor(duration % 60)
            .toString()
            .padStart(2, '0')}
        </span>
      </div>
    </div>
  )
}
