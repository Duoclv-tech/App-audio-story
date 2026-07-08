// Split pasted story text into chapters, mirroring backend chapter_splitter.py.
// Used for the live preview + payload of the "Dán văn bản" import mode.

export interface SplitChapter {
  chapter_number: number
  title: string
  content: string
}

// A line that starts a new chapter: optional "Quyển N" prefix, then
// Chương/Chapter/Hồi, then a number. e.g. "Chương 1", "Chương 1: Tựa", "Hồi 3".
const HEADING_RE =
  /^\s*(?:quyển\s+\d+\s*[-:.]?\s*)?(?:chương|chuong|chapter|hồi|hoi)\s*[:.\-]?\s*(\d+)\b.*$/i

export function splitChapters(text: string): SplitChapter[] {
  if (!text || !text.trim()) return []

  const lines = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n')
  const chapters: { chapter_number: number; title: string; contentLines: string[] }[] = []
  let current: { chapter_number: number; title: string; contentLines: string[] } | null = null
  const preLines: string[] = []

  for (const line of lines) {
    const m = line.match(HEADING_RE)
    if (m) {
      if (current) chapters.push(current)
      current = { chapter_number: parseInt(m[1], 10), title: line.trim(), contentLines: [] }
    } else if (current) {
      current.contentLines.push(line)
    } else {
      preLines.push(line)
    }
  }
  if (current) chapters.push(current)

  // No headings detected -> whole text is one chapter.
  if (chapters.length === 0) {
    return [{ chapter_number: 1, title: 'Chương 1', content: text.trim() }]
  }

  const result: SplitChapter[] = []
  const preText = preLines.join('\n').trim()
  if (preText) result.push({ chapter_number: 0, title: 'Giới thiệu', content: preText })
  for (const ch of chapters) {
    result.push({
      chapter_number: ch.chapter_number,
      title: ch.title,
      content: ch.contentLines.join('\n').trim(),
    })
  }
  return result
}
