import { Link, useNavigate } from 'react-router-dom'
import { Plus, History, BookOpen } from 'lucide-react'
import { useState } from 'react'
import axios from 'axios'

export default function HomePage() {
  const navigate = useNavigate()
  const [creating, setCreating] = useState(false)

  const handleCreateNewProject = async () => {
    setCreating(true)
    try {
      console.log('Creating new project...')
      const response = await axios.post('/api/v1/stories/create-process')
      console.log('Project created:', response.data)
      const processId = response.data.id
      navigate(`/processor/${processId}`)
    } catch (error) {
      console.error('Error creating project:', error)
      alert('Failed to create new project')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="space-y-8">
      {/* Welcome Section */}
      <div className="bg-white rounded-lg shadow-sm p-8">
        <h2 className="text-3xl font-bold mb-4">
          Chào mừng đến với Audio Story
        </h2>
        <p className="text-gray-600 text-lg">
          Công cụ tải truyện từ TruyenFull và chuyển đổi thành audio tự động
        </p>
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <button
          onClick={handleCreateNewProject}
          disabled={creating}
          className="bg-primary-500 text-white rounded-lg p-6 hover:bg-primary-600 transition shadow-lg text-left disabled:bg-gray-400 disabled:cursor-not-allowed"
        >
          <Plus size={32} className="mb-4" />
          <h3 className="text-xl font-semibold mb-2">
            {creating ? 'Đang tạo...' : 'Tạo Project Mới'}
          </h3>
          <p className="text-primary-100">
            Bắt đầu tải và xử lý truyện mới
          </p>
        </button>

        <Link
          to="/history"
          className="bg-white rounded-lg p-6 hover:shadow-lg transition border"
        >
          <History size={32} className="mb-4 text-gray-700" />
          <h3 className="text-xl font-semibold mb-2">Lịch Sử</h3>
          <p className="text-gray-600">
            Xem các project đã xử lý
          </p>
        </Link>

        <div className="bg-white rounded-lg p-6 border">
          <BookOpen size={32} className="mb-4 text-gray-700" />
          <h3 className="text-xl font-semibold mb-2">Hướng Dẫn</h3>
          <p className="text-gray-600">
            Tìm hiểu cách sử dụng công cụ
          </p>
        </div>
      </div>

      {/* Features */}
      <div className="bg-white rounded-lg shadow-sm p-8">
        <h3 className="text-2xl font-bold mb-6">Tính Năng</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <h4 className="font-semibold mb-2">✅ Tải truyện tự động</h4>
            <p className="text-gray-600">Tải nhiều chương cùng lúc từ TruyenFull</p>
          </div>
          <div>
            <h4 className="font-semibold mb-2">✅ Kiểm tra nội dung</h4>
            <p className="text-gray-600">Phát hiện từ bị che và thống kê</p>
          </div>
          <div>
            <h4 className="font-semibold mb-2">✅ Chỉnh sửa trực tiếp</h4>
            <p className="text-gray-600">Editor tích hợp chỉnh sửa nội dung</p>
          </div>
          <div>
            <h4 className="font-semibold mb-2">✅ TTS VBEE</h4>
            <p className="text-gray-600">Chuyển văn bản thành giọng nói</p>
          </div>
          <div>
            <h4 className="font-semibold mb-2">✅ Nối audio</h4>
            <p className="text-gray-600">Gộp tất cả chương thành một file</p>
          </div>
          <div>
            <h4 className="font-semibold mb-2">✅ Theo dõi tiến độ</h4>
            <p className="text-gray-600">Real-time progress tracking</p>
          </div>
        </div>
      </div>

      {/* Supported Hosts */}
      <div className="bg-white rounded-lg shadow-sm p-6">
        <h3 className="text-lg font-semibold mb-4">Các Nguồn Được Hỗ Trợ</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <div className="border rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2 h-2 bg-blue-500 rounded-full"></div>
              <span className="font-semibold">TruyenFull.vision</span>
            </div>
            <p className="text-sm text-gray-600">Nguồn mặc định</p>
          </div>

          <div className="border rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2 h-2 bg-green-500 rounded-full"></div>
              <span className="font-semibold">TruyenMoiii.org</span>
            </div>
            <p className="text-sm text-gray-600">Hỗ trợ đầy đủ</p>
          </div>

          <div className="border rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2 h-2 bg-green-500 rounded-full"></div>
              <span className="font-semibold">TruyenHay.blog</span>
            </div>
            <p className="text-sm text-gray-600">WordPress platform</p>
          </div>

          <div className="border rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2 h-2 bg-green-500 rounded-full"></div>
              <span className="font-semibold">NguyetTruyen.net</span>
            </div>
            <p className="text-sm text-gray-600">Hỗ trợ đầy đủ</p>
          </div>

          <div className="border rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2 h-2 bg-green-500 rounded-full"></div>
              <span className="font-semibold">MeTruyen.mobi</span>
            </div>
            <p className="text-sm text-gray-600">Anti-scraping CSS</p>
          </div>
        </div>
        <p className="text-sm text-gray-500 mt-4">
          💡 Tự động phát hiện domain và áp dụng selectors phù hợp
        </p>
      </div>
    </div>
  )
}
