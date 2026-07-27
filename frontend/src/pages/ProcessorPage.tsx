import { useState, useEffect, useRef, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { SubtitlePanel } from '../components/subtitle/SubtitlePanel'
import { SubtitleOverlay } from '../components/subtitle/SubtitleOverlay'
import { SubtitleSegment, DEFAULT_SUBTITLE_STYLE } from '../components/subtitle/srt'
import { StickerPanel } from '../components/sticker/StickerPanel'
import { StickerOverlay } from '../components/sticker/StickerOverlay'
import { Sticker, toBackendSticker } from '../components/sticker/sticker'
import { hasNativeDialogs, pickFolderNative, pickAudioFileNative, pickImageFileNative, pickTextFileNative } from '../services/nativeDialog'
import { splitChapters } from '../services/chapterSplitter'
import VideoTrimmerPage from './VideoTrimmerPage'

// Define workflow steps
const WORKFLOW_STEPS = [
  { id: 1, name: 'Nhập', description: 'Nhập URL và cấu hình', hidden: false },
  { id: 2, name: 'Tải', description: 'Tải chương từ TruyenFull', hidden: true }, // Hidden - runs automatically
  { id: 3, name: 'Sửa', description: 'Xem lại và chỉnh sửa nội dung chương', hidden: false },
  { id: 4, name: 'Kiểm tra', description: 'Kiểm tra chính tả bằng AI', hidden: false },
  { id: 5, name: 'Cấu hình TTS', description: 'Cấu hình giọng đọc', hidden: false },
  { id: 6, name: 'Đọc TTS', description: 'Chuyển văn bản thành giọng đọc', hidden: false },
  { id: 7, name: 'Video', description: 'Tạo video từ audio', hidden: false },
  { id: 8, name: 'Hoàn tất', description: 'Tải audio hoàn chỉnh', hidden: false }
]

// Visible steps for UI (filter out hidden ones)
const VISIBLE_STEPS = WORKFLOW_STEPS.filter(step => !step.hidden)

// CSS-gradient approximations of FFmpeg's showspectrum color presets, so the
// live preview reflects the chosen preset instead of a single hardcoded rainbow.
// Colors run low→high intensity, matching the horizontal gradient in the preview.
const SPECTRUM_PRESET_GRADIENTS: Record<string, string> = {
  channel:   '#000428, #004e92, #00b09b, #96c93d, #ffd200',
  intensity: '#000033, #0000ff, #00ffff, #ffff00, #ff0000',
  rainbow:   '#110033, #003d66, #00ccaa, #ffee00, #ff3300, #aa00ff',
  moreland:  '#3b4cc0, #b4c8f0, #f7f7f7, #f0b4a0, #b40426',
  nebulae:   '#0d0221, #240046, #5a189a, #c8005a, #ff5d8f',
  fire:      '#000000, #7a0000, #ff3d00, #ffae00, #ffffcc',
  fiery:     '#000000, #8b0000, #ff4500, #ff8c00, #ffd700',
  fruit:     '#12005e, #7b2ff7, #f107a3, #ffd93d, #6bcB77',
  cool:      '#00ffff, #0088ff, #0000ff, #8800ff, #ff00ff',
  magma:     '#000004, #3b0f70, #8c2981, #de4968, #fe9f6d, #fcfdbf',
  green:     '#000000, #003b00, #007a00, #33cc33, #ccffcc',
  viridis:   '#440154, #414487, #2a788e, #22a884, #7ad151, #fde725',
  plasma:    '#0d0887, #6a00a8, #b12a90, #e16462, #fca636, #f0f921',
  cividis:   '#00224e, #35577d, #666970, #97823d, #e1cc55, #fee838',
  terrain:   '#333399, #0099ff, #00cc66, #ffff66, #cc9966, #ffffff',
}

// Prompt gợi ý để người dùng tự kiểm tra chính tả miễn phí trên AI Studio / Gemini
// (thay vì gọi API tốn phí). Copy prompt này kèm nội dung truyện rồi dán vào chat.
const SPELLCHECK_PROMPT =
  'Đọc kĩ từng dòng và check chính tả văn bản, liệt kê các từ sai chính tả và ' +
  'gợi ý chỉnh sửa, xem có các watermark nào không? hãy liệt kê nữa'

// Normalize a FastAPI error `detail` into a plain string. FastAPI 422 responses
// return `detail` as an ARRAY of objects — rendering that directly as a React
// child throws "Objects are not valid as a React child" and blanks the page.
const toMessage = (detail: any, fallback: string): string => {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const parts = detail
      .map((d: any) => (typeof d === 'string' ? d : d?.msg))
      .filter(Boolean)
    if (parts.length) return parts.join(', ')
  }
  if (detail && typeof detail === 'object' && (detail.msg || detail.message)) {
    return detail.msg || detail.message
  }
  return fallback
}
// Extract a safe string from an axios error (or anything).
const errMessage = (err: any, fallback: string): string =>
  toMessage(err?.response?.data?.detail, fallback)

interface StoryData {
  id?: string
  url: string
  title: string
  start_chapter: number
  end_chapter: number
  status?: string
  current_step?: number
  custom_chapter_urls?: string[]
}

interface CustomUrlsDialogState {
  isOpen: boolean
  urlsText: string
}

interface Chapter {
  id: string
  chapter_number: number
  title?: string
  content?: string
  char_count: number
  has_censored_words: boolean
  censored_count: number
  status: string
}

interface EditDialogState {
  isOpen: boolean
  chapter: Chapter | null
  content: string
  title: string
  censoredWords: CensoredWord[]
  findText: string
  replaceText: string
  matchCount: number
  quickBannedWord: string
  quickReplacementWord: string
}

interface CensoredWord {
  id: string
  word: string
  line_number: number
  context: string
  fixed: boolean
  word_type: 'censored' | 'banned'
  suggested_replacement?: string
}

interface ChapterStats {
  story_id: string
  total_chapters: number
  total_characters: number
  average_characters: number
  chapters_with_censored_words: number
  total_censored_words: number
}

interface DeleteDialogState {
  isOpen: boolean
  chapter: Chapter | null
}

interface ToastState {
  isVisible: boolean
  message: string
  type: 'success' | 'error' | 'info'
}

interface AudioRecord {
  chapter_id: string
  chapter_number: number
  chapter_title?: string
  audio_id: string | null
  status: string
  request_id: string | null
  audio_link: string | null
  file_path: string | null
  error_message: string | null
  updated_at: string | null
}

export default function ProcessorPage() {
  const { storyId } = useParams<{ storyId: string }>()
  const navigate = useNavigate()
  const [currentStep, setCurrentStep] = useState(1) // Current viewing step (UI state)
  const [storyData, setStoryData] = useState<StoryData>({
    url: '',
    title: '',
    start_chapter: 1,
    end_chapter: 10
  })
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [voices, setVoices] = useState<any[]>([])
  // Live VBEE voice search (Vietnamese + English) — lets the user pick a voice
  // beyond the 25 seeded in the DB without us storing it.
  const [voiceSearchQuery, setVoiceSearchQuery] = useState('')
  const [voiceSearchResults, setVoiceSearchResults] = useState<any[] | null>(null)
  const [voiceSearching, setVoiceSearching] = useState(false)
  const [searchedVoice, setSearchedVoice] = useState<any | null>(null)
  // The DB-dropdown's own selection, kept separate from ttsConfig.voice_code so
  // a searched voice doesn't clobber it and we can restore it on "bỏ".
  const [dbVoiceCode, setDbVoiceCode] = useState('hn_female_ngochuyen_full_48k-fhg')
  const [chapterStats, setChapterStats] = useState<ChapterStats | null>(null)
  const [checkingGrammar, setCheckingGrammar] = useState(false)
  const [editDialog, setEditDialog] = useState<EditDialogState>({
    isOpen: false,
    chapter: null,
    content: '',
    title: '',
    censoredWords: [],
    findText: '',
    replaceText: '',
    matchCount: 0,
    quickBannedWord: '',
    quickReplacementWord: ''
  })
  const [deleteDialog, setDeleteDialog] = useState<DeleteDialogState>({
    isOpen: false,
    chapter: null
  })
  const [ttsConfig, setTtsConfig] = useState({
    engine: 'vbee' as 'vbee' | 'omnivoice',
    voice_code: 'hn_female_ngochuyen_full_48k-fhg',
    speed: 1.0,
    bitrate: 128,
    audio_type: 'mp3',
    // OmniVoice-only
    mode: 'clone' as 'auto' | 'clone' | 'design',
    model_key: 'base' as 'base',
    preset_id: '',
    instruct: '',
    language: 'Vietnamese',
  })
  // OmniVoice engine state (availability + clone presets)
  const [omniStatus, setOmniStatus] = useState<any>(null)
  const [omniPresets, setOmniPresets] = useState<any[]>([])
  const [omniDownloading, setOmniDownloading] = useState(false)
  const [showOmniAdvanced, setShowOmniAdvanced] = useState(false)
  const [newPreset, setNewPreset] = useState<{ name: string; ref_text: string; file: File | null }>({
    name: '', ref_text: '', file: null,
  })
  const [showCreatePreset, setShowCreatePreset] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [downloadingAudio, setDownloadingAudio] = useState(false)
  const [duplicateStory, setDuplicateStory] = useState<{
    id: string
    title: string
  } | null>(null)
  const [audioRecords, setAudioRecords] = useState<AudioRecord[]>([])
  // Interval handles live in refs, not state: a ref is stable across renders so
  // unmount/story-change cleanup always sees the current timer (a state value
  // captured by a []-deps cleanup would be stale and never clear).
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  // True only while we're actively watching a merge we just kicked off — gates
  // the "TTS hoàn thành!" toast so it fires on the run's completion, not every
  // time step 6 is (re)opened on a story that was already merged before.
  const watchingMergeRef = useRef(false)
  const [toast, setToast] = useState<ToastState>({
    isVisible: false,
    message: '',
    type: 'success'
  })
  const [customUrlsDialog, setCustomUrlsDialog] = useState<CustomUrlsDialogState>({
    isOpen: false,
    urlsText: ''
  })
  // Step 1 content-import (paste / file / folder), replaces the scraper UI.
  const [inputMode, setInputMode] = useState<'paste' | 'file' | 'folder'>('paste')
  const [pasteText, setPasteText] = useState('')
  const pastePreview = useMemo(() => splitChapters(pasteText), [pasteText])

  // Merged content state for Step 3
  const [mergedView, setMergedView] = useState({
    isOpen: false,
    content: '',
    findText: '',
    replaceText: '',
    matchCount: 0,
    isSaving: false,
    isChecking: false,
    aiResult: null as any,
    selectedErrors: {} as Record<number, boolean>,  // idx -> đang tick (mặc định tick hết)
    acceptedErrors: {} as Record<number, boolean>,  // idx -> đã áp dụng => ẩn khỏi danh sách
  })

  // Merged TTS status for Step 6
  const [mergedTtsStatus, setMergedTtsStatus] = useState({
    status: 'idle' as 'idle' | 'running' | 'completed' | 'failed',
    charCount: 0,
    audioFile: null as string | null,
    audioSize: null as number | null,
    error: null as string | null
  })

  // Per-segment TTS for Step 6 (OmniVoice only)
  type TtsSegment = {
    id: string
    seg_index: number
    text: string
    status: 'pending' | 'processing' | 'done' | 'error'
    error_message: string | null
    attempts: number
    duration: number | null
    gen_sec: number | null
    has_audio: boolean
    config?: Record<string, any> | null
  }
  const [segments, setSegments] = useState<TtsSegment[]>([])
  const [splitMode, setSplitMode] = useState<'newline' | 'period'>('newline')
  const [segSourceChanged, setSegSourceChanged] = useState(false)
  const [segBusy, setSegBusy] = useState(false)   // a split/run/merge request is in flight
  const [segRunning, setSegRunning] = useState(false)  // server says a generation batch/retry is active
  const [segMerging, setSegMerging] = useState(false)
  const [autoMergeAfterTts, setAutoMergeAfterTts] = useState(true)  // gộp tự động sau khi TTS xong
  const [segNowPlaying, setSegNowPlaying] = useState<string | null>(null)
  const segAudioRef = useRef<HTMLAudioElement | null>(null)
  const segPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const prevSegRunningRef = useRef(false)  // theo dõi chuyển trạng thái đang chạy -> xong để auto-gộp

  // Video processing state for Step 7
  const VIDEO_TRANSITIONS = [
    'fade','fadeblack','fadewhite','dissolve','pixelize',
    'wipeleft','wiperight','wipeup','wipedown',
    'slideleft','slideright','slideup','slidedown',
    'smoothleft','smoothright','smoothup','smoothdown',
    'circleopen','circleclose','rectcrop','radial','zoomin',
    'crossfade','distance','hblur',
  ]

  type VideoConfig = {
    folder: string; audioPath: string; bannerImage: string;
    bannerVideoScaleX: number; bannerVideoScaleY: number;
    bannerVideoRotation: number;
    bannerVideoOffsetX: number; bannerVideoOffsetY: number;
    watermarkImage: string;
    audio_speed: number; transitions_pool: string[]; transition_duration: number;
    resolution: string; overlay_opacity: number;
    watermark_x: number; watermark_y: number;
    watermark_w: number; watermark_h: number; watermark_shape: string;
    watermark_opacity: number;
    watermark_text: string; watermark_text_font: string; watermark_text_size: number;
    watermark_text_color: string; watermark_text_angle: number;
    watermark_text_x: number; watermark_text_y: number; watermark_text_opacity: number;
    subtitle_srt_path: string | null;
    subtitle_animation: 'none'|'fade'|'pop'|'slide_up'|'typewriter';
    subtitle_font: string; subtitle_font_size: number;
    subtitle_color: string; subtitle_outline_color: string;
    subtitle_outline_width: number; subtitle_shadow: number;
    subtitle_bold: boolean; subtitle_italic: boolean;
    subtitle_align: 'left'|'center'|'right';
    subtitle_x: number; subtitle_y: number; subtitle_opacity: number;
    fade_in: number; fade_out: number;
    mute_source_videos: boolean;
    clip_order: 'shuffle'|'name';
    clip_seed: number;
    bgmPath: string;
    bgm_volume: number; bgm_loop: boolean; bgm_ducking: boolean; bgm_fade: number;
    visualizer_enabled: boolean;
    visualizer_style: 'bars'|'waveform'|'spectrum'|'cqt';
    visualizer_x: number; visualizer_y: number;
    visualizer_w: number; visualizer_h: number;
    visualizer_color1: string; visualizer_color2: string;
    visualizer_opacity: number;
    visualizer_bg_mode: 'transparent'|'solid';
    visualizer_bg_color: string; visualizer_bg_opacity: number;
    visualizer_spectrum_preset: string;
    visualizer_bars_mode: 'bar'|'line'|'dot';
    visualizer_waveform_mode: 'cline'|'line'|'point'|'p2p';
    visualizer_waveform_mirror: boolean;
    ad_flip_random: boolean; ad_flip_all: boolean;
    ad_zoom: boolean; ad_zoom_factor: number;
    ad_color: boolean;
    ad_saturation: number; ad_contrast: number; ad_gamma: number; ad_hue_shift: number;
    ad_clip_speed_jitter: boolean; ad_clip_speed_jitter_range: number;
    ad_strip_metadata: boolean;
    // Stickers (image / GIF / WebP overlays). Stored alongside the rest of the
    // config so a preset can re-apply the same set; absolute paths must still
    // exist on disk for the backend to find them.
    stickers: Sticker[];
  }

  // Preset lưu mọi setting tái dùng được — bao gồm cả transform bố cục banner
  // (scale/rotation/offset) để tái lập layout — chỉ loại các đường dẫn file cụ thể.
  type VideoCfgPreset = Omit<VideoConfig, 'folder'|'audioPath'|'bannerImage'|'watermarkImage'|'bgmPath'>

  // Seed shared by the preview and the final render so "Ngẫu nhiên" shows the
  // exact clip order the output will use. "Trộn lại" generates a fresh one.
  const genClipSeed = () => Math.floor(Math.random() * 1_000_000_000)

  const DEFAULT_VIDEO_CFG: VideoCfgPreset = {
    bannerVideoScaleX: 1.0,
    bannerVideoScaleY: 1.0,
    bannerVideoRotation: 0,
    bannerVideoOffsetX: 0,
    bannerVideoOffsetY: 0,
    audio_speed: 1.0,
    transitions_pool: ['fade', 'crossfade', 'slideleft'],
    transition_duration: 0.5,
    resolution: '1920x1080',
    overlay_opacity: 0.0,
    watermark_x: 0.92,
    watermark_y: 0.92,
    watermark_w: 200,
    watermark_h: 200,
    watermark_shape: 'none',
    watermark_opacity: 0.85,
    watermark_text: '',
    watermark_text_font: 'DejaVu Sans (system default)',
    watermark_text_size: 48,
    watermark_text_color: '#FFFFFF',
    watermark_text_angle: 0.0,
    watermark_text_x: 0.92,
    watermark_text_y: 0.92,
    watermark_text_opacity: 0.85,
    subtitle_srt_path: null,
    ...DEFAULT_SUBTITLE_STYLE,
    fade_in: 0.0,
    fade_out: 0.0,
    mute_source_videos: true,
    clip_order: 'shuffle',
    clip_seed: 0,
    bgm_volume: 0.12,
    bgm_loop: true,
    bgm_ducking: true,
    bgm_fade: 2.0,
    visualizer_enabled: false,
    visualizer_style: 'bars',
    visualizer_x: 0.5,
    visualizer_y: 0.85,
    visualizer_w: 800,
    visualizer_h: 120,
    visualizer_color1: '#00E5FF',
    visualizer_color2: '#FF00FF',
    visualizer_opacity: 0.85,
    visualizer_bg_mode: 'transparent',
    visualizer_bg_color: '#000000',
    visualizer_bg_opacity: 0.3,
    visualizer_spectrum_preset: 'rainbow',
    visualizer_bars_mode: 'bar',
    visualizer_waveform_mode: 'cline',
    visualizer_waveform_mirror: false,
    ad_flip_random: false,
    ad_flip_all: false,
    ad_zoom: false,
    ad_zoom_factor: 1.08,
    ad_color: false,
    ad_saturation: 1.05,
    ad_contrast: 1.00,
    ad_gamma: 1.00,
    ad_hue_shift: 0.0,
    ad_clip_speed_jitter: false,
    ad_clip_speed_jitter_range: 0.03,
    ad_strip_metadata: false,
    stickers: [],
  }

  // Migrate old configs (with *_position string) x/y center coords
  const migrateOldCfg = (cfg: any): any => {
    if (!cfg) return cfg
    const posToXY = (pos: string) => ({
      x: pos.endsWith('left') ? 0.08 : pos.endsWith('right') ? 0.92 : 0.5,
      y: pos.startsWith('top') ? 0.08 : pos.startsWith('bottom') ? 0.92 : 0.5,
    })
    if (typeof cfg.watermark_position === 'string' && cfg.watermark_x === undefined) {
      const xy = posToXY(cfg.watermark_position)
      cfg.watermark_x = xy.x; cfg.watermark_y = xy.y
    }
    if (typeof cfg.watermark_text_position === 'string' && cfg.watermark_text_x === undefined) {
      const xy = posToXY(cfg.watermark_text_position)
      cfg.watermark_text_x = xy.x; cfg.watermark_text_y = xy.y
    }
    delete cfg.watermark_position; delete cfg.watermark_text_position
    // Migrate old watermark_size (% of width) w/h px (assume 1920 base)
    if (typeof cfg.watermark_size === 'number' && cfg.watermark_w === undefined) {
      const wpx = Math.max(32, Math.round(cfg.watermark_size * 1920))
      cfg.watermark_w = wpx
      cfg.watermark_h = wpx
    }
    delete cfg.watermark_size
    return cfg
  }

  const [videoConfig, setVideoConfig] = useState<VideoConfig>(() => {
    const savedFolder = localStorage.getItem('videoConfig_folder') || ''
    const savedBanner = localStorage.getItem('videoConfig_bannerImage') || ''
    const savedWatermark = localStorage.getItem('videoConfig_watermarkImage') || ''
    const savedBgm = localStorage.getItem('videoConfig_bgmPath') || ''
    // Legacy single scale → migrate to per-axis when the new keys are absent.
    const savedScale = parseFloat(localStorage.getItem('videoConfig_bannerVideoScale') || '1.0')
    const legacyScale = isNaN(savedScale) ? 1.0 : savedScale
    const rawSX = localStorage.getItem('videoConfig_bannerVideoScaleX')
    const rawSY = localStorage.getItem('videoConfig_bannerVideoScaleY')
    const savedSX = rawSX === null ? legacyScale : parseFloat(rawSX)
    const savedSY = rawSY === null ? legacyScale : parseFloat(rawSY)
    const savedOffX = parseFloat(localStorage.getItem('videoConfig_bannerVideoOffsetX') || '0')
    const savedOffY = parseFloat(localStorage.getItem('videoConfig_bannerVideoOffsetY') || '0')
    const savedRot = parseFloat(localStorage.getItem('videoConfig_bannerVideoRotation') || '0')
    const savedCfg = (() => { try { return JSON.parse(localStorage.getItem('videoConfig_cfg') || '{}') } catch { return {} } })()
    return {
      folder: savedFolder,
      audioPath: '',
      bannerImage: savedBanner,
      watermarkImage: savedWatermark,
      bgmPath: savedBgm,
      ...DEFAULT_VIDEO_CFG,
      ...migrateOldCfg(savedCfg),
      // Banner transform từ các key localStorage riêng — đặt sau các spread để
      // luôn thắng giá trị mặc định trong DEFAULT_VIDEO_CFG.
      bannerVideoScaleX: isNaN(savedSX) ? 1.0 : Math.max(0.1, Math.min(3, savedSX)),
      bannerVideoScaleY: isNaN(savedSY) ? 1.0 : Math.max(0.1, Math.min(3, savedSY)),
      bannerVideoOffsetX: isNaN(savedOffX) ? 0 : Math.max(-0.5, Math.min(0.5, savedOffX)),
      bannerVideoOffsetY: isNaN(savedOffY) ? 0 : Math.max(-0.5, Math.min(0.5, savedOffY)),
      bannerVideoRotation: isNaN(savedRot) ? 0 : Math.max(-180, Math.min(180, savedRot)),
      // Ensure a non-zero seed exists (old saved configs won't have one).
      clip_seed: savedCfg?.clip_seed || genClipSeed(),
    }
  })

  type VideoPresetRow = { id: string; name: string; cfg: VideoCfgPreset }
  const [videoPresets, setVideoPresets] = useState<VideoPresetRow[]>([])
  const [selectedPresetId, setSelectedPresetId] = useState<string>('')
  const [presetModal, setPresetModal] = useState<{
    isOpen: boolean
    mode: 'create' | 'rename'
    name: string
    presetId: string | null
  }>({ isOpen: false, mode: 'create', name: '', presetId: null })
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean
    title: string
    message: string
    confirmText: string
    variant: 'danger' | 'primary'
    onConfirm: () => void
  }>({ isOpen: false, title: '', message: '', confirmText: 'OK', variant: 'primary', onConfirm: () => {} })
  const [videoStatus, setVideoStatus] = useState({
    status: 'idle' as 'idle' | 'queued' | 'running' | 'completed' | 'failed',
    taskId: null as string | null,
    progress: 0,
    outputPath: null as string | null,
    error: null as string | null
  })
  const [folderValidation, setFolderValidation] = useState({
    valid: false,
    videoCount: 0,
    totalDuration: '',
    checked: false
  })
  const videoPollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [folderBrowser, setFolderBrowser] = useState({
    isOpen: false,
    currentPath: '',
    parentPath: null as string | null,
    folders: [] as string[],
    videoCount: 0,
    loading: false
  })
  const [audioBrowser, setAudioBrowser] = useState({
    isOpen: false,
    currentPath: '',
    parentPath: null as string | null,
    folders: [] as string[],
    files: [] as string[],
    loading: false
  })
  // Which field the audio browser writes to: the main narration or the BGM track.
  const [audioBrowserTarget, setAudioBrowserTarget] = useState<'main' | 'bgm'>('main')
  const [imageBrowser, setImageBrowser] = useState({
    isOpen: false,
    currentPath: '',
    parentPath: null as string | null,
    folders: [] as string[],
    files: [] as string[],
    loading: false
  })
  const [antiDetectionOpen, setAntiDetectionOpen] = useState(false)
  const [videoTab, setVideoTab] = useState<'basic' | 'effects' | 'antidetect'>('basic')
  const [selectedStickerId, setSelectedStickerId] = useState<string | null>(null)
  type ClipInfo = { path: string; name: string; duration: number }
  const [clipList, setClipList] = useState<ClipInfo[]>([])
  const [currentClipIdx, setCurrentClipIdx] = useState<number>(0)
  const [audioDuration, setAudioDuration] = useState<number>(0)
  const [previewCurrentTime, setPreviewCurrentTime] = useState<number>(0)
  const [previewPlaying, setPreviewPlaying] = useState<boolean>(false)
  const previewVideoRef = useRef<HTMLVideoElement | null>(null)
  const previewAudioRef = useRef<HTMLAudioElement | null>(null)
  const previewFrameRef = useRef<HTMLDivElement | null>(null)
  // Chiều rộng khả dụng của cột chứa preview (đo runtime để khung không tràn ra
  // ngoài card khi cột hẹp hơn kích thước tối đa cứng).
  const previewColRef = useRef<HTMLDivElement | null>(null)
  const [previewAvailW, setPreviewAvailW] = useState<number>(720)
  // Offset to apply to <video> after a clip switch finishes loading
  const pendingClipOffsetRef = useRef<number>(0)
  const [previewVolume, setPreviewVolume] = useState<number>(1)
  const previewMuted = previewVolume === 0

  type ExactPreviewState = {
    open: boolean
    hash: string | null
    status: 'idle' | 'queued' | 'running' | 'done' | 'failed'
    progress: number
    error: string | null
    cached: boolean
  }
  const [exactPreview, setExactPreview] = useState<ExactPreviewState>({
    open: false, hash: null, status: 'idle', progress: 0, error: null, cached: false,
  })
  const exactPollRef = useRef<number | null>(null)

  // Apply playback rate without changing pitch — vendor-prefixed for older Safari/Firefox.
  const applyAudioPitchPreserve = (a: HTMLAudioElement, speed: number) => {
    a.playbackRate = Math.max(0.1, speed)
    const aany = a as any
    aany.preservesPitch = true
    aany.mozPreservesPitch = true
    aany.webkitPreservesPitch = true
  }

  const clipsTotalDur = useMemo(
    () => clipList.reduce((s, c) => s + (c.duration || 0), 0),
    [clipList]
  )

  // Audio plays sped up so its wall-clock duration = audioDur / speed.
  const videoTotalDuration = useMemo(() => {
    if (!audioDuration || audioDuration <= 0) return 0
    return audioDuration / Math.max(0.1, videoConfig.audio_speed)
  }, [audioDuration, videoConfig.audio_speed])

  const findClipForTime = (vt: number): { idx: number; offset: number } => {
    if (clipList.length === 0 || clipsTotalDur <= 0) return { idx: 0, offset: 0 }
    const looped = ((vt % clipsTotalDur) + clipsTotalDur) % clipsTotalDur
    let acc = 0
    for (let i = 0; i < clipList.length; i++) {
      const d = clipList[i].duration || 0
      if (looped < acc + d) return { idx: i, offset: looped - acc }
      acc += d
    }
    return { idx: clipList.length - 1, offset: 0 }
  }

  const togglePreviewPlay = () => {
    const a = previewAudioRef.current
    const v = previewVideoRef.current
    if (a) {
      if (a.paused) a.play().catch(() => {})
      else a.pause()
    } else if (v) {
      if (v.paused) v.play().catch(() => {})
      else v.pause()
    }
  }

  const seekPreview = (t: number) => {
    if (!isFinite(t) || t < 0) return
    const a = previewAudioRef.current
    const speed = Math.max(0.1, videoConfig.audio_speed)
    if (a && audioDuration > 0) {
      a.currentTime = Math.max(0, Math.min(audioDuration, t * speed))
    }
    const { idx, offset } = findClipForTime(t)
    if (idx !== currentClipIdx) {
      pendingClipOffsetRef.current = offset
      setCurrentClipIdx(idx)
    } else {
      const v = previewVideoRef.current
      if (v) v.currentTime = offset
    }
    setPreviewCurrentTime(t)
  }

  const togglePreviewMute = () => {
    setPreviewVolume(v => (v > 0 ? 0 : 1))
  }
  const setPreviewVol = (vol: number) => {
    const a = previewAudioRef.current
    if (a) {
      a.volume = vol
      a.muted = vol === 0
    }
    setPreviewVolume(vol)
  }
  const startExactPreview = async () => {
    if (!videoConfig.folder.trim() || !videoConfig.audioPath.trim()) {
      showToast('Cần folder video và audio path để render exact preview', 'error')
      return
    }
    if (exactPollRef.current) { window.clearInterval(exactPollRef.current); exactPollRef.current = null }
    setExactPreview({ open: true, hash: null, status: 'queued', progress: 0, error: null, cached: false })

    // Mirrors /start's payload shape — backend's /render-preview ignores story_id
    // (preview is story-agnostic) but VideoProcessRequest requires it.
    const payload = {
      story_id: storyData.id || 'preview',
      video_source_folder: videoConfig.folder,
      audio_path: videoConfig.audioPath,
      clip_order: videoConfig.clip_order,
      clip_seed: videoConfig.clip_seed,
      audio_speed: videoConfig.audio_speed,
      transitions_pool: videoConfig.transitions_pool,
      transition_duration: videoConfig.transition_duration,
      resolution: videoConfig.resolution,
      banner_image: videoConfig.bannerImage,
      banner_video_scale: videoConfig.bannerVideoScaleX,
      banner_video_scale_x: videoConfig.bannerVideoScaleX,
      banner_video_scale_y: videoConfig.bannerVideoScaleY,
      banner_video_rotation: videoConfig.bannerVideoRotation,
      banner_video_offset_x: videoConfig.bannerVideoOffsetX,
      banner_video_offset_y: videoConfig.bannerVideoOffsetY,
      overlay_opacity: videoConfig.overlay_opacity,
      watermark_image: videoConfig.watermarkImage,
      watermark_x: videoConfig.watermark_x,
      watermark_y: videoConfig.watermark_y,
      watermark_w: videoConfig.watermark_w,
      watermark_h: videoConfig.watermark_h,
      watermark_shape: videoConfig.watermark_shape,
      watermark_opacity: videoConfig.watermark_opacity,
      watermark_text: videoConfig.watermark_text,
      watermark_text_font: videoConfig.watermark_text_font,
      watermark_text_size: videoConfig.watermark_text_size,
      watermark_text_color: videoConfig.watermark_text_color,
      watermark_text_angle: videoConfig.watermark_text_angle,
      watermark_text_x: videoConfig.watermark_text_x,
      watermark_text_y: videoConfig.watermark_text_y,
      watermark_text_opacity: videoConfig.watermark_text_opacity,
      subtitle_srt_path: videoConfig.subtitle_srt_path || undefined,
      subtitle_animation: videoConfig.subtitle_animation,
      subtitle_font: videoConfig.subtitle_font,
      subtitle_font_size: videoConfig.subtitle_font_size,
      subtitle_color: videoConfig.subtitle_color,
      subtitle_outline_color: videoConfig.subtitle_outline_color,
      subtitle_outline_width: videoConfig.subtitle_outline_width,
      subtitle_shadow: videoConfig.subtitle_shadow,
      subtitle_bold: videoConfig.subtitle_bold,
      subtitle_italic: videoConfig.subtitle_italic,
      subtitle_align: videoConfig.subtitle_align,
      subtitle_x: videoConfig.subtitle_x,
      subtitle_y: videoConfig.subtitle_y,
      subtitle_opacity: videoConfig.subtitle_opacity,
      fade_in: videoConfig.fade_in,
      fade_out: videoConfig.fade_out,
      mute_source_videos: videoConfig.mute_source_videos,
      bgm_path: videoConfig.bgmPath || undefined,
      bgm_volume: videoConfig.bgm_volume,
      bgm_loop: videoConfig.bgm_loop,
      bgm_ducking: videoConfig.bgm_ducking,
      bgm_fade: videoConfig.bgm_fade,
      ad_flip_random: videoConfig.ad_flip_random,
      ad_flip_all: videoConfig.ad_flip_all,
      ad_zoom: videoConfig.ad_zoom,
      ad_zoom_factor: videoConfig.ad_zoom_factor,
      ad_color: videoConfig.ad_color,
      ad_saturation: videoConfig.ad_saturation,
      ad_contrast: videoConfig.ad_contrast,
      ad_gamma: videoConfig.ad_gamma,
      ad_hue_shift: videoConfig.ad_hue_shift,
      ad_clip_speed_jitter: videoConfig.ad_clip_speed_jitter,
      ad_clip_speed_jitter_range: videoConfig.ad_clip_speed_jitter_range,
      ad_strip_metadata: videoConfig.ad_strip_metadata,
      visualizer_enabled: videoConfig.visualizer_enabled,
      visualizer_style: videoConfig.visualizer_style,
      visualizer_x: videoConfig.visualizer_x,
      visualizer_y: videoConfig.visualizer_y,
      visualizer_w: videoConfig.visualizer_w,
      visualizer_h: videoConfig.visualizer_h,
      visualizer_color1: videoConfig.visualizer_color1,
      visualizer_color2: videoConfig.visualizer_color2,
      visualizer_opacity: videoConfig.visualizer_opacity,
      visualizer_bg_mode: videoConfig.visualizer_bg_mode,
      visualizer_bg_color: videoConfig.visualizer_bg_color,
      visualizer_bg_opacity: videoConfig.visualizer_bg_opacity,
      visualizer_spectrum_preset: videoConfig.visualizer_spectrum_preset,
      visualizer_bars_mode: videoConfig.visualizer_bars_mode,
      visualizer_waveform_mode: videoConfig.visualizer_waveform_mode,
      visualizer_waveform_mirror: videoConfig.visualizer_waveform_mirror,
      stickers: videoConfig.stickers.map(toBackendSticker),
    }
    try {
      const r = await axios.post('/api/v1/video/render-preview', payload)
      const hash = r.data?.hash
      const status = r.data?.status
      const cached = !!r.data?.cached
      if (!hash) {
        setExactPreview(s => ({ ...s, status: 'failed', error: 'No hash returned', open: true }))
        return
      }
      if (status === 'done') {
        setExactPreview({ open: true, hash, status: 'done', progress: 100, error: null, cached })
        return
      }
      setExactPreview({ open: true, hash, status: 'running', progress: 0, error: null, cached: false })
      exactPollRef.current = window.setInterval(async () => {
        try {
          const sr = await axios.get('/api/v1/video/preview-status', { params: { hash } })
          const st = sr.data
          setExactPreview(prev => ({
            ...prev,
            status: st.status,
            progress: typeof st.progress === 'number' ? st.progress : prev.progress,
            error: st.error || null,
            cached: !!st.cached,
          }))
          if (st.status === 'done' || st.status === 'failed') {
            if (exactPollRef.current) { window.clearInterval(exactPollRef.current); exactPollRef.current = null }
          }
        } catch (e) {
          if (exactPollRef.current) { window.clearInterval(exactPollRef.current); exactPollRef.current = null }
          setExactPreview(prev => ({ ...prev, status: 'failed', error: 'Status poll failed' }))
        }
      }, 1000)
    } catch (e: any) {
      setExactPreview({
        open: true, hash: null, status: 'failed', progress: 0,
        error: errMessage(e, e?.message || 'Render failed'),
        cached: false,
      })
    }
  }

  const closeExactPreview = () => {
    if (exactPollRef.current) { window.clearInterval(exactPollRef.current); exactPollRef.current = null }
    setExactPreview({ open: false, hash: null, status: 'idle', progress: 0, error: null, cached: false })
  }

  const togglePreviewFullscreen = () => {
    // Fullscreen the WHOLE preview frame (banner + clip + watermark + controls),
    // not just the inner video element.
    const target = previewFrameRef.current
    if (!target) return
    if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {})
    else target.requestFullscreen?.().catch(() => {})
  }
  const formatTime = (s: number) => {
    if (!isFinite(s) || s < 0) s = 0
    const m = Math.floor(s / 60)
    const ss = Math.floor(s % 60)
    return `${m}:${ss.toString().padStart(2, '0')}`
  }

  // Shared pointer-drag lifecycle for all preview overlays (watermark, banner
  // video move/resize). Captures the pointer to the grabbed element so the drag
  // keeps tracking even when the cursor leaves the window, and tears down on
  // BOTH pointerup and pointercancel so an interrupted gesture can't leave a
  // dangling "video follows the cursor" listener.
  const beginPointerDrag = (e: React.PointerEvent, update: (cx: number, cy: number, ev: PointerEvent) => void) => {
    e.preventDefault()
    e.stopPropagation()
    const el = e.currentTarget as HTMLElement
    const pointerId = e.pointerId
    try { el.setPointerCapture(pointerId) } catch { /* capture unsupported — fall back to listeners */ }
    const onMove = (ev: PointerEvent) => update(ev.clientX, ev.clientY, ev)
    const end = () => {
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerup', end)
      el.removeEventListener('pointercancel', end)
      try { el.releasePointerCapture(pointerId) } catch { /* already released */ }
    }
    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerup', end)
    el.addEventListener('pointercancel', end)
  }

  // Watermark drag handler factory: drags watermark to any (x, y) in 0..1 within frame.
  // Preserves grab-offset so cursor stays at the same relative spot on the watermark
  // (no jarring "snap-to-cursor" on initial click).
  const startWatermarkDrag = (target: 'image' | 'text' | 'subtitle' | 'viz') => (e: React.PointerEvent) => {
    const frame = previewFrameRef.current
    if (!frame) return
    const rect = frame.getBoundingClientRect()
    const xKey = target === 'image' ? 'watermark_x'
      : target === 'text' ? 'watermark_text_x'
      : target === 'viz' ? 'visualizer_x'
      : 'subtitle_x'
    const yKey = target === 'image' ? 'watermark_y'
      : target === 'text' ? 'watermark_text_y'
      : target === 'viz' ? 'visualizer_y'
      : 'subtitle_y'
    const startCenterX = videoConfig[xKey] as number
    const startCenterY = videoConfig[yKey] as number
    // Offset (in fraction of frame) between cursor and current overlay center
    const grabOffsetX = (e.clientX - rect.left) / rect.width - startCenterX
    const grabOffsetY = (e.clientY - rect.top) / rect.height - startCenterY
    beginPointerDrag(e, (clientX, clientY) => {
      const r = frame.getBoundingClientRect()
      const x = Math.max(0, Math.min(1, (clientX - r.left) / r.width - grabOffsetX))
      const y = Math.max(0, Math.min(1, (clientY - r.top) / r.height - grabOffsetY))
      setVideoConfig(prev => ({ ...prev, [xKey]: x, [yKey]: y }) as typeof prev)
    })
  }

  // Banner video drag = MOVE. Stores offset as a fraction of the frame from
  // center (0 = centered), matching the backend overlay position expression.
  // The offset/scale is a single shared transform, so moving the sample clip
  // moves EVERY clip in the folder the same way.
  const startBannerVideoMove = (e: React.PointerEvent) => {
    const frame = previewFrameRef.current
    if (!frame) return
    const startOffX = videoConfig.bannerVideoOffsetX
    const startOffY = videoConfig.bannerVideoOffsetY
    const startClientX = e.clientX
    const startClientY = e.clientY
    beginPointerDrag(e, (cx, cy) => {
      const r = frame.getBoundingClientRect()
      const dx = (cx - startClientX) / r.width
      const dy = (cy - startClientY) / r.height
      const nx = Math.max(-0.5, Math.min(0.5, startOffX + dx))
      const ny = Math.max(-0.5, Math.min(0.5, startOffY + dy))
      setVideoConfig(prev => ({ ...prev, bannerVideoOffsetX: nx, bannerVideoOffsetY: ny }))
    })
  }

  // Banner video RESIZE — factory parameterised by which edge/corner is grabbed.
  // dirX/dirY ∈ {-1,0,+1}: a non-zero axis is resized, 0 is left untouched
  // (so edge handles change only width OR height → aspect can be distorted, and
  // corner handles change both). The video box always fills scale*frame exactly
  // (object-fill), so a handle sits on the box edge and the scale reads directly
  // off the cursor distance to center — no grab snap. The sign keeps a drag past
  // the center clamped at the minimum instead of inverting and re-growing.
  const startBannerVideoResize = (dirX: number, dirY: number) => (e: React.PointerEvent) => {
    const frame = previewFrameRef.current
    if (!frame) return
    const offX = videoConfig.bannerVideoOffsetX
    const offY = videoConfig.bannerVideoOffsetY
    beginPointerDrag(e, (cx, cy) => {
      const r = frame.getBoundingClientRect()
      const centerX = r.left + (0.5 + offX) * r.width
      const centerY = r.top + (0.5 + offY) * r.height
      setVideoConfig(prev => {
        let sx = prev.bannerVideoScaleX
        let sy = prev.bannerVideoScaleY
        // Project the cursor→center vector onto the box's own (unrotated) axes so
        // edge/corner drags stay correct even when the box is rotated.
        const rad = (prev.bannerVideoRotation * Math.PI) / 180
        const dx = cx - centerX
        const dy = cy - centerY
        const localDX = dx * Math.cos(rad) + dy * Math.sin(rad)
        const localDY = -dx * Math.sin(rad) + dy * Math.cos(rad)
        if (dirX !== 0) sx = Math.max(0.1, Math.min(3, (2 * localDX * dirX) / r.width))
        if (dirY !== 0) sy = Math.max(0.1, Math.min(3, (2 * localDY * dirY) / r.height))
        return { ...prev, bannerVideoScaleX: sx, bannerVideoScaleY: sy }
      })
    })
  }

  // Banner video ROTATE — grab the round handle above the box and swing it.
  // Angle = direction from box center to cursor; the handle rests at the top
  // (−90° in atan2), so +90 reads 0° at rest. Hold Shift to snap to 15°.
  const startBannerVideoRotate = (e: React.PointerEvent) => {
    const frame = previewFrameRef.current
    if (!frame) return
    const offX = videoConfig.bannerVideoOffsetX
    const offY = videoConfig.bannerVideoOffsetY
    beginPointerDrag(e, (cx, cy, ev) => {
      const r = frame.getBoundingClientRect()
      const centerX = r.left + (0.5 + offX) * r.width
      const centerY = r.top + (0.5 + offY) * r.height
      let deg = (Math.atan2(cy - centerY, cx - centerX) * 180) / Math.PI + 90
      if (deg > 180) deg -= 360
      if (deg < -180) deg += 360
      if (ev?.shiftKey) deg = Math.round(deg / 15) * 15
      setVideoConfig(prev => ({ ...prev, bannerVideoRotation: Math.round(deg) }))
    })
  }
  const [availableFonts, setAvailableFonts] = useState<string[]>(['DejaVu Sans (system default)'])
  const [wmCardOpen, setWmCardOpen] = useState<boolean>(() => localStorage.getItem('wmCardOpen') === 'true')
  useEffect(() => { localStorage.setItem('wmCardOpen', String(wmCardOpen)) }, [wmCardOpen])
  const [stickersCardOpen, setStickersCardOpen] = useState<boolean>(() => localStorage.getItem('stickersCardOpen') === 'true')
  useEffect(() => { localStorage.setItem('stickersCardOpen', String(stickersCardOpen)) }, [stickersCardOpen])
  const [vizCardOpen, setVizCardOpen] = useState<boolean>(() => localStorage.getItem('vizCardOpen') === 'true')
  useEffect(() => { localStorage.setItem('vizCardOpen', String(vizCardOpen)) }, [vizCardOpen])
  const [subtitleCardOpen, setSubtitleCardOpen] = useState<boolean>(() => localStorage.getItem('subtitleCardOpen') === 'true')
  useEffect(() => { localStorage.setItem('subtitleCardOpen', String(subtitleCardOpen)) }, [subtitleCardOpen])
  // Parsed SRT segments live FE-only — backend stores the raw .srt and re-parses
  // at render time. We keep a copy here for the live preview overlay.
  const [subtitleSegments, setSubtitleSegments] = useState<SubtitleSegment[] | null>(null)
  useEffect(() => {
    const main = document.querySelector('main') as HTMLElement | null
    if (!main) return
    if (currentStep === 7) {
      main.style.paddingRight = '520px'
    } else {
      main.style.paddingRight = ''
    }
    return () => { main.style.paddingRight = '' }
  }, [currentStep])

  // Đo chiều rộng khả dụng của cột preview (step 7) để khung video co lại vừa
  // card thay vì tràn khi cột hẹp hơn kích thước tối đa cứng.
  useEffect(() => {
    if (currentStep !== 7) return
    const el = previewColRef.current
    if (!el) return
    const update = () => setPreviewAvailW(el.clientWidth)
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [currentStep])

  // Fetch font list once on mount
  useEffect(() => {
    axios.get('/api/v1/video/fonts')
      .then(resp => { if (Array.isArray(resp.data) && resp.data.length) setAvailableFonts(resp.data) })
      .catch(() => {})
  }, [])

  // Inject @font-face for preview when font selection changes
  useEffect(() => {
    const id = 'watermark-font-face'
    document.getElementById(id)?.remove()
    const key = videoConfig.watermark_text_font
    if (!key || key.includes('system default')) return
    const fontCssName = key.split(' (')[0]
    const style = document.createElement('style')
    style.id = id
    style.textContent = `@font-face{font-family:'${fontCssName}';src:url('/api/v1/video/fonts/${encodeURIComponent(key)}/file') format('truetype');font-display:swap;}`
    document.head.appendChild(style)
    return () => { document.getElementById(id)?.remove() }
  }, [videoConfig.watermark_text_font])

  // Fetch audio duration when audioPath changes
  useEffect(() => {
    if (!videoConfig.audioPath.trim()) { setAudioDuration(0); return }
    const t = setTimeout(() => {
      axios.get('/api/v1/video/audio-duration', { params: { path: videoConfig.audioPath } })
        .then(resp => setAudioDuration(resp.data.duration || 0))
        .catch(() => setAudioDuration(0))
    }, 300)
    return () => clearTimeout(t)
  }, [videoConfig.audioPath])

  // When audio duration or speed changes, reset playhead so timeline doesn't show
  // a stale position past the new total.
  useEffect(() => {
    setPreviewCurrentTime(0)
    setCurrentClipIdx(0)
    pendingClipOffsetRef.current = 0
    const a = previewAudioRef.current
    if (a) a.currentTime = 0
    const v = previewVideoRef.current
    if (v) v.currentTime = 0
  }, [audioDuration, videoConfig.audio_speed])

  useEffect(() => {
    const a = previewAudioRef.current
    if (a) applyAudioPitchPreserve(a, videoConfig.audio_speed)
  }, [videoConfig.audio_speed])

  useEffect(() => {
    const a = previewAudioRef.current
    if (!a) return
    a.volume = previewVolume
    a.muted = previewVolume === 0
  }, [previewVolume])

  useEffect(() => () => {
    if (exactPollRef.current) window.clearInterval(exactPollRef.current)
  }, [])

  // Per-clip flip state for inline preview. Re-rolls when clip changes or the
  // flip toggle changes, so "Random flip per-clip" mirrors the ffmpeg behavior
  // of deciding hflip independently per clip.
  const inlineClipFlip = useMemo(() => {
    if (videoConfig.ad_flip_all) return true
    if (videoConfig.ad_flip_random) return Math.random() < 0.5
    return false
  }, [currentClipIdx, videoConfig.ad_flip_all, videoConfig.ad_flip_random])

  // Fetch the clip schedule when the folder / order / seed changes. Passing
  // clip_order + seed makes this preview list match the final render's order.
  useEffect(() => {
    if (currentStep !== 7 || !videoConfig.folder.trim()) {
      setClipList([])
      setCurrentClipIdx(0)
      return
    }
    axios.get('/api/v1/video/folder-clips', {
      params: {
        folder: videoConfig.folder,
        limit: 200,
        clip_order: videoConfig.clip_order,
        seed: videoConfig.clip_order === 'shuffle' ? videoConfig.clip_seed : undefined,
      }
    })
      .then(r => {
        const list: ClipInfo[] = r.data?.clips || []
        setClipList(list)
        setCurrentClipIdx(0)
        pendingClipOffsetRef.current = 0
      })
      .catch(() => { setClipList([]); setCurrentClipIdx(0) })
  }, [currentStep, videoConfig.folder, videoConfig.clip_order, videoConfig.clip_seed])

  // Show toast notification
  const showToast = (message: string, type: 'success' | 'error' | 'info' = 'success') => {
    setToast({ isVisible: true, message, type })
    setTimeout(() => {
      setToast(prev => ({ ...prev, isVisible: false }))
    }, 3000)
  }

  // Copy text vào clipboard + báo toast (dùng cho nút copy prompt gợi ý).
  const copyText = async (text: string, okMsg = 'Đã copy') => {
    try {
      await navigator.clipboard.writeText(text)
      showToast(okMsg, 'success')
    } catch {
      showToast('Không copy được, hãy bôi đen và Ctrl+C thủ công', 'error')
    }
  }

  // Download the finished merged audio (the wizard's final deliverable).
  // Desktop (WebView2) can't trigger a programmatic blob download, and the file
  // is already delivered to the user's Downloads folder — so there we just
  // reveal it in Explorer. In a plain browser (dev) we do a real blob download.
  const handleDownloadAudio = async () => {
    const id = storyData.id
    if (!id) {
      showToast('Không tìm thấy truyện để tải audio.', 'error')
      return
    }
    if (hasNativeDialogs()) {
      try {
        await axios.post(`/api/v1/video/reveal-audio/${id}`)
      } catch (err: any) {
        showToast(errMessage(err, 'Không mở được thư mục chứa file.'), 'error')
      }
      return
    }
    setDownloadingAudio(true)
    try {
      const resp = await axios.get(`/api/v1/video/download-audio/${id}`, { responseType: 'blob' })
      const disposition: string = resp.headers['content-disposition'] || ''
      const match = /filename\*?=(?:UTF-8'')?["']?([^"';\n]+)/i.exec(disposition)
      const filename = match ? decodeURIComponent(match[1]) : `audiobook_${id}.mp3`
      const url = window.URL.createObjectURL(resp.data)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch (err: any) {
      // With responseType 'blob', an error body is a Blob — read it back to text
      // so a real backend message (e.g. 404 "chưa có audio") still surfaces.
      let msg = 'Không tải được audio hoàn chỉnh.'
      try {
        const blob = err?.response?.data
        if (blob && typeof blob.text === 'function') {
          const parsed = JSON.parse(await blob.text())
          msg = toMessage(parsed?.detail, msg)
        }
      } catch { /* keep default message */ }
      showToast(msg, 'error')
    } finally {
      setDownloadingAudio(false)
    }
  }

  // Open Explorer (or the OS file manager) at the finished video, with it
  // selected. Works both in the packaged desktop app and dev — the backend
  // runs the file-manager command on the same machine as the server.
  const handleOpenVideoFolder = async () => {
    const id = storyData.id
    if (!id) {
      showToast('Không tìm thấy truyện để mở thư mục.', 'error')
      return
    }
    try {
      await axios.post(`/api/v1/video/reveal-video/${id}`)
    } catch (err: any) {
      showToast(errMessage(err, 'Không mở được thư mục chứa video.'), 'error')
    }
  }

  // Refs for line numbers and highlight sync
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const lineNumbersRef = useRef<HTMLDivElement>(null)
  const highlightRef = useRef<HTMLDivElement>(null)
  const mergedTextareaRef = useRef<HTMLTextAreaElement>(null)
  const mergedHighlightRef = useRef<HTMLDivElement>(null)

  // Sync scroll between textarea, line numbers, and highlight overlay
  const handleTextareaScroll = () => {
    if (textareaRef.current && lineNumbersRef.current) {
      lineNumbersRef.current.scrollTop = textareaRef.current.scrollTop
    }
    if (textareaRef.current && highlightRef.current) {
      highlightRef.current.scrollTop = textareaRef.current.scrollTop
      highlightRef.current.scrollLeft = textareaRef.current.scrollLeft
    }
  }

  // Calculate line numbers
  const getLineNumbers = (text: string) => {
    const lines = text.split('\n')
    return lines.map((_, index) => index + 1)
  }

  // Load story data if storyId exists in URL.
  // The route reuses one component instance across /processor/:storyId, so
  // switching stories does NOT remount — we must tear down the previous story's
  // pollers here, otherwise story A's intervals keep writing over story B's
  // audio/video status.
  useEffect(() => {
    stopPolling()
    if (videoPollingRef.current) {
      clearInterval(videoPollingRef.current)
      videoPollingRef.current = null
    }
    if (storyId) {
      loadStory(storyId)
    }
  }, [storyId])

  // Fetch available voices on mount
  useEffect(() => {
    fetchVoices()
    fetchOmniStatus()
    fetchOmniPresets()
  }, [])

  // While an OmniVoice model download is in progress, poll status every 2s so
  // the progress bar updates; auto-stops when state leaves "downloading".
  useEffect(() => {
    const state = omniStatus?.downloads?.base?.state
    if (state !== 'downloading') return
    const id = setInterval(fetchOmniStatus, 2000)
    return () => clearInterval(id)
  }, [omniStatus?.downloads?.base?.state])

  const loadStory = async (id: string) => {
    try {
      console.log('Loading story:', id)
      const response = await axios.get(`/api/v1/stories/${id}`)
      console.log('Story loaded:', response.data)
      const story = response.data

      setStoryData({
        id: story.id,
        url: story.url || '',
        title: story.title || 'Untitled Project',
        start_chapter: story.start_chapter || 1,
        end_chapter: story.end_chapter || 10,
        status: story.status,
        current_step: story.current_step
      })

      // Load chapters if story has been downloaded
      if (story.status !== 'draft' && story.status !== 'created') {
        await fetchChapters(id)
      }

      // Set current step from database
      // current_step in DB is the max step reached - we can navigate to any step <= this
      if (story.current_step) {
        setCurrentStep(story.current_step)

        // If current step is 3 or higher, load chapter stats
        if (story.current_step >= 3) {
          await fetchChapterStats(id)
        }

        // If current step is 6 (TTS Process), load audio records
        if (story.current_step === 6) {
          await fetchAudioRecords(id)
        }

        // If current step is 7 (Video), load video status + audio path
        if (story.current_step >= 7) {
          try {
            const audioResp = await axios.get(`/api/v1/video/audio-path/${id}`)
            if (audioResp.data.found && audioResp.data.audio_path) {
              setVideoConfig(prev => ({ ...prev, audioPath: audioResp.data.audio_path }))
            }
          } catch {}
          try {
            const videoResp = await axios.get(`/api/v1/video/result/${id}`)
            if (videoResp.data) {
              setVideoStatus({
                status: videoResp.data.status as any,
                taskId: null,
                progress: videoResp.data.status === 'completed' ? 100 : 0,
                outputPath: videoResp.data.output_path,
                error: videoResp.data.error_message
              })
            }
          } catch {
            // No video output yet - this is normal
          }
        }

        // If current step is 4 (Grammar), auto-load merged content
        if (story.current_step === 4) {
          // Will be loaded when component renders
        }
      }
    } catch (error) {
      console.error('Error loading story:', error)
    }
  }

  const fetchVoices = async () => {
    try {
      const response = await axios.get('/api/v1/tts/voices')
      setVoices(response.data.voices || [])
    } catch (error) {
      console.error('Error fetching voices:', error)
    }
  }

  // Search VBEE's live catalog (Việt + Anh) by name. Diacritic-insensitive on
  // the backend, so "ngoc" matches "Ngọc".
  const searchVbeeVoices = async () => {
    const q = voiceSearchQuery.trim()
    setVoiceSearching(true)
    try {
      const res = await axios.get('/api/v1/tts/voices/search', { params: { q } })
      setVoiceSearchResults(res.data.voices || [])
    } catch (error) {
      setVoiceSearchResults([])
      showToast(errMessage(error, 'Không tìm được giọng trên VBEE'), 'error')
    } finally {
      setVoiceSearching(false)
    }
  }

  // Pick a searched voice: route TTS through its code, leaving the DB dropdown
  // selection (dbVoiceCode) untouched so "bỏ" can restore it.
  const useSearchedVoice = (voice: any) => {
    setSearchedVoice(voice)
    setTtsConfig((c) => ({ ...c, voice_code: voice.code }))
    setVoiceSearchResults(null)
  }

  // Drop the searched voice and restore the user's prior DB dropdown selection.
  const clearSearchedVoice = () => {
    setSearchedVoice(null)
    setVoiceSearchQuery('')
    setVoiceSearchResults(null)
    setTtsConfig((c) => ({ ...c, voice_code: dbVoiceCode }))
  }

  // ---- OmniVoice (local TTS) ----
  const fetchOmniStatus = async () => {
    try {
      const res = await axios.get('/api/v1/tts/omnivoice/status')
      setOmniStatus(res.data)
    } catch (error) {
      console.error('Error fetching OmniVoice status:', error)
      setOmniStatus(null)
    }
  }

  const fetchOmniPresets = async () => {
    try {
      const res = await axios.get('/api/v1/tts/omnivoice/presets')
      setOmniPresets(res.data.presets || [])
    } catch (error) {
      console.error('Error fetching OmniVoice presets:', error)
    }
  }

  const handleDownloadOmniModel = async (modelKey: string) => {
    setOmniDownloading(true)
    try {
      await axios.post(`/api/v1/tts/omnivoice/download?model_key=${modelKey}`)
      showToast('Bắt đầu tải model OmniVoice…', 'info')
      await fetchOmniStatus()  // the polling effect below tracks progress from here
    } catch (error: any) {
      showToast(errMessage(error, 'Lỗi khi tải model'), 'error')
    } finally {
      setOmniDownloading(false)
    }
  }

  // Persist the OmniVoice device choice (CPU vs GPU) and refresh status so the
  // availability/reason banners reflect it immediately.
  const handleSetOmniCpu = async (useCpu: boolean) => {
    try {
      await axios.put('/api/v1/settings/', { OMNIVOICE_USE_CPU: useCpu })
      await fetchOmniStatus()
    } catch (error: any) {
      showToast(errMessage(error, 'Lỗi khi đổi thiết bị chạy'), 'error')
    }
  }

  const handleCreatePreset = async () => {
    if (!newPreset.name.trim() || !newPreset.ref_text.trim() || !newPreset.file) {
      showToast('Cần nhập tên, transcript và chọn file audio mẫu', 'error')
      return
    }
    try {
      const fd = new FormData()
      fd.append('name', newPreset.name)
      fd.append('ref_text', newPreset.ref_text)
      fd.append('ref_audio', newPreset.file)
      const res = await axios.post('/api/v1/tts/omnivoice/presets', fd)
      showToast('Đã tạo giọng clone', 'success')
      setNewPreset({ name: '', ref_text: '', file: null })
      await fetchOmniPresets()
      setTtsConfig((c) => ({ ...c, preset_id: res.data.preset?.id || c.preset_id }))
    } catch (error: any) {
      showToast(errMessage(error, 'Lỗi khi tạo giọng clone'), 'error')
    }
  }

  const handleDeletePreset = async (presetId: string) => {
    try {
      await axios.delete(`/api/v1/tts/omnivoice/presets/${presetId}`)
      await fetchOmniPresets()
      setTtsConfig((c) => (c.preset_id === presetId ? { ...c, preset_id: '' } : c))
    } catch (error: any) {
      showToast(errMessage(error, 'Lỗi khi xóa giọng'), 'error')
    }
  }

  const fetchChapters = async (storyId?: string) => {
    const id = storyId || storyData.id
    if (!id) return

    try {
      console.log('Fetching chapters for story:', id)
      const response = await axios.get(`/api/v1/stories/${id}/chapters`)
      console.log('Chapters response:', response.data)
      console.log('Number of chapters:', response.data?.length || 0)
      setChapters(response.data || [])
    } catch (error) {
      console.error('Error fetching chapters:', error)
    }
  }

  const fetchChapterStats = async (storyId?: string) => {
    const id = storyId || storyData.id
    if (!id) return

    try {
      console.log('Fetching chapter stats for story:', id)
      const response = await axios.get(`/api/v1/chapters/story/${id}/stats`)
      console.log('Chapter stats:', response.data)
      setChapterStats(response.data)
    } catch (error) {
      console.error('Error fetching chapter stats:', error)
    }
  }

  const checkStoryGrammar = async (storyId?: string) => {
    const id = storyId || storyData.id
    if (!id) return

    setCheckingGrammar(true)
    try {
      console.log('Checking grammar for story:', id)
      const response = await axios.post(`/api/v1/chapters/story/${id}/check-grammar`)
      console.log('Grammar check result:', response.data)

      // Refresh chapters and stats after checking
      await fetchChapters(id)
      await fetchChapterStats(id)
    } catch (error) {
      console.error('Error checking grammar:', error)
    } finally {
      setCheckingGrammar(false)
    }
  }

  // Create Chapter 0 for intro content
  const createChapterZero = async (storyId: string) => {
    try {
      console.log('Creating Chapter 0 for story:', storyId)
      const response = await axios.post(`/api/v1/chapters/story/${storyId}/create-chapter-zero`)
      console.log('Chapter 0 response:', response.data)
      return response.data
    } catch (error) {
      console.error('Error creating Chapter 0:', error)
      return null
    }
  }

  // Helper function to move to a new step and update DB
  const moveToStep = async (newStep: number) => {
    setCurrentStep(newStep)

    // Load stats and check grammar when entering Step 3
    if (newStep === 3 && storyData.id) {
      // Auto-create Chapter 0 first
      await createChapterZero(storyData.id)
      // Refresh chapters to include Chapter 0
      await fetchChapters(storyData.id)
      await fetchChapterStats(storyData.id)
      await checkStoryGrammar(storyData.id)
    }

    // Auto-fill audio path when entering Video step
    if (newStep === 7 && storyData.id) {
      try {
        const resp = await axios.get(`/api/v1/video/audio-path/${storyData.id}`)
        if (resp.data.found && resp.data.audio_path) {
          setVideoConfig(prev => ({ ...prev, audioPath: resp.data.audio_path }))
        }
      } catch {
        // No merged audio - user will need to input manually
      }
    }

    // Update current_step in DB when moving forward
    if (storyData.id && newStep > (storyData.current_step || 1)) {
      try {
        await axios.put(`/api/v1/stories/${storyData.id}`, {
          current_step: newStep
        })
        // Update local state
        setStoryData(prev => ({ ...prev, current_step: newStep }))
      } catch (error) {
        console.error('Error updating step:', error)
      }
    }
  }

  // Video Processing Functions
  const validateVideoFolder = async () => {
    if (!videoConfig.folder.trim()) return
    try {
      const response = await axios.post('/api/v1/video/validate-folder', {
        folder_path: videoConfig.folder
      })
      const data = response.data
      setFolderValidation({
        valid: data.valid,
        videoCount: data.video_count,
        totalDuration: data.total_duration_formatted,
        checked: true
      })
      if (!data.valid) {
        showToast(data.error || 'Invalid folder', 'error')
      }
    } catch (err: any) {
      setFolderValidation({ valid: false, videoCount: 0, totalDuration: '', checked: true })
      showToast(errMessage(err, 'Không kiểm tra được thư mục'), 'error')
    }
  }

  const startVideoProcessing = async () => {
    if (!storyData.id || !videoConfig.folder.trim() || !videoConfig.audioPath.trim()) return
    try {
      setVideoStatus({ status: 'queued', taskId: null, progress: 0, outputPath: null, error: null })
      const response = await axios.post('/api/v1/video/start', {
        story_id: storyData.id,
        video_source_folder: videoConfig.folder,
        audio_path: videoConfig.audioPath || undefined,
        clip_order: videoConfig.clip_order,
        clip_seed: videoConfig.clip_seed,
        audio_speed: videoConfig.audio_speed,
        transitions_pool: videoConfig.transitions_pool.length ? videoConfig.transitions_pool : undefined,
        transition_duration: videoConfig.transition_duration,
        resolution: videoConfig.resolution,
        banner_image: videoConfig.bannerImage || undefined,
        // Transform (scale/offset) applies with or without a banner — when no
        // banner is set the backend composites the clip onto a black frame.
        banner_video_scale: videoConfig.bannerVideoScaleX,
        banner_video_scale_x: videoConfig.bannerVideoScaleX,
        banner_video_scale_y: videoConfig.bannerVideoScaleY,
        banner_video_rotation: videoConfig.bannerVideoRotation,
        banner_video_offset_x: videoConfig.bannerVideoOffsetX,
        banner_video_offset_y: videoConfig.bannerVideoOffsetY,
        overlay_opacity: videoConfig.overlay_opacity,
        watermark_image: videoConfig.watermarkImage || undefined,
        watermark_x: videoConfig.watermark_x,
        watermark_y: videoConfig.watermark_y,
        watermark_w: videoConfig.watermark_w,
        watermark_h: videoConfig.watermark_h,
        watermark_shape: videoConfig.watermark_shape,
        watermark_opacity: videoConfig.watermark_opacity,
        watermark_text: videoConfig.watermark_text || undefined,
        watermark_text_font: videoConfig.watermark_text_font,
        watermark_text_size: videoConfig.watermark_text_size,
        watermark_text_color: videoConfig.watermark_text_color,
        watermark_text_angle: videoConfig.watermark_text_angle,
        watermark_text_x: videoConfig.watermark_text_x,
        watermark_text_y: videoConfig.watermark_text_y,
        watermark_text_opacity: videoConfig.watermark_text_opacity,
        subtitle_srt_path: videoConfig.subtitle_srt_path || undefined,
        subtitle_animation: videoConfig.subtitle_animation,
        subtitle_font: videoConfig.subtitle_font,
        subtitle_font_size: videoConfig.subtitle_font_size,
        subtitle_color: videoConfig.subtitle_color,
        subtitle_outline_color: videoConfig.subtitle_outline_color,
        subtitle_outline_width: videoConfig.subtitle_outline_width,
        subtitle_shadow: videoConfig.subtitle_shadow,
        subtitle_bold: videoConfig.subtitle_bold,
        subtitle_italic: videoConfig.subtitle_italic,
        subtitle_align: videoConfig.subtitle_align,
        subtitle_x: videoConfig.subtitle_x,
        subtitle_y: videoConfig.subtitle_y,
        subtitle_opacity: videoConfig.subtitle_opacity,
        fade_in: videoConfig.fade_in,
        fade_out: videoConfig.fade_out,
        mute_source_videos: videoConfig.mute_source_videos,
        bgm_path: videoConfig.bgmPath || undefined,
        bgm_volume: videoConfig.bgm_volume,
        bgm_loop: videoConfig.bgm_loop,
        bgm_ducking: videoConfig.bgm_ducking,
        bgm_fade: videoConfig.bgm_fade,
        ad_flip_random: videoConfig.ad_flip_random,
        ad_flip_all: videoConfig.ad_flip_all,
        ad_zoom: videoConfig.ad_zoom,
        ad_zoom_factor: videoConfig.ad_zoom_factor,
        ad_color: videoConfig.ad_color,
        ad_saturation: videoConfig.ad_saturation,
        ad_contrast: videoConfig.ad_contrast,
        ad_gamma: videoConfig.ad_gamma,
        ad_hue_shift: videoConfig.ad_hue_shift,
        ad_clip_speed_jitter: videoConfig.ad_clip_speed_jitter,
        ad_clip_speed_jitter_range: videoConfig.ad_clip_speed_jitter_range,
        ad_strip_metadata: videoConfig.ad_strip_metadata,
        visualizer_enabled: videoConfig.visualizer_enabled,
        visualizer_style: videoConfig.visualizer_style,
        visualizer_x: videoConfig.visualizer_x,
        visualizer_y: videoConfig.visualizer_y,
        visualizer_w: videoConfig.visualizer_w,
        visualizer_h: videoConfig.visualizer_h,
        visualizer_color1: videoConfig.visualizer_color1,
        visualizer_color2: videoConfig.visualizer_color2,
        visualizer_opacity: videoConfig.visualizer_opacity,
        visualizer_bg_mode: videoConfig.visualizer_bg_mode,
        visualizer_bg_color: videoConfig.visualizer_bg_color,
        visualizer_bg_opacity: videoConfig.visualizer_bg_opacity,
        visualizer_spectrum_preset: videoConfig.visualizer_spectrum_preset,
        visualizer_bars_mode: videoConfig.visualizer_bars_mode,
        visualizer_waveform_mode: videoConfig.visualizer_waveform_mode,
        visualizer_waveform_mirror: videoConfig.visualizer_waveform_mirror,
        stickers: videoConfig.stickers.map(toBackendSticker),
      })
      setVideoStatus(prev => ({ ...prev, taskId: response.data.task_id, status: 'queued' }))
      startVideoPolling(response.data.task_id)
    } catch (err: any) {
      setVideoStatus(prev => ({
        ...prev,
        status: 'failed',
        error: errMessage(err, 'Không bắt đầu được xử lý video')
      }))
    }
  }

  const startVideoPolling = (taskId: string) => {
    if (videoPollingRef.current) clearInterval(videoPollingRef.current)
    const interval = setInterval(async () => {
      try {
        const response = await axios.get(`/api/v1/video/${taskId}/status`)
        const task = response.data
        setVideoStatus(prev => ({
          ...prev,
          status: task.status === 'completed' ? 'completed' : task.status === 'failed' ? 'failed' : 'running',
          progress: task.progress || 0,
          error: task.error_message
        }))
        if (task.status === 'completed' || task.status === 'failed') {
          clearInterval(interval)
          videoPollingRef.current = null
          if (task.status === 'completed') {
            try {
              const resultResp = await axios.get(`/api/v1/video/result/${storyData.id}`)
              setVideoStatus(prev => ({ ...prev, outputPath: resultResp.data.output_path }))
            } catch {}
            showToast('Video processing completed!', 'success')
          } else {
            showToast(task.error_message || 'Video processing failed', 'error')
          }
        }
      } catch (err) {
        console.error('Error polling video status:', err)
      }
    }, 10000)
    videoPollingRef.current = interval
  }

  const fetchVideoStatus = async () => {
    if (!storyData.id) return
    try {
      const response = await axios.get(`/api/v1/video/result/${storyData.id}`)
      const data = response.data
      setVideoStatus({
        status: data.status as any,
        taskId: null,
        progress: data.status === 'completed' ? 100 : 0,
        outputPath: data.output_path,
        error: data.error_message
      })
    } catch {
      // No video output yet
    }
  }

  const openFolderBrowser = async (startPath?: string) => {
    // In the packaged desktop app, use the native Windows folder picker.
    if (hasNativeDialogs()) {
      const picked = await pickFolderNative(startPath)
      if (picked) {
        setVideoConfig(prev => ({ ...prev, folder: picked }))
        setFolderValidation({ valid: false, videoCount: 0, totalDuration: '', checked: false })
      }
      return
    }
    setFolderBrowser(prev => ({ ...prev, isOpen: true, loading: true }))
    try {
      const response = await axios.post('/api/v1/video/browse', { path: startPath || '' })
      setFolderBrowser({
        isOpen: true,
        currentPath: response.data.current_path,
        parentPath: response.data.parent_path,
        folders: response.data.folders,
        videoCount: response.data.video_count,
        loading: false
      })
    } catch (err: any) {
      setFolderBrowser(prev => ({ ...prev, loading: false }))
      showToast(errMessage(err, 'Không duyệt được thư mục'), 'error')
    }
  }

  const navigateFolder = async (folderName: string) => {
    const newPath = folderBrowser.currentPath
      ? `${folderBrowser.currentPath.replace(/[\\/]$/, '')}${folderBrowser.currentPath.includes('/') ? '/' : '\\'}${folderName}`
      : folderName
    await openFolderBrowser(newPath)
  }

  const selectFolder = () => {
    if (folderBrowser.currentPath) {
      setVideoConfig(prev => ({ ...prev, folder: folderBrowser.currentPath }))
      setFolderValidation({ valid: false, videoCount: 0, totalDuration: '', checked: false })
      setFolderBrowser(prev => ({ ...prev, isOpen: false }))
    }
  }

  // Audio file browser functions
  const openAudioBrowser = async (startPath?: string, isFilePath: boolean = false, target?: 'main' | 'bgm') => {
    if (target !== undefined) setAudioBrowserTarget(target)
    const tgt = target !== undefined ? target : audioBrowserTarget
    // In the packaged desktop app, use the native Windows file picker.
    if (hasNativeDialogs()) {
      const picked = await pickAudioFileNative(startPath)
      if (picked) {
        if (tgt === 'bgm') setVideoConfig(prev => ({ ...prev, bgmPath: picked }))
        else setVideoConfig(prev => ({ ...prev, audioPath: picked }))
      }
      return
    }
    setAudioBrowser(prev => ({ ...prev, isOpen: true, loading: true }))
    try {
      let dirPath = startPath || ''
      // If startPath is a file path, extract the directory part
      if (isFilePath && dirPath && !dirPath.endsWith('\\') && !dirPath.endsWith('/')) {
        const lastSep = Math.max(dirPath.lastIndexOf('\\'), dirPath.lastIndexOf('/'))
        if (lastSep > 0) dirPath = dirPath.substring(0, lastSep + 1)
      }
      const response = await axios.post('/api/v1/video/browse-files', { path: dirPath })
      setAudioBrowser({
        isOpen: true,
        currentPath: response.data.current_path,
        parentPath: response.data.parent_path,
        folders: response.data.folders,
        files: response.data.files,
        loading: false
      })
    } catch (err: any) {
      setAudioBrowser(prev => ({ ...prev, loading: false }))
      showToast(errMessage(err, 'Không duyệt được tệp'), 'error')
    }
  }

  const navigateAudioFolder = async (folderName: string) => {
    const newPath = audioBrowser.currentPath
      ? `${audioBrowser.currentPath.replace(/[\\/]$/, '')}${audioBrowser.currentPath.includes('/') ? '/' : '\\'}${folderName}`
      : folderName
    await openAudioBrowser(newPath)
  }

  const selectAudioFile = (fileName: string) => {
    const sep = audioBrowser.currentPath.includes('/') ? '/' : '\\'
    const fullPath = `${audioBrowser.currentPath.replace(/[\\/]$/, '')}${sep}${fileName}`
    if (audioBrowserTarget === 'bgm') {
      setVideoConfig(prev => ({ ...prev, bgmPath: fullPath }))
    } else {
      setVideoConfig(prev => ({ ...prev, audioPath: fullPath }))
    }
    setAudioBrowser(prev => ({ ...prev, isOpen: false }))
  }

  // Image file browser functions
  const [imageBrowserTarget, setImageBrowserTarget] = useState<'banner' | 'watermark'>('banner')
  // target is optional; only set when explicitly passed (so folder navigation
  // doesn't reset the target back to 'banner').
  const openImageBrowser = async (startPath?: string, isFilePath: boolean = false, target?: 'banner' | 'watermark') => {
    if (target !== undefined) setImageBrowserTarget(target)
    // In the packaged desktop app, use the native Windows file picker.
    if (hasNativeDialogs()) {
      const tgt = target !== undefined ? target : imageBrowserTarget
      const picked = await pickImageFileNative(startPath)
      if (picked) {
        if (tgt === 'watermark') setVideoConfig(prev => ({ ...prev, watermarkImage: picked }))
        else setVideoConfig(prev => ({ ...prev, bannerImage: picked }))
      }
      return
    }
    setImageBrowser(prev => ({ ...prev, isOpen: true, loading: true }))
    try {
      let dirPath = startPath || ''
      if (isFilePath && dirPath && !dirPath.endsWith('\\') && !dirPath.endsWith('/')) {
        const lastSep = Math.max(dirPath.lastIndexOf('\\'), dirPath.lastIndexOf('/'))
        if (lastSep > 0) dirPath = dirPath.substring(0, lastSep + 1)
      }
      const response = await axios.post('/api/v1/video/browse-images', { path: dirPath })
      setImageBrowser({
        isOpen: true,
        currentPath: response.data.current_path,
        parentPath: response.data.parent_path,
        folders: response.data.folders,
        files: response.data.files,
        loading: false
      })
    } catch (err: any) {
      setImageBrowser(prev => ({ ...prev, loading: false }))
      showToast(errMessage(err, 'Không duyệt được ảnh'), 'error')
    }
  }

  const navigateImageFolder = async (folderName: string) => {
    const newPath = imageBrowser.currentPath
      ? `${imageBrowser.currentPath.replace(/[\\/]$/, '')}${imageBrowser.currentPath.includes('/') ? '/' : '\\'}${folderName}`
      : folderName
    await openImageBrowser(newPath)
  }

  const selectImageFile = (fileName: string) => {
    const sep = imageBrowser.currentPath.includes('/') ? '/' : '\\'
    const fullPath = `${imageBrowser.currentPath.replace(/[\\/]$/, '')}${sep}${fileName}`
    if (imageBrowserTarget === 'watermark') {
      setVideoConfig(prev => ({ ...prev, watermarkImage: fullPath }))
    } else {
      setVideoConfig(prev => ({ ...prev, bannerImage: fullPath }))
    }
    setImageBrowser(prev => ({ ...prev, isOpen: false }))
  }

  // Persist video config to localStorage
  useEffect(() => {
    localStorage.setItem('videoConfig_folder', videoConfig.folder)
    localStorage.setItem('videoConfig_bannerImage', videoConfig.bannerImage)
    localStorage.setItem('videoConfig_bannerVideoScaleX', String(videoConfig.bannerVideoScaleX))
    localStorage.setItem('videoConfig_bannerVideoScaleY', String(videoConfig.bannerVideoScaleY))
    localStorage.setItem('videoConfig_bannerVideoOffsetX', String(videoConfig.bannerVideoOffsetX))
    localStorage.setItem('videoConfig_bannerVideoOffsetY', String(videoConfig.bannerVideoOffsetY))
    localStorage.setItem('videoConfig_bannerVideoRotation', String(videoConfig.bannerVideoRotation))
    localStorage.setItem('videoConfig_watermarkImage', videoConfig.watermarkImage)
    localStorage.setItem('videoConfig_bgmPath', videoConfig.bgmPath)
    const { folder, audioPath, bannerImage, bannerVideoScaleX, bannerVideoScaleY, bannerVideoRotation, bannerVideoOffsetX, bannerVideoOffsetY, watermarkImage, bgmPath, ...cfg } = videoConfig
    localStorage.setItem('videoConfig_cfg', JSON.stringify(cfg))
  }, [videoConfig])

  // Load presets from server on mount
  useEffect(() => {
    axios.get<VideoPresetRow[]>('/api/v1/video-presets/')
      .then(res => setVideoPresets(res.data))
      .catch(err => {
        console.error('Failed to load video presets:', err)
        showToast('Không tải được danh sách preset', 'error')
      })
  }, [])

  const extractCfgFromConfig = () => {
    // Chỉ loại đường dẫn file cụ thể; giữ lại banner transform để preset tái lập bố cục.
    const { folder, audioPath, bannerImage, watermarkImage, bgmPath, ...cfg } = videoConfig
    return cfg
  }

  const savePreset = () => {
    setPresetModal({ isOpen: true, mode: 'create', name: '', presetId: null })
  }

  const renamePreset = () => {
    const cur = videoPresets.find(p => p.id === selectedPresetId)
    if (!cur) return
    setPresetModal({ isOpen: true, mode: 'rename', name: cur.name, presetId: cur.id })
  }

  const confirmPresetModal = async () => {
    const name = presetModal.name.trim()
    if (!name) {
      showToast('Tên preset không được để trống', 'error')
      return
    }

    try {
      if (presetModal.mode === 'create') {
        const res = await axios.post<VideoPresetRow>('/api/v1/video-presets/', {
          name,
          cfg: extractCfgFromConfig(),
        })
        setVideoPresets(prev => [res.data, ...prev])
        setSelectedPresetId(res.data.id)
        setPresetModal({ isOpen: false, mode: 'create', name: '', presetId: null })
        showToast(`Đã lưu preset "${name}"`, 'success')
      } else if (presetModal.mode === 'rename' && presetModal.presetId) {
        const res = await axios.put<VideoPresetRow>(
          `/api/v1/video-presets/${presetModal.presetId}`,
          { name },
        )
        setVideoPresets(prev => prev.map(p => (p.id === res.data.id ? res.data : p)))
        setPresetModal({ isOpen: false, mode: 'create', name: '', presetId: null })
        showToast(`Đã đổi tên preset thành "${name}"`, 'success')
      }
    } catch (err: any) {
      const msg = errMessage(err, 'Lỗi không xác định')
      showToast(msg, 'error')
    }
  }

  const loadPreset = (id: string) => {
    const preset = videoPresets.find(p => p.id === id)
    if (!preset) return
    // Clone + migrate so old presets (with *_position string) get x/y applied.
    const cfg = migrateOldCfg(JSON.parse(JSON.stringify(preset.cfg)))
    setVideoConfig(prev => ({ ...prev, ...cfg }))
  }

  const updateSelectedPresetCfg = () => {
    if (!selectedPresetId) return
    const cur = videoPresets.find(p => p.id === selectedPresetId)
    if (!cur) return
    setConfirmDialog({
      isOpen: true,
      title: ' Cập nhật preset',
      message: `Ghi đè preset "${cur.name}" bằng config hiện tại?`,
      confirmText: 'Cập nhật',
      variant: 'primary',
      onConfirm: async () => {
        try {
          const res = await axios.put<VideoPresetRow>(
            `/api/v1/video-presets/${selectedPresetId}`,
            { cfg: extractCfgFromConfig() },
          )
          setVideoPresets(prev => prev.map(p => (p.id === res.data.id ? res.data : p)))
          showToast(`Đã cập nhật preset "${cur.name}"`, 'success')
        } catch (err: any) {
          const msg = errMessage(err, 'Lỗi không xác định')
          showToast(msg, 'error')
        }
      },
    })
  }

  const deletePreset = async (id: string) => {
    const cur = videoPresets.find(p => p.id === id)
    if (!cur) return
    try {
      await axios.delete(`/api/v1/video-presets/${id}`)
      setVideoPresets(prev => prev.filter(p => p.id !== id))
      setSelectedPresetId(prev => (prev === id ? '' : prev))
      showToast(`Đã xoá preset "${cur.name}"`, 'success')
    } catch (err: any) {
      const msg = errMessage(err, 'Lỗi không xác định')
      showToast(msg, 'error')
    }
  }

  const toggleTransition = (t: string) => {
    setVideoConfig(prev => ({
      ...prev,
      transitions_pool: prev.transitions_pool.includes(t)
        ? prev.transitions_pool.filter(x => x !== t)
        : [...prev.transitions_pool, t]
    }))
  }

  // Cleanup video polling on unmount
  useEffect(() => {
    return () => {
      if (videoPollingRef.current) clearInterval(videoPollingRef.current)
    }
  }, [])

  // Step 1: Update story info and start download
  // Ensure a story row exists (the route normally already created one) and
  // return its id. Used by the content-import handlers below.
  const ensureStoryId = async (): Promise<string> => {
    if (storyData.id) return storyData.id
    const resp = await axios.post('/api/v1/stories', {
      title: storyData.title || 'Truyện mới',
      url: '',
      start_chapter: 1,
      end_chapter: 1,
    })
    const id = resp.data.id
    setStoryData({ ...storyData, id })
    return id
  }

  const afterImport = async (id: string) => {
    await fetchChapters(id)
    await fetchChapterStats(id)
    moveToStep(3)
  }

  // Mode A — split the pasted text on the client and import the chapters.
  const handlePasteImport = async () => {
    if (pastePreview.length === 0) {
      setError('Chưa có nội dung để nhập.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const id = await ensureStoryId()
      await axios.post(`/api/v1/chapters/story/${id}/import`, {
        title: storyData.title || undefined,
        chapters: pastePreview,
      })
      await afterImport(id)
    } catch (err: any) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Nhập nội dung thất bại.')
    } finally {
      setLoading(false)
    }
  }

  // Mode B/C — pick a file/folder via the native dialog; the backend reads it.
  const handlePathImport = async (mode: 'file' | 'folder') => {
    const path = mode === 'file' ? await pickTextFileNative() : await pickFolderNative()
    if (!path) return
    setLoading(true)
    setError(null)
    try {
      const id = await ensureStoryId()
      const endpoint = mode === 'file' ? 'import-file' : 'import-folder'
      await axios.post(`/api/v1/chapters/story/${id}/${endpoint}`, {
        path,
        title: storyData.title || undefined,
      })
      await afterImport(id)
    } catch (err: any) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Nhập nội dung thất bại.')
    } finally {
      setLoading(false)
    }
  }

  const handleSubmitURL = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    setDuplicateStory(null)

    try {
      let currentStoryId = storyData.id

      // Update or create story
      if (currentStoryId) {
        // Update existing story
        console.log('Updating story:', currentStoryId, storyData)
        await axios.put(`/api/v1/stories/${currentStoryId}`, {
          title: storyData.title,
          url: storyData.url,
          start_chapter: storyData.start_chapter,
          end_chapter: storyData.end_chapter,
          custom_chapter_urls: storyData.custom_chapter_urls || null
        })
        console.log('Story updated')
      } else {
        // Create new story (fallback)
        console.log('Creating story:', storyData)
        const storyResponse = await axios.post('/api/v1/stories', storyData)
        console.log('Story created:', storyResponse.data)
        currentStoryId = storyResponse.data.id
        setStoryData({ ...storyData, id: currentStoryId })
      }

      // Start download (waits for completion)
      console.log('Starting download for story:', currentStoryId)
      const downloadResponse = await axios.post('/api/v1/download/start', {
        story_id: currentStoryId
      })
      console.log('Download response:', downloadResponse.data)

      if (downloadResponse.data.status === 'completed') {
        console.log('Download completed, fetching chapters...')
        await fetchChapters(currentStoryId)
        moveToStep(3)
      } else {
        console.warn('Download status is not completed:', downloadResponse.data.status)
      }
    } catch (error: any) {
      console.error('Error during download:', error)

      // Check if this is a duplicate story error (HTTP 409)
      if (error.response?.status === 409) {
        const detail = error.response.data?.detail
        if (typeof detail === 'object' && detail.existing_story_id) {
          // Handle duplicate story
          setDuplicateStory({
            id: detail.existing_story_id,
            title: detail.existing_story_title
          })
          setError(detail.message || 'Story already exists with same URL and chapter range')
        } else {
          setError('Story already exists')
        }
      } else {
        // Handle other errors
        const detail = error.response?.data?.detail
        setError(typeof detail === 'string' ? detail : 'Failed to download chapters')
      }
    } finally {
      setLoading(false)
    }
  }

  // Step 3->4: Save chapters, generate & save merged content, then move to Grammar
  const handleSaveChapters = async () => {
    if (!storyData.id) return

    setLoading(true)
    try {
      // Step 1: Update story status
      await axios.put(`/api/v1/stories/${storyData.id}`, {
        status: 'ready_for_tts',
        current_step: 4
      })

      // Step 2: Get merged content (generated from chapters)
      const response = await axios.get(`/api/v1/stories/${storyData.id}/merged-content`)
      const mergedContent = response.data.merged_content

      // Step 3: Save merged content to DB
      await axios.put(`/api/v1/stories/${storyData.id}/merged-content`, {
        merged_content: mergedContent
      })

      // Step 4: Update local state
      setMergedView(prev => ({
        ...prev,
        content: mergedContent,
        isOpen: true
      }))

      showToast('Đã lưu nội dung ghép vào DB', 'success')
      moveToStep(4)
    } catch (error) {
      console.error('Error saving chapters:', error)
      showToast('Lỗi khi lưu, nhưng vẫn chuyển sang bước tiếp', 'error')
      moveToStep(4) // Move forward anyway
    } finally {
      setLoading(false)
    }
  }

  // Step 5->6: Start TTS processing (merged content)
  const handleStartTTS = async () => {
    if (!storyData.id) return

    setLoading(true)
    setError(null)

    try {
      // Move to Step 6 first
      await moveToStep(6)

      // OmniVoice → per-segment workspace (split, run per line, merge). Don't
      // auto-generate; just land on the step. Segments are (re)loaded/split by
      // the step's own effect. VBEE keeps the classic one-shot merged flow.
      if (ttsConfig.engine === 'omnivoice') {
        return
      }

      // Start merged TTS processing (VBEE)
      console.log('Starting merged TTS processing...')
      const response = await axios.post('/api/v1/tts/start-merged', {
        story_id: storyData.id,
        ...ttsConfig
      })

      console.log('TTS started:', response.data)
      showToast(`Đang xử lý TTS cho ${response.data.char_count?.toLocaleString()} ký tự...`, 'info')

      // Start polling for status
      startMergedPolling()

    } catch (error: any) {
      console.error('Error during TTS:', error)
      setError(errMessage(error, 'Lỗi khi xử lý TTS'))
      showToast(errMessage(error, 'Lỗi khi xử lý TTS'), 'error')
    } finally {
      setLoading(false)
    }
  }

  // Fetch audio records
  const fetchAudioRecords = async (storyId?: string) => {
    const id = storyId || storyData.id
    if (!id) return

    try {
      const response = await axios.get(`/api/v1/tts/audio-status/${id}`)
      setAudioRecords(response.data.audio_records || [])
    } catch (error) {
      console.error('Error fetching audio records:', error)
    }
  }

  // Start polling for audio status
  const startPolling = () => {
    // Clear existing interval
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
    }

    // Poll every 30 seconds
    pollingRef.current = setInterval(() => {
      fetchAudioRecords()
    }, 30000)
  }

  // Stop polling
  const stopPolling = () => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
    watchingMergeRef.current = false
  }

  // Fetch merged TTS status
  const fetchMergedTtsStatus = async () => {
    if (!storyData.id) return

    try {
      const response = await axios.get(`/api/v1/tts/merged-status/${storyData.id}`, {
        params: { engine: ttsConfig.engine },
      })
      const data = response.data

      setMergedTtsStatus({
        status: data.task_status || 'idle',
        charCount: data.char_count || 0,
        audioFile: data.audio_file,
        audioSize: data.audio_size,
        error: data.task_error
      })

      // Announce the result only when we were actively watching a merge we just
      // started (stopPolling clears the flag, so capture it first). Without this,
      // merely opening step 6 on an already-merged story would re-fire the toast.
      if (data.task_status === 'completed' || data.task_status === 'failed') {
        const wasWatching = watchingMergeRef.current
        stopPolling()
        if (wasWatching && data.task_status === 'completed') {
          showToast('TTS hoàn thành!', 'success')
        } else if (wasWatching && data.task_status === 'failed') {
          showToast(`TTS thất bại: ${data.task_error}`, 'error')
        }
      }
    } catch (error) {
      console.error('Error fetching merged TTS status:', error)
    }
  }

  // Start polling for merged TTS status
  const startMergedPolling = () => {
    // Clear existing interval
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
    }

    // We initiated this merge → allow its completion toast to fire (set before
    // the immediate fetch below so a fast-completing run still announces).
    watchingMergeRef.current = true

    // Poll immediately
    fetchMergedTtsStatus()

    // Poll every 10 seconds
    pollingRef.current = setInterval(() => {
      fetchMergedTtsStatus()
    }, 10000)
  }

  // ===== Per-segment TTS (OmniVoice, Step 6) =====
  const segStats = useMemo(() => {
    const total = segments.length
    const by = { pending: 0, processing: 0, done: 0, error: 0 }
    for (const s of segments) by[s.status]++
    return { total, ...by, allDone: total > 0 && by.done === total }
  }, [segments])

  // Estimated time left for the remaining (pending/error/processing) segments,
  // based on this run's own actual gen_sec/char rate — no hardcoded guess.
  const segEtaSec = useMemo(() => {
    let doneChars = 0, doneGenSec = 0
    for (const s of segments) {
      if (s.status === 'done' && s.gen_sec) { doneChars += s.text.length; doneGenSec += s.gen_sec }
    }
    if (doneChars === 0) return null
    const rate = doneGenSec / doneChars
    let remainingChars = 0
    for (const s of segments) {
      if (s.status === 'pending' || s.status === 'error' || s.status === 'processing') remainingChars += s.text.length
    }
    return remainingChars > 0 ? rate * remainingChars : null
  }, [segments])

  const formatEta = (sec: number) => {
    const total = Math.max(1, Math.round(sec))
    const m = Math.floor(total / 60)
    const s = total % 60
    return m > 0 ? `${m}m ${s}s` : `${s}s`
  }

  const stopSegPolling = () => {
    if (segPollRef.current) {
      clearInterval(segPollRef.current)
      segPollRef.current = null
    }
  }

  const fetchSegments = async (opts?: { silent?: boolean }) => {
    if (!storyData.id) return null
    try {
      const res = await axios.get(`/api/v1/tts/segments/${storyData.id}`)
      const segs: TtsSegment[] = res.data.segments || []
      setSegments(segs)
      setSegSourceChanged(!!res.data.source_changed)
      if (res.data.split_mode) setSplitMode(res.data.split_mode)
      // Stop polling once the backend reports no batch/retry is running. We rely
      // on the server's `running` flag rather than segment statuses because after
      // a cancel some segments stay 'pending' with nothing actually generating —
      // keying off 'pending' would poll forever. `running` is true from the moment
      // /run acquires the story (before the first 'processing'), so no startup race.
      // `running` is authoritative: the server sets it true the moment /run or a
      // retry acquires the story and keeps it true until the task's finally
      // releases it, so it's true for the whole generation. We deliberately do
      // NOT also treat a 'processing' segment as running — a row left stuck in
      // 'processing' by a crashed process would otherwise make this poll forever.
      const running = !!res.data.running
      setSegRunning(running)
      if (segPollRef.current && !running) stopSegPolling()
      return res.data
    } catch (e) {
      if (!opts?.silent) console.error('fetchSegments error', e)
      return null
    }
  }

  const startSegPolling = () => {
    stopSegPolling()
    fetchSegments({ silent: true })
    segPollRef.current = setInterval(() => fetchSegments({ silent: true }), 4000)
  }

  const handleSplitSegments = async () => {
    if (!storyData.id) return
    setSegBusy(true)
    setError(null)
    try {
      const res = await axios.post('/api/v1/tts/segments/split', {
        story_id: storyData.id,
        ...ttsConfig,
        split_mode: splitMode,
      })
      setSegments(res.data.segments || [])
      setSegSourceChanged(false)
      showToast(`Đã tách ${res.data.segments?.length || 0} câu.`, 'success')
    } catch (e: any) {
      showToast(errMessage(e, 'Lỗi khi tách câu'), 'error')
    } finally {
      setSegBusy(false)
    }
  }

  const handleRunSegments = async () => {
    if (!storyData.id) return
    setSegBusy(true)
    try {
      const res = await axios.post('/api/v1/tts/segments/run', { story_id: storyData.id, ...ttsConfig })
      if (res.data.status === 'started') {
        showToast(`Đang đọc ${res.data.queued} câu...`, 'info')
        startSegPolling()
      } else if (res.data.status === 'busy') {
        showToast(res.data.message || 'Đang chạy, vui lòng chờ...', 'info')
        startSegPolling()   // a run is already active — reflect its progress
      } else {
        showToast(res.data.message || 'Tất cả câu đã xong.', 'info')
      }
    } catch (e: any) {
      showToast(errMessage(e, 'Lỗi khi chạy TTS'), 'error')
    } finally {
      setSegBusy(false)
    }
  }

  // Re-synthesise EVERY sentence with the current voice/settings — for when the
  // user changed the voice (or speed/bitrate/…) after some/all audio was already
  // generated. Confirmed first because it throws away all existing audio.
  const handleRegenerateAll = () => {
    if (!storyData.id) return
    setConfirmDialog({
      isOpen: true,
      title: '♻️ Tạo lại toàn bộ',
      message: 'Xóa toàn bộ audio đã tạo và đọc lại TẤT CẢ câu bằng giọng/thiết lập hiện tại?\n\nDùng khi bạn vừa đổi giọng hoặc thiết lập. Không thể hoàn tác.',
      confirmText: 'Tạo lại toàn bộ',
      variant: 'danger',
      onConfirm: async () => {
        setSegBusy(true)
        try {
          const res = await axios.post('/api/v1/tts/segments/run', { story_id: storyData.id, ...ttsConfig, regenerate_all: true })
          if (res.data.status === 'started') {
            showToast(`Đang tạo lại ${res.data.queued} câu...`, 'info')
            startSegPolling()
          } else if (res.data.status === 'busy') {
            showToast(res.data.message || 'Đang chạy, vui lòng chờ...', 'info')
            startSegPolling()
          } else {
            showToast(res.data.message || 'Không có câu nào để tạo lại.', 'info')
          }
        } catch (e: any) {
          showToast(errMessage(e, 'Lỗi khi tạo lại TTS'), 'error')
        } finally {
          setSegBusy(false)
        }
      },
    })
  }

  // Stop the batch after the current sentence. Confirmed first so an accidental
  // click can't throw away an in-progress run.
  const handleCancelSegments = () => {
    if (!storyData.id) return
    setConfirmDialog({
      isOpen: true,
      title: '⏸ Dừng chạy TTS',
      message: 'Dừng sinh audio cho các câu còn lại?\n\nCâu đang chạy sẽ được sinh nốt cho xong. Các câu chưa chạy giữ nguyên để bạn có thể "Chạy TTS tất cả" tiếp sau này.',
      confirmText: 'Dừng lại',
      variant: 'danger',
      onConfirm: async () => {
        try {
          const res = await axios.post('/api/v1/tts/segments/cancel', { story_id: storyData.id })
          showToast(res.data?.message || 'Đang dừng…', 'info')
          fetchSegments({ silent: true })   // reflect the current segment finishing then stopping
        } catch (e: any) {
          showToast(errMessage(e, 'Lỗi khi dừng TTS'), 'error')
        }
      },
    })
  }

  const handleRetrySegment = async (segId: string) => {
    if (!storyData.id) return
    try {
      const res = await axios.post(`/api/v1/tts/segments/${segId}/retry`, { story_id: storyData.id, ...ttsConfig })
      if (res.data.status === 'busy') {
        showToast(res.data.message || 'Đang chạy, vui lòng chờ...', 'info')
        startSegPolling()
        return
      }
      // Optimistically mark processing, then poll for the result.
      setSegments(prev => prev.map(s => s.id === segId ? { ...s, status: 'processing', error_message: null } : s))
      startSegPolling()
    } catch (e: any) {
      showToast(errMessage(e, 'Lỗi khi chạy lại câu'), 'error')
    }
  }

  const handleDeleteSegment = async (segId: string) => {
    try {
      await axios.delete(`/api/v1/tts/segments/${segId}`)
      await fetchSegments({ silent: true })
    } catch (e: any) {
      showToast(errMessage(e, 'Lỗi khi xóa câu'), 'error')
    }
  }

  const handleMergeSegments = async () => {
    if (!storyData.id) return
    setSegMerging(true)
    setMergedTtsStatus(s => ({ ...s, status: 'running', error: null }))
    try {
      await axios.post('/api/v1/tts/segments/merge', { story_id: storyData.id })
      startMergedPolling()   // reuse merged-status polling for the final file
      showToast('Đang ghép các câu thành 1 file...', 'info')
    } catch (e: any) {
      setMergedTtsStatus(s => ({ ...s, status: 'failed', error: errMessage(e, 'Lỗi khi ghép') }))
      showToast(errMessage(e, 'Lỗi khi ghép audio'), 'error')
    } finally {
      setSegMerging(false)
    }
  }

  // Tự động gộp thành 1 file ngay khi một đợt TTS vừa chạy xong (segRunning: true -> false)
  // và tất cả câu đã "Đã xong". Chỉ chạy khi user bật tuỳ chọn autoMergeAfterTts.
  // Bám vào lần chuyển trạng thái nên không tự gộp lại mỗi khi mở lại bước 6.
  useEffect(() => {
    const wasRunning = prevSegRunningRef.current
    prevSegRunningRef.current = segRunning
    if (
      wasRunning && !segRunning &&
      autoMergeAfterTts &&
      segStats.allDone &&
      !segMerging &&
      mergedTtsStatus.status !== 'running'
    ) {
      handleMergeSegments()
    }
  }, [segRunning])

  const toggleSegPlay = (seg: TtsSegment) => {
    if (!seg.has_audio) return
    const el = segAudioRef.current
    if (!el) return
    if (segNowPlaying === seg.id) {
      el.pause()
      setSegNowPlaying(null)
      return
    }
    el.src = `/api/v1/tts/segments/${seg.id}/audio`
    el.play().then(() => setSegNowPlaying(seg.id)).catch(() => setSegNowPlaying(null))
  }

  // Check if all audio records are completed (success, skipped, or failed)
  const checkAllCompleted = () => {
    if (audioRecords.length === 0) return false

    const hasProcessing = audioRecords.some(r => r.status === 'idle' || r.status === 'processing')
    if (!hasProcessing) {
      stopPolling()
      return true
    }
    return false
  }

  // Auto-load merged content when entering step 4 (Grammar)
  useEffect(() => {
    if (currentStep === 4 && storyData.id && !mergedView.content) {
      loadMergedContent()
    }
  }, [currentStep, storyData.id])

  // Load merged TTS status and content when entering step 6 (TTS Process)
  useEffect(() => {
    if (currentStep === 6 && storyData.id) {
      // Load merged content if not already loaded
      if (!mergedView.content) {
        loadMergedContent()
      }

      if (ttsConfig.engine === 'omnivoice') {
        // Per-segment flow: load existing segments; auto-split on first arrival.
        fetchSegments({ silent: true }).then((data) => {
          if (!data) return
          const segs = data.segments ?? []
          if (segs.length === 0 && !data.source_changed) {
            handleSplitSegments()
          } else if (data.running || segs.some((s: TtsSegment) => s.status === 'processing')) {
            // A run was still in flight when we left — resume live polling.
            startSegPolling()
          }
        })
        // Also fetch merged status so a previously merged file shows up.
        fetchMergedTtsStatus()
      } else {
        // Fetch merged TTS status (VBEE one-shot)
        fetchMergedTtsStatus()
      }
    } else if (currentStep !== 6) {
      // Stop polling when leaving step 6
      stopPolling()
      stopSegPolling()
    }

    // Cleanup on unmount or step change
    return () => {
      if (currentStep !== 6) {
        stopPolling()
        stopSegPolling()
      }
    }
  }, [currentStep])

  // Effect to check completion when audio records change
  useEffect(() => {
    if (currentStep === 6 && audioRecords.length > 0) {
      checkAllCompleted()
    }
  }, [audioRecords, currentStep])

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      stopPolling()
      stopSegPolling()
    }
  }, [])

  // Handle retry failed chapter
  const handleRetryChapter = async (chapterId: string) => {
    try {
      setLoading(true)
      await axios.post(`/api/v1/tts/retry-chapter/${chapterId}`)

      // Refresh audio records immediately
      await fetchAudioRecords()

      // Show success message briefly
      setError(null)
    } catch (error: any) {
      console.error('Error retrying chapter:', error)
      setError(errMessage(error, 'Không thử lại được chương'))
    } finally {
      setLoading(false)
    }
  }

  // Handle step click - allow navigation to any step up to current_step in DB
  const handleStepClick = (stepId: number) => {
    // Can only click on steps that have been reached (up to current_step in DB)
    const maxAccessibleStep = storyData.current_step || 1
    if (stepId <= maxAccessibleStep) {
      setCurrentStep(stepId) // Just change UI view, no need to update DB
    }
  }

  // Handle edit chapter
  const handleEditChapter = async (chapter: Chapter) => {
    console.log('=== handleEditChapter called ===')
    console.log('Chapter:', chapter)

    try {
      // Fetch full chapter content
      console.log('Fetching chapter content...')
      const contentResponse = await axios.get(`/api/v1/chapters/${chapter.id}`)
      console.log('Content response:', contentResponse.data)

      // Fetch censored words
      console.log('Fetching censored words...')
      const censoredResponse = await axios.get(`/api/v1/chapters/${chapter.id}/censored-words`)
      console.log('Censored words response:', censoredResponse.data)

      const newDialogState = {
        isOpen: true,
        chapter: chapter,
        content: contentResponse.data.content || '',
        title: contentResponse.data.title || `Chapter ${chapter.chapter_number}`,
        censoredWords: censoredResponse.data.censored_words || [],
        findText: '',
        replaceText: '',
        matchCount: 0,
        quickBannedWord: '',
        quickReplacementWord: ''
      }

      console.log('Setting editDialog state:', newDialogState)
      setEditDialog(newDialogState)
      console.log('Dialog should be open now!')
    } catch (error: any) {
      console.error('=== Error fetching chapter ===')
      console.error('Error:', error)
      console.error('Error response:', error.response?.data)
      setError(errMessage(error, 'Không tải được chương'))
    }
  }

  // Helper function to escape HTML
  const escapeHtml = (text: string) => {
    const div = document.createElement('div')
    div.textContent = text
    return div.innerHTML
  }

  // Helper function to get highlighted HTML
  const getHighlightedText = (text: string, searchTerm: string) => {
    if (!searchTerm) return escapeHtml(text)

    try {
      const escapedSearchTerm = searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      const regex = new RegExp(`(${escapedSearchTerm})`, 'gi')
      const parts = text.split(regex)

      return parts.map((part, index) => {
        const escaped = escapeHtml(part)
        if (index % 2 === 1) {
          // This is a match - highlight with yellow background
          return `<mark style="background-color: #FFEB3B; color: black; font-weight: 600; padding: 0 1px; border-radius: 2px;">${escaped}</mark>`
        }
        return escaped
      }).join('')
    } catch {
      return escapeHtml(text)
    }
  }

  // Handle find text
  const handleFindText = () => {
    if (!editDialog.findText) {
      setEditDialog({ ...editDialog, matchCount: 0 })
      return
    }

    const regex = new RegExp(editDialog.findText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi')
    const matches = editDialog.content.match(regex)
    setEditDialog({ ...editDialog, matchCount: matches ? matches.length : 0 })
  }

  // Handle replace all
  const handleReplaceAll = () => {
    if (!editDialog.findText) return

    const regex = new RegExp(editDialog.findText, 'g')
    const newContent = editDialog.content.replace(regex, editDialog.replaceText)

    setEditDialog({
      ...editDialog,
      content: newContent,
      matchCount: 0,
      findText: '',
      replaceText: ''
    })
  }

  // Handle replace first occurrence
  const handleReplaceFirst = () => {
    if (!editDialog.findText) return

    const index = editDialog.content.indexOf(editDialog.findText)
    if (index === -1) {
      setEditDialog({ ...editDialog, matchCount: 0 })
      return
    }

    const newContent =
      editDialog.content.substring(0, index) +
      editDialog.replaceText +
      editDialog.content.substring(index + editDialog.findText.length)

    // Recalculate match count
    const regex = new RegExp(editDialog.findText, 'gi')
    const matches = newContent.match(regex)

    setEditDialog({
      ...editDialog,
      content: newContent,
      matchCount: matches ? matches.length : 0
    })
  }

  // Handle accept replacement for banned word
  const handleAcceptReplacement = async (censoredWordId: string) => {
    try {
      setLoading(true)
      const response = await axios.post(`/api/v1/chapters/censored-word/${censoredWordId}/accept`)

      // Refresh chapter content
      if (editDialog.chapter) {
        const contentResponse = await axios.get(`/api/v1/chapters/${editDialog.chapter.id}`)
        const censoredResponse = await axios.get(`/api/v1/chapters/${editDialog.chapter.id}/censored-words`)

        setEditDialog({
          ...editDialog,
          content: contentResponse.data.content || '',
          censoredWords: censoredResponse.data.censored_words || []
        })

        // Update chapters list
        await fetchChapters()
      }

      console.log(response.data.message)
    } catch (error: any) {
      console.error('Error accepting replacement:', error)
      setError(errMessage(error, 'Không áp dụng được thay thế'))
    } finally {
      setLoading(false)
    }
  }

  // Handle quick add banned word
  const handleQuickAddBannedWord = async () => {
    if (!editDialog.quickBannedWord || !editDialog.quickReplacementWord) {
      setError('Vui lòng nhập cả từ bị cấm và từ thay thế')
      return
    }

    try {
      setLoading(true)
      setError(null)

      // Add to banned words database
      await axios.post('/api/v1/banned-words/', {
        banned_word: editDialog.quickBannedWord,
        replacement_word: editDialog.quickReplacementWord,
        description: 'Thêm từ dialog edit chapter',
        is_active: true
      })

      // Re-check grammar for current chapter to detect newly added banned word
      if (editDialog.chapter) {
        await axios.post(`/api/v1/chapters/${editDialog.chapter.id}/check-grammar`)

        // Refresh censored words list
        const censoredResponse = await axios.get(`/api/v1/chapters/${editDialog.chapter.id}/censored-words`)

        setEditDialog({
          ...editDialog,
          censoredWords: censoredResponse.data.censored_words || [],
          quickBannedWord: '',
          quickReplacementWord: ''
        })
      }

      console.log(`Added banned word: ${editDialog.quickBannedWord} -> ${editDialog.quickReplacementWord}`)
    } catch (error: any) {
      console.error('Error adding banned word:', error)
      setError(errMessage(error, 'Không thêm được từ cấm'))
    } finally {
      setLoading(false)
    }
  }

  // Handle check grammar without saving
  const handleCheckGrammar = async () => {
    if (!editDialog.chapter) return

    try {
      setLoading(true)

      // Check grammar for the current content
      console.log('Checking grammar for current content...')

      // Check grammar with the current edited content
      const grammarResponse = await axios.post(`/api/v1/chapters/${editDialog.chapter.id}/check-grammar`, {
        content: editDialog.content
      })
      console.log('Grammar check result:', grammarResponse.data)

      // Update the dialog state with the grammar check results
      // Since we're passing custom content, the API returns the issues directly
      setEditDialog({
        ...editDialog,
        censoredWords: grammarResponse.data.all_issues || []
      })

      // Show a notification about the check results
      const totalIssues = grammarResponse.data.total_issues || 0
      if (totalIssues > 0) {
        console.log(`Found ${totalIssues} grammar issues`)
      } else {
        console.log('No grammar issues found')
      }

    } catch (error: any) {
      console.error('Error checking grammar:', error)
      setError(errMessage(error, 'Không kiểm tra được ngữ pháp'))
    } finally {
      setLoading(false)
    }
  }

  // Handle save edited chapter
  const handleSaveEditedChapter = async () => {
    if (!editDialog.chapter) return

    try {
      setLoading(true)

      // Step 1: Save the chapter
      await axios.put(`/api/v1/chapters/${editDialog.chapter.id}`, {
        title: editDialog.title,
        content: editDialog.content
      })

      // Step 2: Re-check grammar for saved content and save to database
      console.log('Re-checking grammar after save...')
      const grammarResponse = await axios.post(`/api/v1/chapters/${editDialog.chapter.id}/check-grammar-save`)
      console.log('Grammar check result:', grammarResponse.data)

      // Step 3: Update local state with new data
      const updatedChapters = chapters.map(ch =>
        ch.id === editDialog.chapter!.id
          ? {
              ...ch,
              title: editDialog.title,
              content: editDialog.content,
              char_count: editDialog.content.length,
              censored_count: grammarResponse.data.censored_count || 0,
              has_censored_words: (grammarResponse.data.censored_count || 0) > 0
            }
          : ch
      )
      setChapters(updatedChapters)

      // Step 4: Refresh chapter stats to update totals
      if (storyData.id) {
        await fetchChapterStats(storyData.id)
      }

      // Close dialog
      setEditDialog({
        isOpen: false,
        chapter: null,
        content: '',
        title: '',
        censoredWords: [],
        findText: '',
        replaceText: '',
        matchCount: 0,
        quickBannedWord: '',
        quickReplacementWord: ''
      })

      // Show success message
      console.log(`Chapter saved. Found ${grammarResponse.data.censored_count} grammar errors.`)
    } catch (error: any) {
      console.error('Error updating chapter:', error)
      setError(errMessage(error, 'Không cập nhật được chương'))
    } finally {
      setLoading(false)
    }
  }

  // Handle delete chapter
  const handleDeleteChapter = (chapter: Chapter) => {
    setDeleteDialog({
      isOpen: true,
      chapter: chapter
    })
  }

  // Handle confirm delete
  const handleConfirmDelete = async () => {
    if (!deleteDialog.chapter) return

    try {
      setLoading(true)
      await axios.delete(`/api/v1/chapters/${deleteDialog.chapter.id}`)

      // Update local state
      const updatedChapters = chapters.filter(ch => ch.id !== deleteDialog.chapter!.id)
      setChapters(updatedChapters)

      // Close dialog
      setDeleteDialog({
        isOpen: false,
        chapter: null
      })
    } catch (error: any) {
      console.error('Error deleting chapter:', error)
      setError(errMessage(error, 'Không xoá được chương'))
    } finally {
      setLoading(false)
    }
  }

  // Render step indicator
  const renderStepIndicator = () => {
    const maxAccessibleStep = storyData.current_step || 1

    return (
      <div className="mb-8 overflow-x-auto pb-1">
        <div className="flex items-start min-w-[620px]">
          {VISIBLE_STEPS.map((step, index) => {
            const isCurrentStep = currentStep === step.id
            const isAccessible = step.id <= maxAccessibleStep
            const isCompleted = step.id < maxAccessibleStep
            const isLast = index === VISIBLE_STEPS.length - 1

            const dotStyle = isCurrentStep
              ? { background: 'var(--accent)', color: '#fff', boxShadow: '0 0 0 4px var(--accent-soft)' }
              : isCompleted
              ? { background: 'rgba(31,157,107,0.14)', color: '#1F9D6B', border: '1.5px solid rgba(31,157,107,0.45)' }
              : { background: 'var(--surface-2)', border: '1.5px solid var(--border-strong)' }

            return (
              <div key={step.id} className={`flex items-start ${isLast ? '' : 'flex-1'}`}>
                <div className="flex flex-col items-center gap-1.5 w-16 shrink-0">
                  <button
                    type="button"
                    onClick={() => handleStepClick(step.id)}
                    disabled={!isAccessible}
                    title={isAccessible ? `Tới bước: ${step.name}` : 'Hoàn thành các bước trước đã'}
                    className={`w-9 h-9 rounded-full grid place-items-center font-mono text-[13px] font-semibold border border-transparent transition-all ${
                      isAccessible ? 'cursor-pointer hover:brightness-95' : 'cursor-not-allowed text-faint'
                    }`}
                    style={dotStyle}
                  >
                    {isCompleted ? '✓' : index + 1}
                  </button>
                  <span
                    className={`text-[11px] leading-tight text-center ${
                      isCurrentStep ? 'font-semibold text-[var(--text)]' : 'text-dim'
                    }`}
                  >
                    {step.name}
                  </span>
                </div>
                {!isLast && (
                  <div
                    className="flex-1 h-0.5 rounded mt-[17px] mx-1"
                    style={{ background: step.id < maxAccessibleStep ? 'rgba(31,157,107,0.5)' : 'var(--border-strong)' }}
                  />
                )}
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  // ============== Merged Content Functions ==============

  // Load merged content from API
  const loadMergedContent = async () => {
    if (!storyData.id) return
    try {
      const response = await axios.get(`/api/v1/stories/${storyData.id}/merged-content`)
      setMergedView(prev => ({
        ...prev,
        content: response.data.merged_content,
        isOpen: true
      }))
    } catch (error) {
      console.error('Error loading merged content:', error)
      showToast('Lỗi khi tải nội dung ghép', 'error')
    }
  }

  // Save merged content to DB
  const saveMergedContent = async () => {
    if (!storyData.id) return
    setMergedView(prev => ({ ...prev, isSaving: true }))
    try {
      await axios.put(`/api/v1/stories/${storyData.id}/merged-content`, {
        merged_content: mergedView.content
      })
      showToast('Đã lưu nội dung thành công!', 'success')
    } catch (error) {
      console.error('Error saving merged content:', error)
      showToast('Lỗi khi lưu nội dung', 'error')
    } finally {
      setMergedView(prev => ({ ...prev, isSaving: false }))
    }
  }

  // Find & Replace in merged content
  const handleMergedFindReplace = () => {
    if (!mergedView.findText) return
    const regex = new RegExp(mergedView.findText, 'g')
    const newContent = mergedView.content.replace(regex, mergedView.replaceText)
    const matchCount = (mergedView.content.match(regex) || []).length
    setMergedView(prev => ({
      ...prev,
      content: newContent,
      matchCount: 0
    }))
    showToast(`Đã thay thế ${matchCount} kết quả`, 'success')
  }

  // Count matches in merged content and scroll to first match
  const countMergedMatches = () => {
    if (!mergedView.findText) {
      setMergedView(prev => ({ ...prev, matchCount: 0 }))
      return
    }
    try {
      const regex = new RegExp(mergedView.findText, 'g')
      const matches = mergedView.content.match(regex) || []
      setMergedView(prev => ({ ...prev, matchCount: matches.length }))

      // Scroll to first match
      if (matches.length > 0 && mergedTextareaRef.current) {
        const firstMatchIndex = mergedView.content.indexOf(mergedView.findText)
        if (firstMatchIndex !== -1) {
          const textarea = mergedTextareaRef.current
          // Calculate approximate line position
          const textBeforeMatch = mergedView.content.substring(0, firstMatchIndex)
          const linesBefore = textBeforeMatch.split('\n').length - 1
          const lineHeight = 24 // approximate line height in pixels
          const scrollPosition = Math.max(0, linesBefore * lineHeight - 100) // offset 100px from top
          textarea.scrollTop = scrollPosition
          // Also scroll highlight overlay
          if (mergedHighlightRef.current) {
            mergedHighlightRef.current.scrollTop = scrollPosition
          }
        }
      }
    } catch (e) {
      setMergedView(prev => ({ ...prev, matchCount: 0 }))
    }
  }

  // AI Grammar check for merged content
  const checkMergedGrammar = async () => {
    if (!storyData.id || !mergedView.content) return
    setMergedView(prev => ({ ...prev, isChecking: true, aiResult: null, selectedErrors: {}, acceptedErrors: {} }))
    try {
      // Send the FULL story; the backend splits it into chunks and checks all of it.
      const response = await axios.post(`/api/v1/chapters/${chapters[0]?.id || 'temp'}/ai-grammar-check`, {
        content: mergedView.content
      })
      // Tick sẵn mọi lỗi (mặc định chọn hết), chưa lỗi nào được áp dụng.
      const selected: Record<number, boolean> = {}
      const errs = response.data?.spelling_errors || []
      errs.forEach((_: any, i: number) => { selected[i] = true })
      setMergedView(prev => ({
        ...prev,
        aiResult: response.data,
        selectedErrors: selected,
        acceptedErrors: {},
        isChecking: false
      }))
      if (response.data.success) {
        showToast(`Tìm thấy ${response.data.total_issues || 0} lỗi ngữ pháp`, 'info')
      }
    } catch (error: any) {
      console.error('AI grammar check error:', error)
      showToast(errMessage(error, 'Lỗi khi kiểm tra ngữ pháp'), 'error')
      setMergedView(prev => ({ ...prev, isChecking: false }))
    }
  }

  // Bật/tắt tick một lỗi.
  const toggleErrorSelected = (idx: number) => {
    setMergedView(prev => ({
      ...prev,
      selectedErrors: { ...prev.selectedErrors, [idx]: !prev.selectedErrors[idx] }
    }))
  }

  // Tick/bỏ tick toàn bộ lỗi chưa áp dụng.
  const toggleSelectAllErrors = (checked: boolean) => {
    setMergedView(prev => {
      const next: Record<number, boolean> = { ...prev.selectedErrors }
      const errs = prev.aiResult?.spelling_errors || []
      errs.forEach((_: any, i: number) => { if (!prev.acceptedErrors[i]) next[i] = checked })
      return { ...prev, selectedErrors: next }
    })
  }

  // Áp dụng MỘT lỗi rồi ẩn nó khỏi danh sách.
  const acceptSingleError = (idx: number) => {
    const err = mergedView.aiResult?.spelling_errors?.[idx]
    if (!err) return
    const newContent = mergedView.content.replaceAll(err.original, err.suggestion)
    setMergedView(prev => ({
      ...prev,
      content: newContent,
      acceptedErrors: { ...prev.acceptedErrors, [idx]: true }
    }))
    showToast(`Đã thay "${err.original}" → "${err.suggestion}"`, 'success')
  }

  // Áp dụng TẤT CẢ lỗi đang tick (chưa áp dụng), thay từ dài → ngắn để tránh chồng lấn.
  const acceptAllErrors = () => {
    const errs = mergedView.aiResult?.spelling_errors || []
    const targets = errs
      .map((e: any, i: number) => ({ ...e, _idx: i }))
      .filter((e: any) => mergedView.selectedErrors[e._idx] && !mergedView.acceptedErrors[e._idx])
      .sort((a: any, b: any) => b.original.length - a.original.length)

    if (targets.length === 0) {
      showToast('Chưa chọn lỗi nào để áp dụng', 'info')
      return
    }

    let text = mergedView.content
    const accepted: Record<number, boolean> = { ...mergedView.acceptedErrors }
    let applied = 0
    for (const e of targets) {
      if (text.includes(e.original)) {
        text = text.replaceAll(e.original, e.suggestion)
        applied++
      }
      accepted[e._idx] = true  // đánh dấu đã xử lý dù còn tìm thấy hay không
    }
    setMergedView(prev => ({ ...prev, content: text, acceptedErrors: accepted }))
    showToast(`Đã áp dụng ${applied}/${targets.length} lỗi`, 'success')
  }

  // Render current step content
  const renderStepContent = () => {
    switch (currentStep) {
      case 1:
        return (
          <div className="space-y-5">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-xl font-semibold tracking-tight">Nhập nội dung truyện</h3>
              <span className="step-badge">BƯỚC 1/7</span>
            </div>

            {/* Story title */}
            <div>
              <label className="block text-sm font-medium mb-1">Tên truyện</label>
              <input
                type="text"
                value={storyData.title}
                onChange={(e) => setStoryData({ ...storyData, title: e.target.value })}
                placeholder="Nhập tên truyện"
                className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                disabled={loading}
              />
            </div>

            {/* Input mode tabs */}
            <div className="inline-flex gap-1 p-1 rounded-lg bg-surface-2 border border-token">
              {([
                { k: 'paste', label: 'Dán văn bản' },
                { k: 'file', label: 'Nhập file' },
                { k: 'folder', label: 'Nhập thư mục' },
              ] as const).map((t) => (
                <button
                  key={t.k}
                  type="button"
                  onClick={() => { setInputMode(t.k); setError(null) }}
                  disabled={loading}
                  className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                    inputMode === t.k
                      ? 'bg-surface text-strong shadow-sm'
                      : 'text-dim hover:text-strong'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {/* Mode A — paste */}
            {inputMode === 'paste' && (
              <div className="space-y-3">
                <textarea
                  value={pasteText}
                  onChange={(e) => setPasteText(e.target.value)}
                  placeholder="Dán toàn bộ nội dung truyện vào đây. Ứng dụng sẽ tự nhận diện các mốc &quot;Chương 1&quot;, &quot;Chương 2&quot;... để tách chương."
                  rows={10}
                  className="w-full px-3 py-2 border rounded-md text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-primary-500"
                  disabled={loading}
                />
                <p className="text-xs text-faint -mt-1">
                  Mẹo: mỗi chương nên bắt đầu bằng một dòng &quot;Chương 1&quot;, &quot;Chương 2&quot;... để tách tự động.
                </p>
                {pasteText.trim() && (
                  <div className="rounded-lg border border-token bg-surface-2 p-3">
                    <div className="text-sm font-medium mb-1.5">
                      Đã nhận diện{' '}
                      <span className="text-primary-600 dark:text-primary-400 font-semibold">
                        {pastePreview.length}
                      </span>{' '}
                      chương
                    </div>
                    <div className="text-xs text-dim max-h-28 overflow-y-auto space-y-0.5">
                      {pastePreview.slice(0, 8).map((c, i) => (
                        <div key={i} className="truncate">
                          {c.chapter_number === 0 ? 'Giới thiệu' : `Chương ${c.chapter_number}`}
                          <span className="text-faint"> — {c.content.replace(/\n/g, '').length.toLocaleString()} ký tự</span>
                        </div>
                      ))}
                      {pastePreview.length > 8 && (
                        <div className="text-faint">...và {pastePreview.length - 8} chương khác</div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Mode B — file */}
            {inputMode === 'file' && (
              <div className="rounded-lg border border-dashed border-token-strong p-6 text-center bg-surface-2">
                <p className="text-sm text-dim mb-3">
                  Chọn một file <strong>.txt</strong> hoặc <strong>.docx</strong>. Ứng dụng sẽ tự tách chương theo mốc &quot;Chương N&quot;.
                </p>
                <button
                  type="button"
                  onClick={() => handlePathImport('file')}
                  disabled={loading}
                  className="btn btn-secondary mx-auto disabled:opacity-60"
                >
                  {loading ? 'Đang nhập...' : 'Chọn file...'}
                </button>
                {!hasNativeDialogs() && (
                  <p className="text-xs text-faint mt-2">Chức năng này chỉ khả dụng trong ứng dụng desktop.</p>
                )}
              </div>
            )}

            {/* Mode C — folder */}
            {inputMode === 'folder' && (
              <div className="rounded-lg border border-dashed border-token-strong p-6 text-center bg-surface-2">
                <p className="text-sm text-dim mb-3">
                  Chọn thư mục chứa các file chương — mỗi file <strong>.txt</strong>/<strong>.docx</strong> là 1 chương, sắp theo tên file.
                </p>
                <button
                  type="button"
                  onClick={() => handlePathImport('folder')}
                  disabled={loading}
                  className="btn btn-secondary mx-auto disabled:opacity-60"
                >
                  {loading ? 'Đang nhập...' : 'Chọn thư mục...'}
                </button>
                {!hasNativeDialogs() && (
                  <p className="text-xs text-faint mt-2">Chức năng này chỉ khả dụng trong ứng dụng desktop.</p>
                )}
              </div>
            )}

            {error && (
              <div className="p-4 rounded-md bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 text-sm text-red-700 dark:text-red-300">
                {error}
              </div>
            )}

            {inputMode === 'paste' && (
              <button
                type="button"
                onClick={handlePasteImport}
                disabled={loading || !pasteText.trim()}
                className="btn btn-primary w-full justify-center disabled:opacity-60"
              >
                {loading
                  ? 'Đang nhập...'
                  : `Nhập ${pastePreview.length || ''} chương & tiếp tục`}
              </button>
            )}
          </div>
        )

      case 3:
        return (
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3 mb-4">
              <h3 className="text-xl font-semibold tracking-tight">Sửa nội dung chương</h3>
              <span className="step-badge">BƯỚC 2/7</span>
            </div>

            {/* Statistics Section */}
            {checkingGrammar && (
              <div className="bg-primary-50 dark:bg-primary-500/10 border border-primary-200 dark:border-primary-500/30 rounded-lg p-4">
                <div className="flex items-center gap-2">
                  <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-primary-600"></div>
                  <span className="text-sm text-primary-800 dark:text-primary-300">Đang kiểm tra ngữ pháp...</span>
                </div>
              </div>
            )}

            {chapterStats && !checkingGrammar && (
              <div className="bg-gradient-to-r from-primary-50 to-primary-50 border border-primary-200 dark:border-primary-500/30 rounded-lg p-4">
                <h4 className="font-semibold text-strong mb-3">Thống kê</h4>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                  <div className="bg-surface rounded-lg p-3 shadow-sm">
                    <div className="text-xs text-dim mb-1">Tổng số chương</div>
                    <div className="text-2xl font-bold text-strong">{chapterStats.total_chapters}</div>
                  </div>
                  <div className="bg-surface rounded-lg p-3 shadow-sm">
                    <div className="text-xs text-dim mb-1">Tổng số ký tự</div>
                    <div className="text-2xl font-bold text-primary-600 dark:text-primary-400">{chapterStats.total_characters.toLocaleString()}</div>
                  </div>
                  <div className="bg-surface rounded-lg p-3 shadow-sm">
                    <div className="text-xs text-dim mb-1">Trung bình/chương</div>
                    <div className="text-2xl font-bold text-green-600 dark:text-green-400">{chapterStats.average_characters.toLocaleString()}</div>
                  </div>
                  <div className="bg-surface rounded-lg p-3 shadow-sm">
                    <div className="text-xs text-dim mb-1">Chương có lỗi</div>
                    <div className={`text-2xl font-bold ${chapterStats.chapters_with_censored_words > 0 ? 'text-orange-600 dark:text-orange-400' : 'text-green-600 dark:text-green-400'}`}>
                      {chapterStats.chapters_with_censored_words}
                    </div>
                  </div>
                  <div className="bg-surface rounded-lg p-3 shadow-sm">
                    <div className="text-xs text-dim mb-1">Tổng lỗi ngữ pháp</div>
                    <div className={`text-2xl font-bold ${chapterStats.total_censored_words > 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'}`}>
                      {chapterStats.total_censored_words}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Chapters List */}
            <div className="max-h-[500px] overflow-y-auto border rounded-md p-4">
              {chapters.length > 0 ? (
                <div className="space-y-2">
                  {chapters.map((chapter) => (
                    <div key={chapter.id} className={`p-3 border rounded hover:bg-surface-2 transition-colors ${chapter.chapter_number === 0 ? 'border-primary-300 dark:border-primary-500/30 bg-primary-50 dark:bg-primary-500/10' : ''}`}>
                      <div className="flex justify-between items-start">
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <span className="font-medium">
                              {chapter.chapter_number === 0 ? ' Giới thiệu (Chapter 0)' : `Chapter ${chapter.chapter_number}`}
                            </span>
                            {chapter.chapter_number !== 0 && chapter.title && (
                              <span className="text-sm text-dim">- {chapter.title}</span>
                            )}
                          </div>
                          <div className="flex items-center gap-4 mt-1">
                            <span className="text-sm text-dim">{chapter.char_count.toLocaleString()} ký tự</span>
                            {chapter.chapter_number === 0 && chapter.char_count === 0 && (
                              <span className="text-sm text-primary-600 dark:text-primary-400 italic">
                                 Thêm nội dung giới thiệu (hoặc để trống để bỏ qua)
                              </span>
                            )}
                            {(chapter.chapter_number !== 0 || chapter.char_count > 0) && chapter.censored_count > 0 && (
                              <span className="text-sm text-orange-600 dark:text-orange-400 font-medium">
                                 {chapter.censored_count} lỗi ngữ pháp
                              </span>
                            )}
                            {(chapter.chapter_number !== 0 || chapter.char_count > 0) && chapter.censored_count === 0 && (
                              <span className="text-sm text-green-600 dark:text-green-400">
                                ✓ Không có lỗi
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center gap-2 ml-4">
                          <button
                            onClick={() => handleEditChapter(chapter)}
                            className="p-2 text-primary-600 dark:text-primary-400 hover:bg-primary-50 dark:hover:bg-primary-500/15 rounded-md transition-colors"
                            title="Edit chapter"
                          >
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                            </svg>
                          </button>
                          <button
                            onClick={() => handleDeleteChapter(chapter)}
                            className="p-2 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/15 rounded-md transition-colors"
                            title="Delete chapter"
                          >
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                            </svg>
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-dim">No chapters found</p>
              )}
            </div>
            {/* Action buttons */}
            <div className="flex gap-3">
              <button
                onClick={handleSaveChapters}
                className="flex-1 bg-primary-500 text-white py-2 px-4 rounded-md hover:bg-primary-600 transition"
              >
                Tiếp tục: Kiểm tra chính tả
              </button>
            </div>
          </div>
        )

      case 4:
        // Grammar Check Step - NEW
        return (
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3 mb-4">
              <h3 className="text-xl font-semibold tracking-tight flex items-center gap-2">
                Kiểm tra chính tả
                {/* Icon hướng dẫn: hover để hiện cách kiểm tra miễn phí bằng AI Studio/Gemini */}
                <span className="relative group inline-flex align-middle">
                  <span
                    className="flex items-center justify-center w-5 h-5 rounded-full bg-primary-100 dark:bg-primary-500/20 text-primary-700 dark:text-primary-300 text-xs font-bold cursor-help select-none"
                    aria-label="Hướng dẫn kiểm tra chính tả miễn phí"
                  >
                    i
                  </span>
                  <div className="pointer-events-none absolute left-0 top-full z-30 pt-2 w-[26rem] max-w-[90vw] opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-hover:pointer-events-auto">
                    <div className="rounded-lg border border-primary-200 dark:border-primary-500/30 bg-primary-50 dark:bg-primary-500/10 p-4 shadow-lg text-left font-normal">
                      <div className="text-sm font-medium text-primary-800 dark:text-primary-300 mb-2">
                        Không muốn tốn phí API? Kiểm tra miễn phí bằng AI Studio / Gemini
                      </div>
                      <p className="text-sm text-dim mb-3">
                        Copy prompt bên dưới kèm nội dung truyện rồi dán vào{' '}
                        <b>Google AI Studio</b> (aistudio.google.com) hoặc <b>Gemini</b> để nhờ AI
                        kiểm tra miễn phí, sau đó tự sửa lại trong ô nội dung.
                      </p>
                      <div className="bg-surface border rounded-lg p-3 font-mono text-xs leading-5 whitespace-pre-wrap text-strong mb-3">
                        {SPELLCHECK_PROMPT}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <button
                          onClick={() => copyText(SPELLCHECK_PROMPT, 'Đã copy prompt')}
                          className="btn btn-secondary text-xs"
                        >
                          📋 Copy prompt
                        </button>
                        <button
                          onClick={() => copyText(`${SPELLCHECK_PROMPT}\n\n${mergedView.content}`, 'Đã copy prompt + nội dung truyện')}
                          disabled={!mergedView.content}
                          className="btn btn-primary text-xs disabled:opacity-50"
                        >
                          📋 Copy prompt + nội dung truyện
                        </button>
                      </div>
                    </div>
                  </div>
                </span>
              </h3>
              <span className="step-badge">BƯỚC 3/7</span>
            </div>

            {/* Auto load merged content when entering this step */}
            {!mergedView.content && !mergedView.isOpen && (
              <div className="text-center py-8">
                <button
                  onClick={loadMergedContent}
                  className="bg-primary-500 text-white px-6 py-3 rounded-lg font-medium hover:bg-primary-600 transition"
                >
                   Tải nội dung để kiểm tra
                </button>
              </div>
            )}

            {(mergedView.content || mergedView.isOpen) && (
              <div className="space-y-4">
                {/* Find & Replace — thu gọn được để không chiếm chỗ */}
                <details className="bg-surface border rounded-lg group/fr">
                  <summary className="flex items-center gap-2 cursor-pointer select-none font-semibold text-strong px-4 py-3 list-none [&::-webkit-details-marker]:hidden">
                    <svg className="w-4 h-4 shrink-0 transition-transform group-open/fr:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                    Tìm và Thay thế
                  </summary>
                  <div className="flex flex-wrap gap-2 items-center px-4 pb-4">
                    <input
                      type="text"
                      placeholder="Tìm kiếm..."
                      value={mergedView.findText}
                      onChange={(e) => {
                        setMergedView(prev => ({ ...prev, findText: e.target.value }))
                        setTimeout(countMergedMatches, 100)
                      }}
                      className="flex-1 min-w-[150px] px-3 py-2 border rounded"
                    />
                    <input
                      type="text"
                      placeholder="Thay thế bằng..."
                      value={mergedView.replaceText}
                      onChange={(e) => setMergedView(prev => ({ ...prev, replaceText: e.target.value }))}
                      className="flex-1 min-w-[150px] px-3 py-2 border rounded"
                    />
                    {mergedView.matchCount > 0 && (
                      <span className="text-sm text-orange-600 dark:text-orange-400 font-medium px-2">
                        {mergedView.matchCount} kết quả
                      </span>
                    )}
                    <button
                      onClick={handleMergedFindReplace}
                      disabled={!mergedView.findText}
                      className="bg-orange-500 text-white px-4 py-2 rounded font-medium hover:bg-orange-600 disabled:bg-gray-300 transition"
                    >
                      Thay thế tất cả
                    </button>
                  </div>
                </details>

                {/* Text Editor */}
                <div className="border rounded-lg overflow-hidden">
                  <div className="bg-surface-3 px-4 py-2 flex items-center justify-between border-b">
                    <span className="text-sm font-medium text-dim">
                       Nội dung truyện ({mergedView.content.length.toLocaleString()} ký tự)
                    </span>
                    <button
                      onClick={checkMergedGrammar}
                      disabled={mergedView.isChecking || !mergedView.content}
                      className="bg-primary-500 text-white px-3 py-1 rounded text-sm font-medium hover:bg-primary-600 disabled:bg-gray-400 transition flex items-center gap-1"
                    >
                      {mergedView.isChecking ? (
                        <><div className="animate-spin rounded-full h-3 w-3 border-b-2 border-white"></div> Đang kiểm tra...</>
                      ) : (
                        <>Kiểm tra AI</>
                      )}
                    </button>
                  </div>
                  <div className="relative">
                    {/* Highlight overlay */}
                    {mergedView.findText && (
                      <div
                        ref={mergedHighlightRef}
                        className="absolute top-0 left-0 p-4 font-mono text-sm pointer-events-none whitespace-pre-wrap break-words overflow-hidden"
                        style={{
                          width: '100%',
                          height: 'calc(100vh - 350px)',
                          minHeight: '500px',
                          overflowY: 'auto',
                          color: 'transparent',
                          lineHeight: '1.5'
                        }}
                        dangerouslySetInnerHTML={{
                          __html: getHighlightedText(mergedView.content, mergedView.findText)
                        }}
                      />
                    )}
                    <textarea
                      ref={mergedTextareaRef}
                      value={mergedView.content}
                      onChange={(e) => setMergedView(prev => ({ ...prev, content: e.target.value }))}
                      onScroll={() => {
                        if (mergedTextareaRef.current && mergedHighlightRef.current) {
                          mergedHighlightRef.current.scrollTop = mergedTextareaRef.current.scrollTop
                        }
                      }}
                      className="w-full p-4 font-mono text-sm resize-none focus:outline-none"
                      style={{
                        height: 'calc(100vh - 350px)',
                        minHeight: '500px',
                        backgroundColor: mergedView.findText ? 'transparent' : 'var(--surface)',
                        color: 'var(--text)',
                        caretColor: 'var(--text)',
                        lineHeight: '1.5'
                      }}
                      placeholder="Nội dung truyện sẽ hiển thị ở đây..."
                    />
                  </div>
                </div>

                {/* AI Result Popup - Right Side Panel */}
                {mergedView.aiResult && (
                  <div className="fixed top-0 right-0 h-full w-[500px] bg-surface shadow-2xl border-l z-50 flex flex-col">
                    {/* Header */}
                    <div className="bg-primary-600 text-white px-4 py-3 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-lg"></span>
                        <span className="font-semibold">Kết quả AI Check</span>
                      </div>
                      <button
                        onClick={() => setMergedView(prev => ({ ...prev, aiResult: null }))}
                        className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-primary-700 transition"
                      >
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>

                    {/* Response Content - Scrollable */}
                    <div className="flex-1 overflow-y-auto p-4">
                      {/* Error */}
                      {mergedView.aiResult.error && (
                        <div className="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 rounded-lg p-4 mb-4">
                          <h4 className="font-semibold text-red-700 dark:text-red-400 mb-2"> Lỗi</h4>
                          <p className="text-red-600 dark:text-red-400 text-sm">{mergedView.aiResult.error}</p>
                        </div>
                      )}

                      {/* Summary */}
                      {mergedView.aiResult.summary && (
                        <div className="bg-primary-50 dark:bg-primary-500/10 border border-primary-200 dark:border-primary-500/30 rounded-lg p-4 mb-4">
                          <h4 className="font-semibold text-primary-700 dark:text-primary-400 mb-2"> Tóm tắt</h4>
                          <p className="text-dim">{mergedView.aiResult.summary}</p>
                        </div>
                      )}

                      {/* Stats */}
                      {mergedView.aiResult.success && (
                        <div className="flex gap-3 mb-4">
                          <span className="px-3 py-2 rounded-lg bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400 font-medium">
                             {mergedView.aiResult.total_issues || 0} lỗi chính tả
                          </span>
                          <span className="px-3 py-2 rounded-lg bg-orange-100 dark:bg-orange-500/20 text-orange-700 dark:text-orange-400 font-medium">
                             {mergedView.aiResult.total_watermarks || 0} watermark
                          </span>
                        </div>
                      )}

                      {/* Spelling Errors */}
                      {mergedView.aiResult.spelling_errors && mergedView.aiResult.spelling_errors.length > 0 && (() => {
                        const errs = mergedView.aiResult.spelling_errors
                        // Chỉ số các lỗi CHƯA áp dụng (còn hiển thị).
                        const remaining = errs
                          .map((_: any, i: number) => i)
                          .filter((i: number) => !mergedView.acceptedErrors[i])
                        const selectedCount = remaining.filter((i: number) => mergedView.selectedErrors[i]).length
                        const allChecked = remaining.length > 0 && selectedCount === remaining.length

                        if (remaining.length === 0) {
                          return (
                            <div className="mb-4 bg-green-50 dark:bg-green-500/10 border border-green-200 dark:border-green-500/30 rounded-lg p-3 text-green-700 dark:text-green-400 text-sm">
                              ✓ Đã áp dụng toàn bộ {errs.length} lỗi chính tả.
                            </div>
                          )
                        }

                        return (
                          <div className="mb-4">
                            <div className="flex items-center justify-between gap-2 mb-3">
                              <h4 className="font-semibold text-red-700 dark:text-red-400 text-lg">
                                Lỗi chính tả <span className="text-dim text-sm font-normal">(còn {remaining.length})</span>
                              </h4>
                              <div className="flex items-center gap-3">
                                <label className="flex items-center gap-1.5 text-sm text-dim cursor-pointer select-none">
                                  <input
                                    type="checkbox"
                                    checked={allChecked}
                                    onChange={(e) => toggleSelectAllErrors(e.target.checked)}
                                    className="w-4 h-4 accent-green-500"
                                  />
                                  Chọn tất cả
                                </label>
                                <button
                                  onClick={acceptAllErrors}
                                  disabled={selectedCount === 0}
                                  className="bg-green-500 text-white px-3 py-1.5 rounded text-sm font-medium hover:bg-green-600 disabled:bg-gray-300 dark:disabled:bg-gray-600 transition whitespace-nowrap"
                                >
                                  ✓ Accept tất cả ({selectedCount})
                                </button>
                              </div>
                            </div>
                            <div className="space-y-3">
                              {errs.map((error: any, idx: number) => (
                                mergedView.acceptedErrors[idx] ? null : (
                                  <div key={idx} className="bg-surface-2 border rounded-lg p-3">
                                    <div className="flex items-center justify-between gap-2 mb-2">
                                      <div className="flex items-center gap-2 flex-wrap">
                                        <input
                                          type="checkbox"
                                          checked={!!mergedView.selectedErrors[idx]}
                                          onChange={() => toggleErrorSelected(idx)}
                                          className="w-4 h-4 accent-green-500"
                                        />
                                        <span className="text-dim text-sm">{idx + 1}.</span>
                                        <span className="bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400 px-2 py-1 rounded line-through">{error.original}</span>
                                        <span className="text-faint">→</span>
                                        <span className="bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400 px-2 py-1 rounded font-medium">{error.suggestion}</span>
                                      </div>
                                      <button
                                        onClick={() => acceptSingleError(idx)}
                                        className="bg-green-500 text-white px-3 py-1 rounded text-sm font-medium hover:bg-green-600 transition whitespace-nowrap"
                                      >
                                        ✓ Accept
                                      </button>
                                    </div>
                                    {error.context && (
                                      <p className="text-dim text-sm italic ml-5">"{error.context}"</p>
                                    )}
                                  </div>
                                )
                              ))}
                            </div>
                          </div>
                        )
                      })()}

                      {/* Watermarks */}
                      {mergedView.aiResult.watermarks && mergedView.aiResult.watermarks.length > 0 && (
                        <div className="mb-4">
                          <h4 className="font-semibold text-orange-700 dark:text-orange-400 mb-3 text-lg"> Watermark phát hiện</h4>
                          <div className="space-y-3">
                            {mergedView.aiResult.watermarks.map((wm: any, idx: number) => (
                              <div key={idx} className="bg-orange-50 dark:bg-orange-500/10 border border-orange-200 dark:border-orange-500/30 rounded-lg p-3">
                                <div className="flex items-center justify-between gap-2 mb-2">
                                  <div className="flex items-center gap-2">
                                    <span className="text-dim text-sm">{idx + 1}.</span>
                                    <span className="bg-orange-100 dark:bg-orange-500/20 text-orange-700 dark:text-orange-400 px-2 py-1 rounded font-medium">{wm.text}</span>
                                  </div>
                                  <button
                                    onClick={() => {
                                      const newContent = mergedView.content.replaceAll(wm.text, '')
                                      setMergedView(prev => ({ ...prev, content: newContent }))
                                      showToast(`Đã xóa "${wm.text}"`, 'success')
                                    }}
                                    className="bg-red-500 text-white px-3 py-1 rounded text-sm font-medium hover:bg-red-600 transition whitespace-nowrap"
                                  >
                                     Xóa
                                  </button>
                                </div>
                                {wm.context && (
                                  <p className="text-dim text-sm italic ml-5">"{wm.context}"</p>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* No issues */}
                      {mergedView.aiResult.success &&
                       (!mergedView.aiResult.spelling_errors || mergedView.aiResult.spelling_errors.length === 0) &&
                       (!mergedView.aiResult.watermarks || mergedView.aiResult.watermarks.length === 0) && (
                        <div className="text-center py-8">
                          <div className="mx-auto mb-4 w-14 h-14 rounded-full grid place-items-center" style={{ background: 'rgba(31,157,107,0.14)', color: '#1F9D6B' }}>
                            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
                          </div>
                          <p className="text-green-600 dark:text-green-400 font-semibold text-lg">Không tìm thấy lỗi!</p>
                          <p className="text-dim">Văn bản đã sạch chính tả và watermark</p>
                        </div>
                      )}

                      {/* Raw response (collapsible) */}
                      <details className="mt-4">
                        <summary className="cursor-pointer text-dim text-sm hover:text-dim">
                           Xem JSON gốc
                        </summary>
                        <pre className="mt-2 bg-gray-900 text-green-400 text-xs p-3 rounded-lg overflow-x-auto">
                          {JSON.stringify(mergedView.aiResult, null, 2)}
                        </pre>
                      </details>
                    </div>
                  </div>
                )}

                {/* Continue button */}
                <div className="flex gap-4">
                  <button
                    onClick={saveMergedContent}
                    disabled={mergedView.isSaving}
                    className="flex-1 bg-green-500 text-white py-2 px-4 rounded-md hover:bg-green-600 transition disabled:bg-gray-400"
                  >
                    {mergedView.isSaving ? 'Đang lưu...' : 'Lưu thay đổi'}
                  </button>
                  <button
                    onClick={() => moveToStep(5)}
                    className="flex-1 bg-primary-500 text-white py-2 px-4 rounded-md hover:bg-primary-600 transition"
                  >
                    Tiếp tục: Cấu hình TTS
                  </button>
                  <button
                    onClick={() => moveToStep(7)}
                    className="flex-1 bg-primary-500 text-white py-2 px-4 rounded-md hover:bg-primary-600 transition"
                  >
                    Bỏ qua sang Video
                  </button>
                </div>
              </div>
            )}
          </div>
        )

      case 5:
        return (
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3 mb-4">
              <h3 className="text-xl font-semibold tracking-tight">Cấu hình giọng đọc</h3>
              <span className="step-badge">BƯỚC 4/7</span>
            </div>
            <div className="space-y-4">
              {/* Engine tabs: VBEE (cloud) vs OmniVoice (local) */}
              <div className="flex gap-1 p-1 rounded-lg bg-surface-2 border border-token w-fit">
                {([
                  { key: 'vbee', label: 'VBEE (cloud)' },
                  { key: 'omnivoice', label: 'OmniVoice (local, clone giọng)' },
                ] as const).map((t) => (
                  <button
                    key={t.key}
                    onClick={() => setTtsConfig({ ...ttsConfig, engine: t.key })}
                    disabled={loading}
                    className={`px-4 py-1.5 rounded-md text-sm font-medium transition ${
                      ttsConfig.engine === t.key
                        ? 'bg-primary-500 text-white'
                        : 'text-dim hover:text-primary-600'
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              {/* Scrollable settings area — tabs above stay fixed */}
              <div className="space-y-4 overflow-y-auto pr-2 max-h-[calc(100vh-340px)]">
              {/* ---------- VBEE tab ---------- */}
              {ttsConfig.engine === 'vbee' && (
                <div className="space-y-4">
                  {/* Live VBEE search (Việt + Anh) — pick a voice beyond the 25 in the DB */}
                  <div>
                    <label className="block text-sm font-medium mb-1">🔎 Tìm giọng khác trên VBEE (Việt + Anh)</label>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={voiceSearchQuery}
                        onChange={(e) => setVoiceSearchQuery(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); searchVbeeVoices() } }}
                        placeholder="nhập tên giọng… (vd: alloy, ngoc)"
                        className="flex-1 px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                        disabled={loading || voiceSearching}
                      />
                      <button
                        onClick={searchVbeeVoices}
                        disabled={loading || voiceSearching}
                        className="px-4 py-2 rounded-md text-sm font-medium bg-primary-500 text-white hover:bg-primary-600 disabled:opacity-50"
                      >
                        {voiceSearching ? 'Đang tìm…' : 'Tìm'}
                      </button>
                    </div>

                    {/* Results list */}
                    {voiceSearchResults !== null && (
                      voiceSearchResults.length === 0 ? (
                        <div className="mt-2 text-sm text-dim">Không có giọng khớp — thử tên khác hoặc dùng danh sách bên dưới.</div>
                      ) : (
                        <div className="mt-2 border border-token rounded-md divide-y divide-token max-h-56 overflow-y-auto">
                          <div className="px-3 py-1.5 text-xs text-dim">Kết quả ({voiceSearchResults.length}):</div>
                          {voiceSearchResults.map((v) => (
                            <div key={v.code} className="flex items-center justify-between gap-2 px-3 py-2">
                              <div className="min-w-0">
                                <div className="text-sm font-medium truncate">{v.name}</div>
                                <div className="text-xs text-dim truncate">
                                  {[v.language_code, v.gender, v.locale].filter(Boolean).join(' · ')}
                                </div>
                              </div>
                              <button
                                onClick={() => useSearchedVoice(v)}
                                disabled={loading}
                                className="shrink-0 px-3 py-1 rounded-md text-sm font-medium border border-primary-500 text-primary-600 hover:bg-primary-50 dark:hover:bg-primary-500/10"
                              >
                                Chọn
                              </button>
                            </div>
                          ))}
                        </div>
                      )
                    )}
                  </div>

                  {/* Banner shown when a searched voice is active */}
                  {searchedVoice && (
                    <div className="flex items-center justify-between gap-3 px-3 py-2 rounded-md bg-green-50 dark:bg-green-500/10 border border-green-300 dark:border-green-500/30">
                      <div className="min-w-0 text-sm">
                        <span className="font-medium text-green-700 dark:text-green-400">✔ Đang dùng giọng từ VBEE: {searchedVoice.name}</span>
                        <span className="text-dim"> ({searchedVoice.code})</span>
                        <div className="text-xs text-dim">{[searchedVoice.language_code, searchedVoice.gender].filter(Boolean).join(' · ')}</div>
                      </div>
                      <button
                        onClick={clearSearchedVoice}
                        disabled={loading}
                        className="shrink-0 px-2 py-1 rounded-md text-sm text-dim hover:text-red-600"
                      >
                        ✕ bỏ, quay lại danh sách
                      </button>
                    </div>
                  )}

                  <div className={searchedVoice ? 'opacity-50 pointer-events-none' : ''}>
                    <label className="block text-sm font-medium mb-1">Voice ({voices.length} giọng đã lưu)</label>
                    <select
                      value={dbVoiceCode}
                      onChange={(e) => {
                        setDbVoiceCode(e.target.value)
                        setTtsConfig({ ...ttsConfig, voice_code: e.target.value })
                      }}
                      className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                      disabled={loading || !!searchedVoice}
                    >
                      {voices.map((voice) => (
                        <option key={voice.code} value={voice.code}>
                          {voice.name} ({voice.gender})
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              )}

              {/* ---------- OmniVoice tab ---------- */}
              {ttsConfig.engine === 'omnivoice' && (
                <div className="space-y-4">
                  {/* Device (GPU/CPU) selector — hidden in happy path (folded into the compact chip below) */}
                  {omniStatus?.availability && (() => {
                    const av = omniStatus.availability
                    const dl = omniStatus.downloads?.base
                    // Happy path (model ready & not downloading) → collapse into the compact chip below
                    if (av?.ready && dl?.state !== 'downloading') return null
                    const noGpu = av.deps_installed && !av.gpu_available
                    return (
                      <div className="rounded-lg p-3 border border-token bg-surface-2 space-y-2">
                        <div className="text-sm">
                          {av.gpu_available
                            ? '✓ Đã phát hiện GPU NVIDIA — mặc định chạy trên GPU (nhanh).'
                            : '⚠️ Không phát hiện GPU NVIDIA — tự động chạy trên CPU (rất chậm).'}
                        </div>
                        <label className={`flex items-start gap-2 text-sm ${noGpu ? 'opacity-70 cursor-not-allowed' : 'cursor-pointer'}`}>
                          <input
                            type="checkbox"
                            className="mt-0.5 h-4 w-4"
                            checked={!!av.cpu_mode}
                            disabled={noGpu}
                            onChange={(e) => handleSetOmniCpu(e.target.checked)}
                          />
                          <span>
                            <span className="font-medium">Chạy trên CPU thay vì GPU</span>
                            <span className="text-dim"> — {noGpu
                                ? 'Máy không có GPU NVIDIA nên bắt buộc chạy CPU. ⚠️ Rất chậm (~15–20× thời gian thực) — hợp câu ngắn.'
                                : 'Tích nếu muốn chạy bằng CPU. ⚠️ Chậm hơn GPU nhiều lần — bình thường nên để tắt.'}</span>
                          </span>
                        </label>
                      </div>
                    )
                  })()}

                  {/* Model download status + progress */}
                  {omniStatus && (() => {
                    const dl = omniStatus.downloads?.base
                    const av = omniStatus.availability
                    const ready = av?.ready
                    const state = dl?.state
                    const mb = (b?: number) => ((b || 0) / 1048576).toFixed(0)
                    // Ready and not currently downloading → green confirmation
                    if (ready && state !== 'downloading') {
                      const noGpu = av?.deps_installed && !av?.gpu_available
                      const device = av?.cpu_mode ? 'CPU' : (av?.gpu_available ? 'GPU NVIDIA' : 'CPU')
                      return (
                        <div className="rounded-lg border border-token bg-surface-2">
                          <div className="flex items-center justify-between px-3 py-2 text-sm">
                            <span className="flex items-center gap-1.5 min-w-0">
                              <span className="text-green-600 dark:text-green-400">✅</span>
                              <span className="font-medium">Sẵn sàng</span>
                              <span className="text-dim">·</span>
                              <span className="text-dim truncate">{device}</span>
                            </span>
                            <button
                              type="button"
                              onClick={() => setShowOmniAdvanced((v) => !v)}
                              className="shrink-0 flex items-center gap-1 text-xs text-dim hover:text-primary-600"
                            >
                              ⚙ Tuỳ chọn
                              <span className={`transition-transform ${showOmniAdvanced ? 'rotate-180' : ''}`}>▾</span>
                            </button>
                          </div>
                          {showOmniAdvanced && av && (
                            <label className={`flex items-start gap-2 text-sm px-3 pb-3 pt-1 border-t border-token ${noGpu ? 'opacity-70 cursor-not-allowed' : 'cursor-pointer'}`}>
                              <input
                                type="checkbox"
                                className="mt-0.5 h-4 w-4"
                                checked={!!av.cpu_mode}
                                disabled={noGpu}
                                onChange={(e) => handleSetOmniCpu(e.target.checked)}
                              />
                              <span>
                                <span className="font-medium">Chạy trên CPU thay vì GPU</span>
                                <span className="text-dim"> — {noGpu
                                    ? 'Máy không có GPU NVIDIA nên bắt buộc chạy CPU. ⚠️ Rất chậm (~15–20× thời gian thực) — hợp câu ngắn.'
                                    : 'Tích nếu muốn chạy bằng CPU. ⚠️ Chậm hơn GPU nhiều lần — bình thường nên để tắt.'}</span>
                              </span>
                            </label>
                          )}
                        </div>
                      )
                    }
                    if (state === 'downloading') {
                      const pct = dl?.percent
                      return (
                        <div className="rounded-lg p-3 text-sm bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/30">
                          <div className="flex items-center justify-between mb-2">
                            <span className="font-medium flex items-center gap-2">
                              <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-amber-600"></span>
                              Đang tải model OmniVoice…
                            </span>
                            <span className="text-dim tabular-nums">
                              {pct != null ? `${pct}% · ` : ''}{mb(dl?.downloaded_bytes)}
                              {dl?.total_bytes ? ` / ${mb(dl?.total_bytes)}` : ''} MB
                            </span>
                          </div>
                          <div className="w-full h-2 rounded-full bg-black/10 dark:bg-white/10 overflow-hidden">
                            <div
                              className={`h-full bg-primary-500 transition-all ${pct == null ? 'animate-pulse w-full' : ''}`}
                              style={pct != null ? { width: `${pct}%` } : undefined}
                            />
                          </div>
                          <div className="text-dim text-xs mt-1.5">
                            Tải xong sẽ tự bật. Model ~1–2GB, có thể mất vài phút — cứ để chạy nền.
                          </div>
                        </div>
                      )
                    }
                    if (state === 'error') {
                      return (
                        <div className="rounded-lg p-3 text-sm bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30">
                          <div className="font-medium mb-1 text-red-600 dark:text-red-400">Tải model thất bại</div>
                          <div className="text-dim mb-2 break-words">{dl?.error}</div>
                          <button
                            onClick={() => handleDownloadOmniModel('base')}
                            className="px-3 py-1.5 rounded-md bg-primary-500 text-white text-sm hover:bg-primary-600"
                          >Thử lại</button>
                        </div>
                      )
                    }
                    // Not downloaded yet
                    return (
                      <div className="rounded-lg p-3 text-sm bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/30">
                        <div className="font-medium mb-1">Chưa có model OmniVoice</div>
                        <div className="text-dim mb-2">Cần tải model về máy (~1–2GB) để dùng OmniVoice.</div>
                        <button
                          onClick={() => handleDownloadOmniModel('base')}
                          disabled={omniDownloading}
                          className="px-3 py-1.5 rounded-md bg-primary-500 text-white text-sm hover:bg-primary-600 disabled:bg-gray-400"
                        >
                          {omniDownloading ? 'Đang bắt đầu…' : 'Tải model về'}
                        </button>
                      </div>
                    )
                  })()}

                  {/* Mode + its matching UI side by side (left = chế độ, right = UI của chế độ đó) */}
                  <div className="grid grid-cols-1 md:grid-cols-[minmax(0,260px)_1fr] gap-4 items-start">
                    {/* Left column: mode selector */}
                    <div>
                      <label className="block text-sm font-medium mb-1">Chế độ</label>
                      <select
                        value={ttsConfig.mode}
                        onChange={(e) => setTtsConfig({ ...ttsConfig, mode: e.target.value as any })}
                        className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                        disabled={loading}
                      >
                        <option value="auto">Auto (model tự chọn giọng)</option>
                        <option value="clone">Clone (giọng từ mẫu)</option>
                        <option value="design">Design (mô tả giọng)</option>
                      </select>
                    </div>

                    {/* Right column: UI tương ứng với chế độ đang chọn.
                        md:mt-6 = chiều cao label + mb-1 của cột trái, để hàng đầu căn ngang ô select thay vì ngang label. */}
                    <div className="space-y-4 md:mt-6">
                      {ttsConfig.mode === 'auto' && (
                        <div className="rounded-xl p-4 bg-surface-2 border border-token text-sm text-dim">
                          Auto: model tự chọn giọng đọc — không cần cấu hình thêm.
                        </div>
                      )}

                  {/* Clone mode: preset picker + create */}
                  {ttsConfig.mode === 'clone' && (
                    <div className="space-y-4 rounded-xl p-4 bg-surface-2 border border-token">
                      {/* Pick an existing cloned voice */}
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label className="text-sm font-medium">Giọng đã clone</label>
                          {ttsConfig.preset_id && (
                            <button
                              onClick={() => {
                                const preset = omniPresets.find((p) => p.id === ttsConfig.preset_id)
                                setConfirmDialog({
                                  isOpen: true,
                                  title: '🗑️ Xóa giọng clone',
                                  message: `Xóa giọng "${preset?.name || ''}"?\n\nKhông thể hoàn tác.`,
                                  confirmText: 'Xóa',
                                  variant: 'danger',
                                  onConfirm: () => handleDeletePreset(ttsConfig.preset_id),
                                })
                              }}
                              className="text-xs text-red-600 dark:text-red-400 hover:underline"
                            >
                              Xóa giọng này
                            </button>
                          )}
                        </div>
                        <select
                          value={ttsConfig.preset_id}
                          onChange={(e) => setTtsConfig({ ...ttsConfig, preset_id: e.target.value })}
                          className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                          disabled={loading}
                        >
                          <option value="">
                            {omniPresets.length ? '— Chọn giọng —' : '— Chưa có giọng nào, tạo bên dưới —'}
                          </option>
                          {omniPresets.map((p) => (
                            <option key={p.id} value={p.id}>{p.name}</option>
                          ))}
                        </select>
                        {ttsConfig.preset_id && (
                          <audio
                            key={ttsConfig.preset_id}
                            controls
                            preload="metadata"
                            src={`/api/v1/tts/omnivoice/presets/${ttsConfig.preset_id}/audio`}
                            className="w-full mt-2 h-10"
                          />
                        )}
                      </div>

                      {/* Create a new cloned voice — collapse để đỡ chiếm diện tích, click header để mở */}
                      <div className="border-t border-token pt-4">
                        <button
                          type="button"
                          onClick={() => setShowCreatePreset((v) => !v)}
                          className="w-full flex items-center gap-1.5 text-sm font-semibold hover:text-primary-500 transition"
                        >
                          <span className="text-primary-500 text-base leading-none">{showCreatePreset ? '−' : '+'}</span>
                          Tạo giọng clone mới
                          <svg
                            className={`w-4 h-4 ml-auto text-dim transition-transform ${showCreatePreset ? 'rotate-180' : ''}`}
                            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
                          >
                            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                          </svg>
                        </button>

                        {showCreatePreset && (
                        <div className="space-y-3 mt-3">
                        <div>
                          <label className="block text-xs font-medium text-dim mb-1">Tên giọng</label>
                          <input
                            type="text"
                            placeholder="VD: Giọng nữ miền Nam"
                            value={newPreset.name}
                            onChange={(e) => setNewPreset({ ...newPreset, name: e.target.value })}
                            className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                          />
                        </div>

                        <div>
                          <label className="block text-xs font-medium text-dim mb-1">Transcript của audio mẫu</label>
                          <textarea
                            placeholder="Nhập đúng nội dung được đọc trong file audio mẫu"
                            value={newPreset.ref_text}
                            onChange={(e) => setNewPreset({ ...newPreset, ref_text: e.target.value })}
                            rows={2}
                            className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                          />
                        </div>

                        <div>
                          <label className="block text-xs font-medium text-dim mb-1">Audio mẫu (5–15 giây)</label>
                          <label className="flex items-center gap-3 cursor-pointer">
                            <span className="px-3 py-1.5 rounded-md border border-token bg-black/5 dark:bg-white/10 text-sm font-medium hover:bg-primary-500/10 whitespace-nowrap transition">
                              Chọn file…
                            </span>
                            <span className={`text-sm truncate ${newPreset.file ? '' : 'text-dim'}`}>
                              {newPreset.file ? newPreset.file.name : 'Chưa chọn file'}
                            </span>
                            <input
                              type="file"
                              accept="audio/*"
                              onChange={(e) => setNewPreset({ ...newPreset, file: e.target.files?.[0] || null })}
                              className="hidden"
                            />
                          </label>
                        </div>

                        <button
                          onClick={handleCreatePreset}
                          disabled={!newPreset.name.trim() || !newPreset.ref_text.trim() || !newPreset.file}
                          className="w-full py-2 rounded-md bg-primary-500 text-white text-sm font-medium hover:bg-primary-600 disabled:opacity-50 disabled:cursor-not-allowed transition"
                        >
                          Tạo giọng
                        </button>
                        </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Design mode: voice description */}
                  {ttsConfig.mode === 'design' && (
                    <div>
                      <label className="block text-sm font-medium mb-1">Mô tả giọng (instruct)</label>
                      <textarea
                        placeholder="VD: A warm female voice, gentle and slow."
                        value={ttsConfig.instruct}
                        onChange={(e) => setTtsConfig({ ...ttsConfig, instruct: e.target.value })}
                        rows={2}
                        className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                        disabled={loading}
                      />
                    </div>
                  )}
                    </div>
                  </div>

                </div>
              )}

              {/* Shared: speed + bitrate */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium mb-1">Speed</label>
                  <input
                    type="number"
                    value={ttsConfig.speed}
                    onChange={(e) => setTtsConfig({ ...ttsConfig, speed: parseFloat(e.target.value) })}
                    min="0.5"
                    max="2.0"
                    step="0.1"
                    className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                    disabled={loading}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Bitrate</label>
                  <select
                    value={ttsConfig.bitrate}
                    onChange={(e) => setTtsConfig({ ...ttsConfig, bitrate: parseInt(e.target.value) })}
                    className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                    disabled={loading}
                  >
                    <option value={128}>128 kbps</option>
                    <option value={192}>192 kbps</option>
                    <option value={256}>256 kbps</option>
                  </select>
                </div>
              </div>
              {error && (
                <div className="text-red-600 dark:text-red-400 text-sm">{error}</div>
              )}
              {/* Hint why the Start button is locked (OmniVoice needs a valid voice/config) */}
              {(() => {
                if (ttsConfig.engine !== 'omnivoice' || !omniStatus?.availability?.ready) return null
                if (ttsConfig.mode === 'clone' && !ttsConfig.preset_id)
                  return <div className="text-amber-600 dark:text-amber-400 text-sm">Hãy chọn một giọng đã clone (hoặc tạo giọng mới) trước khi bắt đầu.</div>
                if (ttsConfig.mode === 'design' && !ttsConfig.instruct.trim())
                  return <div className="text-amber-600 dark:text-amber-400 text-sm">Hãy nhập mô tả giọng (instruct) trước khi bắt đầu.</div>
                return null
              })()}
              <button
                onClick={handleStartTTS}
                disabled={
                  loading ||
                  (ttsConfig.engine === 'omnivoice' && (
                    !omniStatus?.availability?.ready ||
                    (ttsConfig.mode === 'clone' && !ttsConfig.preset_id) ||
                    (ttsConfig.mode === 'design' && !ttsConfig.instruct.trim())
                  ))
                }
                className="w-full bg-primary-500 text-white py-2 px-4 rounded-md hover:bg-primary-600 transition disabled:bg-gray-400 disabled:cursor-not-allowed"
              >
                {loading
                  ? 'Đang chuyển...'
                  : ttsConfig.engine === 'omnivoice'
                    ? 'Tiếp tục → Đọc TTS'
                    : 'Start TTS Processing'}
              </button>
              </div>
            </div>
          </div>
        )

      case 6:
        if (ttsConfig.engine === 'omnivoice') {
          const total = segStats.total
          const progressed = segStats.done + segStats.error
          const pct = total ? Math.round((progressed / total) * 100) : 0
          // "A generation batch/retry is active." Prefer the server `running`
          // flag (set from the moment /run acquires the story) over just
          // processing>0 so the cancel button appears immediately on start and
          // doesn't flicker in the gap between two sentences.
          const anyBusy = segStats.processing > 0 || segRunning
          // Detect stale audio: a done segment generated with a config that no
          // longer matches the current settings (voice/mode/speed/bitrate/lang).
          // Only voice-affecting fields matter — compare a compact signature.
          const voiceSig = (c: any) => [c?.engine, c?.mode, c?.preset_id || '', c?.instruct || '', c?.language, c?.speed, c?.bitrate].join('|')
          const currentSig = voiceSig(ttsConfig)
          const configStale = !anyBusy && segments.some(s => s.status === 'done' && s.config && voiceSig(s.config) !== currentSig)
          // Regenerate deletes segment files, so block it while a merge is
          // concatenating them (merge doesn't hold the story lock).
          const merging = mergedTtsStatus.status === 'running' || segMerging
          const regenBlocked = segBusy || anyBusy || merging
          return (
            <div className="space-y-4">
              <audio ref={segAudioRef} onEnded={() => setSegNowPlaying(null)} className="hidden" />

              <div className="flex items-center justify-between gap-3 flex-wrap">
                <h3 className="text-xl font-semibold tracking-tight">Đọc TTS theo từng câu</h3>
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center gap-1.5 text-xs font-medium text-green-700 dark:text-green-400 bg-green-100 dark:bg-green-500/15 border border-green-300 dark:border-green-500/30 rounded-full px-2.5 py-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-green-500"></span>
                    Đã lưu tạm · tự khôi phục sau khi tắt app
                  </span>
                  <span className="step-badge">BƯỚC 5/7</span>
                </div>
              </div>

              {/* Config summary */}
              <div className="flex flex-wrap gap-2 text-xs">
                <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 bg-primary-50 dark:bg-primary-500/10 text-primary-700 dark:text-primary-400 border border-primary-200 dark:border-primary-500/30">⚙️ OmniVoice <span className="opacity-60">local</span></span>
                {ttsConfig.mode === 'clone' && (
                  <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 bg-surface-2 border border-token text-dim">🎭 Giọng clone: <b className="text-token">{omniPresets.find(p => p.id === ttsConfig.preset_id)?.name || '—'}</b></span>
                )}
                <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 bg-surface-2 border border-token text-dim">🌐 <b className="text-token">{ttsConfig.language === 'Vietnamese' ? 'Tiếng Việt' : ttsConfig.language}</b></span>
                <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 bg-surface-2 border border-token text-dim">⏩ Speed <b className="text-token">{ttsConfig.speed}×</b></span>
                <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 bg-surface-2 border border-token text-dim">🎚️ <b className="text-token">{ttsConfig.bitrate} kbps</b></span>
              </div>

              {/* Source changed warning (ask before re-splitting) */}
              {segSourceChanged && (
                <div className="flex items-start gap-3 text-sm bg-amber-50 dark:bg-amber-500/10 border border-amber-300 dark:border-amber-500/30 rounded-lg p-3">
                  <span>⚠️</span>
                  <div className="flex-1">
                    <b className="text-amber-800 dark:text-amber-300">Nội dung truyện đã thay đổi</b> so với lúc tách câu. Tách lại sẽ <b>xóa toàn bộ câu &amp; audio đã tạo</b>.
                    <div className="mt-2">
                      <button
                        onClick={handleSplitSegments}
                        disabled={segBusy || anyBusy}
                        className="bg-amber-600 text-white px-3 py-1.5 rounded-md text-xs font-medium hover:bg-amber-700 disabled:opacity-50 transition"
                      >
                        {segBusy ? 'Đang tách...' : anyBusy ? 'Đang chạy TTS…' : '✂️ Tách lại từ đầu'}
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Settings changed since audio was generated — offer a full re-run */}
              {configStale && (
                <div className="flex items-start gap-3 text-sm bg-amber-50 dark:bg-amber-500/10 border border-amber-300 dark:border-amber-500/30 rounded-lg p-3">
                  <span>🎛️</span>
                  <div className="flex-1">
                    <b className="text-amber-800 dark:text-amber-300">Giọng/thiết lập đã thay đổi</b> so với lúc tạo audio. Các câu “Đã xong” vẫn đang dùng giọng cũ — bấm <b>Tạo lại toàn bộ</b> để đọc lại tất cả bằng thiết lập hiện tại.
                    <div className="mt-2">
                      <button
                        onClick={handleRegenerateAll}
                        disabled={regenBlocked}
                        className="bg-amber-600 text-white px-3 py-1.5 rounded-md text-xs font-medium hover:bg-amber-700 disabled:opacity-50 transition"
                      >♻️ Tạo lại toàn bộ với thiết lập mới</button>
                    </div>
                  </div>
                </div>
              )}

              {/* Toolbar */}
              <div className="flex flex-wrap items-center gap-2">
                <div className="inline-flex bg-surface-2 border border-token rounded-lg p-0.5 gap-0.5">
                  <span className="self-center text-xs text-dim px-2">Tách theo:</span>
                  <button
                    onClick={() => setSplitMode('period')}
                    className={`text-xs font-medium rounded-md px-3 py-1.5 transition ${splitMode === 'period' ? 'bg-surface text-primary-600 dark:text-primary-400 shadow-sm' : 'text-dim hover:text-token'}`}
                  >. Dấu chấm</button>
                  <button
                    onClick={() => setSplitMode('newline')}
                    className={`text-xs font-medium rounded-md px-3 py-1.5 transition ${splitMode === 'newline' ? 'bg-surface text-primary-600 dark:text-primary-400 shadow-sm' : 'text-dim hover:text-token'}`}
                  >↵ Xuống dòng</button>
                </div>
                <button
                  onClick={handleSplitSegments}
                  disabled={segBusy || anyBusy}
                  className="text-sm font-medium rounded-lg px-3 py-2 border border-token bg-surface-2 hover:bg-surface-3 disabled:opacity-50 transition"
                >✂️ Tách câu</button>
                <div className="flex-1"></div>
                <button
                  onClick={handleRunSegments}
                  disabled={segBusy || anyBusy || total === 0 || segStats.pending + segStats.error === 0}
                  className="text-sm font-medium rounded-lg px-3 py-2 bg-primary-500 text-white hover:bg-primary-600 disabled:opacity-50 disabled:cursor-not-allowed transition"
                >🎙️ Chạy TTS tất cả</button>
                <button
                  onClick={handleRunSegments}
                  disabled={segBusy || anyBusy || segStats.error === 0}
                  className="text-sm font-medium rounded-lg px-3 py-2 border border-token bg-surface-2 hover:bg-surface-3 disabled:opacity-50 transition"
                >↻ Chạy lại lỗi</button>
                {segStats.done > 0 && (
                  <button
                    onClick={handleRegenerateAll}
                    disabled={regenBlocked}
                    title="Xóa audio cũ và đọc lại TẤT CẢ câu bằng giọng/thiết lập hiện tại"
                    className={`text-sm font-medium rounded-lg px-3 py-2 border transition disabled:opacity-50 ${
                      configStale
                        ? 'border-amber-400 dark:border-amber-500/50 bg-amber-100 dark:bg-amber-500/15 text-amber-800 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-500/25'
                        : 'border-token bg-surface-2 hover:bg-surface-3 text-token'
                    }`}
                  >♻️ Tạo lại toàn bộ</button>
                )}
                {anyBusy && (
                  <button
                    onClick={handleCancelSegments}
                    className="text-sm font-medium rounded-lg px-3 py-2 border border-red-300 dark:border-red-500/40 bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-500/20 transition"
                  >⏸ Dừng tất cả</button>
                )}
              </div>

              {/* Progress + stats */}
              {total > 0 && (
                <div className="space-y-2">
                  <div className="text-xs font-mono text-dim tabular-nums">
                    {total} dòng · <span className="text-primary-600 dark:text-primary-400">chạy {segStats.processing}</span> · <span className="text-green-600 dark:text-green-400">xong {segStats.done}</span> · <span className="text-red-600 dark:text-red-400">lỗi {segStats.error}</span> · chờ {segStats.pending}
                  </div>
                  <div className="h-2 rounded-full bg-surface-3 border border-token overflow-hidden">
                    <div className="h-full rounded-full transition-all duration-300" style={{ width: `${pct}%`, background: 'linear-gradient(90deg, var(--primary-500, #c07a12), #22c55e)' }}></div>
                  </div>
                </div>
              )}

              {/* Segment list */}
              <div className="flex items-baseline justify-between">
                <h4 className="text-sm font-semibold">Danh sách câu</h4>
                <span className="text-xs text-dim">
                  tiến độ {progressed} / {total || 0}
                  {segEtaSec !== null && <> · còn lại ~{formatEta(segEtaSec)}</>}
                </span>
              </div>

              <div className="space-y-2 max-h-[calc(100vh-520px)] min-h-[180px] overflow-y-auto pr-1">
                {total === 0 && (
                  <div className="text-sm text-dim bg-surface-2 border border-token rounded-lg p-4 text-center">
                    Chưa có câu nào. Bấm <b>Tách câu</b> để tách nội dung truyện.
                  </div>
                )}
                {segments.map((seg) => (
                  <div
                    key={seg.id}
                    className={`grid grid-cols-[36px_1fr_auto_auto] gap-3 items-center rounded-lg border p-2.5 ${
                      seg.status === 'processing' ? 'border-primary-300 dark:border-primary-500/40 bg-primary-50/50 dark:bg-primary-500/5' :
                      seg.status === 'error' ? 'border-red-300 dark:border-red-500/40' :
                      'border-token bg-surface'
                    }`}
                  >
                    <span className="text-xs font-mono text-dim">#{seg.seg_index}</span>
                    <div className="min-w-0">
                      <div className="text-sm text-token leading-snug">{seg.text}</div>
                      <div className="text-[11px] font-mono text-dim mt-0.5">
                        {seg.status === 'done' && [
                          seg.duration ? `audio ${seg.duration.toFixed(2)}s` : null,
                          seg.gen_sec ? `gen ${seg.gen_sec.toFixed(2)}s` : null,
                          seg.attempts > 1 ? `try ${seg.attempts}` : null,
                        ].filter(Boolean).join(' · ')}
                        {seg.status === 'processing' && 'đang sinh audio trên GPU…'}
                        {seg.status === 'pending' && 'chờ trong hàng đợi'}
                        {seg.status === 'error' && <span className="text-red-600 dark:text-red-400">✕ {seg.error_message || 'Lỗi'}{seg.attempts > 0 ? ` · try ${seg.attempts}` : ''}</span>}
                      </div>
                    </div>
                    <span className={`justify-self-end text-[11px] font-medium rounded-full px-2.5 py-1 border whitespace-nowrap ${
                      seg.status === 'done' ? 'text-green-700 dark:text-green-400 bg-green-100 dark:bg-green-500/15 border-green-300 dark:border-green-500/30' :
                      seg.status === 'processing' ? 'text-primary-700 dark:text-primary-400 bg-primary-100 dark:bg-primary-500/15 border-primary-300 dark:border-primary-500/40' :
                      seg.status === 'error' ? 'text-red-700 dark:text-red-400 bg-red-100 dark:bg-red-500/15 border-red-300 dark:border-red-500/30' :
                      'text-dim bg-surface-2 border-token'
                    }`}>
                      {seg.status === 'processing' && <span className="inline-block w-2 h-2 mr-1 rounded-full border-2 border-current border-r-transparent animate-spin align-[-1px]"></span>}
                      {seg.status === 'done' ? 'Đã xong' : seg.status === 'processing' ? 'Đang chạy' : seg.status === 'error' ? 'Lỗi' : 'Chưa chạy'}
                    </span>
                    <div className="flex gap-1.5">
                      <button
                        onClick={() => toggleSegPlay(seg)}
                        disabled={!seg.has_audio}
                        className="text-xs font-medium rounded-md px-2 py-1.5 border border-token bg-surface-2 text-dim hover:text-token disabled:opacity-40 disabled:cursor-not-allowed transition"
                      >{segNowPlaying === seg.id ? '⏸ Dừng' : '▶ Nghe'}</button>
                      <button
                        onClick={() => handleRetrySegment(seg.id)}
                        disabled={anyBusy || seg.status === 'processing'}
                        className="text-xs font-medium rounded-md px-2 py-1.5 border border-primary-300 dark:border-primary-500/40 bg-primary-50 dark:bg-primary-500/10 text-primary-700 dark:text-primary-400 hover:bg-primary-100 disabled:opacity-40 transition"
                      >↻ Re-TTS</button>
                      <button
                        onClick={() => handleDeleteSegment(seg.id)}
                        disabled={anyBusy || seg.status === 'processing'}
                        className="text-xs font-medium rounded-md px-2 py-1.5 border border-token bg-surface-2 text-dim hover:text-red-600 disabled:opacity-40 transition"
                      >✕</button>
                    </div>
                  </div>
                ))}
              </div>

              {/* Merge */}
              <div className="flex flex-wrap items-center gap-3">
                <label className="inline-flex items-center gap-2 cursor-pointer select-none text-sm text-token">
                  <input
                    type="checkbox"
                    checked={autoMergeAfterTts}
                    onChange={e => setAutoMergeAfterTts(e.target.checked)}
                    className="w-4 h-4 rounded border-token text-primary-500 focus:ring-primary-500 cursor-pointer"
                  />
                  <span>Tự động gộp thành 1 file sau khi TTS xong</span>
                </label>
                <button
                  onClick={handleMergeSegments}
                  disabled={!segStats.allDone || segMerging || anyBusy}
                  className="text-sm font-medium rounded-lg px-4 py-2 bg-primary-500 text-white hover:bg-primary-600 disabled:opacity-50 disabled:cursor-not-allowed transition"
                >🔗 Ghép tất cả thành 1 file</button>
                {!segStats.allDone && total > 0 && (
                  <span className="text-xs text-dim">chỉ ghép được khi tất cả câu “Đã xong”</span>
                )}
                {segStats.allDone && !autoMergeAfterTts && mergedTtsStatus.status !== 'running' && (
                  <span className="text-xs text-dim">bấm nút để gộp thủ công</span>
                )}
              </div>

              {/* Merged output — always visible. Shows the product when one exists,
                  otherwise "chưa có". Buttons stay available regardless: "Mở thư mục"
                  falls back to the story folder, "Sang bước Video" is just navigation. */}
              {(
                <div className="rounded-xl border border-dashed border-token bg-surface-2 p-4 space-y-3">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold">🎧 File thành phẩm</span>
                    {mergedTtsStatus.status === 'running' && (
                      <span className="inline-flex items-center gap-2 text-xs text-primary-600 dark:text-primary-400">
                        <span className="animate-spin rounded-full h-3.5 w-3.5 border-b-2 border-primary-600"></span> Đang ghép…
                      </span>
                    )}
                    {segStats.allDone && mergedTtsStatus.audioFile ? (
                      <span className="text-xs font-mono text-dim break-all">
                        {mergedTtsStatus.audioFile.split(/[\\/]/).pop()}
                        {mergedTtsStatus.audioSize ? ` · ${(mergedTtsStatus.audioSize / 1024 / 1024).toFixed(2)} MB` : ''}
                      </span>
                    ) : (
                      <span className="text-xs text-dim">chưa có</span>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={handleDownloadAudio}
                      disabled={downloadingAudio}
                      className="text-sm font-medium rounded-lg px-3 py-2 border border-token bg-surface hover:bg-surface-3 disabled:opacity-50 transition"
                    >{hasNativeDialogs() ? '📂 Mở thư mục' : '⬇️ Tải audio'}</button>
                    <button
                      onClick={() => moveToStep(7)}
                      className="text-sm font-medium rounded-lg px-3 py-2 bg-green-500 text-white hover:bg-green-600 transition"
                    >➡️ Sang bước Video</button>
                  </div>
                  {mergedTtsStatus.error && (
                    <div className="text-sm text-red-700 dark:text-red-400">Lỗi: {mergedTtsStatus.error}</div>
                  )}
                </div>
              )}

              {error && (
                <div className="text-red-600 dark:text-red-400 text-sm bg-red-50 dark:bg-red-500/10 p-3 rounded-md">{error}</div>
              )}
            </div>
          )
        }
        return (
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3 mb-4">
              <h3 className="text-xl font-semibold tracking-tight">Chuyển thành giọng đọc</h3>
              <span className="step-badge">BƯỚC 5/7</span>
            </div>

            {/* TTS Status */}
            <div className={`border rounded-lg p-4 ${
              mergedTtsStatus.status === 'completed' ? 'bg-green-50 dark:bg-green-500/10 border-green-200 dark:border-green-500/30' :
              mergedTtsStatus.status === 'failed' ? 'bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/30' :
              mergedTtsStatus.status === 'running' ? 'bg-primary-50 dark:bg-primary-500/10 border-primary-200 dark:border-primary-500/30' :
              'bg-surface-2 border-token'
            }`}>
              <div className="flex items-center justify-between mb-3">
                <span className="font-medium">Trạng thái TTS</span>
                <button
                  onClick={() => fetchMergedTtsStatus()}
                  className="text-xs text-primary-600 dark:text-primary-400 hover:text-primary-800 dark:hover:text-primary-300 underline"
                >
                  Refresh
                </button>
              </div>

              <div className="space-y-2">
                {/* Status Badge */}
                <div className="flex items-center gap-3">
                  {mergedTtsStatus.status === 'idle' && (
                    <span className="px-3 py-1 rounded-full bg-gray-200 dark:bg-gray-700 text-dim text-sm font-medium">
                      ⏳ Chờ xử lý
                    </span>
                  )}
                  {mergedTtsStatus.status === 'running' && (
                    <span className="px-3 py-1 rounded-full bg-primary-200 text-primary-700 dark:text-primary-400 text-sm font-medium flex items-center gap-2">
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary-700"></div>
                      Đang xử lý TTS...
                    </span>
                  )}
                  {mergedTtsStatus.status === 'completed' && (
                    <span className="px-3 py-1 rounded-full bg-green-200 text-green-700 dark:text-green-400 text-sm font-medium">
                       Hoàn thành
                    </span>
                  )}
                  {mergedTtsStatus.status === 'failed' && (
                    <span className="px-3 py-1 rounded-full bg-red-200 text-red-700 dark:text-red-400 text-sm font-medium">
                       Thất bại
                    </span>
                  )}
                </div>

                {/* Info */}
                <div className="text-sm text-dim">
                   Số ký tự: {mergedTtsStatus.charCount?.toLocaleString() || mergedView.content?.length?.toLocaleString() || 0}
                </div>

                {/* Audio File */}
                {mergedTtsStatus.audioFile && (
                  <div className="flex items-center justify-between gap-2 text-sm text-green-700 dark:text-green-400 bg-green-100 dark:bg-green-500/20 p-2 rounded">
                    <span className="min-w-0 break-all">
                       File: {mergedTtsStatus.audioFile.split(/[\\/]/).pop()}
                      {mergedTtsStatus.audioSize && (
                        <span className="ml-2 whitespace-nowrap">({(mergedTtsStatus.audioSize / 1024 / 1024).toFixed(2)} MB)</span>
                      )}
                    </span>
                    <button
                      onClick={handleDownloadAudio}
                      disabled={downloadingAudio}
                      title={hasNativeDialogs() ? 'File đã lưu ở Downloads — bấm để mở thư mục chứa file' : 'Tải file .mp3 về máy'}
                      className="shrink-0 inline-flex items-center gap-1 bg-green-600 text-white px-3 py-1 rounded text-xs font-medium hover:bg-green-700 disabled:opacity-50 transition"
                    >
                      {downloadingAudio ? (
                        <><div className="animate-spin rounded-full h-3 w-3 border-b-2 border-white"></div> Đang tải...</>
                      ) : hasNativeDialogs() ? (
                        <>📂 Mở thư mục</>
                      ) : (
                        <>⬇ Tải xuống</>
                      )}
                    </button>
                  </div>
                )}

                {/* Error */}
                {mergedTtsStatus.error && (
                  <div className="text-sm text-red-700 dark:text-red-400 bg-red-100 dark:bg-red-500/20 p-2 rounded">
                     Lỗi: {mergedTtsStatus.error}
                  </div>
                )}
              </div>
            </div>

            {/* Merged Content Preview */}
            <div className="border rounded-md">
              <div className="bg-surface-3 px-4 py-2 border-b flex items-center justify-between">
                <span className="text-sm font-medium text-dim">
                   Nội dung đã chỉnh sửa ({mergedView.content?.length?.toLocaleString() || 0} ký tự)
                </span>
              </div>
              <textarea
                value={mergedView.content || ''}
                readOnly
                className="w-full p-4 font-mono text-sm bg-surface-2 resize-none focus:outline-none"
                style={{
                  height: 'calc(100vh - 550px)',
                  minHeight: '250px'
                }}
                placeholder="Nội dung truyện sẽ hiển thị ở đây..."
              />
            </div>

            {/* Info Message */}
            {mergedTtsStatus.status === 'running' && (
              <div className="text-sm text-primary-600 dark:text-primary-400 bg-primary-50 dark:bg-primary-500/10 p-3 rounded-md flex items-center gap-2">
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary-600"></div>
                Đang xử lý TTS... Trang sẽ tự động cập nhật mỗi 10 giây.
              </div>
            )}

            {error && (
              <div className="text-red-600 dark:text-red-400 text-sm bg-red-50 dark:bg-red-500/10 p-3 rounded-md">{error}</div>
            )}

            {/* Continue Button - Show when TTS is complete */}
            {mergedTtsStatus.status === 'completed' && (
              <button
                onClick={() => moveToStep(7)}
                className="w-full bg-green-500 text-white py-3 px-4 rounded-md hover:bg-green-600 transition font-semibold"
              >
                 TTS Hoàn thành - Tiếp tục
              </button>
            )}
          </div>
        )

      case 7: {
        const [resW, resH] = videoConfig.resolution.split('x').map(Number)
        const ratio = resW / resH
        // maxW co theo chiều rộng cột (trừ ~10px cho outline offset của khung)
        // để preview không tràn ra ngoài card khi cột hẹp.
        const maxW = Math.min(720, Math.max(200, previewAvailW - 10)), maxH = 540
        const previewW = ratio >= 1 ? maxW : Math.round(maxH * ratio)
        const previewH = ratio >= 1 ? Math.round(maxW / ratio) : maxH
        const previewScaleX = videoConfig.bannerVideoScaleX
        const previewScaleY = videoConfig.bannerVideoScaleY
        // A composite pass runs when a banner is set OR the transform is non-default.
        // Mirrors the backend: at identity + no banner the clip is letterboxed
        // (contain on black); once composited it fills the scaleX×scaleY box (stretch).
        const previewTransformActive =
          Math.abs(videoConfig.bannerVideoScaleX - 1) > 0.001 ||
          Math.abs(videoConfig.bannerVideoScaleY - 1) > 0.001 ||
          Math.abs(videoConfig.bannerVideoOffsetX) > 0.001 ||
          Math.abs(videoConfig.bannerVideoOffsetY) > 0.001 ||
          Math.abs(videoConfig.bannerVideoRotation) > 0.5
        const previewCompositeMode = !!videoConfig.bannerImage || previewTransformActive
        const currentClip = clipList[currentClipIdx] || null
        const clipUrl = currentClip
          ? `/api/v1/video/preview-video?path=${encodeURIComponent(currentClip.path)}`
          : null
        const audioUrl = videoConfig.audioPath
          ? `/api/v1/video/preview-audio?path=${encodeURIComponent(videoConfig.audioPath)}`
          : null
        // Anti-detection CSS approximations for the inline preview. ffmpeg
        // applies these per-clip; here we approximate with transform+filter on
        // the <video> element. Gamma is approximated via brightness() since
        // CSS has no native gamma. Speed jitter and strip metadata are not
        // mirrored (no visible effect / not meaningful in HTML preview).
        const adTransforms: string[] = []
        if (inlineClipFlip) adTransforms.push('scaleX(-1)')
        if (videoConfig.ad_zoom && videoConfig.ad_zoom_factor > 1) {
          adTransforms.push(`scale(${videoConfig.ad_zoom_factor})`)
        }
        const adFilters: string[] = []
        if (videoConfig.ad_color) {
          if (Math.abs(videoConfig.ad_saturation - 1) > 0.001) adFilters.push(`saturate(${videoConfig.ad_saturation})`)
          if (Math.abs(videoConfig.ad_contrast - 1) > 0.001) adFilters.push(`contrast(${videoConfig.ad_contrast})`)
          if (Math.abs(videoConfig.ad_gamma - 1) > 0.001) adFilters.push(`brightness(${videoConfig.ad_gamma})`)
          if (Math.abs(videoConfig.ad_hue_shift) > 0.1) adFilters.push(`hue-rotate(${videoConfig.ad_hue_shift}deg)`)
        }
        const adVideoStyle: React.CSSProperties = {
          transform: adTransforms.join(' ') || undefined,
          filter: adFilters.join(' ') || undefined,
        }
        const isProcessing = videoStatus.status === 'running' || videoStatus.status === 'queued'
        // Estimated final video duration (matches backend logic):
        // = ceil(audio_duration / audio_speed / 60) * 60 (rounded up to next minute)
        const estimatedFinalDuration = audioDuration > 0
          ? Math.ceil((audioDuration / videoConfig.audio_speed) / 60) * 60
          : 0
        // Real-time playback total = audio_dur / speed (without minute-rounding,
        // since the preview audio is the source of truth for time)
        const timelineTotal = videoTotalDuration > 0 ? videoTotalDuration : clipsTotalDur

        return (
          <div className="space-y-4">
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <h3 className="text-xl font-semibold tracking-tight">Xử lý video</h3>
                  <span className="step-badge">BƯỚC 6/7</span>
                </div>
                <p className="text-sm text-dim">
                  Tạo video từ audio + video ngắn làm nền. Bước này là tùy chọn, có thể bỏ qua.
                </p>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-semibold text-primary-600 dark:text-primary-400"> Preset:</span>
                <select
                  value={selectedPresetId}
                  onChange={(e) => {
                    const v = e.target.value
                    setSelectedPresetId(v)
                    if (v !== '') loadPreset(v)
                  }}
                  disabled={isProcessing}
                  className="px-2 py-1.5 text-sm border rounded bg-surface focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50 min-w-[180px]"
                >
                  <option value="">
                    {videoPresets.length === 0 ? '-- Chưa có preset --' : '-- Chọn preset --'}
                  </option>
                  {videoPresets.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
                {selectedPresetId !== '' && (
                  <>
                    <button
                      onClick={updateSelectedPresetCfg}
                      disabled={isProcessing}
                      className="text-xs px-2 py-1.5 bg-surface-3 hover:bg-primary-100 dark:hover:bg-primary-500/25 text-dim hover:text-primary-700 dark:hover:text-primary-400 rounded border disabled:opacity-50"
                      title="Cập nhật preset đã chọn với config hiện tại"
                    >
                      🔄
                    </button>
                    <button
                      onClick={renamePreset}
                      disabled={isProcessing}
                      className="text-xs px-2 py-1.5 bg-surface-3 hover:bg-yellow-100 dark:hover:bg-yellow-500/25 text-dim hover:text-yellow-700 dark:hover:text-yellow-400 rounded border disabled:opacity-50"
                      title="Đổi tên preset đã chọn"
                    >
                      ✏️
                    </button>
                    <button
                      onClick={() => {
                        const cur = videoPresets.find(p => p.id === selectedPresetId)
                        if (!cur) return
                        setConfirmDialog({
                          isOpen: true,
                          title: ' Xoá preset',
                          message: `Bạn có chắc muốn xoá preset "${cur.name}"? Thao tác này không thể hoàn tác.`,
                          confirmText: 'Xoá',
                          variant: 'danger',
                          onConfirm: () => deletePreset(selectedPresetId),
                        })
                      }}
                      disabled={isProcessing}
                      className="text-xs px-2 py-1.5 bg-surface-3 hover:bg-red-100 dark:hover:bg-red-500/25 text-dim hover:text-red-600 rounded border disabled:opacity-50"
                      title="Xoá preset đã chọn"
                    >
                      🗑️
                    </button>
                  </>
                )}
                <button
                  onClick={savePreset}
                  disabled={isProcessing}
                  className="text-xs px-3 py-1.5 bg-primary-500 text-white rounded hover:bg-primary-600 disabled:opacity-50"
                >
                   Lưu config hiện tại
                </button>
                <button
                  onClick={() => {
                    setConfirmDialog({
                      isOpen: true,
                      title: ' Reset cài đặt video',
                      message: 'Reset TOÀN BỘ cài đặt video về mặc định (subtitle, watermark, banner config, fade, transitions, anti-detect, visualizer…)?\n\nFolder video, audio, ảnh banner & watermark đã chọn sẽ được giữ lại.',
                      confirmText: 'Reset',
                      variant: 'danger',
                      onConfirm: () => {
                        // DEFAULT_VIDEO_CFG is typed Omit<…, file-path keys> so the
                        // spread leaves folder/audioPath/bannerImage/watermarkImage
                        // intact — those are the painful inputs to re-pick.
                        setVideoConfig(prev => ({ ...prev, ...DEFAULT_VIDEO_CFG, clip_seed: genClipSeed() }))
                        setSubtitleSegments(null)
                      },
                    })
                  }}
                  disabled={isProcessing}
                  className="text-xs px-3 py-1.5 bg-red-50 dark:bg-red-500/10 hover:bg-red-100 dark:hover:bg-red-500/25 text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-400 rounded border border-red-200 dark:border-red-500/30 disabled:opacity-50"
                  title="Reset toàn bộ cài đặt video (giữ folder/audio/file đã chọn)"
                >
                   Reset
                </button>
              </div>
            </div>

            {/* Right sidebar: settings tabs (fixed to viewport right) */}
            <div className="fixed right-0 top-0 h-screen w-[520px] z-30 bg-surface border-l border-token shadow-2xl overflow-y-auto flex flex-col">

            {/* Video settings tabs */}
            <div className="flex border-b border-token">
              {([
                { key: 'basic', label: ' Cơ bản' },
                { key: 'effects', label: ' Hiệu ứng' },
                { key: 'antidetect', label: ' Bản quyền' },
              ] as const).map(tab => (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setVideoTab(tab.key)}
                  className={`flex-1 py-2 text-sm font-medium border-b-2 transition-colors ${
                    videoTab === tab.key
                      ? 'border-primary-500 text-primary-600 dark:text-primary-400'
                      : 'border-transparent text-dim hover:text-dim hover:border-token'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* Tab: Cơ bản */}
            {videoTab === 'basic' && <div className="space-y-3 p-3">
                {/* Inputs card */}
                <div className="border rounded-lg p-4 bg-surface space-y-3">
                  <h4 className="font-semibold text-primary-600 dark:text-primary-400 text-sm"> Nguồn dữ liệu</h4>

                  <div>
                    <label className="block text-xs font-medium mb-1 text-dim">Audio File Path</label>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={videoConfig.audioPath}
                        onChange={(e) => setVideoConfig(prev => ({ ...prev, audioPath: e.target.value }))}
                        placeholder="D:\path\to\audio\file.mp3"
                        className="flex-1 px-2 py-1.5 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500"
                        disabled={isProcessing}
                      />
                      <button
                        onClick={() => openAudioBrowser(videoConfig.audioPath || '', true, 'main')}
                        disabled={isProcessing}
                        className="px-3 py-1.5 text-sm bg-gray-600 text-white rounded hover:bg-gray-700 disabled:opacity-50"
                      >
                        Browse
                      </button>
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-medium mb-1 text-dim">Video Source Folder</label>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={videoConfig.folder}
                        onChange={(e) => {
                          setVideoConfig(prev => ({ ...prev, folder: e.target.value }))
                          setFolderValidation({ valid: false, videoCount: 0, totalDuration: '', checked: false })
                        }}
                        placeholder="D:\path\to\video\folder"
                        className="flex-1 px-2 py-1.5 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500"
                        disabled={isProcessing}
                      />
                      <button
                        onClick={() => openFolderBrowser(videoConfig.folder || '')}
                        disabled={isProcessing}
                        className="px-3 py-1.5 text-sm bg-gray-600 text-white rounded hover:bg-gray-700 disabled:opacity-50"
                      >
                        Browse
                      </button>
                      <button
                        onClick={validateVideoFolder}
                        disabled={!videoConfig.folder.trim() || videoStatus.status === 'running'}
                        className="px-3 py-1.5 text-sm bg-primary-500 text-white rounded hover:bg-primary-600 disabled:opacity-50"
                      >
                        Validate
                      </button>
                    </div>
                    {folderValidation.checked && (
                      <div className={`mt-1 text-xs ${folderValidation.valid ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                        {folderValidation.valid
                          ? `✓ ${folderValidation.videoCount} videos (${folderValidation.totalDuration})`
                          : 'Invalid folder'}
                      </div>
                    )}

                    {/* Cách chọn clip nền từ folder */}
                    <div className="mt-2">
                      <label className="block text-xs font-medium mb-1 text-dim">Cách chọn clip nền</label>
                      <div className="flex gap-4">
                        <label
                          className="flex items-center gap-1.5 text-xs text-dim cursor-pointer select-none"
                          title="Xáo trộn thứ tự clip nền. Preview và video xuất ra dùng chung một thứ tự (khớp nhau). Bấm 'Trộn lại' để đổi sang thứ tự khác."
                        >
                          <input
                            type="radio"
                            name="clip_order"
                            checked={videoConfig.clip_order === 'shuffle'}
                            onChange={() => setVideoConfig(prev => ({ ...prev, clip_order: 'shuffle' }))}
                            disabled={isProcessing}
                          />
                          Ngẫu nhiên (mặc định)
                        </label>
                        <label
                          className="flex items-center gap-1.5 text-xs text-dim cursor-pointer select-none"
                          title="Chọn clip theo thứ tự tên file (A→Z), luôn bắt đầu từ clip đầu tiên. Kết quả tái lập được, nhưng các video cùng folder nền sẽ ra phần nền giống nhau."
                        >
                          <input
                            type="radio"
                            name="clip_order"
                            checked={videoConfig.clip_order === 'name'}
                            onChange={() => setVideoConfig(prev => ({ ...prev, clip_order: 'name' }))}
                            disabled={isProcessing}
                          />
                          Theo thứ tự tên
                        </label>
                        {videoConfig.clip_order === 'shuffle' && (
                          <button
                            type="button"
                            onClick={() => setVideoConfig(prev => ({ ...prev, clip_seed: genClipSeed() }))}
                            disabled={isProcessing}
                            title="Đổi sang một thứ tự trộn khác (cả preview lẫn video xuất ra sẽ đổi theo)"
                            className="flex items-center gap-1 text-xs px-2 py-0.5 rounded border border-token hover:bg-surface-2 disabled:opacity-50"
                          >
                            🎲 Trộn lại
                          </button>
                        )}
                      </div>
                      <p className="text-[11px] text-faint mt-0.5">
                        {videoConfig.clip_order === 'shuffle'
                          ? 'Clip được xáo trộn — preview và video xuất ra khớp nhau. Bấm “Trộn lại” để đổi thứ tự.'
                          : 'Chọn theo tên file A→Z → video cùng folder sẽ có nền giống nhau.'}
                      </p>
                    </div>
                  </div>

                  {/* Kích thước & vị trí của SOURCE VIDEO — độc lập với banner.
                      Đặt trên Banner Background để tránh hiểu lầm là chỉnh banner. */}
                  <div>
                    <label className="block text-xs font-medium mb-1 text-dim">Kích thước & vị trí video</label>
                    <div className="mt-1 flex items-center gap-2">
                      <label className="text-xs text-dim whitespace-nowrap w-20">Rộng: {Math.round(videoConfig.bannerVideoScaleX * 100)}%</label>
                      <input
                        type="range" min="0.1" max="3" step="0.05"
                        value={videoConfig.bannerVideoScaleX}
                        onChange={(e) => setVideoConfig(prev => ({ ...prev, bannerVideoScaleX: parseFloat(e.target.value) }))}
                        className="flex-1"
                        disabled={isProcessing}
                      />
                    </div>
                    <div className="mt-1 flex items-center gap-2">
                      <label className="text-xs text-dim whitespace-nowrap w-20">Cao: {Math.round(videoConfig.bannerVideoScaleY * 100)}%</label>
                      <input
                        type="range" min="0.1" max="3" step="0.05"
                        value={videoConfig.bannerVideoScaleY}
                        onChange={(e) => setVideoConfig(prev => ({ ...prev, bannerVideoScaleY: parseFloat(e.target.value) }))}
                        className="flex-1"
                        disabled={isProcessing}
                      />
                      <button
                        onClick={() => setVideoConfig(prev => ({ ...prev, bannerVideoScaleY: prev.bannerVideoScaleX }))}
                        disabled={isProcessing}
                        className="text-[11px] text-primary-600 dark:text-primary-400 hover:underline disabled:opacity-50 whitespace-nowrap"
                        title="Đặt chiều cao bằng chiều rộng (khôi phục tỉ lệ vuông theo cạnh rộng)"
                      >
                        = Rộng
                      </button>
                    </div>
                    <div className="mt-1 flex items-center gap-2">
                      <label className="text-xs text-dim whitespace-nowrap w-20">Xoay: {videoConfig.bannerVideoRotation}°</label>
                      <input
                        type="range" min="-180" max="180" step="1"
                        value={videoConfig.bannerVideoRotation}
                        onChange={(e) => setVideoConfig(prev => ({ ...prev, bannerVideoRotation: parseInt(e.target.value, 10) }))}
                        className="flex-1"
                        disabled={isProcessing}
                      />
                      <button
                        onClick={() => setVideoConfig(prev => ({ ...prev, bannerVideoRotation: 0 }))}
                        disabled={isProcessing}
                        className="text-[11px] text-primary-600 dark:text-primary-400 hover:underline disabled:opacity-50 whitespace-nowrap"
                        title="Đặt lại về 0°"
                      >
                        = 0°
                      </button>
                    </div>
                    <div className="mt-1 flex items-center justify-between">
                      <span className="text-[11px] text-faint">
                        💡 Kéo thân để di chuyển · kéo góc/cạnh để resize (cạnh = riêng rộng/cao). Áp cho mọi clip.
                        {!videoConfig.bannerImage && ' Không có banner → phần trống là nền đen.'}
                      </span>
                      {(Math.abs(videoConfig.bannerVideoOffsetX) > 0.001 || Math.abs(videoConfig.bannerVideoOffsetY) > 0.001) && (
                        <button
                          onClick={() => setVideoConfig(prev => ({ ...prev, bannerVideoOffsetX: 0, bannerVideoOffsetY: 0 }))}
                          disabled={isProcessing}
                          className="text-[11px] text-primary-600 dark:text-primary-400 hover:underline disabled:opacity-50 whitespace-nowrap ml-2"
                          title="Đưa video về giữa khung"
                        >
                          Về giữa
                        </button>
                      )}
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-medium mb-1 text-dim">Banner Background (Optional)</label>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={videoConfig.bannerImage}
                        onChange={(e) => setVideoConfig(prev => ({ ...prev, bannerImage: e.target.value }))}
                        placeholder="D:\path\to\banner.png"
                        className="flex-1 px-2 py-1.5 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500"
                        disabled={isProcessing}
                      />
                      <button
                        onClick={() => openImageBrowser(videoConfig.bannerImage || '', true)}
                        disabled={isProcessing}
                        className="px-3 py-1.5 text-sm bg-gray-600 text-white rounded hover:bg-gray-700 disabled:opacity-50"
                      >
                        Browse
                      </button>
                      {videoConfig.bannerImage && (
                        <button
                          onClick={() => setVideoConfig(prev => ({ ...prev, bannerImage: '' }))}
                          disabled={isProcessing}
                          className="px-2 py-1.5 text-sm bg-red-500 text-white rounded hover:bg-red-600 disabled:opacity-50"
                          title="Clear banner"
                        >
                          ×
                        </button>
                      )}
                    </div>
                  </div>
                </div>

                {/* Config card */}
                <div className="border rounded-lg p-4 bg-surface space-y-3">
                  <h4 className="font-semibold text-primary-600 dark:text-primary-400 text-sm"> Cấu hình video</h4>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium mb-1 text-dim">Audio Speed</label>
                      <input
                        type="number"
                        value={videoConfig.audio_speed}
                        onChange={(e) => setVideoConfig(prev => ({ ...prev, audio_speed: parseFloat(e.target.value) || 1.0 }))}
                        step="0.01" min="0.5" max="2.0"
                        className="w-full px-2 py-1.5 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500"
                        disabled={videoStatus.status === 'running'}
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium mb-1 text-dim">Transition Duration (s)</label>
                      <input
                        type="number"
                        value={videoConfig.transition_duration}
                        onChange={(e) => setVideoConfig(prev => ({ ...prev, transition_duration: parseFloat(e.target.value) || 0.5 }))}
                        step="0.1" min="0.1" max="3"
                        className="w-full px-2 py-1.5 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500"
                        disabled={videoStatus.status === 'running'}
                      />
                    </div>
                    <div className="col-span-2">
                      <label className="block text-xs font-medium mb-1 text-dim">Resolution</label>
                      <select
                        value={videoConfig.resolution}
                        onChange={(e) => setVideoConfig(prev => ({ ...prev, resolution: e.target.value }))}
                        className="w-full px-2 py-1.5 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500"
                        disabled={videoStatus.status === 'running'}
                      >
                        <option value="1920x1080">1920x1080 (16:9 — 1080p)</option>
                        <option value="1080x1920">1080x1920 (9:16 — Vertical)</option>
                      </select>
                    </div>
                    <div className="col-span-2">
                      <label className="block text-xs font-medium mb-1 text-dim">
                         Overlay tối: {Math.round(videoConfig.overlay_opacity * 100)}%
                      </label>
                      <input
                        type="range" min="0" max="0.8" step="0.05"
                        value={videoConfig.overlay_opacity}
                        onChange={(e) => setVideoConfig(prev => ({ ...prev, overlay_opacity: parseFloat(e.target.value) }))}
                        className="w-full"
                        disabled={videoStatus.status === 'running'}
                      />
                      <p className="text-[11px] text-faint mt-0.5">Lớp đen mờ đè lên video, giúp tăng tương phản</p>
                    </div>
                    <div className="col-span-2">
                      <label className="flex items-center gap-2 text-xs text-dim cursor-pointer select-none">
                        <input
                          type="checkbox"
                          checked={videoConfig.mute_source_videos}
                          onChange={(e) => setVideoConfig(prev => ({ ...prev, mute_source_videos: e.target.checked }))}
                          disabled={videoStatus.status === 'running'}
                        />
                         Tắt âm video nền (chỉ giữ âm thanh chính)
                      </label>
                      <p className="text-[11px] text-faint mt-0.5 ml-5">Bỏ tích nếu muốn trộn cả tiếng từ video nguồn vào</p>
                    </div>
                  </div>
                </div>

                {/* Background music card */}
                <div className="border rounded-lg p-4 bg-surface space-y-3">
                  <h4 className="font-semibold text-primary-600 dark:text-primary-400 text-sm">🎵 Nhạc nền (tùy chọn)</h4>

                  <div>
                    <label className="block text-xs font-medium mb-1 text-dim">Music File Path</label>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={videoConfig.bgmPath}
                        onChange={(e) => setVideoConfig(prev => ({ ...prev, bgmPath: e.target.value }))}
                        placeholder="D:\path\to\music.mp3"
                        className="flex-1 px-2 py-1.5 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500"
                        disabled={isProcessing}
                      />
                      <button
                        onClick={() => openAudioBrowser(videoConfig.bgmPath || '', true, 'bgm')}
                        disabled={isProcessing}
                        className="px-3 py-1.5 text-sm bg-gray-600 text-white rounded hover:bg-gray-700 disabled:opacity-50"
                      >
                        Browse
                      </button>
                      {videoConfig.bgmPath && (
                        <button
                          onClick={() => setVideoConfig(prev => ({ ...prev, bgmPath: '' }))}
                          disabled={isProcessing}
                          className="px-2 py-1.5 text-sm bg-red-500 text-white rounded hover:bg-red-600 disabled:opacity-50"
                          title="Xoá nhạc nền"
                        >
                          ×
                        </button>
                      )}
                    </div>
                    <p className="text-[11px] text-faint mt-0.5">Nhạc phát dưới giọng đọc. Bỏ trống = không dùng nhạc nền.</p>
                  </div>

                  {videoConfig.bgmPath && (
                    <>
                      <div>
                        <label className="block text-xs font-medium mb-1 text-dim">
                          Âm lượng nhạc: {Math.round(videoConfig.bgm_volume * 100)}%
                        </label>
                        <input
                          type="range" min="0" max="0.5" step="0.01"
                          value={videoConfig.bgm_volume}
                          onChange={(e) => setVideoConfig(prev => ({ ...prev, bgm_volume: parseFloat(e.target.value) }))}
                          className="w-full"
                          disabled={isProcessing}
                        />
                        <p className="text-[11px] text-faint mt-0.5">Mức âm nhạc so với giọng đọc (giọng luôn giữ nguyên 100%).</p>
                      </div>

                      <div>
                        <label className="block text-xs font-medium mb-1 text-dim">Fade in/out nhạc (s)</label>
                        <input
                          type="number"
                          value={videoConfig.bgm_fade}
                          onChange={(e) => setVideoConfig(prev => ({ ...prev, bgm_fade: Math.max(0, parseFloat(e.target.value) || 0) }))}
                          step="0.5" min="0" max="10"
                          className="w-32 px-2 py-1.5 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500"
                          disabled={isProcessing}
                        />
                      </div>

                      <label className="flex items-center gap-2 text-xs text-dim cursor-pointer select-none">
                        <input
                          type="checkbox"
                          checked={videoConfig.bgm_loop}
                          onChange={(e) => setVideoConfig(prev => ({ ...prev, bgm_loop: e.target.checked }))}
                          disabled={isProcessing}
                        />
                        Lặp nhạc cho đủ độ dài video
                      </label>

                      <div>
                        <label className="flex items-center gap-2 text-xs text-dim cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={videoConfig.bgm_ducking}
                            onChange={(e) => setVideoConfig(prev => ({ ...prev, bgm_ducking: e.target.checked }))}
                            disabled={isProcessing}
                          />
                          Tự động hạ nhạc khi có giọng đọc (ducking)
                        </label>
                        <p className="text-[11px] text-faint mt-0.5 ml-5">Nhạc tự nhỏ lại khi đang đọc, to lại ở khoảng lặng.</p>
                      </div>
                    </>
                  )}
                </div>

            </div>}

            {/* Tab: Hiệu ứng */}
            {videoTab === 'effects' && <>

            {/* Watermark & Fade card (full width, collapsible) */}
            <div className="border rounded-lg bg-surface">
              <button
                type="button"
                onClick={() => setWmCardOpen(o => !o)}
                className="w-full flex items-center justify-between p-4 text-left hover:bg-surface-2 rounded-lg"
              >
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-primary-600 dark:text-primary-400 text-sm"> Watermark & Fade</span>
                  {(() => {
                    const active: string[] = []
                    if (videoConfig.watermarkImage) active.push('logo')
                    if (videoConfig.watermark_text) active.push('text')
                    if (videoConfig.fade_in > 0 || videoConfig.fade_out > 0) active.push('fade')
                    return active.length > 0 ? (
                      <span className="text-[11px] text-dim">({active.join(' · ')})</span>
                    ) : (
                      <span className="text-[11px] text-faint">(không bật)</span>
                    )
                  })()}
                </div>
                <span className="text-faint text-xs">{wmCardOpen ? '▲ ẩn' : '▼ hiện'}</span>
              </button>

              {wmCardOpen && (
              <div className="px-4 pb-4 space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Watermark column */}
                <div className="space-y-2">
                  <div className="text-xs font-medium text-dim"> Watermark / Logo (image, optional)</div>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={videoConfig.watermarkImage}
                      onChange={(e) => setVideoConfig(prev => ({ ...prev, watermarkImage: e.target.value }))}
                      placeholder="D:\path\to\logo.png"
                      className="flex-1 min-w-0 px-2 py-1.5 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500"
                      disabled={isProcessing}
                    />
                    <button
                      onClick={() => openImageBrowser(videoConfig.watermarkImage || '', true, 'watermark')}
                      disabled={isProcessing}
                      className="px-3 py-1.5 text-sm bg-gray-600 text-white rounded hover:bg-gray-700 disabled:opacity-50"
                    >
                      Browse
                    </button>
                    {videoConfig.watermarkImage && (
                      <button
                        onClick={() => setVideoConfig(prev => ({ ...prev, watermarkImage: '' }))}
                        disabled={isProcessing}
                        className="px-2 py-1.5 text-sm bg-red-500 text-white rounded hover:bg-red-600 disabled:opacity-50"
                        title="Clear watermark"
                      >
                        ×
                      </button>
                    )}
                  </div>

                  {videoConfig.watermarkImage && (
                    <>
                      <div>
                        <label className="block text-xs text-dim mb-1">
                          Vị trí: X {Math.round(videoConfig.watermark_x * 100)}% · Y {Math.round(videoConfig.watermark_y * 100)}%
                          <span className="ml-2 text-[10px] text-primary-500 dark:text-primary-400">(kéo trên preview để chỉnh)</span>
                        </label>
                        <div className="grid grid-cols-5 gap-1">
                          {([
                            { lbl: '', x: 0.08, y: 0.08 },
                            { lbl: '', x: 0.92, y: 0.08 },
                            { lbl: '⊙', x: 0.5, y: 0.5 },
                            { lbl: '', x: 0.08, y: 0.92 },
                            { lbl: '', x: 0.92, y: 0.92 },
                          ]).map(({ lbl, x, y }) => {
                            const active = Math.abs(videoConfig.watermark_x - x) < 0.02 && Math.abs(videoConfig.watermark_y - y) < 0.02
                            return (
                              <button
                                key={lbl}
                                onClick={() => setVideoConfig(prev => ({ ...prev, watermark_x: x, watermark_y: y }))}
                                disabled={isProcessing}
                                className={`text-sm px-2 py-1 rounded border ${
                                  active
                                    ? 'bg-primary-500 text-white border-primary-500'
                                    : 'bg-surface text-dim border-token hover:border-primary-400'
                                }`}
                                title={`${Math.round(x*100)}%, ${Math.round(y*100)}%`}
                              >
                                {lbl}
                              </button>
                            )
                          })}
                        </div>
                      </div>
                      <div>
                        <label className="block text-xs text-dim mb-1">Kích thước (px)</label>
                        <div className="flex gap-2 items-center">
                          <div className="flex-1">
                            <div className="text-[10px] text-dim mb-0.5">W</div>
                            <input
                              type="number" min={16} max={4096} step={4}
                              value={videoConfig.watermark_w}
                              onChange={(e) => setVideoConfig(prev => ({ ...prev, watermark_w: parseInt(e.target.value) || 200 }))}
                              className="w-full px-2 py-1 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500"
                              disabled={isProcessing}
                            />
                          </div>
                          <span className="text-faint mt-3">×</span>
                          <div className="flex-1">
                            <div className="text-[10px] text-dim mb-0.5">H</div>
                            <input
                              type="number" min={16} max={4096} step={4}
                              value={videoConfig.watermark_h}
                              onChange={(e) => setVideoConfig(prev => ({ ...prev, watermark_h: parseInt(e.target.value) || 200 }))}
                              className="w-full px-2 py-1 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500"
                              disabled={isProcessing}
                            />
                          </div>
                          <button
                            type="button"
                            onClick={() => setVideoConfig(prev => ({ ...prev, watermark_h: prev.watermark_w }))}
                            disabled={isProcessing}
                            className="mt-3 text-xs px-2 py-1 bg-surface-3 text-dim rounded hover:bg-gray-200 dark:hover:bg-gray-700"
                            title="Đồng bộ H = W (vuông)"
                          >
                            ⊡
                          </button>
                        </div>
                      </div>

                      <div>
                        <label className="block text-xs text-dim mb-1">Cắt theo hình</label>
                        <div className="grid grid-cols-5 gap-1">
                          {([
                            { v: 'none', lbl: '▭', t: 'Mặc định (giữ nguyên)' },
                            { v: 'circle', lbl: '●', t: 'Bo tròn' },
                            { v: 'rounded', lbl: '▢', t: 'Bo ô vuông' },
                            { v: 'star', lbl: '', t: 'Hình sao' },
                            { v: 'sun', lbl: '', t: 'Mặt trời' },
                          ]).map(({ v, lbl, t }) => {
                            const active = videoConfig.watermark_shape === v
                            return (
                              <button
                                key={v}
                                onClick={() => setVideoConfig(prev => ({ ...prev, watermark_shape: v }))}
                                disabled={isProcessing}
                                title={t}
                                className={`text-base px-2 py-1 rounded border ${
                                  active
                                    ? 'bg-primary-500 text-white border-primary-500'
                                    : 'bg-surface text-dim border-token hover:border-primary-400'
                                }`}
                              >
                                {lbl}
                              </button>
                            )
                          })}
                        </div>
                      </div>
                      <div>
                        <label className="block text-xs text-dim mb-1">
                          Độ mờ: {Math.round(videoConfig.watermark_opacity * 100)}%
                        </label>
                        <input
                          type="range" min="0.1" max="1" step="0.05"
                          value={videoConfig.watermark_opacity}
                          onChange={(e) => setVideoConfig(prev => ({ ...prev, watermark_opacity: parseFloat(e.target.value) }))}
                          className="w-full"
                          disabled={isProcessing}
                        />
                      </div>
                      <img
                        src={`/api/v1/video/preview-image?path=${encodeURIComponent(videoConfig.watermarkImage)}`}
                        alt="watermark preview"
                        className="max-h-16 rounded border border-token object-contain bg-surface-2"
                        onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                      />
                    </>
                  )}
                </div>

                {/* Text watermark column */}
                <div className="space-y-2">
                  <div className="text-xs font-medium text-dim"> Watermark text (optional)</div>
                  <input
                    type="text"
                    value={videoConfig.watermark_text}
                    onChange={(e) => setVideoConfig(prev => ({ ...prev, watermark_text: e.target.value }))}
                    placeholder="Vd: @MyChannel, ©2026..."
                    className="w-full px-2 py-1.5 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500"
                    disabled={isProcessing}
                  />

                  {videoConfig.watermark_text && (
                    <>
                      <div>
                        <label className="block text-xs text-dim mb-1">Font</label>
                        <select
                          value={videoConfig.watermark_text_font}
                          onChange={(e) => setVideoConfig(prev => ({ ...prev, watermark_text_font: e.target.value }))}
                          className="w-full px-2 py-1.5 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500"
                          disabled={isProcessing}
                        >
                          {availableFonts.map(f => <option key={f} value={f}>{f}</option>)}
                        </select>
                      </div>

                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <label className="block text-xs text-dim mb-1">Size: {videoConfig.watermark_text_size}px</label>
                          <input
                            type="range" min="16" max="200" step="2"
                            value={videoConfig.watermark_text_size}
                            onChange={(e) => setVideoConfig(prev => ({ ...prev, watermark_text_size: parseInt(e.target.value) }))}
                            className="w-full"
                            disabled={isProcessing}
                          />
                        </div>
                        <div>
                          <label className="block text-xs text-dim mb-1">Màu chữ</label>
                          <input
                            type="color"
                            value={videoConfig.watermark_text_color}
                            onChange={(e) => setVideoConfig(prev => ({ ...prev, watermark_text_color: e.target.value }))}
                            className="w-full h-8 rounded border"
                            disabled={isProcessing}
                          />
                        </div>
                      </div>

                      <div>
                        <label className="block text-xs text-dim mb-1">
                          Góc nghiêng: {videoConfig.watermark_text_angle.toFixed(0)}°
                        </label>
                        <input
                          type="range" min="-45" max="45" step="1"
                          value={videoConfig.watermark_text_angle}
                          onChange={(e) => setVideoConfig(prev => ({ ...prev, watermark_text_angle: parseFloat(e.target.value) }))}
                          className="w-full"
                          disabled={isProcessing}
                        />
                      </div>

                      <div>
                        <label className="block text-xs text-dim mb-1">
                          Vị trí: X {Math.round(videoConfig.watermark_text_x * 100)}% · Y {Math.round(videoConfig.watermark_text_y * 100)}%
                          <span className="ml-2 text-[10px] text-primary-500 dark:text-primary-400">(kéo trên preview để chỉnh)</span>
                        </label>
                        <div className="grid grid-cols-5 gap-1">
                          {([
                            { lbl: '', x: 0.08, y: 0.08 },
                            { lbl: '', x: 0.92, y: 0.08 },
                            { lbl: '⊙', x: 0.5, y: 0.5 },
                            { lbl: '', x: 0.08, y: 0.92 },
                            { lbl: '', x: 0.92, y: 0.92 },
                          ]).map(({ lbl, x, y }) => {
                            const active = Math.abs(videoConfig.watermark_text_x - x) < 0.02 && Math.abs(videoConfig.watermark_text_y - y) < 0.02
                            return (
                              <button
                                key={lbl}
                                onClick={() => setVideoConfig(prev => ({ ...prev, watermark_text_x: x, watermark_text_y: y }))}
                                disabled={isProcessing}
                                className={`text-sm px-2 py-1 rounded border ${
                                  active
                                    ? 'bg-primary-500 text-white border-primary-500'
                                    : 'bg-surface text-dim border-token hover:border-primary-400'
                                }`}
                                title={`${Math.round(x*100)}%, ${Math.round(y*100)}%`}
                              >
                                {lbl}
                              </button>
                            )
                          })}
                        </div>
                      </div>

                      <div>
                        <label className="block text-xs text-dim mb-1">
                          Độ mờ: {Math.round(videoConfig.watermark_text_opacity * 100)}%
                        </label>
                        <input
                          type="range" min="0.1" max="1" step="0.05"
                          value={videoConfig.watermark_text_opacity}
                          onChange={(e) => setVideoConfig(prev => ({ ...prev, watermark_text_opacity: parseFloat(e.target.value) }))}
                          className="w-full"
                          disabled={isProcessing}
                        />
                      </div>
                    </>
                  )}
                </div>
              </div>

              {/* Fade row (full width below) */}
              <div className="border-t pt-3 mt-2 grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-dim mb-1">
                     Fade in: {videoConfig.fade_in.toFixed(1)}s {videoConfig.fade_in === 0 && '(tắt)'}
                  </label>
                  <input
                    type="range" min="0" max="3" step="0.1"
                    value={videoConfig.fade_in}
                    onChange={(e) => setVideoConfig(prev => ({ ...prev, fade_in: parseFloat(e.target.value) }))}
                    className="w-full"
                    disabled={isProcessing}
                  />
                </div>
                <div>
                  <label className="block text-xs text-dim mb-1">
                     Fade out: {videoConfig.fade_out.toFixed(1)}s {videoConfig.fade_out === 0 && '(tắt)'}
                  </label>
                  <input
                    type="range" min="0" max="3" step="0.1"
                    value={videoConfig.fade_out}
                    onChange={(e) => setVideoConfig(prev => ({ ...prev, fade_out: parseFloat(e.target.value) }))}
                    className="w-full"
                    disabled={isProcessing}
                  />
                </div>
              </div>
              </div>
              )}
            </div>

            {/* Audio Visualizer card (collapsible) */}
            <div className="border rounded-lg bg-surface">
              <button
                type="button"
                onClick={() => setVizCardOpen(o => !o)}
                className="w-full flex items-center justify-between p-4 text-left hover:bg-surface-2 rounded-lg"
              >
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-primary-600 dark:text-primary-400 text-sm"> Audio Visualizer</span>
                  {videoConfig.visualizer_enabled ? (
                    <span className="text-[11px] text-dim">
                      ({videoConfig.visualizer_style}
                      {videoConfig.visualizer_style === 'spectrum' ? ` · ${videoConfig.visualizer_spectrum_preset}` : ''})
                    </span>
                  ) : (
                    <span className="text-[11px] text-faint">(không bật)</span>
                  )}
                </div>
                <span className="text-faint text-xs">{vizCardOpen ? '▲ ẩn' : '▼ hiện'}</span>
              </button>

              {vizCardOpen && (
              <div className="px-4 pb-4 space-y-3">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={videoConfig.visualizer_enabled}
                    onChange={(e) => setVideoConfig(prev => ({ ...prev, visualizer_enabled: e.target.checked }))}
                    disabled={isProcessing}
                  />
                  <span className="text-sm font-medium text-dim">Bật visualizer (sóng nhạc theo audio)</span>
                </label>

                {videoConfig.visualizer_enabled && (
                  <>
                    {/* Style picker — 4 top-level styles */}
                    <div>
                      <label className="block text-xs text-dim mb-1">Kiểu hiển thị</label>
                      <div className="grid grid-cols-4 gap-1">
                        {([
                          { v: 'bars', lbl: ' Bars', t: 'Cột tần số (showfreqs)' },
                          { v: 'waveform', lbl: '〰️ Wave', t: 'Sóng (showwaves) — Smooth/Linear/Dots/Filled + Symmetrical' },
                          { v: 'spectrum', lbl: ' Spectrum', t: 'Phổ tần số scrolling' },
                          { v: 'cqt', lbl: ' CQT', t: 'Music-aware bars (showcqt) — đẹp nhất' },
                        ] as const).map(({ v, lbl, t }) => {
                          const active = videoConfig.visualizer_style === v
                          return (
                            <button
                              key={v}
                              onClick={() => setVideoConfig(prev => ({ ...prev, visualizer_style: v }))}
                              disabled={isProcessing}
                              title={t}
                              className={`text-xs px-2 py-1.5 rounded border ${
                                active
                                  ? 'bg-primary-500 text-white border-primary-500'
                                  : 'bg-surface text-dim border-token hover:border-primary-400'
                              }`}
                            >
                              {lbl}
                            </button>
                          )
                        })}
                      </div>
                    </div>

                    {/* Sub-mode picker for Bars */}
                    {videoConfig.visualizer_style === 'bars' && (
                      <div>
                        <label className="block text-xs text-dim mb-1">Bars mode</label>
                        <div className="grid grid-cols-3 gap-1">
                          {([
                            { v: 'bar', lbl: 'Bar', t: 'Cột đặc (mặc định)' },
                            { v: 'line', lbl: 'Line', t: 'Đường nối đỉnh' },
                            { v: 'dot', lbl: 'Dot', t: 'Chấm đỉnh' },
                          ] as const).map(({ v, lbl, t }) => {
                            const active = videoConfig.visualizer_bars_mode === v
                            return (
                              <button
                                key={v}
                                onClick={() => setVideoConfig(prev => ({ ...prev, visualizer_bars_mode: v }))}
                                disabled={isProcessing}
                                title={t}
                                className={`text-xs px-2 py-1 rounded border ${
                                  active
                                    ? 'bg-primary-500 text-white border-primary-500'
                                    : 'bg-surface text-dim border-token hover:border-primary-400'
                                }`}
                              >
                                {lbl}
                              </button>
                            )
                          })}
                        </div>
                      </div>
                    )}

                    {/* Sub-mode picker + mirror toggle for Waveform */}
                    {videoConfig.visualizer_style === 'waveform' && (
                      <div className="space-y-2">
                        <div>
                          <label className="block text-xs text-dim mb-1">Waveform mode</label>
                          <div className="grid grid-cols-4 gap-1">
                            {([
                              { v: 'cline', lbl: 'Smooth', t: 'Đường centered, cong mượt (cline) — mặc định' },
                              { v: 'line', lbl: 'Linear', t: 'Đường line nối thẳng các sample' },
                              { v: 'point', lbl: 'Dots', t: 'Chỉ chấm điểm sample, không vẽ đường' },
                              { v: 'p2p', lbl: 'Filled', t: 'Lấp đầy giữa các sample (peer-to-peer fill)' },
                            ] as const).map(({ v, lbl, t }) => {
                              const active = videoConfig.visualizer_waveform_mode === v
                              return (
                                <button
                                  key={v}
                                  onClick={() => setVideoConfig(prev => ({ ...prev, visualizer_waveform_mode: v }))}
                                  disabled={isProcessing}
                                  title={t}
                                  className={`text-xs px-2 py-1 rounded border ${
                                    active
                                      ? 'bg-primary-500 text-white border-primary-500'
                                      : 'bg-surface text-dim border-token hover:border-primary-400'
                                  }`}
                                >
                                  {lbl}
                                </button>
                              )
                            })}
                          </div>
                        </div>
                        <label className="flex items-center gap-2 text-xs cursor-pointer">
                          <input
                            type="checkbox"
                            checked={videoConfig.visualizer_waveform_mirror}
                            onChange={(e) => setVideoConfig(prev => ({ ...prev, visualizer_waveform_mirror: e.target.checked }))}
                            disabled={isProcessing}
                          />
                          Symmetrical (sóng đối xứng trên/dưới — như audio meter)
                        </label>
                      </div>
                    )}

                    {/* Position */}
                    <div>
                      <label className="block text-xs text-dim mb-1">
                        Vị trí: X {Math.round(videoConfig.visualizer_x * 100)}% · Y {Math.round(videoConfig.visualizer_y * 100)}%
                        <span className="ml-2 text-[10px] text-primary-500 dark:text-primary-400">(kéo trên preview để chỉnh)</span>
                      </label>
                      <div className="grid grid-cols-5 gap-1">
                        {([
                          { lbl: '', x: 0.08, y: 0.08 },
                          { lbl: '', x: 0.5, y: 0.08 },
                          { lbl: '⊙', x: 0.5, y: 0.5 },
                          { lbl: '', x: 0.5, y: 0.85 },
                          { lbl: '', x: 0.92, y: 0.92 },
                        ]).map(({ lbl, x, y }) => {
                          const active = Math.abs(videoConfig.visualizer_x - x) < 0.02 && Math.abs(videoConfig.visualizer_y - y) < 0.02
                          return (
                            <button
                              key={lbl}
                              onClick={() => setVideoConfig(prev => ({ ...prev, visualizer_x: x, visualizer_y: y }))}
                              disabled={isProcessing}
                              className={`text-sm px-2 py-1 rounded border ${
                                active
                                  ? 'bg-primary-500 text-white border-primary-500'
                                  : 'bg-surface text-dim border-token hover:border-primary-400'
                              }`}
                              title={`${Math.round(x*100)}%, ${Math.round(y*100)}%`}
                            >
                              {lbl}
                            </button>
                          )
                        })}
                      </div>
                    </div>

                    {/* Size W x H */}
                    <div>
                      <label className="block text-xs text-dim mb-1">Kích thước (px)</label>
                      <div className="flex gap-2 items-center">
                        <div className="flex-1">
                          <div className="text-[10px] text-dim mb-0.5">W</div>
                          <input
                            type="number" min={64} max={4096} step={4}
                            value={videoConfig.visualizer_w}
                            onChange={(e) => setVideoConfig(prev => ({ ...prev, visualizer_w: parseInt(e.target.value) || 800 }))}
                            className="w-full px-2 py-1 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500"
                            disabled={isProcessing}
                          />
                        </div>
                        <span className="text-faint mt-3">×</span>
                        <div className="flex-1">
                          <div className="text-[10px] text-dim mb-0.5">H</div>
                          <input
                            type="number" min={32} max={1080} step={4}
                            value={videoConfig.visualizer_h}
                            onChange={(e) => setVideoConfig(prev => ({ ...prev, visualizer_h: parseInt(e.target.value) || 120 }))}
                            className="w-full px-2 py-1 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500"
                            disabled={isProcessing}
                          />
                        </div>
                      </div>
                    </div>

                    {/* Colors — visibility depends on style */}
                    {(() => {
                      const s = videoConfig.visualizer_style
                      // spectrum has its own preset
                      if (s === 'spectrum') return null
                      // CQT (showcqt) uses a fixed cscheme in the render — neither
                      // color is honored, so don't offer color pickers here.
                      if (s === 'cqt') return (
                        <div className="text-xs text-dim italic">
                          CQT dùng bảng màu cố định (đỏ→xanh), không chỉnh được màu.
                        </div>
                      )
                      // Styles that use both color1 + color2 gradient
                      const usesC2 = s === 'bars'
                      return (
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <label className="block text-xs text-dim mb-1">Màu chính</label>
                            <input
                              type="color"
                              value={videoConfig.visualizer_color1}
                              onChange={(e) => setVideoConfig(prev => ({ ...prev, visualizer_color1: e.target.value }))}
                              className="w-full h-8 rounded border"
                              disabled={isProcessing}
                            />
                          </div>
                          <div>
                            <label className="block text-xs text-dim mb-1">
                              Màu phụ {!usesC2 && <span className="text-[10px] text-faint">(không dùng)</span>}
                            </label>
                            <input
                              type="color"
                              value={videoConfig.visualizer_color2}
                              onChange={(e) => setVideoConfig(prev => ({ ...prev, visualizer_color2: e.target.value }))}
                              className="w-full h-8 rounded border disabled:opacity-50"
                              disabled={isProcessing || !usesC2}
                            />
                          </div>
                        </div>
                      )
                    })()}

                    {/* Spectrum color preset */}
                    {videoConfig.visualizer_style === 'spectrum' && (
                      <div>
                        <label className="block text-xs text-dim mb-1">Color preset (showspectrum)</label>
                        <select
                          value={videoConfig.visualizer_spectrum_preset}
                          onChange={(e) => setVideoConfig(prev => ({ ...prev, visualizer_spectrum_preset: e.target.value }))}
                          className="w-full px-2 py-1.5 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500"
                          disabled={isProcessing}
                        >
                          {['rainbow','intensity','channel','moreland','nebulae','fire','fiery','fruit','cool','magma','green','viridis','plasma','cividis','terrain'].map(p => (
                            <option key={p} value={p}>{p}</option>
                          ))}
                        </select>
                      </div>
                    )}

                    {/* Opacity */}
                    <div>
                      <label className="block text-xs text-dim mb-1">
                        Độ mờ: {Math.round(videoConfig.visualizer_opacity * 100)}%
                      </label>
                      <input
                        type="range" min="0.1" max="1" step="0.05"
                        value={videoConfig.visualizer_opacity}
                        onChange={(e) => setVideoConfig(prev => ({ ...prev, visualizer_opacity: parseFloat(e.target.value) }))}
                        className="w-full"
                        disabled={isProcessing}
                      />
                    </div>

                    {/* Background */}
                    <div className="border-t pt-2">
                      <div className="text-xs font-medium text-dim mb-1">Background phía sau visualizer</div>
                      <div className="flex gap-3 mb-2">
                        {([
                          { v: 'transparent', lbl: 'Trong suốt' },
                          { v: 'solid', lbl: 'Đặc' },
                        ] as const).map(({ v, lbl }) => (
                          <label key={v} className="flex items-center gap-1 text-sm cursor-pointer">
                            <input
                              type="radio"
                              checked={videoConfig.visualizer_bg_mode === v}
                              onChange={() => setVideoConfig(prev => ({ ...prev, visualizer_bg_mode: v }))}
                              disabled={isProcessing}
                            />
                            {lbl}
                          </label>
                        ))}
                      </div>
                      {videoConfig.visualizer_bg_mode === 'solid' && (
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <label className="block text-xs text-dim mb-1">Màu nền</label>
                            <input
                              type="color"
                              value={videoConfig.visualizer_bg_color}
                              onChange={(e) => setVideoConfig(prev => ({ ...prev, visualizer_bg_color: e.target.value }))}
                              className="w-full h-8 rounded border"
                              disabled={isProcessing}
                            />
                          </div>
                          <div>
                            <label className="block text-xs text-dim mb-1">
                              Mờ nền: {Math.round(videoConfig.visualizer_bg_opacity * 100)}%
                            </label>
                            <input
                              type="range" min="0" max="1" step="0.05"
                              value={videoConfig.visualizer_bg_opacity}
                              onChange={(e) => setVideoConfig(prev => ({ ...prev, visualizer_bg_opacity: parseFloat(e.target.value) }))}
                              className="w-full"
                              disabled={isProcessing}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>
              )}
            </div>

            {/* Subtitle (SRT) card — burns styled subtitles into the video. */}
            <div className="border rounded-lg bg-surface">
              <button
                type="button"
                onClick={() => setSubtitleCardOpen(o => !o)}
                className="w-full flex items-center justify-between p-4 text-left hover:bg-surface-2 rounded-lg"
              >
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-primary-600 dark:text-primary-400 text-sm"> Subtitle (SRT)</span>
                  {videoConfig.subtitle_srt_path ? (
                    <span className="text-[11px] text-dim">({videoConfig.subtitle_animation})</span>
                  ) : (
                    <span className="text-[11px] text-faint">(không bật)</span>
                  )}
                </div>
                <span className="text-faint text-xs">{subtitleCardOpen ? '▲ ẩn' : '▼ hiện'}</span>
              </button>
              {subtitleCardOpen && (
                <div className="px-4 pb-4">
                  <SubtitlePanel
                    storyId={storyData.id || ''}
                    audioPath={videoConfig.audioPath}
                    audioDuration={audioDuration}
                    audioSpeed={videoConfig.audio_speed}
                    style={{
                      subtitle_animation: videoConfig.subtitle_animation,
                      subtitle_font: videoConfig.subtitle_font,
                      subtitle_font_size: videoConfig.subtitle_font_size,
                      subtitle_color: videoConfig.subtitle_color,
                      subtitle_outline_color: videoConfig.subtitle_outline_color,
                      subtitle_outline_width: videoConfig.subtitle_outline_width,
                      subtitle_shadow: videoConfig.subtitle_shadow,
                      subtitle_bold: videoConfig.subtitle_bold,
                      subtitle_italic: videoConfig.subtitle_italic,
                      subtitle_align: videoConfig.subtitle_align,
                      subtitle_x: videoConfig.subtitle_x,
                      subtitle_y: videoConfig.subtitle_y,
                      subtitle_opacity: videoConfig.subtitle_opacity,
                    }}
                    onChange={(patch) => setVideoConfig(prev => ({ ...prev, ...patch }))}
                    srtPath={videoConfig.subtitle_srt_path}
                    onSrtUploaded={(info, segments) => {
                      setVideoConfig(prev => ({ ...prev, subtitle_srt_path: info?.srt_path ?? null }))
                      setSubtitleSegments(segments)
                    }}
                    availableFonts={availableFonts}
                  />
                </div>
              )}
            </div>

            {/* Transitions card (full width) */}
            <div className="border rounded-lg p-4 bg-surface space-y-2">
              <div className="flex items-center justify-between">
                <h4 className="font-semibold text-primary-600 dark:text-primary-400 text-sm"> Transitions Pool</h4>
                <span className="text-xs text-faint">
                  {videoConfig.transitions_pool.length} chọn · random mỗi clip
                </span>
              </div>
              <div className="flex flex-wrap gap-1">
                {VIDEO_TRANSITIONS.map(t => {
                  const active = videoConfig.transitions_pool.includes(t)
                  return (
                    <button
                      key={t}
                      onClick={() => toggleTransition(t)}
                      disabled={videoStatus.status === 'running'}
                      className={`text-xs px-2 py-1 rounded transition ${
                        active
                          ? 'bg-primary-500 text-white'
                          : 'bg-surface-3 text-dim hover:bg-gray-200 dark:hover:bg-gray-700'
                      }`}
                    >
                      {t}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Stickers card (full width, collapsible) */}
            <div className="border rounded-lg bg-surface">
              <button
                type="button"
                onClick={() => setStickersCardOpen(o => !o)}
                className="w-full flex items-center justify-between p-4 text-left hover:bg-surface-2 rounded-lg"
              >
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-primary-600 dark:text-primary-400 text-sm"> Stickers / Nhãn dán</span>
                  <span className="text-[11px] text-dim">
                    {videoConfig.stickers.length > 0
                      ? `(${videoConfig.stickers.length} đang dùng)`
                      : '(chưa có)'}
                  </span>
                </div>
                <span className="text-faint text-xs">{stickersCardOpen ? '▲ ẩn' : '▼ hiện'}</span>
              </button>

              {stickersCardOpen && (
                <div className="px-4 pb-4">
                  <StickerPanel
                    stickers={videoConfig.stickers}
                    audioDuration={audioDuration / Math.max(0.1, videoConfig.audio_speed)}
                    selectedId={selectedStickerId}
                    onSelect={setSelectedStickerId}
                    onAdd={(s) => {
                      setVideoConfig(prev => ({ ...prev, stickers: [...prev.stickers, s] }))
                      setSelectedStickerId(s.id)
                    }}
                    onUpdate={(id, patch) => {
                      setVideoConfig(prev => ({
                        ...prev,
                        stickers: prev.stickers.map(s => s.id === id ? { ...s, ...patch } : s),
                      }))
                    }}
                    onRemove={(id) => {
                      setVideoConfig(prev => ({
                        ...prev,
                        stickers: prev.stickers.filter(s => s.id !== id),
                      }))
                      if (selectedStickerId === id) setSelectedStickerId(null)
                    }}
                  />
                </div>
              )}
            </div>
            </>}

            {/* Tab: Bản quyền */}
            {videoTab === 'antidetect' && <>

            {/* Anti-detection card (full width) */}
            <div className="border rounded-lg p-4 bg-surface space-y-3">
              <button
                type="button"
                className="flex items-center justify-between w-full text-left"
                onClick={() => setAntiDetectionOpen(v => !v)}
              >
                <h4 className="font-semibold text-primary-600 dark:text-primary-400 text-sm"> Chống quét bản quyền</h4>
                <span className="flex items-center gap-2 text-xs text-faint">
                  {!antiDetectionOpen && <span>tích option để bật</span>}
                  <span className="text-dim">{antiDetectionOpen ? '▲' : '▼'}</span>
                </span>
              </button>

              {antiDetectionOpen && <>
              {/* 1. Random flip per-clip */}
              <label className="flex items-start gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={videoConfig.ad_flip_random}
                  onChange={(e) => setVideoConfig(prev => ({
                    ...prev,
                    ad_flip_random: e.target.checked,
                    ad_flip_all: e.target.checked ? false : prev.ad_flip_all,
                  }))}
                  disabled={isProcessing}
                  className="mt-0.5"
                />
                <div className="flex-1">
                  <div className="text-sm font-medium">Random flip per-clip</div>
                  <div className="text-xs text-dim">Mỗi clip 50% xác suất lật ngang. Phá fingerprint mạnh nhất.</div>
                </div>
              </label>

              {/* 2. Flip all */}
              <label className="flex items-start gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={videoConfig.ad_flip_all}
                  onChange={(e) => setVideoConfig(prev => ({
                    ...prev,
                    ad_flip_all: e.target.checked,
                    ad_flip_random: e.target.checked ? false : prev.ad_flip_random,
                  }))}
                  disabled={isProcessing}
                  className="mt-0.5"
                />
                <div className="flex-1">
                  <div className="text-sm font-medium">Flip toàn bộ</div>
                  <div className="text-xs text-dim">Lật ngang 100% clip. Tránh dùng nếu folder có text/biển hiệu.</div>
                </div>
              </label>

              {/* 3. Zoom + crop */}
              <div className="border-t pt-3">
                <label className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={videoConfig.ad_zoom}
                    onChange={(e) => setVideoConfig(prev => ({ ...prev, ad_zoom: e.target.checked }))}
                    disabled={isProcessing}
                    className="mt-0.5"
                  />
                  <div className="flex-1">
                    <div className="text-sm font-medium">Zoom + crop center</div>
                    <div className="text-xs text-dim">Phóng to rồi cắt rìa để đổi pixel layout.</div>
                  </div>
                </label>
                {videoConfig.ad_zoom && (
                  <div className="ml-6 mt-2">
                    <label className="block text-xs text-dim mb-1">
                      Zoom factor: {videoConfig.ad_zoom_factor.toFixed(2)}x
                    </label>
                    <input
                      type="range" min="1.00" max="1.15" step="0.01"
                      value={videoConfig.ad_zoom_factor}
                      onChange={(e) => setVideoConfig(prev => ({ ...prev, ad_zoom_factor: parseFloat(e.target.value) }))}
                      disabled={isProcessing}
                      className="w-full"
                    />
                  </div>
                )}
              </div>

              {/* 4. Color grading */}
              <div className="border-t pt-3">
                <label className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={videoConfig.ad_color}
                    onChange={(e) => setVideoConfig(prev => ({ ...prev, ad_color: e.target.checked }))}
                    disabled={isProcessing}
                    className="mt-0.5"
                  />
                  <div className="flex-1">
                    <div className="text-sm font-medium">Color grading</div>
                    <div className="text-xs text-dim">Đổi saturation/contrast/gamma/hue nhẹ.</div>
                  </div>
                </label>
                {videoConfig.ad_color && (
                  <div className="ml-6 mt-2 grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs text-dim mb-1">
                        Saturation: {videoConfig.ad_saturation.toFixed(2)}
                      </label>
                      <input
                        type="range" min="0.85" max="1.15" step="0.01"
                        value={videoConfig.ad_saturation}
                        onChange={(e) => setVideoConfig(prev => ({ ...prev, ad_saturation: parseFloat(e.target.value) }))}
                        disabled={isProcessing}
                        className="w-full"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-dim mb-1">
                        Contrast: {videoConfig.ad_contrast.toFixed(2)}
                      </label>
                      <input
                        type="range" min="0.90" max="1.10" step="0.01"
                        value={videoConfig.ad_contrast}
                        onChange={(e) => setVideoConfig(prev => ({ ...prev, ad_contrast: parseFloat(e.target.value) }))}
                        disabled={isProcessing}
                        className="w-full"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-dim mb-1">
                        Gamma: {videoConfig.ad_gamma.toFixed(2)}
                      </label>
                      <input
                        type="range" min="0.90" max="1.10" step="0.01"
                        value={videoConfig.ad_gamma}
                        onChange={(e) => setVideoConfig(prev => ({ ...prev, ad_gamma: parseFloat(e.target.value) }))}
                        disabled={isProcessing}
                        className="w-full"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-dim mb-1">
                        Hue shift: {videoConfig.ad_hue_shift.toFixed(0)}°
                      </label>
                      <input
                        type="range" min="-15" max="15" step="1"
                        value={videoConfig.ad_hue_shift}
                        onChange={(e) => setVideoConfig(prev => ({ ...prev, ad_hue_shift: parseFloat(e.target.value) }))}
                        disabled={isProcessing}
                        className="w-full"
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* 5. Per-clip speed jitter */}
              <div className="border-t pt-3">
                <label className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={videoConfig.ad_clip_speed_jitter}
                    onChange={(e) => setVideoConfig(prev => ({ ...prev, ad_clip_speed_jitter: e.target.checked }))}
                    disabled={isProcessing}
                    className="mt-0.5"
                  />
                  <div className="flex-1">
                    <div className="text-sm font-medium">Per-clip speed jitter</div>
                    <div className="text-xs text-dim">Mỗi clip random tốc độ trong ±range. Độc lập với audio_speed.</div>
                  </div>
                </label>
                {videoConfig.ad_clip_speed_jitter && (
                  <div className="ml-6 mt-2">
                    <label className="block text-xs text-dim mb-1">
                      Range: ±{(videoConfig.ad_clip_speed_jitter_range * 100).toFixed(0)}%
                    </label>
                    <input
                      type="range" min="0.01" max="0.05" step="0.005"
                      value={videoConfig.ad_clip_speed_jitter_range}
                      onChange={(e) => setVideoConfig(prev => ({ ...prev, ad_clip_speed_jitter_range: parseFloat(e.target.value) }))}
                      disabled={isProcessing}
                      className="w-full"
                    />
                  </div>
                )}
              </div>

              {/* 6. Strip metadata */}
              <div className="border-t pt-3">
                <label className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={videoConfig.ad_strip_metadata}
                    onChange={(e) => setVideoConfig(prev => ({ ...prev, ad_strip_metadata: e.target.checked }))}
                    disabled={isProcessing}
                    className="mt-0.5"
                  />
                  <div className="flex-1">
                    <div className="text-sm font-medium">Strip metadata</div>
                    <div className="text-xs text-dim">Xóa title/comment/encoder của output. An toàn, không đổi nội dung.</div>
                  </div>
                </label>
              </div>
              </>}
            </div>
            </>}

            </div>{/* end right sidebar */}

            {/* Preview */}
            <div className="border rounded-lg p-4 bg-gradient-to-br from-slate-50 to-slate-100 space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="font-semibold text-primary-600 dark:text-primary-400 text-sm"> Preview</h4>
                {clipList.length > 0 && (
                  <span className="text-[11px] text-faint">{clipList.length} clip · cycle theo folder order</span>
                )}
              </div>
              <div ref={previewColRef} className="flex flex-col items-center">
                <div
                  ref={previewFrameRef}
                  className="relative overflow-hidden bg-black shadow-lg"
                  style={{
                    width: previewW,
                    height: previewH,
                    borderRadius: 10,
                    outline: '1px dashed rgba(148,163,184,0.5)',
                    outlineOffset: 4,
                  }}
                >
                  {/* Banner background layer */}
                  {videoConfig.bannerImage ? (
                    <img
                      src={`/api/v1/video/preview-image?path=${encodeURIComponent(videoConfig.bannerImage)}`}
                      alt="banner bg"
                      // object-fill (stretch to exact frame) mirrors the backend's
                      // ffmpeg `scale={width}:{height}` so the position the user sets
                      // against the banner matches the rendered output.
                      className="absolute inset-0 w-full h-full object-fill"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                    />
                  ) : (
                    // No banner: black background — matches the backend, which
                    // letterbox-pads on black (non-composite) or composites the clip
                    // onto a black frame (when the transform is active).
                    <div className="absolute inset-0 bg-black" />
                  )}
                  {/* Video clip layer */}
                  {(() => {
                    const clipPlaceholder = (
                      <div className="w-full h-full border-2 border-dashed border-token flex items-center justify-center text-faint text-xs text-center px-2">
                        {videoConfig.folder.trim() ? 'Đang tải clip mẫu...' : 'Chọn folder để xem clip mẫu'}
                      </div>
                    )
                    const clipVideo = clipUrl ? (
                      <video
                        key={clipUrl}
                        ref={previewVideoRef}
                        src={clipUrl}
                        muted playsInline
                        onLoadedMetadata={() => {
                          // Apply pending offset (from a seek that crossed a clip boundary)
                          const v = previewVideoRef.current
                          if (!v) return
                          if (pendingClipOffsetRef.current > 0) {
                            v.currentTime = pendingClipOffsetRef.current
                            pendingClipOffsetRef.current = 0
                          }
                          // Match audio play state
                          const a = previewAudioRef.current
                          if (a && !a.paused) v.play().catch(() => {})
                        }}
                        onEnded={() => {
                          // Advance to next clip in folder order; loop back at end
                          if (clipList.length === 0) return
                          const next = (currentClipIdx + 1) % clipList.length
                          pendingClipOffsetRef.current = 0
                          setCurrentClipIdx(next)
                        }}
                        style={previewCompositeMode
                          // object-fill so the clip stretches to exactly fill the
                          // scaleX×scaleY box, matching the backend's per-axis scale.
                          ? { width: '100%', height: '100%', objectFit: 'fill', display: 'block', pointerEvents: 'none', ...adVideoStyle }
                          : { maxWidth: '100%', maxHeight: '100%', objectFit: 'contain', pointerEvents: 'none', ...adVideoStyle }}
                      />
                    ) : null

                    // Video is always a movable + resizable box — drag the body to
                    // move, corners/edges to resize width/height — with or without a
                    // banner. Offset + per-axis scale are a single shared transform,
                    // so adjusting this sample clip adjusts EVERY clip. The box is
                    // exactly scaleX×scaleY of the frame. At identity + no banner the
                    // clip is letterboxed (object-contain, matching the backend's
                    // pad); once the transform is touched it fills the box
                    // (object-fill), matching the composite pass.
                    const boxW = previewScaleX * previewW
                    const boxH = previewScaleY * previewH
                    // dx/dy pick which axis a handle resizes (0 = leave that axis).
                    // Corners resize both; edges resize one → independent width/height.
                    const handles = [
                      { k: 'nw', dx: -1, dy: -1, style: { left: -6, top: -6, cursor: 'nwse-resize' } },
                      { k: 'ne', dx: 1, dy: -1, style: { right: -6, top: -6, cursor: 'nesw-resize' } },
                      { k: 'sw', dx: -1, dy: 1, style: { left: -6, bottom: -6, cursor: 'nesw-resize' } },
                      { k: 'se', dx: 1, dy: 1, style: { right: -6, bottom: -6, cursor: 'nwse-resize' } },
                      { k: 'n', dx: 0, dy: -1, style: { left: '50%', top: -6, marginLeft: -6, cursor: 'ns-resize' } },
                      { k: 's', dx: 0, dy: 1, style: { left: '50%', bottom: -6, marginLeft: -6, cursor: 'ns-resize' } },
                      { k: 'w', dx: -1, dy: 0, style: { top: '50%', left: -6, marginTop: -6, cursor: 'ew-resize' } },
                      { k: 'e', dx: 1, dy: 0, style: { top: '50%', right: -6, marginTop: -6, cursor: 'ew-resize' } },
                    ] as const
                    return (
                      <div
                        className="absolute"
                        style={{
                          left: `${(0.5 + videoConfig.bannerVideoOffsetX) * 100}%`,
                          top: `${(0.5 + videoConfig.bannerVideoOffsetY) * 100}%`,
                          width: `${boxW}px`,
                          height: `${boxH}px`,
                          transform: `translate(-50%, -50%) rotate(${videoConfig.bannerVideoRotation}deg)`,
                          cursor: isProcessing ? 'default' : 'move',
                          touchAction: 'none',
                          // Center the clip in the box so a letterboxed (object-contain)
                          // clip sits centered like the backend's pad; absolute handles
                          // and outline are unaffected.
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                        onPointerDown={isProcessing ? undefined : startBannerVideoMove}
                      >
                        {clipVideo || clipPlaceholder}
                        {!isProcessing && (
                          <>
                            {/* selection outline */}
                            <div className="absolute inset-0 pointer-events-none" style={{ outline: '1.5px solid rgba(56,189,248,0.9)', outlineOffset: -1 }} />
                            {/* resize handles: 4 corners (both axes) + 4 edges (one axis) */}
                            {handles.map(h => (
                              <div
                                key={h.k}
                                onPointerDown={startBannerVideoResize(h.dx, h.dy)}
                                style={{
                                  position: 'absolute',
                                  width: 12, height: 12,
                                  background: '#38bdf8',
                                  border: '1.5px solid #fff',
                                  borderRadius: 2,
                                  touchAction: 'none',
                                  boxShadow: '0 0 2px rgba(0,0,0,0.5)',
                                  ...h.style,
                                }}
                              />
                            ))}
                            {/* rotate handle: round grip above the box + connector line */}
                            <div style={{ position: 'absolute', left: '50%', top: -24, width: 2, height: 24, marginLeft: -1, background: 'rgba(56,189,248,0.9)', pointerEvents: 'none' }} />
                            <div
                              onPointerDown={startBannerVideoRotate}
                              title="Kéo để xoay video (giữ Shift để bám 15°)"
                              style={{
                                position: 'absolute',
                                left: '50%', top: -34, marginLeft: -8,
                                width: 16, height: 16,
                                background: '#38bdf8',
                                border: '2px solid #fff',
                                borderRadius: '50%',
                                cursor: 'grab',
                                touchAction: 'none',
                                boxShadow: '0 0 2px rgba(0,0,0,0.5)',
                              }}
                            />
                          </>
                        )}
                      </div>
                    )
                  })()}
                  {/* Hidden master audio element (drives playback time + sync) */}
                  {audioUrl && (
                    <audio
                      ref={previewAudioRef}
                      src={audioUrl}
                      preload="metadata"
                      onLoadedMetadata={(e) => {
                        const a = e.target as HTMLAudioElement
                        applyAudioPitchPreserve(a, videoConfig.audio_speed)
                        a.volume = previewVolume
                        a.muted = previewVolume === 0
                      }}
                      onTimeUpdate={(e) => {
                        const a = e.target as HTMLAudioElement
                        const speed = Math.max(0.1, videoConfig.audio_speed)
                        const vt = a.currentTime / speed // real-time / video time
                        setPreviewCurrentTime(vt)
                        if (clipList.length === 0 || clipsTotalDur <= 0) return
                        const { idx, offset } = findClipForTime(vt)
                        if (idx !== currentClipIdx) {
                          // Crossed a clip boundary while seeking or audio drifted ahead
                          pendingClipOffsetRef.current = offset
                          setCurrentClipIdx(idx)
                        } else {
                          const v = previewVideoRef.current
                          if (v && Math.abs(v.currentTime - offset) > 0.5) {
                            v.currentTime = offset
                          }
                        }
                      }}
                      onPlay={() => {
                        setPreviewPlaying(true)
                        const v = previewVideoRef.current
                        if (v) v.play().catch(() => {})
                      }}
                      onPause={() => {
                        setPreviewPlaying(false)
                        const v = previewVideoRef.current
                        if (v) v.pause()
                      }}
                      onEnded={() => {
                        setPreviewPlaying(false)
                        const v = previewVideoRef.current
                        if (v) v.pause()
                      }}
                    />
                  )}
                  {/* Dark overlay */}
                  {videoConfig.overlay_opacity > 0 && (
                    <div
                      className="absolute inset-0 pointer-events-none"
                      style={{ background: `rgba(0,0,0,${videoConfig.overlay_opacity})` }}
                    />
                  )}
                  {/* Audio Visualizer mock (draggable; CSS-only — real render uses ffmpeg) */}
                  {videoConfig.visualizer_enabled && (() => {
                    const [resWnum] = videoConfig.resolution.split('x').map(Number)
                    const scalePx = previewW / resWnum
                    const vw = Math.max(40, videoConfig.visualizer_w * scalePx)
                    const vh = Math.max(20, videoConfig.visualizer_h * scalePx)
                    const c1 = videoConfig.visualizer_color1
                    const c2 = videoConfig.visualizer_color2
                    const op = videoConfig.visualizer_opacity
                    const bgStyle: React.CSSProperties = videoConfig.visualizer_bg_mode === 'solid'
                      ? { backgroundColor: videoConfig.visualizer_bg_color, opacity: 1 }
                      : {}
                    const bgOp = videoConfig.visualizer_bg_mode === 'solid' ? videoConfig.visualizer_bg_opacity : 0
                    const style = videoConfig.visualizer_style
                    const barsMode = videoConfig.visualizer_bars_mode
                    const waveformMode = videoConfig.visualizer_waveform_mode
                    const waveformMirror = videoConfig.visualizer_waveform_mirror
                    return (
                      <div
                        onPointerDown={startWatermarkDrag('viz')}
                        style={{
                          position: 'absolute',
                          left: `${videoConfig.visualizer_x * 100}%`,
                          top: `${videoConfig.visualizer_y * 100}%`,
                          transform: 'translate(-50%, -50%)',
                          width: vw,
                          height: vh,
                          cursor: 'move',
                          touchAction: 'none',
                          userSelect: 'none',
                          outline: '1px dashed rgba(255,255,255,0.4)',
                          overflow: 'hidden',
                        }}
                        title="Visualizer (kéo để chỉnh vị trí; render thật khi xuất video)"
                      >
                        {/* Solid background layer */}
                        {videoConfig.visualizer_bg_mode === 'solid' && (
                          <div
                            className="absolute inset-0"
                            style={{ ...bgStyle, opacity: bgOp }}
                          />
                        )}
                        {/* Style-specific mock */}
                        {style === 'bars' && (
                          <div
                            className="absolute inset-0 flex items-end justify-around px-1 pb-1"
                            style={{ opacity: op }}
                          >
                            {Array.from({ length: 32 }).map((_, i) => {
                              const heightPct = 20 + Math.abs(Math.sin((i + 1) * 0.7)) * 70 + Math.abs(Math.cos(i * 1.3)) * 10
                              if (barsMode === 'dot') {
                                return (
                                  <div
                                    key={i}
                                    style={{
                                      width: 4, height: 4,
                                      background: c1,
                                      borderRadius: '50%',
                                      marginBottom: `${heightPct}%`,
                                      animation: `vizBarShift 0.${4 + (i % 6)}s ease-in-out infinite alternate`,
                                      animationDelay: `${(i % 8) * 0.05}s`,
                                    }}
                                  />
                                )
                              }
                              if (barsMode === 'line') {
                                return (
                                  <div
                                    key={i}
                                    style={{
                                      width: 1.5,
                                      background: c1,
                                      height: `${heightPct}%`,
                                      animation: `vizBar 0.${4 + (i % 6)}s ease-in-out infinite alternate`,
                                      animationDelay: `${(i % 8) * 0.05}s`,
                                    }}
                                  />
                                )
                              }
                              return (
                                <div
                                  key={i}
                                  style={{
                                    width: `${100 / 36}%`,
                                    background: `linear-gradient(to top, ${c1}, ${c2})`,
                                    height: `${heightPct}%`,
                                    animation: `vizBar 0.${4 + (i % 6)}s ease-in-out infinite alternate`,
                                    animationDelay: `${(i % 8) * 0.05}s`,
                                    borderRadius: '1px 1px 0 0',
                                  }}
                                />
                              )
                            })}
                          </div>
                        )}
                        {style === 'waveform' && (() => {
                          // mirror = vstack with vflipped copy render same wave at half-height
                          const renderWave = (transform?: string) => (
                            <svg
                              className="absolute inset-x-0"
                              style={{
                                top: waveformMirror ? (transform === 'flip' ? '50%' : '0') : '0',
                                height: waveformMirror ? '50%' : '100%',
                                width: '100%',
                                opacity: op,
                                transform: transform === 'flip' ? 'scaleY(-1)' : undefined,
                              }}
                              viewBox="0 0 200 60"
                              preserveAspectRatio="none"
                            >
                              {waveformMode === 'point' ? (
                                <g fill={c1}>
                                  {Array.from({ length: 40 }).map((_, i) => (
                                    <circle key={i} cx={i * 5} cy={30} r={1.5}>
                                      <animate
                                        attributeName="cy"
                                        values={`30;${30 + 20 * Math.sin(i * 0.7)};30`}
                                        dur={`${0.8 + (i % 5) * 0.1}s`}
                                        repeatCount="indefinite"
                                      />
                                    </circle>
                                  ))}
                                </g>
                              ) : (
                                <path
                                  d="M0,30 Q12,5 25,30 T50,30 T75,30 T100,30 T125,30 T150,30 T175,30 T200,30"
                                  fill={waveformMode === 'p2p' ? c1 : 'none'}
                                  fillOpacity={waveformMode === 'p2p' ? 0.5 : 0}
                                  stroke={c1}
                                  strokeWidth={waveformMode === 'line' ? 1 : 2}
                                  strokeLinecap="round"
                                >
                                  <animate
                                    attributeName="d"
                                    values="M0,30 Q12,5 25,30 T50,30 T75,30 T100,30 T125,30 T150,30 T175,30 T200,30;M0,30 Q12,55 25,30 T50,30 T75,30 T100,30 T125,30 T150,30 T175,30 T200,30;M0,30 Q12,5 25,30 T50,30 T75,30 T100,30 T125,30 T150,30 T175,30 T200,30"
                                    dur="1.2s"
                                    repeatCount="indefinite"
                                  />
                                </path>
                              )}
                            </svg>
                          )
                          if (waveformMirror) {
                            return <>{renderWave()}{renderWave('flip')}</>
                          }
                          return renderWave()
                        })()}
                        {style === 'spectrum' && (
                          <div
                            className="absolute inset-0"
                            style={{
                              opacity: op,
                              background: `linear-gradient(90deg, ${SPECTRUM_PRESET_GRADIENTS[videoConfig.visualizer_spectrum_preset] || SPECTRUM_PRESET_GRADIENTS.rainbow})`,
                              backgroundSize: '200% 100%',
                              animation: 'vizSpectrum 4s linear infinite',
                            }}
                          />
                        )}
                        {style === 'cqt' && (
                          <div
                            className="absolute inset-0 flex items-end justify-around"
                            style={{ opacity: op }}
                          >
                            {Array.from({ length: 48 }).map((_, i) => (
                              <div
                                key={i}
                                style={{
                                  width: `${100 / 52}%`,
                                  // showcqt uses a fixed cscheme (low→red, high→green);
                                  // color1/color2 are ignored by the render, so mirror that.
                                  background: `linear-gradient(to top, #ff2a2a, #2aff2a)`,
                                  height: `${30 + Math.abs(Math.sin((i + 1) * 0.4)) * 60}%`,
                                  animation: `vizBar 0.${5 + (i % 5)}s ease-in-out infinite alternate`,
                                  animationDelay: `${(i % 12) * 0.04}s`,
                                  borderRadius: '2px 2px 0 0',
                                  boxShadow: `0 0 4px #2aff2a`,
                                }}
                              />
                            ))}
                          </div>
                        )}
                        {/* Hint label */}
                        <div
                          className="absolute top-0 left-1 text-[9px] text-white/70 pointer-events-none"
                          style={{ textShadow: '0 1px 2px rgba(0,0,0,0.7)' }}
                        >
                           viz · {style}
                          {style === 'bars' && barsMode !== 'bar' ? `:${barsMode}` : ''}
                          {style === 'waveform' ? `:${waveformMode}${waveformMirror ? '+mirror' : ''}` : ''}
                        </div>
                      </div>
                    )
                  })()}
                  {/* Watermark image (draggable, with optional shape mask) */}
                  {videoConfig.watermarkImage && (() => {
                    const [resWnum] = videoConfig.resolution.split('x').map(Number)
                    const previewScalePx = previewW / resWnum
                    const wPx = Math.max(8, videoConfig.watermark_w * previewScalePx)
                    const hPx = Math.max(8, videoConfig.watermark_h * previewScalePx)
                    // CSS shape masks
                    const shapeStyle: React.CSSProperties = {}
                    const sh = videoConfig.watermark_shape
                    if (sh === 'circle') shapeStyle.borderRadius = '50%'
                    else if (sh === 'rounded') shapeStyle.borderRadius = '16%'
                    else if (sh === 'star') shapeStyle.clipPath = 'polygon(50% 1%,61% 35%,98% 35%,68% 57%,79% 91%,50% 70%,21% 91%,32% 57%,2% 35%,39% 35%)'
                    else if (sh === 'sun') {
                      // 12-ray sun matching backend
                      const rays = 12
                      const outerR = 49
                      const innerR = outerR * 0.55
                      const pts: string[] = []
                      for (let i = 0; i < rays * 2; i++) {
                        const angle = -Math.PI / 2 + (i * Math.PI) / rays
                        const r = i % 2 === 0 ? outerR : innerR
                        const x = 50 + r * Math.cos(angle)
                        const y = 50 + r * Math.sin(angle)
                        pts.push(`${x.toFixed(2)}% ${y.toFixed(2)}%`)
                      }
                      shapeStyle.clipPath = `polygon(${pts.join(',')})`
                    }
                    return (
                      <img
                        src={`/api/v1/video/preview-image?path=${encodeURIComponent(videoConfig.watermarkImage)}`}
                        alt="watermark"
                        onPointerDown={startWatermarkDrag('image')}
                        onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                        style={{
                          position: 'absolute',
                          left: `${videoConfig.watermark_x * 100}%`,
                          top: `${videoConfig.watermark_y * 100}%`,
                          transform: 'translate(-50%, -50%)',
                          width: `${wPx}px`,
                          height: `${hPx}px`,
                          // Backend stretches the logo to exactly w×h (scale=w:h,
                          // no aspect preserve) — 'fill' mirrors that.
                          objectFit: 'fill',
                          opacity: videoConfig.watermark_opacity,
                          cursor: 'move',
                          userSelect: 'none',
                          touchAction: 'none',
                          outline: sh === 'none' ? '1px dashed rgba(255,255,255,0.4)' : 'none',
                          ...shapeStyle,
                        }}
                      />
                    )
                  })()}
                  {/* Watermark text (draggable) */}
                  {videoConfig.watermark_text && (() => {
                    const fontKey = videoConfig.watermark_text_font.split(' (')[0]
                    const scale = previewW / parseInt(videoConfig.resolution.split('x')[0])
                    const previewFontPx = Math.max(8, Math.round(videoConfig.watermark_text_size * scale))
                    return (
                      <span
                        onPointerDown={startWatermarkDrag('text')}
                        style={{
                          position: 'absolute',
                          left: `${videoConfig.watermark_text_x * 100}%`,
                          top: `${videoConfig.watermark_text_y * 100}%`,
                          transform: `translate(-50%, -50%) rotate(${videoConfig.watermark_text_angle}deg)`,
                          transformOrigin: 'center',
                          fontFamily: `'${fontKey}', Arial, sans-serif`,
                          fontSize: previewFontPx,
                          color: videoConfig.watermark_text_color,
                          opacity: videoConfig.watermark_text_opacity,
                          whiteSpace: 'nowrap',
                          fontWeight: 700,
                          textShadow: '0 1px 2px rgba(0,0,0,0.4)',
                          cursor: 'move',
                          userSelect: 'none',
                          touchAction: 'none',
                          padding: '2px 4px',
                          outline: '1px dashed rgba(255,255,255,0.3)',
                        }}
                      >
                        {videoConfig.watermark_text}
                      </span>
                    )
                  })()}
                  {/* Subtitle overlay (draggable; live preview from parsed SRT) */}
                  {videoConfig.subtitle_srt_path && subtitleSegments && (
                    <div
                      onPointerDown={startWatermarkDrag('subtitle')}
                      style={{
                        position: 'absolute',
                        left: `${videoConfig.subtitle_x * 100}%`,
                        top: `${videoConfig.subtitle_y * 100}%`,
                        transform: 'translate(-50%, -50%)',
                        cursor: 'move',
                        touchAction: 'none',
                        // Invisible 60×30 hit-area centered on the anchor — gives the
                        // user a stable handle even between subtitle segments.
                        width: 60, height: 30,
                        marginLeft: -30, marginTop: -15,
                        outline: '1px dashed rgba(255,255,255,0.25)',
                      }}
                    />
                  )}
                  {videoConfig.subtitle_srt_path && subtitleSegments && (
                    <SubtitleOverlay
                      segments={subtitleSegments}
                      style={{
                        subtitle_animation: videoConfig.subtitle_animation,
                        subtitle_font: videoConfig.subtitle_font,
                        subtitle_font_size: videoConfig.subtitle_font_size,
                        subtitle_color: videoConfig.subtitle_color,
                        subtitle_outline_color: videoConfig.subtitle_outline_color,
                        subtitle_outline_width: videoConfig.subtitle_outline_width,
                        subtitle_shadow: videoConfig.subtitle_shadow,
                        subtitle_bold: videoConfig.subtitle_bold,
                        subtitle_italic: videoConfig.subtitle_italic,
                        subtitle_align: videoConfig.subtitle_align,
                        subtitle_x: videoConfig.subtitle_x,
                        subtitle_y: videoConfig.subtitle_y,
                        subtitle_opacity: videoConfig.subtitle_opacity,
                      }}
                      audioRef={previewAudioRef}
                      currentTime={previewCurrentTime}
                      previewFrameW={previewW}
                      outputW={parseInt(videoConfig.resolution.split('x')[0])}
                    />
                  )}
                  {videoConfig.stickers.length > 0 && (
                    <StickerOverlay
                      stickers={videoConfig.stickers}
                      audioRef={previewAudioRef}
                      currentTime={previewCurrentTime}
                      previewFrameW={previewW}
                      previewFrameH={previewH}
                      outputW={resW}
                      outputH={resH}
                      selectedId={selectedStickerId}
                      onSelect={setSelectedStickerId}
                      onDrag={(id, x, y) => setVideoConfig(prev => ({
                        ...prev,
                        stickers: prev.stickers.map(s => s.id === id ? { ...s, x, y } : s),
                      }))}
                      onResize={(id, w, h) => setVideoConfig(prev => ({
                        ...prev,
                        stickers: prev.stickers.map(s => s.id === id ? { ...s, w, h } : s),
                      }))}
                    />
                  )}
                  {/* Fade in/out hint (subtle vignette-like edges) */}
                  {(videoConfig.fade_in > 0 || videoConfig.fade_out > 0) && (
                    <div
                      className="absolute inset-0 pointer-events-none"
                      style={{
                        background: 'linear-gradient(90deg, rgba(0,0,0,0.35) 0%, transparent 12%, transparent 88%, rgba(0,0,0,0.35) 100%)',
                      }}
                    />
                  )}
                  {/* Resolution badge (top-right) */}
                  <div className="absolute top-1 right-1 bg-black/70 text-white text-[10px] px-1.5 py-0.5 rounded font-mono">
                    {videoConfig.resolution}
                  </div>
                  {/* Custom video controls bar (bottom of preview frame) */}
                  <div
                    className="absolute left-0 right-0 bottom-0 px-4 pt-10 pb-3"
                    style={{ background: 'linear-gradient(to top, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0.45) 60%, transparent 100%)' }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    {/* Progress bar (visual) + invisible range above for scrub */}
                    <div className="relative h-1.5 mb-2 group cursor-pointer">
                      <div className="absolute inset-0 rounded-full bg-white/25" />
                      <div
                        className="absolute top-0 left-0 bottom-0 rounded-full bg-primary-500 group-hover:bg-primary-400 transition-colors"
                        style={{ width: `${timelineTotal ? (previewCurrentTime / timelineTotal) * 100 : 0}%` }}
                      />
                      <div
                        className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3 h-3 rounded-full bg-surface shadow-md opacity-0 group-hover:opacity-100 transition-opacity"
                        style={{ left: `${timelineTotal ? (previewCurrentTime / timelineTotal) * 100 : 0}%` }}
                      />
                      <input
                        type="range"
                        min={0}
                        max={timelineTotal || 0}
                        step={0.5}
                        value={previewCurrentTime}
                        onChange={(e) => seekPreview(parseFloat(e.target.value))}
                        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                        disabled={!timelineTotal}
                      />
                    </div>

                    {/* Bottom row: play, time, spacer, volume, fullscreen */}
                    <div className="flex items-center gap-3 text-white">
                      <button
                        type="button"
                        onClick={togglePreviewPlay}
                        className="hover:text-primary-300 transition"
                        title={previewPlaying ? 'Pause (k)' : 'Play (k)'}
                      >
                        {previewPlaying ? (
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>
                        ) : (
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                        )}
                      </button>

                      <span className="text-[11px] font-mono tabular-nums">
                        {formatTime(previewCurrentTime)} <span className="text-white/60">/ {formatTime(timelineTotal)}</span>
                        {estimatedFinalDuration > 0 && (
                          <span className="ml-2 text-[10px] text-white/50 font-sans">(ước tính output)</span>
                        )}
                      </span>

                      <div className="flex-1" />

                      <div className="flex items-center gap-1.5 group">
                        <button
                          type="button"
                          onClick={togglePreviewMute}
                          className="hover:text-primary-300 transition"
                          title={previewMuted ? 'Unmute (m)' : 'Mute (m)'}
                        >
                          {previewMuted || previewVolume === 0 ? (
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M3.63 3.63a1 1 0 0 0 0 1.41L7.29 8.7 7 9H4a1 1 0 0 0-1 1v4a1 1 0 0 0 1 1h3l3.29 3.29a1 1 0 0 0 1.71-.71v-4.17l4.18 4.18c-.49.37-1.02.68-1.6.91a1 1 0 0 0 .76 1.85c.86-.35 1.65-.83 2.34-1.42l1.62 1.62a1 1 0 0 0 1.41-1.41L5.05 3.63a1 1 0 0 0-1.42 0zM19 12c0 .82-.15 1.61-.41 2.34l1.53 1.53A8.95 8.95 0 0 0 21 12c0-4.28-3-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM10 12 8.83 10.83 12 7.66v2.51L10 12zm5.5 0c0-1.77-1.02-3.29-2.5-4.03v1.79l2.48 2.48c.01-.08.02-.16.02-.24z"/></svg>
                          ) : (
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M3 10v4a1 1 0 0 0 1 1h3l3.29 3.29a1 1 0 0 0 1.71-.71V6.41a1 1 0 0 0-1.71-.71L7 9H4a1 1 0 0 0-1 1zm13.5 2c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4-.91 7-4.49 7-8.77s-3-7.86-7-8.77z"/></svg>
                          )}
                        </button>
                        <input
                          type="range"
                          min={0} max={1} step={0.05}
                          value={previewMuted ? 0 : previewVolume}
                          onChange={(e) => setPreviewVol(parseFloat(e.target.value))}
                          className="w-0 group-hover:w-16 transition-all opacity-0 group-hover:opacity-100"
                          style={{ accentColor: '#fff' }}
                        />
                      </div>

                      <button
                        type="button"
                        onClick={togglePreviewFullscreen}
                        className="hover:text-primary-300 transition"
                        title="Fullscreen (f)"
                      >
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/></svg>
                      </button>
                    </div>
                  </div>
                </div>
                <p className="text-xs text-dim mt-3 text-center max-w-md">
                  {previewCompositeMode
                    ? `${videoConfig.bannerImage ? 'Banner nền' : 'Nền đen'} · video ${Math.round(previewScaleX * 100)}×${Math.round(previewScaleY * 100)}%${
                        (Math.abs(videoConfig.bannerVideoOffsetX) > 0.001 || Math.abs(videoConfig.bannerVideoOffsetY) > 0.001)
                          ? ` @ ${Math.round(videoConfig.bannerVideoOffsetX * 100)},${Math.round(videoConfig.bannerVideoOffsetY * 100)}`
                          : ' · canh giữa'} · kéo thân/góc/cạnh`
                    : 'Không banner · video full khung'}
                  {videoConfig.overlay_opacity > 0 && ` · overlay tối ${Math.round(videoConfig.overlay_opacity * 100)}%`}
                  {videoConfig.watermarkImage && ` · logo @${Math.round(videoConfig.watermark_x*100)},${Math.round(videoConfig.watermark_y*100)}`}
                  {videoConfig.watermark_text && ` · text "${videoConfig.watermark_text.slice(0, 20)}${videoConfig.watermark_text.length > 20 ? '…' : ''}"`}
                  {(videoConfig.fade_in > 0 || videoConfig.fade_out > 0) && ` · fade ${videoConfig.fade_in.toFixed(1)}/${videoConfig.fade_out.toFixed(1)}s`}
                </p>
                <div className="text-[11px] text-faint mt-1 text-center space-x-2">
                  <span> audio×{videoConfig.audio_speed}</span>
                  <span>·</span>
                  <span> {videoConfig.transitions_pool.length || 1} transition</span>
                  <span>·</span>
                  <span>⏱️ {videoConfig.transition_duration}s</span>
                  {audioDuration > 0 && (
                    <>
                      <span>·</span>
                      <span> audio {formatTime(audioDuration)}</span>
                      <span></span>
                      <span> video ~{formatTime(estimatedFinalDuration)}</span>
                    </>
                  )}
                </div>
                <button
                  type="button"
                  onClick={startExactPreview}
                  disabled={!videoConfig.folder.trim() || !videoConfig.audioPath.trim() || exactPreview.status === 'queued' || exactPreview.status === 'running'}
                  className="block mx-auto mt-3 text-xs bg-slate-800 text-white px-3 py-1.5 rounded hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
                  title="Render khoảng 60s preview thực tế bằng ffmpeg, khớp 100% với output cuối"
                >
                  {exactPreview.status === 'queued' || exactPreview.status === 'running'
                    ? ` Đang render… ${exactPreview.progress}%`
                    : ' Render exact preview (60s)'}
                </button>
              </div>
            </div>

            {/* Start Button */}
            <button
              onClick={startVideoProcessing}
              disabled={!videoConfig.folder.trim() || !videoConfig.audioPath.trim() || isProcessing}
              className="w-full bg-primary-600 text-white py-3 px-4 rounded-md hover:bg-primary-700 disabled:opacity-50 transition font-semibold"
            >
              {isProcessing ? 'Processing...' : ' Start Video Processing'}
            </button>

            {/* Progress */}
            {(videoStatus.status === 'running' || videoStatus.status === 'queued') && (
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-primary-600 dark:text-primary-400 flex items-center gap-2">
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary-600"></div>
                    Đang xử lý video...
                  </span>
                  <span>{videoStatus.progress}%</span>
                </div>
                <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                  <div
                    className="bg-primary-600 h-2 rounded-full transition-all"
                    style={{ width: `${videoStatus.progress}%` }}
                  ></div>
                </div>
              </div>
            )}

            {/* Status */}
            {videoStatus.status === 'completed' && (
              <div className="bg-green-50 dark:bg-green-500/10 border border-green-200 dark:border-green-500/30 p-4 rounded-md">
                <p className="text-green-700 dark:text-green-400 font-semibold">Video processing completed!</p>
                {videoStatus.outputPath && (
                  <div className="mt-1 flex items-center gap-3 flex-wrap">
                    <p className="text-sm text-green-600 dark:text-green-400 break-all">Output: {videoStatus.outputPath}</p>
                    <button
                      onClick={handleOpenVideoFolder}
                      className="shrink-0 inline-flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-md bg-green-600 hover:bg-green-700 text-white transition-colors"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
                      </svg>
                      Mở thư mục
                    </button>
                  </div>
                )}
              </div>
            )}

            {videoStatus.status === 'failed' && (
              <div className="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 p-4 rounded-md">
                <p className="text-red-700 dark:text-red-400 font-semibold">Video processing failed</p>
                {videoStatus.error && (
                  <p className="text-sm text-red-600 dark:text-red-400 mt-1">{videoStatus.error}</p>
                )}
              </div>
            )}

            {error && (
              <div className="text-red-600 dark:text-red-400 text-sm bg-red-50 dark:bg-red-500/10 p-3 rounded-md">{error}</div>
            )}

            {/* ── Cắt video thành phẩm (clone từ tab Cắt video) ── */}
            <div className="border-t border-token pt-6 mt-2">
              <VideoTrimmerPage
                sourceVideoPath={
                  videoStatus.status === 'completed' ? (videoStatus.outputPath || '') : ''
                }
              />
            </div>

            {/* Action Buttons */}
            <div className="flex gap-3">
              {videoStatus.status === 'completed' && (
                <button
                  onClick={() => moveToStep(8)}
                  className="flex-1 bg-green-500 text-white py-3 px-4 rounded-md hover:bg-green-600 transition font-semibold"
                >
                  Continue
                </button>
              )}
              <button
                onClick={() => moveToStep(8)}
                className={`${videoStatus.status === 'completed' ? 'flex-1' : 'w-full'} bg-gray-400 dark:bg-gray-600 text-white py-3 px-4 rounded-md hover:bg-gray-500 dark:hover:bg-gray-600 transition`}
                disabled={videoStatus.status === 'running' || videoStatus.status === 'queued'}
              >
                Skip Video
              </button>
            </div>
          </div>
        )
      }

      case 8:
        return (
          <div className="space-y-4 text-center py-4">
            <div className="mx-auto mb-2 w-16 h-16 rounded-full grid place-items-center" style={{ background: 'rgba(31,157,107,0.14)', color: '#1F9D6B' }}>
              <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
            </div>
            <h3 className="text-2xl font-bold tracking-tight">Hoàn tất!</h3>
            <p className="text-dim mb-6">
              Audiobook của bạn đã được tạo thành công và sẵn sàng để tải về.
            </p>
            <div className="space-y-3">
              <button
                onClick={handleDownloadAudio}
                disabled={downloadingAudio}
                className="btn btn-primary w-full justify-center py-3 text-base disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {downloadingAudio ? 'Đang tải...' : hasNativeDialogs() ? '📂 Mở thư mục chứa audio' : 'Tải audio hoàn chỉnh'}
              </button>
              <button
                onClick={() => {
                  setCurrentStep(1)
                  setStoryData({ url: '', title: '', start_chapter: 1, end_chapter: 10 })
                  setError(null)
                }}
                className="btn btn-secondary w-full justify-center"
              >
                Xử lý truyện khác
              </button>
            </div>
          </div>
        )

      default:
        return null
    }
  }

  return (
    <div className="w-full">
      <div className="card p-6 md:p-8">
        <h2 className="text-2xl font-bold tracking-tight mb-6">Xử lý truyện</h2>

        {renderStepIndicator()}

        <div className="mt-8">
          {renderStepContent()}
        </div>
      </div>

      {/* Edit Chapter Dialog */}
      {editDialog.isOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-surface rounded-lg max-w-7xl w-full max-h-[90vh] overflow-y-auto">
            <div className="p-6">
              <h3 className="text-xl font-semibold mb-4">
                Edit Chapter {editDialog.chapter?.chapter_number}
              </h3>

              {/* Grammar Errors Section */}
              {editDialog.censoredWords.length > 0 && (
                <div className="mb-4 bg-orange-50 dark:bg-orange-500/10 border border-orange-200 dark:border-orange-500/30 rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <svg className="w-5 h-5 text-orange-600 dark:text-orange-400" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                    </svg>
                    <h4 className="font-semibold text-orange-800 dark:text-orange-300">
                      Phát hiện {editDialog.censoredWords.length} lỗi
                      {editDialog.censoredWords.filter(w => w.word_type === 'banned').length > 0 && (
                        <span className="ml-2 text-sm font-normal">
                          ({editDialog.censoredWords.filter(w => w.word_type === 'banned').length} từ bị kiểm duyệt)
                        </span>
                      )}
                    </h4>
                  </div>
                  <div className="max-h-60 overflow-y-auto space-y-2">
                    {editDialog.censoredWords.map((word) => (
                      <div
                        key={word.id}
                        className={`bg-surface rounded p-3 text-sm border-l-4 ${
                          word.word_type === 'banned' ? 'border-red-500' : 'border-orange-500'
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1">
                            <div className="flex items-center gap-2 mb-2">
                              <span className={`font-mono px-2 py-0.5 rounded ${
                                word.word_type === 'banned'
                                  ? 'bg-red-100 dark:bg-red-500/20 text-red-800 dark:text-red-300'
                                  : 'bg-orange-100 dark:bg-orange-500/20 text-orange-800 dark:text-orange-300'
                              }`}>
                                {word.word}
                              </span>
                              {word.word_type === 'banned' && (
                                <span className="text-xs bg-red-600 text-white px-2 py-0.5 rounded">
                                  Từ kiểm duyệt
                                </span>
                              )}
                              <span className="text-xs text-dim">
                                Dòng {word.line_number}
                              </span>
                            </div>
                            {word.suggested_replacement && (
                              <div className="mb-2 text-sm">
                                <span className="text-dim">Thay thế: </span>
                                <span className="font-mono bg-green-100 dark:bg-green-500/20 text-green-800 dark:text-green-300 px-2 py-0.5 rounded">
                                  {word.suggested_replacement}
                                </span>
                              </div>
                            )}
                            <div className="text-dim italic text-xs">
                              {word.context}
                            </div>
                          </div>
                          {word.suggested_replacement && !word.fixed && (
                            <button
                              onClick={() => handleAcceptReplacement(word.id)}
                              disabled={loading}
                              className="px-3 py-1.5 text-xs font-medium text-white bg-green-600 hover:bg-green-700 rounded transition disabled:bg-gray-400"
                              title="Chấp nhận thay thế"
                            >
                              ✓ Accept
                            </button>
                          )}
                          {word.fixed && (
                            <span className="text-xs text-green-600 dark:text-green-400 font-medium">
                              ✓ Đã sửa
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {editDialog.censoredWords.length === 0 && (
                <div className="mb-4 bg-green-50 dark:bg-green-500/10 border border-green-200 dark:border-green-500/30 rounded-lg p-3">
                  <div className="flex items-center gap-2 text-green-800 dark:text-green-300">
                    <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                    </svg>
                    <span className="text-sm font-medium">Không có lỗi ngữ pháp</span>
                  </div>
                </div>
              )}

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-1">Chapter Title</label>
                  <input
                    type="text"
                    value={editDialog.title}
                    onChange={(e) => setEditDialog({ ...editDialog, title: e.target.value })}
                    className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                    placeholder="Enter chapter title"
                    spellCheck={false}
                  />
                </div>

                {/* Find and Replace + Quick Add Banned Word - Side by Side */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Find and Replace Section */}
                  <div className="bg-primary-50 dark:bg-primary-500/10 border border-primary-200 dark:border-primary-500/30 rounded-lg p-4">
                    <h4 className="text-sm font-semibold text-primary-900 dark:text-primary-300 mb-3">Tìm và Thay Thế</h4>
                    <div className="space-y-3">
                      <div>
                        <label className="block text-xs font-medium text-dim mb-1">Tìm kiếm</label>
                        <input
                          type="text"
                          value={editDialog.findText}
                          onChange={(e) => {
                            setEditDialog({ ...editDialog, findText: e.target.value })
                            // Auto search when typing
                            const regex = new RegExp(e.target.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi')
                            const matches = e.target.value ? editDialog.content.match(regex) : null
                            setEditDialog(prev => ({ ...prev, findText: e.target.value, matchCount: matches ? matches.length : 0 }))
                          }}
                          onKeyPress={(e) => e.key === 'Enter' && handleFindText()}
                          className="w-full px-3 py-2 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                          placeholder="Nhập từ cần tìm..."
                          spellCheck={false}
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-dim mb-1">Thay thế bằng</label>
                        <input
                          type="text"
                          value={editDialog.replaceText}
                          onChange={(e) => setEditDialog({ ...editDialog, replaceText: e.target.value })}
                          className="w-full px-3 py-2 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                          placeholder="Nhập từ thay thế..."
                          spellCheck={false}
                        />
                      </div>

                      {/* Match count display */}
                      {editDialog.findText && (
                        <div className={`text-xs px-3 py-1.5 rounded font-medium ${
                          editDialog.matchCount > 0
                            ? 'text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-500/10 border border-green-200 dark:border-green-500/30'
                            : 'text-dim bg-surface-2 border border-token'
                        }`}>
                          {editDialog.matchCount > 0
                            ? ` Tìm thấy ${editDialog.matchCount} kết quả`
                            : ' Không tìm thấy kết quả'}
                        </div>
                      )}

                      {/* Action buttons */}
                      <div className="flex flex-wrap gap-2">
                        <button
                          onClick={handleFindText}
                          className="px-3 py-1.5 text-sm bg-primary-500 text-white rounded hover:bg-primary-600 transition"
                          disabled={!editDialog.findText}
                        >
                           Tìm
                        </button>
                        <button
                          onClick={handleReplaceFirst}
                          className="px-3 py-1.5 text-sm bg-orange-500 text-white rounded hover:bg-orange-600 transition disabled:bg-gray-300"
                          disabled={!editDialog.findText || editDialog.matchCount === 0}
                        >
                          Thay thế 1
                        </button>
                        <button
                          onClick={handleReplaceAll}
                          className="px-3 py-1.5 text-sm bg-red-500 text-white rounded hover:bg-red-600 transition disabled:bg-gray-300"
                          disabled={!editDialog.findText || editDialog.matchCount === 0}
                        >
                          Thay thế tất cả ({editDialog.matchCount})
                        </button>
                        {editDialog.findText && (
                          <button
                            onClick={() => setEditDialog({
                              ...editDialog,
                              findText: '',
                              replaceText: '',
                              matchCount: 0
                            })}
                            className="px-3 py-1.5 text-sm bg-gray-500 dark:bg-gray-600 text-white rounded hover:bg-gray-600 transition"
                          >
                             Xóa
                          </button>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Quick Add Banned Word Section */}
                  <div className="bg-primary-50 dark:bg-primary-500/10 border border-primary-200 dark:border-primary-500/30 rounded-lg p-4">
                    <h4 className="text-sm font-semibold text-primary-900 dark:text-primary-300 mb-3">Thêm Từ Kiểm Duyệt Nhanh</h4>
                    <div className="space-y-3">
                      <div>
                        <label className="block text-xs font-medium text-dim mb-1">Từ bị cấm</label>
                        <input
                          type="text"
                          value={editDialog.quickBannedWord}
                          onChange={(e) => setEditDialog({ ...editDialog, quickBannedWord: e.target.value })}
                          className="w-full px-3 py-2 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                          placeholder="Nhập từ bị cấm..."
                          spellCheck={false}
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-dim mb-1">Từ thay thế</label>
                        <input
                          type="text"
                          value={editDialog.quickReplacementWord}
                          onChange={(e) => setEditDialog({ ...editDialog, quickReplacementWord: e.target.value })}
                          className="w-full px-3 py-2 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                          placeholder="Nhập từ thay thế..."
                          spellCheck={false}
                        />
                      </div>
                      <button
                        onClick={handleQuickAddBannedWord}
                        className="w-full px-3 py-1.5 text-sm bg-primary-600 text-white rounded hover:bg-primary-700 transition disabled:bg-gray-400"
                        disabled={loading || !editDialog.quickBannedWord || !editDialog.quickReplacementWord}
                      >
                         Thêm vào danh sách
                      </button>
                    </div>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Chapter Content</label>

                  {/* Textarea with line numbers and highlight */}
                  <div className="flex border rounded-md overflow-hidden">
                    {/* Line numbers */}
                    <div
                      ref={lineNumbersRef}
                      className="bg-surface-3 text-dim text-right px-2 py-2 select-none overflow-hidden font-mono text-sm leading-6"
                      style={{
                        minWidth: '50px',
                        maxHeight: '480px',
                        overflowY: 'hidden',
                        borderRight: '1px solid #e5e7eb'
                      }}
                    >
                      {getLineNumbers(editDialog.content).map((lineNum) => (
                        <div key={lineNum} style={{ lineHeight: '24px' }}>
                          {lineNum}
                        </div>
                      ))}
                    </div>

                    {/* Container for highlight overlay and textarea */}
                    <div className="relative flex-1">
                      {/* Highlight overlay */}
                      {editDialog.findText && (
                        <div
                          ref={highlightRef}
                          className="absolute top-0 left-0 px-3 py-2 font-mono text-sm leading-6 pointer-events-none whitespace-pre-wrap break-words overflow-hidden"
                          style={{
                            width: '100%',
                            height: '480px',
                            lineHeight: '24px',
                            overflowY: 'auto',
                            overflowX: 'hidden',
                            color: 'transparent'
                          }}
                          dangerouslySetInnerHTML={{
                            __html: getHighlightedText(editDialog.content, editDialog.findText)
                          }}
                        />
                      )}

                      {/* Textarea */}
                      <textarea
                        ref={textareaRef}
                        value={editDialog.content}
                        onChange={(e) => setEditDialog({ ...editDialog, content: e.target.value })}
                        onScroll={handleTextareaScroll}
                        className="relative px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono text-sm resize-none leading-6"
                        style={{
                          width: '100%',
                          height: '480px',
                          lineHeight: '24px',
                          backgroundColor: editDialog.findText ? 'transparent' : 'var(--surface)',
                          color: 'var(--text)',
                          caretColor: 'var(--text)'
                        }}
                        placeholder="Nội dung chương..."
                        spellCheck={false}
                      />
                    </div>
                  </div>

                  <div className="mt-1 text-sm text-dim">
                    Số ký tự: {editDialog.content.length.toLocaleString()} | Số dòng: {getLineNumbers(editDialog.content).length}
                  </div>
                </div>
              </div>

              <div className="flex justify-end gap-3 mt-6">
                <button
                  onClick={() => setEditDialog({
                    isOpen: false,
                    chapter: null,
                    content: '',
                    title: '',
                    censoredWords: [],
                    findText: '',
                    replaceText: '',
                    matchCount: 0,
                    quickBannedWord: '',
                    quickReplacementWord: ''
                  })}
                  className="px-4 py-2 text-dim hover:text-strong transition"
                  disabled={loading}
                >
                  Cancel
                </button>
                <button
                  onClick={handleCheckGrammar}
                  className="px-4 py-2 rounded-md font-medium transition border border-primary-200 dark:border-primary-500/30 bg-primary-50 dark:bg-primary-500/10 text-primary-700 dark:text-primary-300 hover:bg-primary-100 dark:hover:bg-primary-500/20 disabled:opacity-50"
                  disabled={loading}
                >
                  {loading ? 'Checking...' : 'Check Grammar'}
                </button>
                <button
                  onClick={handleSaveEditedChapter}
                  className="px-6 py-2 bg-primary-500 text-white rounded-md hover:bg-primary-600 transition disabled:bg-gray-400"
                  disabled={loading}
                >
                  {loading ? 'Saving...' : 'Save Changes'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Folder Browser Dialog */}
      {folderBrowser.isOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-surface rounded-lg w-full max-w-lg max-h-[80vh] flex flex-col">
            <div className="p-4 border-b flex items-center justify-between">
              <h3 className="text-lg font-semibold">Select Video Folder</h3>
              <button
                onClick={() => setFolderBrowser(prev => ({ ...prev, isOpen: false }))}
                className="text-faint hover:text-dim text-xl"
              >
                x
              </button>
            </div>

            {/* Current Path */}
            <div className="px-4 py-2 bg-surface-2 border-b text-sm font-mono text-dim truncate">
              {folderBrowser.currentPath || 'Drives'}
              {folderBrowser.videoCount > 0 && (
                <span className="ml-2 text-green-600 dark:text-green-400 font-sans">
                  ({folderBrowser.videoCount} videos)
                </span>
              )}
            </div>

            {/* Folder List */}
            <div className="flex-1 overflow-y-auto p-2" style={{ minHeight: '300px' }}>
              {folderBrowser.loading ? (
                <div className="flex items-center justify-center py-8">
                  <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary-600"></div>
                  <span className="ml-2 text-dim">Loading...</span>
                </div>
              ) : (
                <>
                  {/* Go Up */}
                  {folderBrowser.parentPath !== null && (
                    <button
                      onClick={() => openFolderBrowser(folderBrowser.parentPath || '')}
                      className="w-full text-left px-3 py-2 hover:bg-primary-50 dark:hover:bg-primary-500/15 rounded flex items-center gap-2 text-primary-600 dark:text-primary-400"
                    >
                      <span>&#8593;</span> ..
                    </button>
                  )}

                  {/* Folders */}
                  {folderBrowser.folders.length === 0 && !folderBrowser.loading && (
                    <div className="text-faint text-sm text-center py-4">No subfolders</div>
                  )}
                  {folderBrowser.folders.map((folder) => (
                    <button
                      key={folder}
                      onClick={() => navigateFolder(folder)}
                      className="w-full text-left px-3 py-2 hover:bg-surface-3 rounded flex items-center gap-2 text-sm truncate"
                    >
                      <span className="text-yellow-500 dark:text-yellow-400 flex-shrink-0">&#128193;</span>
                      <span className="truncate">{folder}</span>
                    </button>
                  ))}
                </>
              )}
            </div>

            {/* Actions */}
            <div className="p-4 border-t flex gap-2">
              <button
                onClick={selectFolder}
                disabled={!folderBrowser.currentPath}
                className="flex-1 bg-primary-500 text-white py-2 px-4 rounded-md hover:bg-primary-600 disabled:opacity-50 transition font-semibold"
              >
                Select This Folder
                {folderBrowser.videoCount > 0 && ` (${folderBrowser.videoCount} videos)`}
              </button>
              <button
                onClick={() => setFolderBrowser(prev => ({ ...prev, isOpen: false }))}
                className="px-4 py-2 bg-gray-200 dark:bg-gray-700 rounded-md hover:bg-gray-300 dark:hover:bg-gray-600 transition"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Exact Preview Modal */}
      {exactPreview.open && (
        <div className="fixed inset-0 bg-black bg-opacity-70 flex items-center justify-center z-50 p-4" onClick={closeExactPreview}>
          <div className="bg-surface rounded-lg w-full max-w-3xl max-h-[90vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="p-4 border-b flex items-center justify-between">
              <h3 className="text-lg font-semibold">
                 Exact Preview
                {exactPreview.cached && <span className="ml-2 text-xs text-green-600 dark:text-green-400 font-normal">(cache)</span>}
              </h3>
              <button onClick={closeExactPreview} className="text-dim hover:text-strong text-2xl leading-none">×</button>
            </div>
            <div className="p-4 flex-1 overflow-auto">
              {(exactPreview.status === 'queued' || exactPreview.status === 'running') && (
                <div className="space-y-3 py-8">
                  <div className="flex items-center justify-center gap-3 text-dim">
                    <div className="animate-spin rounded-full h-5 w-5 border-2 border-primary-600 border-t-transparent"></div>
                    <span>Đang render preview với ffmpeg... ({exactPreview.progress}%)</span>
                  </div>
                  <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-primary-500 h-full transition-all"
                      style={{ width: `${exactPreview.progress}%` }}
                    />
                  </div>
                  <p className="text-xs text-dim text-center">
                    Quá trình này áp dụng đầy đủ pipeline (concat clips, atempo, overlay, watermark, fade…) — có thể mất 20–60s.
                  </p>
                </div>
              )}
              {exactPreview.status === 'failed' && (
                <div className="bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 p-3 rounded text-sm space-y-2">
                  <div className="font-semibold"> Render failed</div>
                  <div className="font-mono text-xs whitespace-pre-wrap">{exactPreview.error || 'Unknown error'}</div>
                  <button
                    onClick={startExactPreview}
                    className="mt-2 bg-red-600 text-white text-xs px-3 py-1.5 rounded hover:bg-red-700"
                  >Thử lại</button>
                </div>
              )}
              {exactPreview.status === 'done' && exactPreview.hash && (
                <div className="space-y-3">
                  <video
                    key={exactPreview.hash}
                    src={`/api/v1/video/preview-file?hash=${exactPreview.hash}`}
                    controls
                    autoPlay
                    className="w-full rounded bg-black"
                    style={{ maxHeight: '60vh' }}
                  />
                  <div className="flex items-center justify-between text-xs text-dim">
                    <span>Preview render dùng đúng config hiện tại — khớp 100% với output cuối.</span>
                    <a
                      href={`/api/v1/video/preview-file?hash=${exactPreview.hash}`}
                      download={`preview_${exactPreview.hash}.mp4`}
                      className="bg-slate-800 text-white px-3 py-1.5 rounded hover:bg-slate-700"
                    > Download</a>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Audio File Browser Dialog */}
      {audioBrowser.isOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-surface rounded-lg w-full max-w-lg max-h-[80vh] flex flex-col">
            <div className="p-4 border-b flex items-center justify-between">
              <h3 className="text-lg font-semibold">Select Audio File</h3>
              <button
                onClick={() => setAudioBrowser(prev => ({ ...prev, isOpen: false }))}
                className="text-faint hover:text-dim text-xl"
              >
                x
              </button>
            </div>

            {/* Current Path */}
            <div className="px-4 py-2 bg-surface-2 border-b text-sm font-mono text-dim truncate">
              {audioBrowser.currentPath || 'Drives'}
              {audioBrowser.files.length > 0 && (
                <span className="ml-2 text-green-600 dark:text-green-400 font-sans">
                  ({audioBrowser.files.length} audio files)
                </span>
              )}
            </div>

            {/* File List */}
            <div className="flex-1 overflow-y-auto p-2" style={{ minHeight: '300px' }}>
              {audioBrowser.loading ? (
                <div className="flex items-center justify-center py-8">
                  <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary-600"></div>
                  <span className="ml-2 text-dim">Loading...</span>
                </div>
              ) : (
                <>
                  {/* Go Up */}
                  {audioBrowser.parentPath !== null && (
                    <button
                      onClick={() => openAudioBrowser(audioBrowser.parentPath || '')}
                      className="w-full text-left px-3 py-2 hover:bg-primary-50 dark:hover:bg-primary-500/15 rounded flex items-center gap-2 text-primary-600 dark:text-primary-400"
                    >
                      <span>&#8593;</span> ..
                    </button>
                  )}

                  {/* Folders */}
                  {audioBrowser.folders.map((folder) => (
                    <button
                      key={folder}
                      onClick={() => navigateAudioFolder(folder)}
                      className="w-full text-left px-3 py-2 hover:bg-surface-3 rounded flex items-center gap-2 text-sm truncate"
                    >
                      <span className="text-yellow-500 dark:text-yellow-400 flex-shrink-0">&#128193;</span>
                      <span className="truncate">{folder}</span>
                    </button>
                  ))}

                  {/* Audio Files */}
                  {audioBrowser.files.map((file) => (
                    <button
                      key={file}
                      onClick={() => selectAudioFile(file)}
                      className="w-full text-left px-3 py-2 hover:bg-green-50 dark:hover:bg-green-500/15 rounded flex items-center gap-2 text-sm truncate"
                    >
                      <span className="text-primary-500 dark:text-primary-400 flex-shrink-0">&#127925;</span>
                      <span className="truncate">{file}</span>
                    </button>
                  ))}

                  {audioBrowser.folders.length === 0 && audioBrowser.files.length === 0 && (
                    <div className="text-faint text-sm text-center py-4">No folders or audio files</div>
                  )}
                </>
              )}
            </div>

            {/* Actions */}
            <div className="p-4 border-t">
              <button
                onClick={() => setAudioBrowser(prev => ({ ...prev, isOpen: false }))}
                className="w-full px-4 py-2 bg-gray-200 dark:bg-gray-700 rounded-md hover:bg-gray-300 dark:hover:bg-gray-600 transition"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Image File Browser Dialog */}
      {imageBrowser.isOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-surface rounded-lg w-full max-w-lg max-h-[80vh] flex flex-col">
            <div className="p-4 border-b flex items-center justify-between">
              <h3 className="text-lg font-semibold">Select Banner Image</h3>
              <button
                onClick={() => setImageBrowser(prev => ({ ...prev, isOpen: false }))}
                className="text-faint hover:text-dim text-xl"
              >
                x
              </button>
            </div>

            {/* Current Path */}
            <div className="px-4 py-2 bg-surface-2 border-b text-sm font-mono text-dim truncate">
              {imageBrowser.currentPath || 'Drives'}
              {imageBrowser.files.length > 0 && (
                <span className="ml-2 text-green-600 dark:text-green-400 font-sans">
                  ({imageBrowser.files.length} image files)
                </span>
              )}
            </div>

            {/* File List */}
            <div className="flex-1 overflow-y-auto p-2" style={{ minHeight: '300px' }}>
              {imageBrowser.loading ? (
                <div className="flex items-center justify-center py-8">
                  <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary-600"></div>
                  <span className="ml-2 text-dim">Loading...</span>
                </div>
              ) : (
                <>
                  {/* Go Up */}
                  {imageBrowser.parentPath !== null && (
                    <button
                      onClick={() => openImageBrowser(imageBrowser.parentPath || '')}
                      className="w-full text-left px-3 py-2 hover:bg-primary-50 dark:hover:bg-primary-500/15 rounded flex items-center gap-2 text-primary-600 dark:text-primary-400"
                    >
                      <span>&#8593;</span> ..
                    </button>
                  )}

                  {/* Folders */}
                  {imageBrowser.folders.map((folder) => (
                    <button
                      key={folder}
                      onClick={() => navigateImageFolder(folder)}
                      className="w-full text-left px-3 py-2 hover:bg-surface-3 rounded flex items-center gap-2 text-sm truncate"
                    >
                      <span className="text-yellow-500 dark:text-yellow-400 flex-shrink-0">&#128193;</span>
                      <span className="truncate">{folder}</span>
                    </button>
                  ))}

                  {/* Image Files */}
                  {imageBrowser.files.map((file) => (
                    <button
                      key={file}
                      onClick={() => selectImageFile(file)}
                      className="w-full text-left px-3 py-2 hover:bg-green-50 dark:hover:bg-green-500/15 rounded flex items-center gap-2 text-sm truncate"
                    >
                      <span className="text-green-500 dark:text-green-400 flex-shrink-0">&#128444;</span>
                      <span className="truncate">{file}</span>
                    </button>
                  ))}

                  {imageBrowser.folders.length === 0 && imageBrowser.files.length === 0 && (
                    <div className="text-faint text-sm text-center py-4">No folders or image files</div>
                  )}
                </>
              )}
            </div>

            {/* Actions */}
            <div className="p-4 border-t">
              <button
                onClick={() => setImageBrowser(prev => ({ ...prev, isOpen: false }))}
                className="w-full px-4 py-2 bg-gray-200 dark:bg-gray-700 rounded-md hover:bg-gray-300 dark:hover:bg-gray-600 transition"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Dialog */}
      {deleteDialog.isOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-surface rounded-lg max-w-md w-full">
            <div className="p-6">
              <h3 className="text-xl font-semibold mb-4">Confirm Delete</h3>

              <p className="text-dim mb-6">
                Are you sure you want to delete Chapter {deleteDialog.chapter?.chapter_number}?
                {deleteDialog.chapter?.title && (
                  <span className="block mt-2 font-medium">"{deleteDialog.chapter.title}"</span>
                )}
                <span className="block mt-2 text-sm text-red-600 dark:text-red-400">This action cannot be undone.</span>
              </p>

              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setDeleteDialog({
                    isOpen: false,
                    chapter: null
                  })}
                  className="px-4 py-2 text-dim hover:text-strong transition"
                  disabled={loading}
                >
                  Cancel
                </button>
                <button
                  onClick={handleConfirmDelete}
                  className="px-6 py-2 bg-red-500 text-white rounded-md hover:bg-red-600 transition disabled:bg-gray-400"
                  disabled={loading}
                >
                  {loading ? 'Deleting...' : 'Delete Chapter'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Custom URLs Dialog */}
      {customUrlsDialog.isOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-surface rounded-lg max-w-2xl w-full max-h-[90vh] overflow-hidden flex flex-col">
            <div className="p-4 border-b flex items-center justify-between">
              <h3 className="text-xl font-semibold">Nhập link chương thủ công</h3>
              <button
                onClick={() => setCustomUrlsDialog({ isOpen: false, urlsText: '' })}
                className="text-dim hover:text-dim"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="p-4 flex-1 overflow-y-auto">
              <p className="text-sm text-dim mb-3">
                Nhập mỗi link chương trên một dòng. Thứ tự link = thứ tự chương (dòng 1 = chương 1, dòng 2 = chương 2, ...).
              </p>
              <textarea
                value={customUrlsDialog.urlsText}
                onChange={(e) => setCustomUrlsDialog(prev => ({ ...prev, urlsText: e.target.value }))}
                placeholder={`https://example.com/truyen/chuong-1\nhttps://example.com/truyen/chuong-2\nhttps://example.com/truyen/chuong-3`}
                className="w-full h-80 px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono text-sm"
                spellCheck={false}
              />
              <div className="mt-2 text-sm text-dim">
                Số dòng (links): {customUrlsDialog.urlsText.split('\n').filter(line => line.trim()).length}
              </div>
            </div>
            <div className="p-4 border-t flex justify-end gap-3">
              <button
                onClick={() => setCustomUrlsDialog({ isOpen: false, urlsText: '' })}
                className="px-4 py-2 border rounded-md hover:bg-surface-2 transition"
              >
                Hủy
              </button>
              <button
                onClick={() => {
                  const urls = customUrlsDialog.urlsText
                    .split('\n')
                    .map(line => line.trim())
                    .filter(line => line.length > 0)
                  if (urls.length > 0) {
                    setStoryData(prev => ({
                      ...prev,
                      custom_chapter_urls: urls,
                      start_chapter: 1,
                      end_chapter: urls.length
                    }))
                    showToast(`Đã lưu ${urls.length} link chương`, 'success')
                  }
                  setCustomUrlsDialog({ isOpen: false, urlsText: '' })
                }}
                className="px-4 py-2 bg-primary-500 text-white rounded-md hover:bg-primary-600 transition"
              >
                Lưu ({customUrlsDialog.urlsText.split('\n').filter(line => line.trim()).length} links)
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Preset Modal (create | rename) */}
      {presetModal.isOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-surface rounded-lg w-full max-w-md flex flex-col">
            <div className="p-4 border-b flex items-center justify-between">
              <h3 className="text-lg font-semibold">
                {presetModal.mode === 'rename' ? ' Đổi tên preset' : ' Lưu config hiện tại'}
              </h3>
              <button
                onClick={() => setPresetModal({ isOpen: false, mode: 'create', name: '', presetId: null })}
                className="text-faint hover:text-dim text-xl"
              >
                x
              </button>
            </div>
            <div className="p-4 space-y-3">
              <label className="block text-sm font-medium text-dim">Tên preset</label>
              <input
                type="text"
                autoFocus
                value={presetModal.name}
                onChange={(e) => setPresetModal(prev => ({ ...prev, name: e.target.value }))}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    confirmPresetModal()
                  } else if (e.key === 'Escape') {
                    setPresetModal({ isOpen: false, mode: 'create', name: '', presetId: null })
                  }
                }}
                placeholder="VD: Preset mặc định, Quảng cáo 60s..."
                className="w-full px-3 py-2 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
              {presetModal.mode === 'create' && (
                <p className="text-xs text-dim">
                  Preset sẽ lưu các setting video (transitions, fade, codec, ...) — không lưu folder, audio path, banner/watermark cụ thể.
                </p>
              )}
            </div>
            <div className="p-4 border-t flex gap-2 justify-end">
              <button
                onClick={() => setPresetModal({ isOpen: false, mode: 'create', name: '', presetId: null })}
                className="px-4 py-2 bg-gray-200 dark:bg-gray-700 rounded-md hover:bg-gray-300 dark:hover:bg-gray-600 transition text-sm"
              >
                Cancel
              </button>
              <button
                onClick={confirmPresetModal}
                disabled={!presetModal.name.trim()}
                className="px-4 py-2 bg-primary-500 text-white rounded-md hover:bg-primary-600 disabled:opacity-50 transition text-sm font-semibold"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm Dialog */}
      {confirmDialog.isOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-surface rounded-lg w-full max-w-md flex flex-col">
            <div className="p-4 border-b flex items-center justify-between">
              <h3 className="text-lg font-semibold">{confirmDialog.title}</h3>
              <button
                onClick={() => setConfirmDialog(prev => ({ ...prev, isOpen: false }))}
                className="text-faint hover:text-dim text-xl"
              >
                x
              </button>
            </div>
            <div className="p-4">
              <p className="text-sm text-dim whitespace-pre-line">{confirmDialog.message}</p>
            </div>
            <div className="p-4 border-t flex gap-2 justify-end">
              <button
                onClick={() => setConfirmDialog(prev => ({ ...prev, isOpen: false }))}
                className="px-4 py-2 bg-gray-200 dark:bg-gray-700 rounded-md hover:bg-gray-300 dark:hover:bg-gray-600 transition text-sm"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  const cb = confirmDialog.onConfirm
                  setConfirmDialog(prev => ({ ...prev, isOpen: false }))
                  cb()
                }}
                className={`px-4 py-2 text-white rounded-md transition text-sm font-semibold ${
                  confirmDialog.variant === 'danger'
                    ? 'bg-red-500 hover:bg-red-600'
                    : 'bg-primary-500 hover:bg-primary-600'
                }`}
              >
                {confirmDialog.confirmText}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast Notification */}
      {toast.isVisible && (
        <div className="fixed bottom-6 right-6 z-[100] animate-slide-up">
          <div className={`flex items-center gap-3 px-5 py-4 rounded-lg shadow-lg ${
            toast.type === 'success' ? 'bg-green-500' :
            toast.type === 'error' ? 'bg-red-500' : 'bg-primary-500'
          } text-white`}>
            {toast.type === 'success' && (
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            )}
            {toast.type === 'error' && (
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            )}
            {toast.type === 'info' && (
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            )}
            <span className="font-medium">{toast.message}</span>
            <button
              onClick={() => setToast(prev => ({ ...prev, isVisible: false }))}
              className="ml-2 hover:opacity-80 transition"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
