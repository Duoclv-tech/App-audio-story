import { useState, useEffect } from 'react'
import type { ReactNode } from 'react'
import axios from 'axios'
import { hasNativeDialogs, pickFolderNative } from '../services/nativeDialog'

interface Settings {
  VBEE_APP_ID?: string
  VBEE_BEARER_TOKEN?: string
  AI_GRAMMAR_PROVIDER?: string
  OPENAI_API_KEY?: string
  GEMINI_API_KEY?: string
  DEEPSEEK_API_KEY?: string
  output_folder?: string
}

// AI grammar-check providers. Selecting one in the dropdown reveals only that
// provider's key input + its own "how to get a key" tooltip. Adding a provider
// here is all the UI needs — the backend picks the key by AI_GRAMMAR_PROVIDER.
interface ProviderConfig {
  value: string
  label: string
  keyField: 'OPENAI_API_KEY' | 'GEMINI_API_KEY' | 'DEEPSEEK_API_KEY'
  keyLabel: string
  placeholder: string
  note: ReactNode
  tooltip: ReactNode
}

const AI_PROVIDERS: ProviderConfig[] = [
  {
    value: 'openai',
    label: 'OpenAI (mặc định)',
    keyField: 'OPENAI_API_KEY',
    keyLabel: 'OpenAI API Key',
    placeholder: 'sk-...',
    note: (
      <>
        Lấy tại{' '}
        <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer" className="underline">
          platform.openai.com/api-keys
        </a>{' '}
        (dùng model gpt-4o-mini).
      </>
    ),
    tooltip: (
      <>
        <ol className="text-sm text-primary-700 dark:text-primary-400 space-y-1 list-decimal list-inside">
          <li>Đăng nhập <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer" className="underline">platform.openai.com/api-keys</a></li>
          <li>Bấm <strong>"Create new secret key"</strong></li>
          <li>Copy key <strong>ngay</strong> — key chỉ hiển thị 1 lần duy nhất</li>
          <li>Vào <strong>Billing</strong> nạp credit thì key mới dùng được</li>
        </ol>
        <div className="text-xs text-primary-700 dark:text-primary-400 mt-2">
          ⚠️ Chưa nạp credit sẽ báo lỗi <span className="font-mono">insufficient_quota</span> dù key hợp lệ.
        </div>
      </>
    ),
  },
  {
    value: 'deepseek',
    label: 'DeepSeek',
    keyField: 'DEEPSEEK_API_KEY',
    keyLabel: 'DeepSeek API Key',
    placeholder: 'sk-...',
    note: (
      <>
        Lấy tại{' '}
        <a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noopener noreferrer" className="underline">
          platform.deepseek.com/api_keys
        </a>{' '}
        (dùng model deepseek-chat, giá rẻ).
      </>
    ),
    tooltip: (
      <>
        <ol className="text-sm text-primary-700 dark:text-primary-400 space-y-1 list-decimal list-inside">
          <li>Đăng nhập <a href="https://platform.deepseek.com" target="_blank" rel="noopener noreferrer" className="underline">platform.deepseek.com</a></li>
          <li>Mở mục <strong>"API keys"</strong>, bấm <strong>"Create new API key"</strong></li>
          <li>Copy key <strong>ngay</strong> — key chỉ hiển thị 1 lần duy nhất</li>
          <li>Vào <strong>"Top up"</strong> nạp credit thì key mới dùng được</li>
        </ol>
        <div className="text-xs text-primary-700 dark:text-primary-400 mt-2">
          💡 DeepSeek dùng API tương thích OpenAI, chi phí thấp hơn nhiều.
        </div>
      </>
    ),
  },
  {
    value: 'gemini',
    label: 'Google AI Studio (Gemini)',
    keyField: 'GEMINI_API_KEY',
    keyLabel: 'Gemini API Key',
    placeholder: 'AIza...',
    note: (
      <>
        Lấy miễn phí tại{' '}
        <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener noreferrer" className="underline">
          aistudio.google.com/apikey
        </a>{' '}
        (xem hướng dẫn ở nút <strong>?</strong>).
      </>
    ),
    tooltip: (
      <>
        <ol className="text-sm text-primary-700 dark:text-primary-400 space-y-1 list-decimal list-inside">
          <li>Mở <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener noreferrer" className="underline">aistudio.google.com/apikey</a></li>
          <li>Đăng nhập tài khoản Google</li>
          <li>Bấm <strong>"Create API key"</strong></li>
          <li>Copy key vừa tạo</li>
        </ol>
        <div className="text-xs text-primary-700 dark:text-primary-400 mt-2">
          ✅ Gemini có <strong>gói miễn phí</strong> — không cần thẻ thanh toán.
        </div>
      </>
    ),
  },
]

function HelpTooltip({ children }: { children: ReactNode }) {
  return (
    <span className="relative group inline-flex">
      <span
        className="flex items-center justify-center w-5 h-5 rounded-full bg-primary-100 dark:bg-primary-500/20 text-primary-700 dark:text-primary-300 text-xs font-bold cursor-help select-none"
        aria-label="Hướng dẫn lấy API key"
      >
        ?
      </span>
      <div className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 w-80 -translate-x-1/2 rounded-lg border border-primary-200 dark:border-primary-500/30 bg-primary-50 dark:bg-gray-800 p-4 opacity-0 shadow-lg transition-opacity duration-150 group-hover:opacity-100 group-hover:pointer-events-auto">
        <div className="text-sm text-primary-800 dark:text-primary-300 mb-2 font-medium">
          Hướng dẫn lấy API key:
        </div>
        {children}
      </div>
    </span>
  )
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings>({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null)
  const [showTokens, setShowTokens] = useState(false)
  const [effectiveOutput, setEffectiveOutput] = useState<{ path: string; is_default: boolean } | null>(null)

  useEffect(() => {
    loadSettings()
    loadOutputFolderInfo()
  }, [])

  const loadOutputFolderInfo = async () => {
    try {
      const r = await axios.get('/api/v1/settings/output-folder')
      setEffectiveOutput({ path: r.data.path, is_default: r.data.is_default })
    } catch (e) {
      console.error('Error loading output folder info:', e)
    }
  }

  const loadSettings = async () => {
    setLoading(true)
    try {
      const response = await axios.get('/api/v1/settings/')
      // Convert array of settings to object
      const settingsObj: Settings = {}
      response.data.forEach((setting: any) => {
        settingsObj[setting.setting_key as keyof Settings] = setting.setting_value
      })
      setSettings(settingsObj)
    } catch (error) {
      console.error('Error loading settings:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleSaveSettings = async () => {
    setSaving(true)
    setMessage(null)

    try {
      await axios.put('/api/v1/settings/', settings)
      loadOutputFolderInfo()
      setMessage({ type: 'success', text: 'Cài đặt đã được lưu thành công!' })

      // Auto hide success message after 3 seconds
      setTimeout(() => setMessage(null), 3000)
    } catch (error: any) {
      console.error('Error saving settings:', error)
      setMessage({
        type: 'error',
        text: error.response?.data?.detail || 'Lỗi khi lưu cài đặt'
      })
    } finally {
      setSaving(false)
    }
  }

  const handleInputChange = (key: keyof Settings, value: string) => {
    setSettings(prev => ({ ...prev, [key]: value }))
  }

  if (loading) {
    return (
      <div className="bg-surface rounded-lg shadow-sm p-8">
        <div className="text-center text-dim">Đang tải cài đặt...</div>
      </div>
    )
  }

  const activeProvider =
    AI_PROVIDERS.find((p) => p.value === (settings.AI_GRAMMAR_PROVIDER || 'openai')) ||
    AI_PROVIDERS[0]

  return (
    <div className="bg-surface rounded-lg shadow-sm p-8">
      <h2 className="text-2xl font-bold mb-6">Cài Đặt</h2>

      {/* Output folder */}
      <div className="mb-8">
        <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
          Thư Mục Lưu File (Output)
        </h3>
        <p className="text-sm text-dim mb-3">
          Nơi lưu file thành phẩm (video dài, video ngắn cắt, audio ghép, file Word).
          Để trống = thư mục <strong>Downloads</strong> của máy.
        </p>
        <div className="flex gap-2">
          <input
            type="text"
            value={settings.output_folder || ''}
            onChange={(e) => handleInputChange('output_folder', e.target.value)}
            placeholder="Để trống để dùng thư mục Downloads"
            className="flex-1 px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono text-sm"
          />
          {hasNativeDialogs() && (
            <button
              type="button"
              onClick={async () => {
                const picked = await pickFolderNative(settings.output_folder || undefined)
                if (picked) handleInputChange('output_folder', picked)
              }}
              className="px-4 py-2 border rounded-md hover:bg-surface-2 transition text-sm font-medium whitespace-nowrap"
            >
              Chọn thư mục
            </button>
          )}
        </div>
        {effectiveOutput && (
          <p className="text-xs text-dim mt-2 break-all">
            Đang lưu vào:{' '}
            <span className="font-mono text-strong">{effectiveOutput.path}</span>
            {effectiveOutput.is_default && ' (mặc định Downloads)'}
          </p>
        )}
      </div>

      {/* VBEE API Configuration */}
      <div className="mb-8">
        <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <span className="text-primary-600 dark:text-primary-400"></span>
          Cấu Hình VBEE API
          <span className="relative group inline-flex">
            <span
              className="flex items-center justify-center w-5 h-5 rounded-full bg-primary-100 dark:bg-primary-500/20 text-primary-700 dark:text-primary-300 text-xs font-bold cursor-help select-none"
              aria-label="Hướng dẫn lấy credentials"
            >
              ?
            </span>
            <div className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 w-80 -translate-x-1/2 rounded-lg border border-primary-200 dark:border-primary-500/30 bg-primary-50 dark:bg-gray-800 p-4 opacity-0 shadow-lg transition-opacity duration-150 group-hover:opacity-100 group-hover:pointer-events-auto">
              <div className="text-sm text-primary-800 dark:text-primary-300 mb-2 font-medium">
                Hướng dẫn lấy credentials:
              </div>
              <ol className="text-sm text-primary-700 dark:text-primary-400 space-y-1 list-decimal list-inside">
                <li>Đăng nhập <a href="https://vbee.vn" target="_blank" rel="noopener noreferrer" className="underline">vbee.vn</a>, mở trang <strong>Quản lý ứng dụng</strong> (Dashboard)</li>
                <li>Tạo app mới hoặc chọn app có sẵn</li>
                <li>Copy <strong>ID ứng dụng</strong> (App ID)</li>
                <li>Click vào app để lấy <strong>Bearer Token</strong></li>
              </ol>
              <div className="text-xs text-primary-700 dark:text-primary-400 mt-2">
                ⚠️ Bearer Token là JWT <strong>có thời hạn</strong> — khi hết hạn cần quay lại lấy token mới.
              </div>
            </div>
          </span>
        </h3>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">
              App ID
              <span className="text-red-500 dark:text-red-400 ml-1">*</span>
            </label>
            <input
              type="text"
              value={settings.VBEE_APP_ID || ''}
              onChange={(e) => handleInputChange('VBEE_APP_ID', e.target.value)}
              placeholder="c1c5c478-719d-4ec6-b665-58ed39484375"
              className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono text-sm"
            />
            <p className="text-xs text-dim mt-1">
              ID ứng dụng từ VBEE Dashboard
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">
              Bearer Token
              <span className="text-red-500 dark:text-red-400 ml-1">*</span>
            </label>
            <div className="relative">
              <input
                type={showTokens ? "text" : "password"}
                value={settings.VBEE_BEARER_TOKEN || ''}
                onChange={(e) => handleInputChange('VBEE_BEARER_TOKEN', e.target.value)}
                placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI..."
                className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 pr-20 font-mono text-sm"
              />
              <button
                type="button"
                onClick={() => setShowTokens(!showTokens)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-primary-600 dark:text-primary-400 hover:text-primary-800 dark:hover:text-primary-300"
              >
                {showTokens ? 'Ẩn' : 'Hiện'}
              </button>
            </div>
            <p className="text-xs text-dim mt-1">
              JWT token từ VBEE Dashboard (có thời hạn)
            </p>
          </div>
        </div>
      </div>

      {/* AI Grammar Check Configuration — pick a provider, enter only its key */}
      <div className="mb-8">
        <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <span className="text-primary-600 dark:text-primary-400"></span>
          Cấu Hình AI Kiểm Tra Chính Tả
        </h3>

        {/* Provider selector */}
        <div className="mb-4">
          <label className="block text-sm font-medium mb-1">
            Nhà cung cấp AI
          </label>
          <select
            value={activeProvider.value}
            onChange={(e) => handleInputChange('AI_GRAMMAR_PROVIDER', e.target.value)}
            className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm bg-surface"
          >
            {AI_PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
          <p className="text-xs text-dim mt-1">
            Chọn AI dùng để kiểm tra chính tả, rồi nhập key của nhà cung cấp đó bên dưới.
            Nếu key để trống, hệ thống tự dùng nhà cung cấp khác đã có key.
          </p>
        </div>

        {/* API key of the selected provider only */}
        <div>
          <label className="block text-sm font-medium mb-1 flex items-center gap-2">
            {activeProvider.keyLabel}
            <HelpTooltip>{activeProvider.tooltip}</HelpTooltip>
          </label>
          <div className="relative">
            <input
              type={showTokens ? "text" : "password"}
              value={settings[activeProvider.keyField] || ''}
              onChange={(e) => handleInputChange(activeProvider.keyField, e.target.value)}
              placeholder={activeProvider.placeholder}
              className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 pr-20 font-mono text-sm"
            />
            <button
              type="button"
              onClick={() => setShowTokens(!showTokens)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-primary-600 dark:text-primary-400 hover:text-primary-800 dark:hover:text-primary-300"
            >
              {showTokens ? 'Ẩn' : 'Hiện'}
            </button>
          </div>
          <p className="text-xs text-dim mt-1">{activeProvider.note}</p>
        </div>
      </div>

      {/* Message */}
      {message && (
        <div className={`mb-4 p-4 rounded-lg ${
          message.type === 'success'
            ? 'bg-green-50 dark:bg-green-500/10 border border-green-200 dark:border-green-500/30 text-green-800 dark:text-green-300'
            : 'bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 text-red-800 dark:text-red-300'
        }`}>
          {message.text}
        </div>
      )}

      {/* Save Button */}
      <div className="flex justify-end">
        <button
          onClick={handleSaveSettings}
          disabled={saving}
          className="bg-primary-500 text-white px-6 py-2 rounded-md hover:bg-primary-600 transition disabled:bg-gray-400"
        >
          {saving ? 'Đang lưu...' : 'Lưu Cài Đặt'}
        </button>
      </div>
    </div>
  )
}
