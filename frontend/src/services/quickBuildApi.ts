import axios from 'axios'

// ---- Build presets ---------------------------------------------------------
export interface BuildPreset {
  id: string
  name: string
  tts_config: Record<string, any>
  cfg: Record<string, any> | null   // FE videoConfig (used by the wizard, not here)
  video_cfg: Record<string, any>
  video_folder: string | null
  bgm_path: string | null
  watermark_image: string | null
  banner_mode: string
  banner_fixed: string | null
  options: Record<string, any> | null
  created_at: string
  updated_at: string
}

export const listBuildPresets = () =>
  axios.get<BuildPreset[]>('/api/v1/build-presets/').then(r => r.data)

export const deleteBuildPreset = (id: string) =>
  axios.delete(`/api/v1/build-presets/${id}`)

export const renameBuildPreset = (id: string, name: string) =>
  axios.put<BuildPreset>(`/api/v1/build-presets/${id}`, { name }).then(r => r.data)

// ---- Quick build (batch) ---------------------------------------------------
export interface ScanItem {
  source_path: string
  title: string
  has_banner: boolean
}

export interface JobOverrides {
  video_folder?: string
  banner_mode?: 'by_filename' | 'none' | 'fixed'
  banner_fixed?: string
  voice_code?: string
  engine?: string
  speed?: number
  preset_id?: string
  auto_clean?: boolean
  auto_subtitle?: boolean
}

export interface JobIn {
  source_path: string
  title?: string
  selected: boolean
  overrides?: JobOverrides | null
}

export interface JobOut {
  id: string
  order_index: number
  source_path: string
  title: string | null
  story_id: string | null
  stage: string          // create | tts | video | done
  status: string         // pending | running | done | error | skipped
  progress: number       // 0-100, live render % of the running job
  output_path: string | null
  output_size: number | null   // bytes
  error_message: string | null
  updated_at: string | null
}

export interface BatchStatus {
  id: string
  status: string         // queued | running | done | stopped
  total: number
  jobs: JobOut[]
}

export const scanFolder = (path: string) =>
  axios.post<ScanItem[]>('/api/v1/quick-build/scan-folder', { path }).then(r => r.data)

export const startBatch = (preset_id: string, jobs: JobIn[]) =>
  axios.post<{ batch_id: string; total: number }>('/api/v1/quick-build/start', { preset_id, jobs })
    .then(r => r.data)

export const getBatchStatus = (batchId: string) =>
  axios.get<BatchStatus>(`/api/v1/quick-build/${batchId}/status`).then(r => r.data)

export const stopBatch = (batchId: string) =>
  axios.post(`/api/v1/quick-build/${batchId}/stop`)

export const retryJob = (jobId: string) =>
  axios.post<{ batch_id: string }>(`/api/v1/quick-build/job/${jobId}/retry`).then(r => r.data)

export const cancelJob = (jobId: string) =>
  axios.post(`/api/v1/quick-build/job/${jobId}/cancel`)
