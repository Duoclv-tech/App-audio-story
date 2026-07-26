import { forwardRef, useEffect, useRef, useState } from 'react'

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
    },
    ref,
  ) => {
    const [currentTime, setCurrentTime] = useState(0)
    const bgRef = useRef<HTMLVideoElement>(null)

    const reshaping = aspectMode !== 'original'
    const showBlurBg = reshaping && cropMode === 'blur'
    // crop → fill & clip; letterbox/blur/original → fit inside (black or blurred bars)
    const objectFit: 'cover' | 'contain' =
      reshaping && cropMode === 'crop' ? 'cover' : 'contain'

    const getEl = () => (ref as React.RefObject<HTMLVideoElement>).current

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

    return (
      <div className="flex justify-center">
        <div
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
          <div className="absolute top-2 right-2 bg-black/60 text-white text-xs font-mono px-2 py-1 rounded pointer-events-none">
            {fmt(currentTime)}
          </div>
        </div>
      </div>
    )
  },
)

VideoPreview.displayName = 'VideoPreview'
export default VideoPreview
