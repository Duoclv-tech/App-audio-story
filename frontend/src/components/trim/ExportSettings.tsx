import type { AspectRatioParams, WatermarkParams } from '../../services/trimApi'
import WatermarkEditor from './WatermarkEditor'

interface Props {
  quality: string
  setQuality: (q: string) => void
  customBitrate: number
  setCustomBitrate: (n: number) => void

  aspectRatio: AspectRatioParams
  setAspectRatio: (ar: AspectRatioParams) => void
  cropMode: string
  setCropMode: (m: string) => void

  mute: boolean
  setMute: (v: boolean) => void
  volume: number
  setVolume: (v: number) => void
  speed: number
  setSpeed: (v: number) => void
  exactFrame: boolean
  setExactFrame: (v: boolean) => void
  fade: boolean
  setFade: (v: boolean) => void
  watermark: WatermarkParams
  setWatermark: (v: WatermarkParams) => void
  previewAspect: number

  outputFilename: string
  setOutputFilename: (v: string) => void
}

const QUALITY_OPTIONS = [
  { value: 'original', label: 'Gốc (không nén)' },
  { value: '1080p', label: 'Cao · 1080p' },
  { value: '720p', label: 'Trung bình · 720p' },
  { value: '480p', label: 'Thấp · 480p' },
  { value: 'custom', label: 'Tuỳ chỉnh (bitrate)' },
]

const AR_OPTIONS = [
  { value: 'original', label: 'Gốc' },
  { value: '16:9', label: '16:9' },
  { value: '9:16', label: '9:16' },
  { value: '1:1', label: '1:1' },
  { value: '4:3', label: '4:3' },
  { value: '4:5', label: '4:5' },
  { value: '21:9', label: '21:9' },
  { value: '16:10', label: '16:10' },
  { value: '3:4', label: '3:4' },
  { value: 'custom', label: 'Tuỳ chỉnh' },
]

const CROP_MODES = [
  { value: 'crop', label: 'Crop giữa' },
  { value: 'letterbox', label: 'Letterbox' },
  { value: 'blur', label: 'Blur background' },
]

const SPEED_PRESETS = [
  { value: 0.5, label: '0.5x' },
  { value: 0.75, label: '0.75x' },
  { value: 1, label: '1x' },
  { value: 1.25, label: '1.25x' },
  { value: 1.5, label: '1.5x' },
  { value: 2, label: '2x' },
]

function Pill({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-3 py-1.5 rounded-full text-sm border transition ${
        active
          ? 'bg-primary-600 text-white border-primary-600'
          : 'bg-surface text-dim border-token hover:border-primary-400'
      }`}
    >
      {children}
    </button>
  )
}

export default function ExportSettings(props: Props) {
  const {
    quality, setQuality, customBitrate, setCustomBitrate,
    aspectRatio, setAspectRatio, cropMode, setCropMode,
    mute, setMute, volume, setVolume, speed, setSpeed,
    exactFrame, setExactFrame, fade, setFade,
    watermark, setWatermark, previewAspect,
    outputFilename, setOutputFilename,
  } = props

  const isSpeedPreset = SPEED_PRESETS.some((p) => p.value === speed)

  return (
    <div className="space-y-6">
      {/* Quality */}
      <div>
        <h3 className="font-medium text-strong mb-2">Chất lượng video</h3>
        <div className="flex flex-wrap gap-2">
          {QUALITY_OPTIONS.map((q) => (
            <Pill key={q.value} active={quality === q.value} onClick={() => setQuality(q.value)}>
              {q.label}
            </Pill>
          ))}
        </div>
        {quality === 'custom' && (
          <div className="mt-2 flex items-center gap-2">
            <label className="text-sm text-dim">Bitrate (kbps):</label>
            <input
              type="number"
              min={100}
              max={50000}
              value={customBitrate}
              onChange={(e) => setCustomBitrate(parseInt(e.target.value || '0', 10))}
              className="w-28 px-2 py-1 border rounded"
            />
          </div>
        )}
      </div>

      {/* Aspect ratio */}
      <div>
        <h3 className="font-medium text-strong mb-2">Tỉ lệ khung hình</h3>
        <div className="flex flex-wrap gap-2">
          {AR_OPTIONS.map((ar) => (
            <Pill
              key={ar.value}
              active={aspectRatio.mode === ar.value}
              onClick={() => setAspectRatio({ ...aspectRatio, mode: ar.value })}
            >
              {ar.label}
            </Pill>
          ))}
        </div>

        {aspectRatio.mode === 'custom' && (
          <div className="mt-2 flex items-center gap-2">
            <input
              type="number"
              min={1}
              max={100}
              value={aspectRatio.custom_w ?? 16}
              onChange={(e) =>
                setAspectRatio({ ...aspectRatio, custom_w: parseInt(e.target.value || '1', 10) })
              }
              className="w-20 px-2 py-1 border rounded"
            />
            <span className="text-dim">:</span>
            <input
              type="number"
              min={1}
              max={100}
              value={aspectRatio.custom_h ?? 9}
              onChange={(e) =>
                setAspectRatio({ ...aspectRatio, custom_h: parseInt(e.target.value || '1', 10) })
              }
              className="w-20 px-2 py-1 border rounded"
            />
          </div>
        )}

        {aspectRatio.mode !== 'original' && (
          <div className="mt-3">
            <div className="text-sm text-dim mb-1">Chế độ xử lý:</div>
            <div className="flex flex-wrap gap-2">
              {CROP_MODES.map((c) => (
                <Pill key={c.value} active={cropMode === c.value} onClick={() => setCropMode(c.value)}>
                  {c.label}
                </Pill>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Speed */}
      <div>
        <h3 className="font-medium text-strong mb-2">Tốc độ phát</h3>
        <div className="flex flex-wrap gap-2">
          {SPEED_PRESETS.map((p) => (
            <Pill key={p.value} active={speed === p.value} onClick={() => setSpeed(p.value)}>
              {p.label}
            </Pill>
          ))}
          <Pill active={!isSpeedPreset} onClick={() => setSpeed(1.5)}>
            Tuỳ chỉnh
          </Pill>
        </div>
        {!isSpeedPreset && (
          <div className="mt-2 flex items-center gap-2">
            <label className="text-sm text-dim">Tốc độ:</label>
            <input
              type="number"
              min={0.25}
              max={4}
              step={0.05}
              value={speed}
              onChange={(e) => {
                const v = parseFloat(e.target.value)
                if (!isNaN(v) && v >= 0.25 && v <= 4) setSpeed(v)
              }}
              className="w-20 px-2 py-1 border rounded font-mono"
            />
            <span className="text-sm text-dim">× (0.25 – 4.0)</span>
          </div>
        )}
      </div>

      {/* Volume + options */}
      <div>
        <h3 className="font-medium text-strong mb-2">Tuỳ chọn thêm</h3>
        <div className="space-y-3">
          {/* Mute */}
          <label className="flex items-center gap-2 text-sm text-dim">
            <input type="checkbox" checked={mute} onChange={(e) => setMute(e.target.checked)} />
            Tắt tiếng (mute)
          </label>

          {/* Volume slider — only when not muted */}
          {!mute && (
            <div className="flex items-center gap-3 pl-1">
              <label className="text-sm text-dim w-20 shrink-0">Âm lượng</label>
              <input
                type="range"
                min={0}
                max={200}
                step={5}
                value={Math.round(volume * 100)}
                onChange={(e) => setVolume(parseInt(e.target.value, 10) / 100)}
                className="flex-1"
              />
              <span className="font-mono text-sm text-dim w-12 text-right">
                {Math.round(volume * 100)}%
              </span>
            </div>
          )}

          <label className="flex items-center gap-2 text-sm text-dim">
            <input
              type="checkbox"
              checked={exactFrame}
              onChange={(e) => setExactFrame(e.target.checked)}
            />
            Cắt chính xác theo frame (re-encode)
          </label>
          <label className="flex items-center gap-2 text-sm text-dim">
            <input type="checkbox" checked={fade} onChange={(e) => setFade(e.target.checked)} />
            Thêm fade in / fade out
          </label>
          <label className="flex items-center gap-2 text-sm text-dim">
            <input
              type="checkbox"
              checked={watermark.enabled}
              onChange={(e) => setWatermark({ ...watermark, enabled: e.target.checked })}
            />
            Chèn watermark
          </label>
          {watermark.enabled && (
            <WatermarkEditor
              value={watermark}
              onChange={setWatermark}
              previewAspect={previewAspect}
            />
          )}
        </div>
      </div>

      {/* Filename */}
      <div>
        <h3 className="font-medium text-strong mb-2">Tên file xuất</h3>
        <input
          type="text"
          value={outputFilename}
          onChange={(e) => setOutputFilename(e.target.value)}
          className="w-full px-3 py-1.5 border rounded font-mono text-sm"
        />
        <p className="text-xs text-dim mt-1">Luôn xuất ra .mp4</p>
      </div>
    </div>
  )
}
