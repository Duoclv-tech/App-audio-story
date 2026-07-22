import { useState } from 'react'
import axios from 'axios'
import { KeyRound, ShieldCheck, Loader2, Copy, Check } from 'lucide-react'

interface Props {
  /** device_id shown for support; passed in from the gate's status call. */
  deviceId?: string
  /** Called after a successful activation so the gate can re-check and unlock. */
  onActivated: () => void
}

export default function ActivationPage({ deviceId, onActivated }: Props) {
  const [licenseKey, setLicenseKey] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  const handleActivate = async () => {
    const key = licenseKey.trim()
    if (!key) {
      setError('Vui lòng nhập mã kích hoạt.')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      const { data } = await axios.post('/api/v1/license/activate', { license_key: key })
      if (data?.ok) {
        onActivated()
      } else {
        setError(data?.message || 'Kích hoạt thất bại. Vui lòng thử lại.')
      }
    } catch (e: any) {
      setError(e?.response?.data?.message || e?.response?.data?.detail || 'Không kết nối được máy chủ. Vui lòng kiểm tra mạng.')
    } finally {
      setSubmitting(false)
    }
  }

  const copyDeviceId = async () => {
    if (!deviceId) return
    try {
      await navigator.clipboard.writeText(deviceId)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* clipboard may be unavailable */ }
  }

  return (
    <div className="min-h-screen grid place-items-center p-6">
      <div className="w-full max-w-md">
        <div className="card p-8">
          <div
            className="w-14 h-14 rounded-2xl grid place-items-center mb-5"
            style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}
          >
            <ShieldCheck size={28} />
          </div>

          <h1 className="text-2xl font-bold tracking-tight mb-1">Kích hoạt sản phẩm</h1>
          <p className="text-dim text-sm mb-6">
            Nhập mã kích hoạt bạn nhận được sau khi mua để bắt đầu sử dụng. Chỉ cần kết nối
            mạng một lần cho lần kích hoạt đầu tiên.
          </p>

          <label className="block text-sm font-medium mb-1.5">Mã kích hoạt</label>
          <div className="relative mb-1">
            <KeyRound size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
            <input
              type="text"
              value={licenseKey}
              onChange={(e) => setLicenseKey(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !submitting) handleActivate() }}
              placeholder="XXXX-XXXX-XXXX-XXXX"
              autoFocus
              spellCheck={false}
              className="w-full pl-9 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono tracking-wide"
              disabled={submitting}
            />
          </div>

          {error && (
            <p className="text-sm text-red-600 dark:text-red-400 mt-2">{error}</p>
          )}

          <button
            onClick={handleActivate}
            disabled={submitting}
            className="btn-primary w-full mt-5 flex items-center justify-center gap-2"
          >
            {submitting ? (<><Loader2 size={18} className="animate-spin" /> Đang kích hoạt...</>) : 'Kích hoạt'}
          </button>

          {deviceId && (
            <div className="mt-6 pt-5 border-t border-[var(--border)]">
              <p className="text-xs text-faint mb-1.5">
                Mã thiết bị (gửi cho hỗ trợ nếu bạn cần trợ giúp):
              </p>
              <button
                onClick={copyDeviceId}
                className="w-full flex items-center gap-2 text-left font-mono text-[11px] text-dim bg-[var(--surface-2,rgba(0,0,0,0.04))] rounded-lg px-3 py-2 hover:opacity-80 transition"
                title="Bấm để sao chép"
              >
                <span className="truncate flex-1">{deviceId}</span>
                {copied ? <Check size={14} className="text-emerald-500 shrink-0" /> : <Copy size={14} className="shrink-0" />}
              </button>
            </div>
          )}
        </div>

        <p className="text-center text-xs text-faint mt-4">
          Chưa có mã? Vui lòng liên hệ nơi bạn đã mua sản phẩm.
        </p>
      </div>
    </div>
  )
}
