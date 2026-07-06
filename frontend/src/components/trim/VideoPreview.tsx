import { forwardRef, useEffect, useState } from 'react'

interface Props {
  src: string
}

const VideoPreview = forwardRef<HTMLVideoElement, Props>(({ src }, ref) => {
  const [currentTime, setCurrentTime] = useState(0)

  useEffect(() => {
    const el = (ref as React.RefObject<HTMLVideoElement>).current
    if (!el) return
    const handler = () => setCurrentTime(el.currentTime)
    el.addEventListener('timeupdate', handler)
    return () => el.removeEventListener('timeupdate', handler)
  }, [ref, src])

  const fmt = (s: number) => {
    const h = Math.floor(s / 3600)
    const m = Math.floor((s % 3600) / 60)
    const sec = Math.floor(s % 60)
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${sec
      .toString()
      .padStart(2, '0')}`
  }

  return (
    <div className="relative rounded-lg overflow-hidden bg-black aspect-video w-full max-w-4xl mx-auto">
      <video
        ref={ref}
        src={src}
        controls
        className="absolute inset-0 w-full h-full object-contain"
      />
      <div className="absolute top-2 right-2 bg-black/60 text-white text-xs font-mono px-2 py-1 rounded">
        {fmt(currentTime)}
      </div>
    </div>
  )
})

VideoPreview.displayName = 'VideoPreview'
export default VideoPreview
