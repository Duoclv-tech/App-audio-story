// SRT parsing + subtitle type definitions shared between Panel and Overlay.

export type SubtitleAnimation =
  | 'none'
  | 'fade'
  | 'pop'
  | 'slide_up'
  | 'typewriter'

export interface SubtitleStyle {
  subtitle_animation: SubtitleAnimation
  subtitle_font: string
  subtitle_font_size: number
  subtitle_color: string
  subtitle_outline_color: string
  subtitle_outline_width: number
  subtitle_shadow: number
  subtitle_bold: boolean
  subtitle_italic: boolean
  subtitle_align: 'left' | 'center' | 'right'
  subtitle_x: number  // 0..1
  subtitle_y: number  // 0..1
  subtitle_opacity: number
  subtitle_max_width: number  // 0..1 — wrap box width as fraction of frame
}

export const DEFAULT_SUBTITLE_STYLE: SubtitleStyle = {
  subtitle_animation: 'fade',
  subtitle_font: 'Be Vietnam Pro (Vietnamese)',
  subtitle_font_size: 56,
  subtitle_color: '#FFFFFF',
  subtitle_outline_color: '#000000',
  subtitle_outline_width: 3,
  subtitle_shadow: 0,
  subtitle_bold: true,
  subtitle_italic: false,
  subtitle_align: 'center',
  subtitle_x: 0.5,
  subtitle_y: 0.85,
  subtitle_opacity: 1.0,
  subtitle_max_width: 0.9,
}

export interface SubtitleSegment {
  id: number
  start: number  // seconds
  end: number    // seconds
  text: string   // newlines preserved as \n
}

const TIME_RE = /(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})/

export function parseSRT(raw: string): SubtitleSegment[] {
  const cleaned = raw.replace(/^﻿/, '').replace(/\r\n?/g, '\n').trim()
  const blocks = cleaned.split(/\n\s*\n/)
  const out: SubtitleSegment[] = []
  let id = 0
  for (const block of blocks) {
    const lines = block.split('\n').filter(l => l.trim().length > 0)
    if (lines.length === 0) continue
    let timeIdx = -1
    for (let i = 0; i < lines.length; i++) {
      if (TIME_RE.test(lines[i])) { timeIdx = i; break }
    }
    if (timeIdx < 0) continue
    const m = lines[timeIdx].match(TIME_RE)
    if (!m) continue
    const [, h1, mm1, s1, ms1, h2, mm2, s2, ms2] = m
    const start = +h1 * 3600 + +mm1 * 60 + +s1 + +ms1.padEnd(3, '0') / 1000
    const end = +h2 * 3600 + +mm2 * 60 + +s2 + +ms2.padEnd(3, '0') / 1000
    let text = lines.slice(timeIdx + 1).join('\n').trim()
    text = text.replace(/<[^>]+>/g, '')  // strip <b>, <i>, <font>...
    if (text && end > start) {
      out.push({ id: id++, start, end, text })
    }
  }
  return out
}

// Returns the segment active at `t`, or null. Linear scan — fine up to a few
// thousand segments, which covers any realistic single-video SRT.
export function findActiveSegment(
  segments: SubtitleSegment[], t: number
): SubtitleSegment | null {
  for (const s of segments) {
    if (t >= s.start && t < s.end) return s
  }
  return null
}
