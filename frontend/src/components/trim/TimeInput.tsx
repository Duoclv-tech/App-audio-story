import { useEffect, useState } from 'react'

interface Props {
  label: string
  valueSec: number
  maxSec: number
  onChange: (sec: number) => void
  onSetFromPlayer?: () => void
}

function secToParts(sec: number) {
  const s = Math.max(0, sec)
  return {
    h: Math.floor(s / 3600),
    m: Math.floor((s % 3600) / 60),
    s: Math.floor(s % 60),
  }
}

export default function TimeInput({ label, valueSec, maxSec, onChange, onSetFromPlayer }: Props) {
  const [h, setH] = useState(secToParts(valueSec).h)
  const [m, setM] = useState(secToParts(valueSec).m)
  const [s, setS] = useState(secToParts(valueSec).s)

  // Sync from prop (timeline drag etc.)
  useEffect(() => {
    const parts = secToParts(valueSec)
    setH(parts.h)
    setM(parts.m)
    setS(parts.s)
  }, [valueSec])

  // Debounced emit
  useEffect(() => {
    const handle = setTimeout(() => {
      const totalSec = h * 3600 + m * 60 + s
      const clamped = Math.max(0, Math.min(totalSec, maxSec))
      if (Math.abs(clamped - valueSec) > 0.01) {
        onChange(clamped)
      }
    }, 300)
    return () => clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [h, m, s])

  const inputCls =
    'w-14 px-2 py-1 text-center border rounded font-mono text-base focus:outline-none focus:ring-2 focus:ring-primary-500'

  return (
    <div>
      <div className="text-sm font-medium text-gray-700 mb-1">{label}</div>
      <div className="flex items-center gap-1">
        <input
          type="number"
          min={0}
          value={h}
          onChange={(e) => setH(Math.max(0, parseInt(e.target.value || '0', 10)))}
          className={inputCls}
        />
        <span className="text-gray-500">:</span>
        <input
          type="number"
          min={0}
          max={59}
          value={m}
          onChange={(e) => setM(Math.max(0, Math.min(59, parseInt(e.target.value || '0', 10))))}
          className={inputCls}
        />
        <span className="text-gray-500">:</span>
        <input
          type="number"
          min={0}
          max={59}
          value={s}
          onChange={(e) => setS(Math.max(0, Math.min(59, parseInt(e.target.value || '0', 10))))}
          className={inputCls}
        />
        {onSetFromPlayer && (
          <button
            type="button"
            onClick={onSetFromPlayer}
            className="ml-2 text-xs px-2 py-1 border rounded hover:bg-gray-50"
            title="Lấy từ vị trí video đang xem"
          >
             lấy vị trí hiện tại
          </button>
        )}
      </div>
    </div>
  )
}
