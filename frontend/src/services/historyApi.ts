import axios from 'axios'

// One history feed = standalone wizard stories + Quick Build batches, interleaved
// by time. A story entry is a leaf; a batch entry expands into its child jobs.

export interface HistStory {
  id: string
  title: string
  url: string
  author?: string
  start_chapter: number
  end_chapter: number
  status: string
  current_step: number
  is_favorite: boolean
  created_at: string
  updated_at: string
  total_downloaded: number
  total_audio_generated: number
  has_merged_audio: boolean
}

export interface HistBatchJob {
  id: string
  order_index: number
  title: string | null
  story_id: string | null
  stage: string
  status: string                 // pending | running | done | error | skipped
  output_path: string | null
  has_output: boolean            // output file still exists on disk
  error_message: string | null
}

// Build config frozen at run time (or reconstructed from the live preset for
// batches created before snapshotting). Shown as chips when the group expands.
export interface HistBatchConfig {
  preset_name: string | null
  engine: string | null
  voice_code: string | null       // VBEE voice id
  mode: string | null             // OmniVoice: auto | design | clone
  clone_preset_name: string | null // OmniVoice clone voice display name
  speed: number | null
  resolution: string | null
  video_folder: string | null
  has_bgm: boolean
  skip_spellcheck: boolean
  auto_clean: boolean
  auto_subtitle: boolean
}

export interface HistBatch {
  id: string
  status: string                 // queued | running | done | stopped
  total: number
  done_count: number
  error_count: number
  source_folder: string | null
  folder_label: string | null
  preset_name: string | null
  config: HistBatchConfig | null
  created_at: string
  updated_at: string
  jobs: HistBatchJob[]
}

export type FeedEntry =
  | { kind: 'story'; story: HistStory }
  | { kind: 'batch'; batch: HistBatch }

export interface FeedMeta {
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface FeedResponse {
  data: FeedEntry[]
  meta: FeedMeta
}

export const historyFeed = (page: number, favoriteOnly: boolean) =>
  axios
    .get<FeedResponse>(`/api/v1/history/feed?page=${page}&page_size=20&favorite_only=${favoriteOnly}`)
    .then(r => r.data)

export const deleteBatch = (batchId: string) =>
  axios.delete(`/api/v1/history/batch/${batchId}`)

export const revealVideo = (storyId: string) =>
  axios.post(`/api/v1/video/reveal-video/${storyId}`)
