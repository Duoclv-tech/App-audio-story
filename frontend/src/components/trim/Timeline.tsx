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

    const onMove = (e: MouseEvent) => {
      const sec = toSec(e.clientX)
      if (drag === 'start') {
        onChange(Math.min(sec, endSec - 0.1), endSec)
      } else {
        onChange(startSec, Math.max(sec, startSec + 0.1))
      }
    }
    const onUp = () => setDrag(null)

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [drag, toSec, onChange, startSec, endSec])

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
        className="relative h-12 bg-gray-200 rounded"
      >
        {/* Selection highlight */}
        <div
          className="absolute top-0 bottom-0 bg-primary-200/70 border-x-2 border-primary-500"
          style={{ left: `${pctStart}%`, width: `${pctEnd - pctStart}%` }}
        >
          <div className="absolute inset-0 flex items-center justify-center text-xs font-medium text-primary-900">
            {fmt(selectionDuration)}
          </div>
        </div>

        {/* Start handle */}
        <div
          onMouseDown={(e) => {
            e.preventDefault()
            setDrag('start')
          }}
          className="absolute top-0 bottom-0 w-3 -ml-1.5 bg-primary-700 cursor-ew-resize rounded"
          style={{ left: `${pctStart}%` }}
          title="Điểm bắt đầu"
        />
        {/* End handle */}
        <div
          onMouseDown={(e) => {
            e.preventDefault()
            setDrag('end')
          }}
          className="absolute top-0 bottom-0 w-3 -ml-1.5 bg-primary-700 cursor-ew-resize rounded"
          style={{ left: `${pctEnd}%` }}
          title="Điểm kết thúc"
        />
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
