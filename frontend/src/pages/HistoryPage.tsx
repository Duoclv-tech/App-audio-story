import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'

interface Story {
  id: string
  title: string
  url: string
  author?: string
  start_chapter: number
  end_chapter: number
  status: string
  current_step: number
  is_favorite: boolean
  created_at: string
  updated_at: string
  total_downloaded: number
  total_audio_generated: number
  has_merged_audio: boolean
}

interface PaginationMeta {
  total: number
  page: number
  page_size: number
  total_pages: number
}

interface PaginatedResponse {
  data: Story[]
  meta: PaginationMeta
}

export default function HistoryPage() {
  const navigate = useNavigate()
  const [stories, setStories] = useState<Story[]>([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [favoriteOnly, setFavoriteOnly] = useState(false)
  const [currentPage, setCurrentPage] = useState(1)
  const [paginationMeta, setPaginationMeta] = useState<PaginationMeta>({
    total: 0,
    page: 1,
    page_size: 20,
    total_pages: 0
  })
  const [deleteDialog, setDeleteDialog] = useState<{ isOpen: boolean; story: Story | null }>({
    isOpen: false,
    story: null
  })
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    loadStories(currentPage)
  }, [currentPage, favoriteOnly])

  const loadStories = async (page: number = 1) => {
    try {
      setLoading(true)
      const response = await axios.get<PaginatedResponse>(
        `/api/v1/stories/with-stats?page=${page}&page_size=20&favorite_only=${favoriteOnly}`
      )
      setStories(response.data.data)
      setPaginationMeta(response.data.meta)
    } catch (error) {
      console.error('Error loading stories:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleFavoriteFilterChange = (checked: boolean) => {
    setFavoriteOnly(checked)
    setCurrentPage(1) // Reset to page 1 when filter changes
  }

  const handleOpenStory = (storyId: string) => {
    navigate(`/processor/${storyId}`)
  }

  const handleDeleteStory = (story: Story) => {
    setDeleteDialog({ isOpen: true, story })
  }

  const handleConfirmDelete = async () => {
    if (!deleteDialog.story) return

    try {
      setDeleting(true)
      await axios.delete(`/api/v1/stories/${deleteDialog.story.id}`)
      // Reload stories - go to page 1 if current page would be empty
      if (stories.length === 1 && currentPage > 1) {
        setCurrentPage(currentPage - 1)
      } else {
        await loadStories(currentPage)
      }
      setDeleteDialog({ isOpen: false, story: null })
    } catch (error) {
      console.error('Error deleting story:', error)
      alert('Failed to delete story')
    } finally {
      setDeleting(false)
    }
  }

  const handlePageChange = (newPage: number) => {
    if (newPage >= 1 && newPage <= paginationMeta.total_pages) {
      setCurrentPage(newPage)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }

  const handleToggleFavorite = async (storyId: string, event: React.MouseEvent) => {
    event.stopPropagation()

    try {
      const response = await axios.post(`/api/v1/stories/${storyId}/toggle-favorite`)

      // Update the story in the local state
      setStories(prevStories =>
        prevStories.map(story =>
          story.id === storyId
            ? { ...story, is_favorite: response.data.is_favorite }
            : story
        )
      )
    } catch (error) {
      console.error('Error toggling favorite:', error)
      alert('Failed to toggle favorite')
    }
  }

  const getStatusBadge = (status: string) => {
    const statusColors: Record<string, string> = {
      'draft': 'bg-surface-3 text-strong',
      'created': 'bg-primary-100 dark:bg-primary-500/20 text-primary-800 dark:text-primary-300',
      'downloading': 'bg-yellow-100 dark:bg-yellow-500/20 text-yellow-800 dark:text-yellow-300',
      'downloaded': 'bg-green-100 dark:bg-green-500/20 text-green-800 dark:text-green-300',
      'ready_for_tts': 'bg-primary-100 dark:bg-primary-500/20 text-primary-800 dark:text-primary-300',
      'tts_processing': 'bg-orange-100 dark:bg-orange-500/20 text-orange-800 dark:text-orange-300',
      'tts_completed': 'bg-teal-100 dark:bg-teal-500/20 text-teal-800 dark:text-teal-300',
      'completed': 'bg-green-100 dark:bg-green-500/20 text-green-800 dark:text-green-300'
    }

    const statusLabels: Record<string, string> = {
      'draft': 'Draft',
      'created': 'Created',
      'downloading': 'Downloading',
      'downloaded': 'Downloaded',
      'ready_for_tts': 'Ready for TTS',
      'tts_processing': 'TTS Processing',
      'tts_completed': 'TTS Completed',
      'completed': 'Completed'
    }

    return (
      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${statusColors[status] || 'bg-surface-3 text-strong'}`}>
        {statusLabels[status] || status}
      </span>
    )
  }

  const getStepLabel = (step: number) => {
    const steps = [
      'Input',
      'Download',
      'Edit',
      'TTS Config',
      'TTS Process',
      'Merge',
      'Complete'
    ]
    return steps[step - 1] || 'Unknown'
  }

  const filteredStories = stories.filter(story =>
    story.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
    story.url.toLowerCase().includes(searchTerm.toLowerCase()) ||
    (story.author && story.author.toLowerCase().includes(searchTerm.toLowerCase()))
  )

  if (loading) {
    return (
      <div className="bg-surface rounded-lg shadow-sm p-8">
        <div className="text-center text-dim">Đang tải lịch sử...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="bg-surface rounded-lg shadow-sm p-8">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold">Lịch Sử</h2>
          <button
            onClick={() => loadStories(currentPage)}
            className="text-sm text-primary-600 dark:text-primary-400 hover:text-primary-800 dark:hover:text-primary-300 underline"
          >
            Làm mới
          </button>
        </div>

        {/* Search and Filters */}
        <div className="mb-6 space-y-3">
          <input
            type="text"
            placeholder="Tìm kiếm theo tên truyện, URL, hoặc tác giả..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
          />

          <div className="flex items-center gap-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={favoriteOnly}
                onChange={(e) => handleFavoriteFilterChange(e.target.checked)}
                className="w-4 h-4 text-primary-600 dark:text-primary-400 border-token rounded focus:ring-primary-500"
              />
              <span className="flex items-center gap-1 text-sm text-dim">
                <svg
                  className="w-4 h-4 text-yellow-500 dark:text-yellow-400 fill-current"
                  viewBox="0 0 24 24"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                </svg>
                Chỉ hiển thị truyện yêu thích
              </span>
            </label>
            {favoriteOnly && (
              <span className="text-xs text-dim">
                ({paginationMeta.total} truyện)
              </span>
            )}
          </div>
        </div>

        {/* Stats Summary */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          <div className="bg-primary-50 dark:bg-primary-500/10 p-4 rounded-lg">
            <div className="text-2xl font-bold text-primary-600 dark:text-primary-400">{paginationMeta.total}</div>
            <div className="text-sm text-dim">Tổng số truyện</div>
          </div>
          <div className="bg-green-50 dark:bg-green-500/10 p-4 rounded-lg">
            <div className="text-2xl font-bold text-green-600 dark:text-green-400">
              {stories.filter(s => s.status === 'completed').length}
            </div>
            <div className="text-sm text-dim">Đã hoàn thành (trang này)</div>
          </div>
          <div className="bg-orange-50 dark:bg-orange-500/10 p-4 rounded-lg">
            <div className="text-2xl font-bold text-orange-600 dark:text-orange-400">
              {stories.filter(s => s.status === 'tts_processing' || s.status === 'downloading').length}
            </div>
            <div className="text-sm text-dim">Đang xử lý (trang này)</div>
          </div>
          <div className="bg-primary-50 dark:bg-primary-500/10 p-4 rounded-lg">
            <div className="text-2xl font-bold text-primary-600 dark:text-primary-400">
              {stories.filter(s => s.has_merged_audio).length}
            </div>
            <div className="text-sm text-dim">Có file merge (trang này)</div>
          </div>
        </div>

        {/* Story List */}
        {filteredStories.length === 0 ? (
          <div className="text-center text-dim py-12">
            {searchTerm ? 'Không tìm thấy truyện nào' : 'Chưa có truyện nào'}
          </div>
        ) : (
          <div className="space-y-4">
            {filteredStories.map((story) => (
              <div
                key={story.id}
                className="border rounded-lg p-4 hover:bg-surface-2 transition-colors"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <button
                        onClick={(e) => handleToggleFavorite(story.id, e)}
                        className="flex-shrink-0 focus:outline-none hover:scale-110 transition-transform"
                        title={story.is_favorite ? 'Bỏ yêu thích' : 'Yêu thích'}
                      >
                        {story.is_favorite ? (
                          <svg
                            className="w-6 h-6 text-yellow-500 dark:text-yellow-400 fill-current"
                            viewBox="0 0 24 24"
                            xmlns="http://www.w3.org/2000/svg"
                          >
                            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                          </svg>
                        ) : (
                          <svg
                            className="w-6 h-6 text-faint hover:text-yellow-500 transition-colors"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                            xmlns="http://www.w3.org/2000/svg"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"
                            />
                          </svg>
                        )}
                      </button>
                      <h3 className="text-lg font-semibold">{story.title}</h3>
                      {getStatusBadge(story.status)}
                    </div>

                    <div className="space-y-1 text-sm text-dim mb-3">
                      {story.url && (
                        <div className="flex items-center gap-2">
                          <span className="font-medium">URL:</span>
                          <a
                            href={story.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-primary-600 dark:text-primary-400 hover:underline truncate max-w-md"
                          >
                            {story.url}
                          </a>
                        </div>
                      )}
                      {story.author && (
                        <div className="flex items-center gap-2">
                          <span className="font-medium">Tác giả:</span>
                          <span>{story.author}</span>
                        </div>
                      )}
                      <div className="flex items-center gap-4">
                        <span>
                          <span className="font-medium">Chương:</span> {story.start_chapter} - {story.end_chapter}
                        </span>
                        <span>
                          <span className="font-medium">Bước hiện tại:</span> {story.current_step}. {getStepLabel(story.current_step)}
                        </span>
                      </div>
                    </div>

                    {/* Progress Info */}
                    <div className="flex items-center gap-6 text-sm">
                      <div className="flex items-center gap-2">
                        <svg className="w-4 h-4 text-primary-600 dark:text-primary-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                        </svg>
                        <span className="text-dim">
                          {story.total_downloaded} chương
                        </span>
                      </div>

                      <div className="flex items-center gap-2">
                        <svg className="w-4 h-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                        </svg>
                        <span className="text-dim">
                          {story.total_audio_generated} audio
                        </span>
                      </div>

                      {story.has_merged_audio && (
                        <div className="flex items-center gap-2">
                          <svg className="w-4 h-4 text-primary-600 dark:text-primary-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                          </svg>
                          <span className="text-dim">
                            File merge sẵn sàng
                          </span>
                        </div>
                      )}
                    </div>

                    {/* Timestamps */}
                    <div className="mt-3 text-xs text-dim">
                      Tạo: {new Date(story.created_at).toLocaleString('vi-VN')} |
                      Cập nhật: {new Date(story.updated_at).toLocaleString('vi-VN')}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 ml-4">
                    <button
                      onClick={() => handleOpenStory(story.id)}
                      className="px-4 py-2 bg-primary-500 text-white rounded-md hover:bg-primary-600 transition text-sm font-medium"
                    >
                      Mở
                    </button>
                    {/* Export buttons */}
                    {story.total_downloaded > 0 && (
                      <>
                        <a
                          href={`/api/v1/export/${story.id}/word`}
                          download
                          className="px-3 py-2 bg-primary-500 text-white rounded-md hover:bg-primary-600 transition text-sm font-medium"
                          title="Export Word"
                        >
                          Word
                        </a>
                        <a
                          href={`/api/v1/export/${story.id}/txt`}
                          download
                          className="px-3 py-2 bg-gray-500 dark:bg-gray-600 text-white rounded-md hover:bg-gray-600 transition text-sm font-medium"
                          title="Export TXT"
                        >
                          TXT
                        </a>
                      </>
                    )}
                    <button
                      onClick={() => handleDeleteStory(story)}
                      className="px-4 py-2 bg-red-500 text-white rounded-md hover:bg-red-600 transition text-sm font-medium"
                    >
                      Xóa
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Pagination */}
        {paginationMeta.total_pages > 1 && (
          <div className="mt-6 flex items-center justify-between border-t pt-6">
            <div className="text-sm text-dim">
              Hiển thị {(currentPage - 1) * paginationMeta.page_size + 1} - {Math.min(currentPage * paginationMeta.page_size, paginationMeta.total)} trong tổng {paginationMeta.total} truyện
            </div>

            <div className="flex items-center gap-2">
              {/* First page */}
              <button
                onClick={() => handlePageChange(1)}
                disabled={currentPage === 1}
                className="px-3 py-2 rounded-md border disabled:opacity-50 disabled:cursor-not-allowed hover:bg-surface-2"
              >
                ««
              </button>

              {/* Previous page */}
              <button
                onClick={() => handlePageChange(currentPage - 1)}
                disabled={currentPage === 1}
                className="px-3 py-2 rounded-md border disabled:opacity-50 disabled:cursor-not-allowed hover:bg-surface-2"
              >
                «
              </button>

              {/* Page numbers */}
              <div className="flex items-center gap-1">
                {Array.from({ length: Math.min(5, paginationMeta.total_pages) }, (_, i) => {
                  let pageNum: number

                  if (paginationMeta.total_pages <= 5) {
                    pageNum = i + 1
                  } else if (currentPage <= 3) {
                    pageNum = i + 1
                  } else if (currentPage >= paginationMeta.total_pages - 2) {
                    pageNum = paginationMeta.total_pages - 4 + i
                  } else {
                    pageNum = currentPage - 2 + i
                  }

                  return (
                    <button
                      key={pageNum}
                      onClick={() => handlePageChange(pageNum)}
                      className={`px-4 py-2 rounded-md border ${
                        currentPage === pageNum
                          ? 'bg-primary-500 text-white border-primary-500'
                          : 'hover:bg-surface-2'
                      }`}
                    >
                      {pageNum}
                    </button>
                  )
                })}
              </div>

              {/* Next page */}
              <button
                onClick={() => handlePageChange(currentPage + 1)}
                disabled={currentPage === paginationMeta.total_pages}
                className="px-3 py-2 rounded-md border disabled:opacity-50 disabled:cursor-not-allowed hover:bg-surface-2"
              >
                »
              </button>

              {/* Last page */}
              <button
                onClick={() => handlePageChange(paginationMeta.total_pages)}
                disabled={currentPage === paginationMeta.total_pages}
                className="px-3 py-2 rounded-md border disabled:opacity-50 disabled:cursor-not-allowed hover:bg-surface-2"
              >
                »»
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Delete Confirmation Dialog */}
      {deleteDialog.isOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-surface rounded-lg max-w-md w-full p-6">
            <h3 className="text-xl font-semibold mb-4">Xác nhận xóa</h3>

            <p className="text-dim mb-4">
              Bạn có chắc chắn muốn xóa truyện:
              <span className="block mt-2 font-medium text-strong">
                "{deleteDialog.story?.title}"
              </span>
            </p>

            <p className="text-sm text-red-600 dark:text-red-400 mb-6">
              Hành động này sẽ xóa tất cả chapters, audio files và không thể hoàn tác.
            </p>

            <div className="flex justify-end gap-3">
              <button
                onClick={() => setDeleteDialog({ isOpen: false, story: null })}
                disabled={deleting}
                className="px-4 py-2 text-dim hover:text-strong transition"
              >
                Hủy
              </button>
              <button
                onClick={handleConfirmDelete}
                disabled={deleting}
                className="px-6 py-2 bg-red-500 text-white rounded-md hover:bg-red-600 transition disabled:bg-gray-400"
              >
                {deleting ? 'Đang xóa...' : 'Xóa'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
