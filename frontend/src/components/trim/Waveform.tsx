import { useEffect, useRef } from 'react'

interface Segment {
  start: number
  end: number
}

interface Props {
  peaks: number[]
  duration: number
  segments: Segment[]
}

export default function Waveform({ peaks, duration, segments }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || peaks.length === 0) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const W = canvas.width
    const H = canvas.height
    ctx.clearRect(0, 0, W, H)

    const barW = W / peaks.length

    peaks.forEach((peak, i) => {
      const h = Math.max(2, peak * H)
      const y = (H - h) / 2
      const x = i * barW
      const ratio = duration > 0 ? (i / peaks.length) * duration : 0
      const inSelection = segments.some((s) => ratio >= s.start && ratio <= s.end)
      ctx.fillStyle = inSelection ? '#AC6D12' : '#9ca3af'
      ctx.fillRect(x, y, Math.max(1, barW - 1), h)
    })
  }, [peaks, duration, segments])

  return (
    <canvas
      ref={canvasRef}
      width={1200}
      height={80}
      className="w-full h-20 bg-gray-50 rounded border"
    />
  )
}
