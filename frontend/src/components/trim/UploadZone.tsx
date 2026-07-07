import { useRef, useState } from 'react'
import { Upload } from 'lucide-react'

interface Props {
  onFileSelected: (file: File) => void
  uploading: boolean
  uploadProgress: number
}

export default function UploadZone({ onFileSelected, uploading, uploadProgress }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)

  const accept = '.mp4,.mov,.mkv,.avi,.webm,video/*'

  const handleFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return
    const file = files[0]
    if (!file.type.startsWith('video/') && !/\.(mp4|mov|mkv|avi|webm)$/i.test(file.name)) {
      alert('File không phải định dạng video hợp lệ')
      return
    }
    onFileSelected(file)
  }

  return (
    <div
      onClick={() => !uploading && inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragOver(false)
        if (!uploading) handleFiles(e.dataTransfer.files)
      }}
      className={`border-2 border-dashed rounded-lg p-12 text-center cursor-pointer transition ${
        dragOver ? 'border-primary-500 bg-primary-50 dark:bg-primary-500/10' : 'border-token hover:border-primary-400'
      } ${uploading ? 'pointer-events-none opacity-70' : ''}`}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />
      <Upload size={40} className="mx-auto text-faint mb-3" />
      <p className="text-dim font-medium mb-1">
        Kéo thả file video vào đây hoặc bấm để chọn
      </p>
      <p className="text-sm text-dim">MP4, MOV, MKV, AVI, WebM — tối đa 2 GB</p>
      {uploading && (
        <div className="mt-4">
          <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2.5">
            <div
              className="bg-primary-600 h-2.5 rounded-full transition-all"
              style={{ width: `${uploadProgress}%` }}
            />
          </div>
          <p className="text-sm text-dim mt-2">Đang upload… {uploadProgress}%</p>
        </div>
      )}
    </div>
  )
}
