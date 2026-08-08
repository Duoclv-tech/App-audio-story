import axios from 'axios'

const BASE = '/api/v1/trim'

export interface TrimUploadResponse {
  file_id: string
  duration: number
  width: number
  height: number
  video_codec: string
  audio_codec: string | null
  original_filename: string
}

export interface AspectRatioParams {
  mode: string
  custom_w?: number
  custom_h?: number
}

export type WatermarkPosition =
  | 'top-left' | 'top-center' | 'top-right'
  | 'middle-left' | 'center' | 'middle-right'
  | 'bottom-left' | 'bottom-center' | 'bottom-right'
  | 'custom'

export interface WatermarkParams {
  enabled: boolean
  text: string
  font_size: number
  color: string
  opacity: number
  position: WatermarkPosition
  custom_x: number
  custom_y: number
  margin: number
  rotation: number
  border_enabled: boolean
  border_color: string
  border_width: number
}

export const defaultWatermark = (): WatermarkParams => ({
  enabled: false,
  text: '',
  font_size: 36,
  color: '#FFFFFF',
  opacity: 0.85,
  position: 'bottom-center',
  custom_x: 0.5,
  custom_y: 0.5,
  margin: 20,
  rotation: 0,
  border_enabled: true,
  border_color: '#000000',
  border_width: 2,
})

export interface Segment {
  start_sec: number
  end_sec: number
}

/** Burn a re-based SRT onto the trimmed clip. Field names match the backend
 *  SubtitleParams (no `subtitle_` prefix — the UI's SubtitleStyle is mapped to
 *  this shape in VideoTrimmerPage before sending). */
export interface SubtitleParams {
  enabled: boolean
  srt_path?: string | null
  animation: string
  font: string
  font_size: number
  color: string
  outline_color: string
  outline_width: number
  shadow: number
  bold: boolean
  italic: boolean
  align: 'left' | 'center' | 'right'
  x: number
  y: number
  opacity: number
  max_width: number
}

export const defaultSubtitleParams = (): SubtitleParams => ({
  enabled: false,
  srt_path: null,
  animation: 'fade',
  font: 'Be Vietnam Pro (Vietnamese)',
  font_size: 56,
  color: '#FFFFFF',
  outline_color: '#000000',
  outline_width: 3,
  shadow: 0,
  bold: true,
  italic: false,
  align: 'center',
  x: 0.5,
  y: 0.85,
  opacity: 1.0,
  max_width: 0.9,
})

export interface TrimProcessRequest {
  file_id: string
  segments: Segment[]
  quality: string
  custom_bitrate_kbps?: number
  aspect_ratio: AspectRatioParams
  crop_mode: string
  mute: boolean
  volume: number
  speed: number
  exact_frame: boolean
  fade: boolean
  watermark: WatermarkParams
  subtitle?: SubtitleParams
  output_filename: string
}

export interface TrimSrtUploadResponse {
  srt_path: string
  filename: string
  segment_count: number
  first_start: number
  last_end: number
}

/** Upload an SRT scoped to a trim file_id (saved to trim_temp/<file_id>). */
export async function uploadTrimSrt(
  fileId: string,
  file: File
): Promise<TrimSrtUploadResponse> {
  const form = new FormData()
  form.append('file_id', fileId)
  form.append('file', file)
  const { data } = await axios.post<TrimSrtUploadResponse>(`${BASE}/upload-srt`, form)
  return data
}

/** Accept only files that look like a supported video (MIME or extension).
 *  Shared by the drop zone and the in-place "replace video" control. */
export function isVideoFile(file: File): boolean {
  return file.type.startsWith('video/') || /\.(mp4|mov|mkv|avi|webm)$/i.test(file.name)
}

export async function uploadVideo(
  file: File,
  onProgress?: (pct: number) => void
): Promise<TrimUploadResponse> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await axios.post<TrimUploadResponse>(`${BASE}/upload`, form, {
    onUploadProgress: (e) => {
      if (onProgress && e.total) {
        onProgress(Math.round((e.loaded / e.total) * 100))
      }
    },
  })
  return data
}

export async function importVideoFromPath(path: string): Promise<TrimUploadResponse> {
  const { data } = await axios.post<TrimUploadResponse>(`${BASE}/import`, { path })
  return data
}

export interface FolderValidation {
  valid: boolean
  video_count: number
  total_duration: number
  total_duration_formatted: string
  error?: string | null
}

export async function validateVideoFolder(folder: string): Promise<FolderValidation> {
  const { data } = await axios.post<FolderValidation>('/api/v1/video/validate-folder', {
    folder_path: folder,
  })
  return data
}

export interface FromFolderRequest {
  folder: string
  target_duration: number
  width: number
  height: number
  clip_order: string
  clip_seed?: number | null
  /** Mute audio of the folder clips (visual background only). */
  mute_audio?: boolean
  /** file_id of the currently-loaded video whose audio should be muxed onto
   *  the generated background so the original narration is preserved. */
  original_file_id?: string | null
  /** When false (default) the original imported video's audio is kept (muxed
   *  onto the folder background); when true the output drops the original audio. */
  mute_original_audio?: boolean
}

/** Randomly concat clips from a folder into a source video of the given
 *  duration, registered into trim_temp like an upload. */
export async function generateFromFolder(
  req: FromFolderRequest
): Promise<TrimUploadResponse> {
  const { data } = await axios.post<TrimUploadResponse>(`${BASE}/from-folder`, req)
  return data
}

export async function fetchWaveform(fileId: string): Promise<number[]> {
  const { data } = await axios.get<{ waveform: number[] }>(`${BASE}/waveform/${fileId}`)
  return data.waveform
}

export async function startTrim(req: TrimProcessRequest): Promise<string> {
  const { data } = await axios.post<{ job_id: string }>(`${BASE}/process`, req)
  return data.job_id
}

export function openProgressStream(
  jobId: string,
  onEvent: (pct: number, status: string, error?: string, outputPath?: string) => void
): EventSource {
  const es = new EventSource(`${BASE}/progress/${jobId}`)
  // EventSource fires onerror on any transient drop (network blip, proxy idle
  // timeout, OS sleep/resume, backend reload) and would normally auto-reconnect.
  // Reporting 'failed' + close() on the first error defeats that reconnect and
  // permanently reds-out a job the backend is still finishing (the worker runs
  // independently of this stream and keeps the job in _jobs after completion, so
  // a reconnect resumes cleanly). Only surface a failure once the browser has
  // truly given up (readyState CLOSED) or errors persist; otherwise let the
  // built-in reconnect run. Progress is passed as NaN so the caller leaves the
  // bar untouched instead of snapping it back to 0 during a transient reconnect.
  let consecutiveErrors = 0
  es.onmessage = (e) => {
    consecutiveErrors = 0
    const payload = JSON.parse(e.data) as {
      percent: number; status: string; error?: string; output_path?: string
    }
    onEvent(payload.percent, payload.status, payload.error, payload.output_path)
    if (payload.status !== 'running') es.close()
  }
  es.onerror = () => {
    consecutiveErrors += 1
    if (es.readyState === EventSource.CLOSED || consecutiveErrors >= 5) {
      onEvent(NaN, 'failed', 'Mất kết nối tiến trình')
      es.close()
    }
    // else: transient — let EventSource auto-reconnect and keep current progress.
  }
  return es
}

export function getDownloadUrl(jobId: string): string {
  return `${BASE}/download/${jobId}`
}

export async function revealOutput(jobId: string): Promise<void> {
  await axios.post(`${BASE}/reveal/${jobId}`)
}

export function getVideoUrl(fileId: string): string {
  return `${BASE}/video/${fileId}`
}

export async function checkFileExists(fileId: string): Promise<boolean> {
  try {
    const r = await fetch(getVideoUrl(fileId), { method: 'HEAD' })
    return r.ok
  } catch {
    return false
  }
}

export async function clearTemp(fileId: string): Promise<void> {
  await axios.post(`${BASE}/clear/${fileId}`)
}
