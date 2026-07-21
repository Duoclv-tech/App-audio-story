import { useState, useEffect } from 'react'
import axios from 'axios'
import { hasNativeDialogs, pickFolderNative } from '../services/nativeDialog'

interface Settings {
  VBEE_APP_ID?: string
  VBEE_BEARER_TOKEN?: string
  GEMINI_API_KEY?: string
  output_folder?: string
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
      const response = await axios.get('/api/v1/settings')
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
      await axios.put('/api/v1/settings', settings)
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
        </h3>

        <div className="bg-primary-50 dark:bg-primary-500/10 border border-primary-200 dark:border-primary-500/30 rounded-lg p-4 mb-4">
          <div className="text-sm text-primary-800 dark:text-primary-300 mb-2 font-medium">
            Hướng dẫn lấy credentials:
          </div>
          <ol className="text-sm text-primary-700 dark:text-primary-400 space-y-1 list-decimal list-inside">
            <li>Đăng nhập <a href="https://vbee.vn" target="_blank" rel="noopener noreferrer" className="underline">https://vbee.vn</a></li>
            <li>Vào phần <strong>Quản lý ứng dụng</strong></li>
            <li>Tạo app mới hoặc chọn app có sẵn</li>
            <li>Copy <strong>ID ứng dụng</strong> (App ID)</li>
            <li>Click vào app để lấy <strong>Bearer Token</strong></li>
          </ol>
        </div>

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

      {/* Gemini AI Configuration */}
      <div className="mb-8">
        <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <span className="text-primary-600 dark:text-primary-400"></span>
          Cấu Hình Gemini AI (Grammar Check)
        </h3>

        <div className="bg-primary-50 dark:bg-primary-500/10 border border-primary-200 dark:border-primary-500/30 rounded-lg p-4 mb-4">
          <div className="text-sm text-primary-800 dark:text-primary-300 mb-2 font-medium">
            Hướng dẫn lấy API Key (miễn phí):
          </div>
          <ol className="text-sm text-primary-700 dark:text-primary-400 space-y-1 list-decimal list-inside">
            <li>Vào <a href="https://ai.google.dev" target="_blank" rel="noopener noreferrer" className="underline">https://ai.google.dev</a></li>
            <li>Đăng nhập bằng Gmail</li>
            <li>Click <strong>"Get API Key"</strong> (góc trái)</li>
            <li>Tạo API Key mới và copy</li>
          </ol>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">
            Gemini API Key
          </label>
          <div className="relative">
            <input
              type={showTokens ? "text" : "password"}
              value={settings.GEMINI_API_KEY || ''}
              onChange={(e) => handleInputChange('GEMINI_API_KEY', e.target.value)}
              placeholder="AIza..."
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
            Dùng để kiểm tra ngữ pháp bằng AI (Gemini 2.0 Flash - miễn phí)
          </p>
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
