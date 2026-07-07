import { useState, useEffect } from 'react'
import axios from 'axios'

interface BannedWord {
  id: string
  banned_word: string
  replacement_word: string
  description?: string
  is_active: boolean
  created_at: string
  updated_at: string
}

interface PaginationMeta {
  total: number
  page: number
  page_size: number
  total_pages: number
}

interface PaginatedResponse {
  data: BannedWord[]
  meta: PaginationMeta
}

interface FormData {
  banned_word: string
  replacement_word: string
  description: string
  is_active: boolean
}

interface DeleteDialogState {
  isOpen: boolean
  word: BannedWord | null
}

export default function BannedWordsPage() {
  const [bannedWords, setBannedWords] = useState<BannedWord[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [currentPage, setCurrentPage] = useState(1)
  const [paginationMeta, setPaginationMeta] = useState<PaginationMeta>({
    total: 0,
    page: 1,
    page_size: 30,
    total_pages: 0
  })
  const [formData, setFormData] = useState<FormData>({
    banned_word: '',
    replacement_word: '',
    description: '',
    is_active: true
  })
  const [deleteDialog, setDeleteDialog] = useState<DeleteDialogState>({
    isOpen: false,
    word: null
  })

  useEffect(() => {
    fetchBannedWords(currentPage)
  }, [currentPage, searchTerm, statusFilter])

  const fetchBannedWords = async (page: number = 1) => {
    try {
      let url = `/api/v1/banned-words/?page=${page}&page_size=30`

      if (searchTerm) {
        url += `&search=${encodeURIComponent(searchTerm)}`
      }

      if (statusFilter !== 'all') {
        url += `&is_active=${statusFilter === 'active'}`
      }

      const response = await axios.get<PaginatedResponse>(url)
      setBannedWords(response.data.data)
      setPaginationMeta(response.data.meta)
    } catch (error) {
      console.error('Error fetching banned words:', error)
      setError('Failed to load banned words')
    }
  }

  const handleSearchChange = (value: string) => {
    setSearchTerm(value)
    setCurrentPage(1) // Reset to page 1 when searching
  }

  const handleStatusFilterChange = (value: string) => {
    setStatusFilter(value)
    setCurrentPage(1) // Reset to page 1 when filtering
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)

    try {
      if (editingId) {
        // Update existing banned word
        await axios.put(`/api/v1/banned-words/${editingId}`, formData)
      } else {
        // Create new banned word
        await axios.post('/api/v1/banned-words/', formData)
      }

      // Reset form and refresh list
      setFormData({
        banned_word: '',
        replacement_word: '',
        description: '',
        is_active: true
      })
      setShowForm(false)
      setEditingId(null)
      await fetchBannedWords(currentPage)
    } catch (error: any) {
      console.error('Error saving banned word:', error)
      setError(error.response?.data?.detail || 'Failed to save banned word')
    } finally {
      setLoading(false)
    }
  }

  const handleEdit = (word: BannedWord) => {
    setFormData({
      banned_word: word.banned_word,
      replacement_word: word.replacement_word,
      description: word.description || '',
      is_active: word.is_active
    })
    setEditingId(word.id)
    setShowForm(true)
  }

  const handleDelete = (word: BannedWord) => {
    setDeleteDialog({
      isOpen: true,
      word: word
    })
  }

  const handleConfirmDelete = async () => {
    if (!deleteDialog.word) return

    setLoading(true)
    setError(null)
    try {
      await axios.delete(`/api/v1/banned-words/${deleteDialog.word.id}`)

      // Reload banned words - go to previous page if current page would be empty
      if (bannedWords.length === 1 && currentPage > 1) {
        setCurrentPage(currentPage - 1)
      } else {
        await fetchBannedWords(currentPage)
      }

      // Close dialog
      setDeleteDialog({
        isOpen: false,
        word: null
      })
    } catch (error: any) {
      console.error('Error deleting banned word:', error)
      setError(error.response?.data?.detail || 'Failed to delete banned word')
    } finally {
      setLoading(false)
    }
  }

  const handlePageChange = (newPage: number) => {
    if (newPage >= 1 && newPage <= paginationMeta.total_pages) {
      setCurrentPage(newPage)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }

  const handleCancel = () => {
    setFormData({
      banned_word: '',
      replacement_word: '',
      description: '',
      is_active: true
    })
    setShowForm(false)
    setEditingId(null)
    setError(null)
  }

  return (
    <div className="max-w-6xl mx-auto p-6">
      <div className="bg-surface rounded-lg shadow-sm p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-strong">Quản lý từ kiểm duyệt</h1>
            <p className="text-sm text-dim mt-1">
              Quản lý danh sách các từ bị cấm và từ thay thế
            </p>
          </div>
          {!showForm && (
            <button
              onClick={() => setShowForm(true)}
              className="px-4 py-2 bg-primary-500 text-white rounded-md hover:bg-primary-600 transition"
            >
              + Thêm từ mới
            </button>
          )}
        </div>

        {/* Error message */}
        {error && (
          <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-md">
            <p className="text-sm text-red-800">{error}</p>
          </div>
        )}

        {/* Search and Filter */}
        <div className="mb-6 space-y-3">
          <div className="flex gap-4">
            {/* Search input */}
            <div className="flex-1">
              <input
                type="text"
                placeholder="Tìm kiếm theo từ cấm, từ thay thế, mô tả..."
                value={searchTerm}
                onChange={(e) => handleSearchChange(e.target.value)}
                className="w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
            </div>

            {/* Status filter */}
            <div className="w-48">
              <select
                value={statusFilter}
                onChange={(e) => handleStatusFilterChange(e.target.value)}
                className="w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
              >
                <option value="all">Tất cả trạng thái</option>
                <option value="active">Đang hoạt động</option>
                <option value="inactive">Đã tắt</option>
              </select>
            </div>
          </div>

          {/* Filter info */}
          {(searchTerm || statusFilter !== 'all') && (
            <div className="flex items-center gap-2 text-sm text-dim">
              <span>Đang lọc:</span>
              {searchTerm && (
                <span className="inline-flex items-center gap-1 px-2 py-1 bg-primary-100 text-primary-800 rounded">
                  Từ khóa: "{searchTerm}"
                  <button
                    onClick={() => handleSearchChange('')}
                    className="hover:text-primary-900"
                  >
                    ×
                  </button>
                </span>
              )}
              {statusFilter !== 'all' && (
                <span className="inline-flex items-center gap-1 px-2 py-1 bg-green-100 text-green-800 rounded">
                  {statusFilter === 'active' ? 'Đang hoạt động' : 'Đã tắt'}
                  <button
                    onClick={() => handleStatusFilterChange('all')}
                    className="hover:text-green-900"
                  >
                    ×
                  </button>
                </span>
              )}
              <span className="text-dim">
                ({paginationMeta.total} kết quả)
              </span>
            </div>
          )}
        </div>

        {/* Form */}
        {showForm && (
          <div className="mb-6 p-4 bg-primary-50 border border-primary-200 rounded-lg">
            <h3 className="text-lg font-semibold mb-4">
              {editingId ? 'Chỉnh sửa từ kiểm duyệt' : 'Thêm từ kiểm duyệt mới'}
            </h3>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-dim mb-1">
                    Từ bị cấm <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={formData.banned_word}
                    onChange={(e) => setFormData({ ...formData, banned_word: e.target.value })}
                    className="w-full px-3 py-2 border border-token rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                    placeholder="Nhập từ bị cấm..."
                    required
                    disabled={loading}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-dim mb-1">
                    Từ thay thế <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={formData.replacement_word}
                    onChange={(e) => setFormData({ ...formData, replacement_word: e.target.value })}
                    className="w-full px-3 py-2 border border-token rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                    placeholder="Nhập từ thay thế..."
                    required
                    disabled={loading}
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-dim mb-1">
                  Mô tả
                </label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="w-full px-3 py-2 border border-token rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                  placeholder="Nhập mô tả (tùy chọn)..."
                  rows={2}
                  disabled={loading}
                />
              </div>
              <div className="flex items-center">
                <input
                  type="checkbox"
                  id="is_active"
                  checked={formData.is_active}
                  onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                  className="w-4 h-4 text-primary-600 rounded focus:ring-primary-500"
                  disabled={loading}
                />
                <label htmlFor="is_active" className="ml-2 text-sm text-dim">
                  Kích hoạt
                </label>
              </div>
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={loading}
                  className="px-4 py-2 bg-primary-500 text-white rounded-md hover:bg-primary-600 transition disabled:bg-gray-400"
                >
                  {loading ? 'Đang lưu...' : (editingId ? 'Cập nhật' : 'Thêm mới')}
                </button>
                <button
                  type="button"
                  onClick={handleCancel}
                  disabled={loading}
                  className="px-4 py-2 bg-gray-300 text-dim rounded-md hover:bg-gray-400 transition"
                >
                  Hủy
                </button>
              </div>
            </form>
          </div>
        )}

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-surface-2 border-b">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-dim uppercase tracking-wider">
                  Từ bị cấm
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-dim uppercase tracking-wider">
                  Từ thay thế
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-dim uppercase tracking-wider">
                  Mô tả
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-dim uppercase tracking-wider">
                  Trạng thái
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-dim uppercase tracking-wider">
                  Thao tác
                </th>
              </tr>
            </thead>
            <tbody className="bg-surface divide-y divide-gray-200">
              {bannedWords.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-dim">
                    Chưa có từ kiểm duyệt nào
                  </td>
                </tr>
              ) : (
                bannedWords.map((word) => (
                  <tr key={word.id} className="hover:bg-surface-2">
                    <td className="px-4 py-3">
                      <span className="font-mono bg-red-100 text-red-800 px-2 py-1 rounded text-sm">
                        {word.banned_word}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="font-mono bg-green-100 text-green-800 px-2 py-1 rounded text-sm">
                        {word.replacement_word}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-dim">
                      {word.description || '-'}
                    </td>
                    <td className="px-4 py-3">
                      {word.is_active ? (
                        <span className="inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-green-100 text-green-800">
                          Hoạt động
                        </span>
                      ) : (
                        <span className="inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-surface-3 text-strong">
                          Tắt
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => handleEdit(word)}
                        className="text-primary-600 hover:text-primary-800 mr-3"
                        title="Chỉnh sửa"
                      >
                        <svg className="w-5 h-5 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                        </svg>
                      </button>
                      <button
                        onClick={() => handleDelete(word)}
                        className="text-red-600 hover:text-red-800"
                        title="Xóa"
                      >
                        <svg className="w-5 h-5 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Footer info */}
        <div className="mt-4 text-sm text-dim">
          Tổng số: <span className="font-semibold">{paginationMeta.total}</span> từ kiểm duyệt
          {' | '}
          Đang hoạt động (trang này): <span className="font-semibold">{bannedWords.filter(w => w.is_active).length}</span>
        </div>

        {/* Pagination */}
        {paginationMeta.total_pages > 1 && (
          <div className="mt-6 flex items-center justify-between border-t pt-6">
            <div className="text-sm text-dim">
              Hiển thị {(currentPage - 1) * paginationMeta.page_size + 1} - {Math.min(currentPage * paginationMeta.page_size, paginationMeta.total)} trong tổng {paginationMeta.total} từ
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
          <div className="bg-surface rounded-lg max-w-md w-full shadow-2xl transform transition-all">
            <div className="p-6">
              {/* Icon */}
              <div className="flex items-center justify-center w-12 h-12 mx-auto mb-4 bg-red-100 rounded-full">
                <svg className="w-6 h-6 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>

              {/* Title */}
              <h3 className="text-xl font-bold text-center text-strong mb-2">
                Xác nhận xóa
              </h3>

              {/* Content */}
              <div className="text-center mb-6">
                <p className="text-dim mb-4">
                  Bạn có chắc chắn muốn xóa từ kiểm duyệt này không?
                </p>

                {deleteDialog.word && (
                  <div className="bg-surface-2 border border-token rounded-lg p-4 mb-2">
                    <div className="grid grid-cols-2 gap-3 text-sm">
                      <div className="text-left">
                        <span className="text-dim block mb-1">Từ bị cấm:</span>
                        <span className="font-mono bg-red-100 text-red-800 px-2 py-1 rounded inline-block">
                          {deleteDialog.word.banned_word}
                        </span>
                      </div>
                      <div className="text-left">
                        <span className="text-dim block mb-1">Từ thay thế:</span>
                        <span className="font-mono bg-green-100 text-green-800 px-2 py-1 rounded inline-block">
                          {deleteDialog.word.replacement_word}
                        </span>
                      </div>
                    </div>
                    {deleteDialog.word.description && (
                      <div className="mt-3 text-left">
                        <span className="text-dim text-xs block mb-1">Mô tả:</span>
                        <span className="text-dim text-sm">{deleteDialog.word.description}</span>
                      </div>
                    )}
                  </div>
                )}

                <p className="text-sm text-red-600 font-medium">
                   Hành động này không thể hoàn tác!
                </p>
              </div>

              {/* Error message */}
              {error && (
                <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md">
                  <p className="text-sm text-red-800">{error}</p>
                </div>
              )}

              {/* Actions */}
              <div className="flex gap-3">
                <button
                  onClick={() => setDeleteDialog({ isOpen: false, word: null })}
                  className="flex-1 px-4 py-2.5 text-dim bg-surface-3 rounded-lg hover:bg-gray-200 transition font-medium"
                  disabled={loading}
                >
                  Hủy bỏ
                </button>
                <button
                  onClick={handleConfirmDelete}
                  className="flex-1 px-4 py-2.5 bg-red-600 text-white rounded-lg hover:bg-red-700 transition font-medium disabled:bg-gray-400 disabled:cursor-not-allowed"
                  disabled={loading}
                >
                  {loading ? (
                    <span className="flex items-center justify-center gap-2">
                      <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                      </svg>
                      Đang xóa...
                    </span>
                  ) : (
                    'Xóa ngay'
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
