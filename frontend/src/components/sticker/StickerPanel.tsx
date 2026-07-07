import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import {
  Sticker,
  StickerLibraryCategory,
  makeSticker,
  stickerFileUrl,
} from './sticker'

interface PanelProps {
  stickers: Sticker[]
  audioDuration: number // post-speedup duration drives default end_time clamp
  selectedId: string | null
  onSelect: (id: string | null) => void
  onAdd: (s: Sticker) => void
  onUpdate: (id: string, patch: Partial<Sticker>) => void
  onRemove: (id: string) => void
}

export function StickerPanel({
  stickers, audioDuration, selectedId,
  onSelect, onAdd, onUpdate, onRemove,
}: PanelProps) {
  const [library, setLibrary] = useState<StickerLibraryCategory[]>([])
  const [activeCategory, setActiveCategory] = useState<string>('all')
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    axios.get<{ categories: StickerLibraryCategory[] }>('/api/v1/video/stickers/library')
      .then(r => { if (alive) setLibrary(r.data.categories || []) })
      .catch(() => { if (alive) setLibrary([]) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [])

  const categories = ['all', ...library.map(c => c.name)]
  const visibleItems = library
    .filter(c => activeCategory === 'all' || c.name === activeCategory)
    .flatMap(c => c.stickers.map(s => ({ ...s, _category: c.label })))

  const handlePick = (item: { path: string; name: string; animated: boolean; _category: string }) => {
    onAdd(makeSticker({
      image_path: item.path,
      source_label: `${item._category} / ${item.name}`,
      animated: item.animated,
      audio_duration: audioDuration,
    }))
  }

  const handleUpload = async (file: File) => {
    setUploading(true)
    setUploadError(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await axios.post<{ path: string; filename: string; animated: boolean }>(
        '/api/v1/video/stickers/upload', fd
      )
      onAdd(makeSticker({
        image_path: r.data.path,
        source_label: `Custom / ${r.data.filename}`,
        animated: r.data.animated,
        audio_duration: audioDuration,
      }))
    } catch (err: any) {
      setUploadError(err?.response?.data?.detail || 'Upload thất bại')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const fmtTime = (s: number) => {
    const m = Math.floor(s / 60)
    const sec = Math.floor(s % 60)
    return `${m}:${String(sec).padStart(2, '0')}`
  }

  const selected = stickers.find(s => s.id === selectedId)

  return (
    <div className="space-y-3">
      {/* Library picker */}
      <div className="border rounded p-3 bg-white space-y-2">
        <div className="flex items-center justify-between">
          <div className="text-xs font-medium text-gray-700"> Thư viện sticker</div>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="text-xs px-2 py-1 bg-primary-500 text-white rounded hover:bg-primary-600 disabled:opacity-50"
          >
            {uploading ? 'Đang tải...' : '+ Upload custom'}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".png,.gif,.webp,.apng,.jpg,.jpeg"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) handleUpload(f)
            }}
          />
        </div>

        {uploadError && (
          <div className="text-[11px] text-red-600 bg-red-50 p-1.5 rounded">{uploadError}</div>
        )}

        {/* Category tabs */}
        {library.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {categories.map(cat => (
              <button
                key={cat}
                onClick={() => setActiveCategory(cat)}
                className={`text-[11px] px-2 py-0.5 rounded ${
                  activeCategory === cat
                    ? 'bg-primary-500 text-white'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {cat === 'all' ? 'Tất cả' : (library.find(c => c.name === cat)?.label || cat)}
              </button>
            ))}
          </div>
        )}

        {/* Grid */}
        {loading ? (
          <div className="text-[11px] text-gray-500 py-3 text-center">Đang tải thư viện...</div>
        ) : visibleItems.length === 0 ? (
          <div className="text-[11px] text-gray-500 py-3 text-center bg-gray-50 rounded">
            Chưa có sticker nào trong thư viện.<br />
            Thả file PNG/GIF/WebP vào <code>web_app/backend/stickers/&lt;category&gt;/</code> hoặc bấm "Upload custom".
          </div>
        ) : (
          <div className="grid grid-cols-5 gap-1.5 max-h-48 overflow-y-auto">
            {visibleItems.map(item => (
              <button
                key={item.path}
                type="button"
                onClick={() => handlePick(item)}
                title={`${item._category} / ${item.name}${item.animated ? ' (animated)' : ''}`}
                className="relative aspect-square bg-gray-50 rounded border border-gray-200 hover:border-primary-400 hover:bg-white p-1 transition"
              >
                <img
                  src={stickerFileUrl(item.path)}
                  alt={item.name}
                  className="w-full h-full object-contain pointer-events-none"
                />
                {item.animated && (
                  <span className="absolute top-0 right-0 text-[8px] bg-primary-500 text-white px-1 rounded-bl">GIF</span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Active stickers list */}
      <div className="border rounded p-3 bg-white space-y-2">
        <div className="flex items-center justify-between">
          <div className="text-xs font-medium text-gray-700">
             Sticker đang dùng ({stickers.length})
          </div>
          {stickers.length > 5 && (
            <span className="text-[10px] text-amber-600" title="Quá nhiều sticker có thể làm encode chậm">
               &gt;5 sticker, encode có thể chậm
            </span>
          )}
        </div>

        {stickers.length === 0 ? (
          <div className="text-[11px] text-gray-400 py-2">
            Chưa có. Bấm vào sticker trong thư viện ở trên để thêm.
          </div>
        ) : (
          <div className="space-y-1">
            {stickers.map(s => (
              <div
                key={s.id}
                onClick={() => onSelect(s.id)}
                className={`flex items-center gap-2 p-1.5 rounded border cursor-pointer ${
                  selectedId === s.id
                    ? 'border-primary-400 bg-primary-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
              >
                <img
                  src={stickerFileUrl(s.image_path)}
                  alt=""
                  className="w-8 h-8 object-contain bg-white rounded"
                />
                <div className="flex-1 min-w-0">
                  <div className="text-[11px] font-medium text-gray-700 truncate">
                    {s.source_label || s.image_path.split(/[\\/]/).pop()}
                  </div>
                  <div className="text-[10px] text-gray-500">
                    {fmtTime(s.start_time)} {s.end_time == null ? 'hết' : fmtTime(s.end_time)}
                    {' · '}{s.w}×{s.h}px
                  </div>
                </div>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); onRemove(s.id) }}
                  className="text-xs text-red-500 hover:text-red-700 px-1"
                  title="Xoá sticker"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Selected sticker editor */}
      {selected && (
        <div className="border rounded p-3 bg-white space-y-2">
          <div className="text-xs font-medium text-gray-700"> Tinh chỉnh sticker đang chọn</div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-[10px] text-gray-500">Width (px)</label>
              <input
                type="number" min={16} max={4096} step={4}
                value={selected.w}
                onChange={(e) => onUpdate(selected.id, { w: parseInt(e.target.value) || 200 })}
                className="w-full px-2 py-1 text-xs border rounded"
              />
            </div>
            <div>
              <label className="block text-[10px] text-gray-500">Height (px)</label>
              <input
                type="number" min={16} max={4096} step={4}
                value={selected.h}
                onChange={(e) => onUpdate(selected.id, { h: parseInt(e.target.value) || 200 })}
                className="w-full px-2 py-1 text-xs border rounded"
              />
            </div>
          </div>

          <div>
            <label className="block text-[10px] text-gray-500">
              Opacity: {Math.round(selected.opacity * 100)}%
            </label>
            <input
              type="range" min={0.1} max={1} step={0.05}
              value={selected.opacity}
              onChange={(e) => onUpdate(selected.id, { opacity: parseFloat(e.target.value) })}
              className="w-full"
            />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-[10px] text-gray-500">
                Bắt đầu (s): {selected.start_time.toFixed(1)}
              </label>
              <input
                type="range"
                min={0}
                max={Math.max(audioDuration || 60, selected.start_time)}
                step={0.1}
                value={selected.start_time}
                onChange={(e) => {
                  const v = parseFloat(e.target.value)
                  const patch: Partial<Sticker> = { start_time: v }
                  if (selected.end_time != null && v >= selected.end_time) {
                    patch.end_time = v + 0.5
                  }
                  onUpdate(selected.id, patch)
                }}
                className="w-full"
              />
            </div>
            <div>
              <label className="block text-[10px] text-gray-500">
                Kết thúc (s): {selected.end_time == null ? 'hết video' : selected.end_time.toFixed(1)}
              </label>
              <input
                type="range"
                min={selected.start_time + 0.5}
                max={Math.max(audioDuration || 60, (selected.end_time ?? 0) + 0.5)}
                step={0.1}
                value={selected.end_time ?? (audioDuration || 60)}
                onChange={(e) => onUpdate(selected.id, { end_time: parseFloat(e.target.value) })}
                className="w-full"
              />
            </div>
          </div>

          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1 text-[11px]">
              <input
                type="checkbox"
                checked={selected.end_time == null}
                onChange={(e) => onUpdate(selected.id, {
                  end_time: e.target.checked ? null : (audioDuration || 60),
                })}
              />
              Hiện đến hết video
            </label>
            <button
              type="button"
              onClick={() => onUpdate(selected.id, { x: 0.5, y: 0.5 })}
              className="text-[11px] px-2 py-0.5 bg-gray-100 rounded hover:bg-gray-200"
            >
              ⊙ Center
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
