import { useState, useEffect } from 'react'
import { NavLink, Link } from 'react-router-dom'
import axios from 'axios'
import { Home, History, Settings, Shield, MessageSquare, Menu, ChevronLeft, Scissors, AlertTriangle, Mic, Sun, Moon, Zap } from 'lucide-react'

interface LayoutProps {
  children: React.ReactNode
}

interface NavEntry {
  to: string
  label: string
  icon: typeof Home
}

const NAV_SECTIONS: { title: string; items: NavEntry[] }[] = [
  {
    title: 'Sản xuất',
    items: [
      { to: '/', label: 'Trang chủ', icon: Home },
      { to: '/quick-build', label: 'Build Batch', icon: Zap },
      { to: '/history', label: 'Lịch sử', icon: History },
      { to: '/video-trimmer', label: 'Cắt video', icon: Scissors },
    ],
  },
  {
    title: 'Cấu hình',
    items: [
      { to: '/banned-words', label: 'Từ kiểm duyệt', icon: Shield },
      { to: '/prompts', label: 'Prompts', icon: MessageSquare },
      { to: '/settings', label: 'Cài đặt', icon: Settings },
    ],
  },
]

export default function Layout({ children }: LayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [needsApiKey, setNeedsApiKey] = useState(false)
  const [isDark, setIsDark] = useState(() => document.documentElement.classList.contains('dark'))

  const toggleTheme = () => {
    const next = !isDark
    setIsDark(next)
    document.documentElement.classList.toggle('dark', next)
    localStorage.setItem('theme', next ? 'dark' : 'light')
  }

  // First-run nudge: if VBEE credentials aren't set yet, TTS won't work.
  useEffect(() => {
    axios.get('/api/v1/settings/')
      .then((res) => {
        const map: Record<string, any> = {}
        ;(res.data || []).forEach((s: any) => { map[s.setting_key] = s.setting_value })
        const missing = !map['VBEE_APP_ID'] || !map['VBEE_BEARER_TOKEN']
        setNeedsApiKey(missing)
      })
      .catch(() => {})
  }, [])

  return (
    <div className="min-h-screen flex bg-app">
      {/* Sidebar */}
      <aside
        className={`shrink-0 flex flex-col border-r border-token transition-all duration-300 bg-surface-2 ${
          sidebarOpen ? 'w-64' : 'w-[68px]'
        }`}
      >
        {/* Brand + collapse toggle */}
        <div className="flex items-center gap-3 px-4 h-16 border-b border-token">
          <div
            className="w-9 h-9 rounded-[10px] shrink-0 grid place-items-center text-white"
            style={{
              background: 'linear-gradient(150deg, var(--accent-bright), var(--accent))',
              boxShadow: '0 2px 8px var(--accent-line)',
            }}
          >
            <Mic size={19} />
          </div>
          {sidebarOpen && (
            <>
              <div className="min-w-0 flex-1">
                <div className="font-bold text-[15px] tracking-tight leading-tight">AudioStory</div>
                <div className="font-mono text-[10px] text-faint tracking-wide">STUDIO · v1.0</div>
                <div className="font-mono text-[7.5px] text-faint tracking-wide">https://www.storetoolmmo.com</div>
              </div>
              <button
                onClick={() => setSidebarOpen(false)}
                className="p-1.5 rounded-lg text-dim hover:bg-surface hover:text-[var(--text)] transition-colors"
                title="Thu gọn menu"
              >
                <ChevronLeft size={18} />
              </button>
            </>
          )}
        </div>
        {!sidebarOpen && (
          <button
            onClick={() => setSidebarOpen(true)}
            className="mx-auto mt-2 p-2 rounded-lg text-dim hover:bg-surface hover:text-[var(--text)] transition-colors"
            title="Mở menu"
          >
            <Menu size={20} />
          </button>
        )}

        {/* Nav */}
        <nav className="flex-1 px-2.5 py-3 overflow-y-auto">
          {NAV_SECTIONS.map((section) => (
            <div key={section.title} className="mb-1">
              {sidebarOpen && (
                <div className="font-mono text-[10px] tracking-[0.12em] uppercase text-faint px-3 pt-3 pb-1.5">
                  {section.title}
                </div>
              )}
              <div className="flex flex-col gap-0.5">
                {section.items.map(({ to, label, icon: Icon }) => (
                  <NavLink
                    key={to}
                    to={to}
                    end={to === '/'}
                    title={label}
                    className={({ isActive }) =>
                      `relative flex items-center gap-3 px-3 py-2.5 rounded-lg text-[13.5px] font-medium transition-colors ${
                        isActive
                          ? 'text-[var(--text)] font-semibold nav-active'
                          : 'text-dim hover:text-[var(--text)] hover:bg-surface'
                      }`
                    }
                  >
                    <Icon size={18} className="shrink-0" />
                    {sidebarOpen && <span className="truncate">{label}</span>}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        {/* API-key nudge, docked near the bottom of the sidebar */}
        {needsApiKey && sidebarOpen && (
          <div className="px-3 pt-3">
            <Link
              to="/settings"
              className="flex gap-2.5 items-start p-3 rounded-lg transition-colors hover:brightness-95"
              style={{ background: 'rgba(214,75,69,0.10)' }}
            >
              <AlertTriangle size={16} className="shrink-0 mt-0.5" style={{ color: '#D64B45' }} />
              <div>
                <div className="text-xs font-semibold">Chưa có API key VBEE</div>
                <div className="text-[11.5px] text-dim">TTS sẽ không chạy — mở Cài đặt để nhập.</div>
              </div>
            </Link>
          </div>
        )}

        {/* Theme toggle */}
        <div className="p-3 border-t border-token">
          <button
            onClick={toggleTheme}
            title={isDark ? 'Chuyển sang nền sáng' : 'Chuyển sang nền tối'}
            className={`flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-[13.5px] font-medium text-dim hover:text-[var(--text)] hover:bg-surface transition-colors ${
              sidebarOpen ? '' : 'justify-center'
            }`}
          >
            {isDark ? <Sun size={18} className="shrink-0" /> : <Moon size={18} className="shrink-0" />}
            {sidebarOpen && <span>{isDark ? 'Nền sáng' : 'Nền tối'}</span>}
          </button>
        </div>
      </aside>

      {/* Content — no top header; content runs full-width right under the window bar */}
      <main className="flex-1 overflow-auto min-w-0">
        <div className="w-full max-w-[1600px] mx-auto px-6 lg:px-8 py-6">
          {children}
        </div>
      </main>
    </div>
  )
}
