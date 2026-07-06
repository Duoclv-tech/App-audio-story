import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Home, History, Settings, Shield, MessageSquare, Menu, ChevronLeft, Scissors } from 'lucide-react'

interface LayoutProps {
  children: React.ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(true)

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <button
                onClick={() => setSidebarOpen(!sidebarOpen)}
                className="p-2 rounded-lg hover:bg-gray-100 transition"
                title={sidebarOpen ? 'Đóng menu' : 'Mở menu'}
              >
                {sidebarOpen ? <ChevronLeft size={20} /> : <Menu size={20} />}
              </button>
              <h1 className="text-2xl font-bold text-primary-600">
                📖 Audio Story
              </h1>
            </div>
            <div className="flex items-center gap-4">
              <span className="text-sm text-gray-500">v1.0.0</span>
            </div>
          </div>
        </div>
      </header>

      <div className="flex-1 flex">
        {/* Sidebar */}
        <aside
          className={`bg-white border-r transition-all duration-300 overflow-hidden ${
            sidebarOpen ? 'w-64' : 'w-16'
          }`}
        >
          <nav className="p-2 space-y-2">
            <Link
              to="/"
              className="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-gray-100 transition"
              title="Trang chủ"
            >
              <Home size={20} className="shrink-0" />
              {sidebarOpen && <span>Trang chủ</span>}
            </Link>
            <Link
              to="/history"
              className="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-gray-100 transition"
              title="Lịch sử"
            >
              <History size={20} className="shrink-0" />
              {sidebarOpen && <span>Lịch sử</span>}
            </Link>
            <Link
              to="/banned-words"
              className="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-gray-100 transition"
              title="Từ kiểm duyệt"
            >
              <Shield size={20} className="shrink-0" />
              {sidebarOpen && <span>Từ kiểm duyệt</span>}
            </Link>
            <Link
              to="/prompts"
              className="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-gray-100 transition"
              title="Prompts"
            >
              <MessageSquare size={20} className="shrink-0" />
              {sidebarOpen && <span>Prompts</span>}
            </Link>
            <Link
              to="/video-trimmer"
              className="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-gray-100 transition"
              title="Cắt video"
            >
              <Scissors size={20} className="shrink-0" />
              {sidebarOpen && <span>Cắt video</span>}
            </Link>
            <Link
              to="/settings"
              className="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-gray-100 transition"
              title="Cài đặt"
            >
              <Settings size={20} className="shrink-0" />
              {sidebarOpen && <span>Cài đặt</span>}
            </Link>
          </nav>
        </aside>

        {/* Main Content */}
        <main className="flex-1 overflow-auto">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
            {children}
          </div>
        </main>
      </div>
    </div>
  )
}
