import { BrowserRouter, Routes, Route } from 'react-router-dom'
import ErrorBoundary from './components/ErrorBoundary'
import Layout from './components/layout/Layout'
import HomePage from './pages/HomePage'
import ProcessorPage from './pages/ProcessorPage'
import HistoryPage from './pages/HistoryPage'
import SettingsPage from './pages/SettingsPage'
import BannedWordsPage from './pages/BannedWordsPage'
import PromptsPage from './pages/PromptsPage'
import VideoTrimmerPage from './pages/VideoTrimmerPage'

function App() {
  return (
    <BrowserRouter>
      <ErrorBoundary>
      <Layout>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/processor" element={<ProcessorPage />} />
          <Route path="/processor/:storyId" element={<ProcessorPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/banned-words" element={<BannedWordsPage />} />
          <Route path="/prompts" element={<PromptsPage />} />
          <Route path="/video-trimmer" element={<VideoTrimmerPage />} />
        </Routes>
      </Layout>
      </ErrorBoundary>
    </BrowserRouter>
  )
}

export default App
