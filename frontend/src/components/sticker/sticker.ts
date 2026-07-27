// A single sticker placed on the video. Position uses center-based 0..1
// normalized coords so the layout matches across resolutions; size is absolute
// pixels at the output resolution. end_time = null means "show until video end".
export interface Sticker {
  id: string                  // local UI key (uuid). NOT sent to backend.
  image_path: string          // absolute server path returned by library/upload endpoints
  x: number                   // 0..1
  y: number                   // 0..1
  w: number                   // px at output resolution
  h: number                   // px
  opacity: number             // 0..1
  rotation: number            // clockwise degrees, 0..360
  start_time: number          // seconds
  end_time: number | null     // seconds, null = until end
  // UI hints (not sent to BE)
  source_label?: string       // e.g. "subscribe / Bell Ring"  → shown in active list
  animated?: boolean
}

export interface StickerLibraryItem {
  id: string
  name: string
  path: string
  animated: boolean
  ext: string
}

export interface StickerLibraryCategory {
  name: string
  label: string
  stickers: StickerLibraryItem[]
}

// Strip UI-only fields before sending to /start or /render-preview.
export function toBackendSticker(s: Sticker): Omit<Sticker, 'id' | 'source_label' | 'animated'> {
  return {
    image_path: s.image_path,
    x: s.x,
    y: s.y,
    w: s.w,
    h: s.h,
    opacity: s.opacity,
    rotation: s.rotation,
    start_time: s.start_time,
    end_time: s.end_time,
  }
}

// Build a fresh sticker centered on the canvas.
export function makeSticker(args: {
  image_path: string
  source_label?: string
  animated?: boolean
  audio_duration?: number
}): Sticker {
  const dur = args.audio_duration && args.audio_duration > 0 ? args.audio_duration : null
  const defaultEnd = dur ? Math.min(dur, 5) : 5
  return {
    id: (typeof crypto !== 'undefined' && 'randomUUID' in crypto)
      ? crypto.randomUUID()
      : `s_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    image_path: args.image_path,
    x: 0.5,
    y: 0.5,
    w: 200,
    h: 200,
    opacity: 1.0,
    rotation: 0,
    start_time: 0,
    end_time: defaultEnd,
    source_label: args.source_label,
    animated: args.animated,
  }
}

export function stickerFileUrl(path: string): string {
  return `/api/v1/video/stickers/file?path=${encodeURIComponent(path)}`
}
