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
  output_filename: string
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
  es.onmessage = (e) => {
    const payload = JSON.parse(e.data) as {
      percent: number; status: string; error?: string; output_path?: string
    }
    onEvent(payload.percent, payload.status, payload.error, payload.output_path)
    if (payload.status !== 'running') es.close()
  }
  es.onerror = () => {
    onEvent(0, 'failed', 'SSE connection error')
    es.close()
  }
  return es
}

export function getDownloadUrl(jobId: string): string {
  return `${BASE}/download/${jobId}`
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
