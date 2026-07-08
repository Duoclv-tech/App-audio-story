import { useState, useEffect, useRef } from 'react'
import axios from 'axios'

interface Prompt {
  id: string
  title: string
  content: string
  category?: string
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
  data: Prompt[]
  meta: PaginationMeta
}

interface FormData {
  title: string
  content: string
  category: string
  description: string
  is_active: boolean
}

interface DeleteDialogState {
  isOpen: boolean
  prompt: Prompt | null
}

interface ActionMenuState {
  isOpen: boolean
  promptId: string | null
}

export default function PromptsPage() {
  const [prompts, setPrompts] = useState<Prompt[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [searchTerm, setSearchTerm] = useState('')
  const [categoryFilter, setCategoryFilter] = useState<string>('')
  const [currentPage, setCurrentPage] = useState(1)
  const [paginationMeta, setPaginationMeta] = useState<PaginationMeta>({
    total: 0,
    page: 1,
    page_size: 30,
    total_pages: 0
  })
  const [formData, setFormData] = useState<FormData>({
    title: '',
    content: '',
    category: '',
    description: '',
    is_active: true
  })
  const [deleteDialog, setDeleteDialog] = useState<DeleteDialogState>({
    isOpen: false,
    prompt: null
  })
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [actionMenu, setActionMenu] = useState<ActionMenuState>({
    isOpen: false,
    promptId: null
  })

  useEffect(() => {
    fetchPrompts(currentPage)
    fetchCategories()
  }, [currentPage, searchTerm, categoryFilter])

  // Close action menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (actionMenu.isOpen) {
        const target = e.target as HTMLElement
        if (!target.closest('.relative')) {
          setActionMenu({ isOpen: false, promptId: null })
        }
      }
    }
    document.addEventListener('click', handleClickOutside)
    return () => document.removeEventListener('click', handleClickOutside)
  }, [actionMenu.isOpen])

  const fetchCategories = async () => {
    try {
      const response = await axios.get<string[]>('/api/v1/prompts/categories')
      setCategories(response.data)
    } catch (error) {
      console.error('Error fetching categories:', error)
    }
  }

  const fetchPrompts = async (page: number = 1) => {
    try {
      let url = `/api/v1/prompts/?page=${page}&page_size=30`

      if (searchTerm) {
        url += `&search=${encodeURIComponent(searchTerm)}`
      }

      if (categoryFilter) {
        url += `&category=${encodeURIComponent(categoryFilter)}`
      }

      const response = await axios.get<PaginatedResponse>(url)
      setPrompts(response.data.data)
      setPaginationMeta(response.data.meta)
    } catch (error) {
      console.error('Error fetching prompts:', error)
      setError('Failed to load prompts')
    }
  }

  const handleSearchChange = (value: string) => {
    setSearchTerm(value)
    setCurrentPage(1)
  }

  const handleCategoryFilterChange = (value: string) => {
    setCategoryFilter(value)
    setCurrentPage(1)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)

    try {
      if (editingId) {
        await axios.put(`/api/v1/prompts/${editingId}`, formData)
      } else {
        await axios.post('/api/v1/prompts/', formData)
      }

      setFormData({
        title: '',
        content: '',
        category: '',
        description: '',
        is_active: true
      })
      setShowForm(false)
      setEditingId(null)
      await fetchPrompts(currentPage)
      await fetchCategories()
    } catch (error: any) {
      console.error('Error saving prompt:', error)
      setError(error.response?.data?.detail || 'Failed to save prompt')
    } finally {
      setLoading(false)
    }
  }

  const handleEdit = (prompt: Prompt) => {
    setFormData({
      title: prompt.title,
      content: prompt.content,
      category: prompt.category || '',
      description: prompt.description || '',
      is_active: prompt.is_active
    })
    setEditingId(prompt.id)
    setShowForm(true)
  }

  const handleDelete = (prompt: Prompt) => {
    setDeleteDialog({
      isOpen: true,
      prompt: prompt
    })
  }

  const handleConfirmDelete = async () => {
    if (!deleteDialog.prompt) return

    setLoading(true)
    setError(null)
    try {
      await axios.delete(`/api/v1/prompts/${deleteDialog.prompt.id}`)

      if (prompts.length === 1 && currentPage > 1) {
        setCurrentPage(currentPage - 1)
      } else {
        await fetchPrompts(currentPage)
      }
      await fetchCategories()

      setDeleteDialog({
        isOpen: false,
        prompt: null
      })
    } catch (error: any) {
      console.error('Error deleting prompt:', error)
      setError(error.response?.data?.detail || 'Failed to delete prompt')
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
      title: '',
      content: '',
      category: '',
      description: '',
      is_active: true
    })
    setShowForm(false)
    setEditingId(null)
    setError(null)
  }

  const handleCopyContent = async (prompt: Prompt) => {
    try {
      await navigator.clipboard.writeText(prompt.content)
      setCopiedId(prompt.id)
      setTimeout(() => setCopiedId(null), 2000)
      setActionMenu({ isOpen: false, promptId: null })
    } catch (error) {
      console.error('Failed to copy:', error)
    }
  }

  const toggleActionMenu = (promptId: string) => {
    if (actionMenu.isOpen && actionMenu.promptId === promptId) {
      setActionMenu({ isOpen: false, promptId: null })
    } else {
      setActionMenu({ isOpen: true, promptId })
    }
  }

  return (
    <div className="max-w-6xl mx-auto p-6">
      <div className="bg-surface rounded-lg shadow-sm p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-strong">Prompts</h1>
            <p className="text-sm text-dim mt-1">
              Quản lý danh sách các prompt
            </p>
          </div>
          {!showForm && (
            <button
              onClick={() => setShowForm(true)}
              className="px-4 py-2 bg-primary-500 text-white rounded-md hover:bg-primary-600 transition"
            >
              + Thêm prompt
            </button>
          )}
        </div>

        {/* Error message */}
        {error && (
          <div className="mb-4 p-4 bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 rounded-md">
            <p className="text-sm text-red-800 dark:text-red-300">{error}</p>
          </div>
        )}

        {/* Search and Filter */}
        <div className="mb-6 space-y-3">
          <div className="flex gap-4">
            <div className="flex-1">
              <input
                type="text"
                placeholder="Tìm kiếm theo tiêu đề, nội dung, mô tả..."
                value={searchTerm}
                onChange={(e) => handleSearchChange(e.target.value)}
                className="w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
            </div>

            <div className="w-48">
              <select
                value={categoryFilter}
                onChange={(e) => handleCategoryFilterChange(e.target.value)}
                className="w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
              >
                <option value="">Tất cả danh mục</option>
                {categories.map((cat) => (
                  <option key={cat} value={cat}>{cat}</option>
                ))}
              </select>
            </div>
          </div>

          {(searchTerm || categoryFilter) && (
            <div className="flex items-center gap-2 text-sm text-dim">
              <span>Đang lọc:</span>
              {searchTerm && (
                <span className="inline-flex items-center gap-1 px-2 py-1 bg-primary-100 dark:bg-primary-500/20 text-primary-800 dark:text-primary-300 rounded">
                  Từ khóa: "{searchTerm}"
                  <button
                    onClick={() => handleSearchChange('')}
                    className="hover:text-primary-900"
                  >
                    ×
                  </button>
                </span>
              )}
              {categoryFilter && (
                <span className="inline-flex items-center gap-1 px-2 py-1 bg-primary-100 dark:bg-primary-500/20 text-primary-800 dark:text-primary-300 rounded">
                  Danh mục: {categoryFilter}
                  <button
                    onClick={() => handleCategoryFilterChange('')}
                    className="hover:text-primary-900"
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
          <div className="mb-6 p-4 bg-primary-50 dark:bg-primary-500/10 border border-primary-200 dark:border-primary-500/30 rounded-lg">
            <h3 className="text-lg font-semibold mb-4">
              {editingId ? 'Chỉnh sửa prompt' : 'Thêm prompt mới'}
            </h3>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-dim mb-1">
                    Tiêu đề <span className="text-red-500 dark:text-red-400">*</span>
                  </label>
                  <input
                    type="text"
                    value={formData.title}
                    onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                    className="w-full px-3 py-2 border border-token rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                    placeholder="Nhập tiêu đề..."
                    required
                    disabled={loading}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-dim mb-1">
                    Danh mục
                  </label>
                  <input
                    type="text"
                    value={formData.category}
                    onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                    className="w-full px-3 py-2 border border-token rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                    placeholder="Nhập danh mục..."
                    list="category-list"
                    disabled={loading}
                  />
                  <datalist id="category-list">
                    {categories.map((cat) => (
                      <option key={cat} value={cat} />
                    ))}
                  </datalist>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-dim mb-1">
                  Nội dung <span className="text-red-500 dark:text-red-400">*</span>
                </label>
                <textarea
                  value={formData.content}
                  onChange={(e) => setFormData({ ...formData, content: e.target.value })}
                  className="w-full px-3 py-2 border border-token rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono text-sm"
                  placeholder="Nhập nội dung prompt..."
                  rows={6}
                  required
                  disabled={loading}
                />
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
                  className="w-4 h-4 text-primary-600 dark:text-primary-400 rounded focus:ring-primary-500"
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
                  className="px-4 py-2 bg-gray-300 dark:bg-gray-600 text-dim rounded-md hover:bg-gray-400 dark:hover:bg-gray-600 transition"
                >
                  Hủy
                </button>
              </div>
            </form>
          </div>
        )}

        {/* Prompts List */}
        <div className="space-y-4">
          {prompts.length === 0 ? (
            <div className="text-center py-8 text-dim">
              Chưa có prompt nào
            </div>
          ) : (
            prompts.map((prompt) => (
              <div key={prompt.id} className="border rounded-lg p-4 hover:bg-surface-2">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <h3 className="text-lg font-semibold text-strong">{prompt.title}</h3>
                      {prompt.category && (
                        <span className="px-2 py-0.5 text-xs bg-primary-100 dark:bg-primary-500/20 text-primary-800 dark:text-primary-300 rounded">
                          {prompt.category}
                        </span>
                      )}
                      {!prompt.is_active && (
                        <span className="px-2 py-0.5 text-xs bg-surface-3 text-dim rounded">
                          Đã tắt
                        </span>
                      )}
                    </div>
                    {prompt.description && (
                      <p className="text-sm text-dim mb-2">{prompt.description}</p>
                    )}
                    <div className="bg-surface-3 rounded p-3 font-mono text-sm text-dim whitespace-pre-wrap max-h-40 overflow-y-auto">
                      {prompt.content}
                    </div>
                  </div>
                  <div className="relative ml-2">
                    <button
                      onClick={() => toggleActionMenu(prompt.id)}
                      className="p-1.5 text-faint hover:bg-surface-3 hover:text-dim rounded transition"
                      title="Thao tác"
                    >
                      <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                        <circle cx="12" cy="5" r="2" />
                        <circle cx="12" cy="12" r="2" />
                        <circle cx="12" cy="19" r="2" />
                      </svg>
                    </button>
                    {actionMenu.isOpen && actionMenu.promptId === prompt.id && (
                      <div className="absolute right-0 top-8 bg-surface border rounded-lg shadow-lg py-1 z-10 min-w-[140px]">
                        <button
                          onClick={() => handleCopyContent(prompt)}
                          className="w-full px-4 py-2 text-left text-sm hover:bg-surface-2 flex items-center gap-2 text-dim"
                        >
                          {copiedId === prompt.id ? (
                            <>
                              <svg className="w-4 h-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                              </svg>
                              <span className="text-green-600 dark:text-green-400">Đã copy!</span>
                            </>
                          ) : (
                            <>
                              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                  d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                              </svg>
                              Copy
                            </>
                          )}
                        </button>
                        <button
                          onClick={() => {
                            handleEdit(prompt)
                            setActionMenu({ isOpen: false, promptId: null })
                          }}
                          className="w-full px-4 py-2 text-left text-sm hover:bg-surface-2 flex items-center gap-2 text-primary-600 dark:text-primary-400"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                              d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                          </svg>
                          Chỉnh sửa
                        </button>
                        <button
                          onClick={() => {
                            handleDelete(prompt)
                            setActionMenu({ isOpen: false, promptId: null })
                          }}
                          className="w-full px-4 py-2 text-left text-sm hover:bg-surface-2 flex items-center gap-2 text-red-600 dark:text-red-400"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                              d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                          Xóa
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Footer info */}
        <div className="mt-4 text-sm text-dim">
          Tổng số: <span className="font-semibold">{paginationMeta.total}</span> prompt
        </div>

        {/* Pagination */}
        {paginationMeta.total_pages > 1 && (
          <div className="mt-6 flex items-center justify-between border-t pt-6">
            <div className="text-sm text-dim">
              Hiển thị {(currentPage - 1) * paginationMeta.page_size + 1} - {Math.min(currentPage * paginationMeta.page_size, paginationMeta.total)} trong tổng {paginationMeta.total} prompt
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => handlePageChange(1)}
                disabled={currentPage === 1}
                className="px-3 py-2 rounded-md border disabled:opacity-50 disabled:cursor-not-allowed hover:bg-surface-2"
              >
                ««
              </button>

              <button
                onClick={() => handlePageChange(currentPage - 1)}
                disabled={currentPage === 1}
                className="px-3 py-2 rounded-md border disabled:opacity-50 disabled:cursor-not-allowed hover:bg-surface-2"
              >
                «
              </button>

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

              <button
                onClick={() => handlePageChange(currentPage + 1)}
                disabled={currentPage === paginationMeta.total_pages}
                className="px-3 py-2 rounded-md border disabled:opacity-50 disabled:cursor-not-allowed hover:bg-surface-2"
              >
                »
              </button>

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
              <div className="flex items-center justify-center w-12 h-12 mx-auto mb-4 bg-red-100 dark:bg-red-500/20 rounded-full">
                <svg className="w-6 h-6 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>

              <h3 className="text-xl font-bold text-center text-strong mb-2">
                Xác nhận xóa
              </h3>

              <div className="text-center mb-6">
                <p className="text-dim mb-4">
                  Bạn có chắc chắn muốn xóa prompt này không?
                </p>

                {deleteDialog.prompt && (
                  <div className="bg-surface-2 border border-token rounded-lg p-4 mb-2">
                    <div className="text-left">
                      <span className="text-dim block mb-1">Tiêu đề:</span>
                      <span className="font-semibold text-strong">
                        {deleteDialog.prompt.title}
                      </span>
                    </div>
                  </div>
                )}

                <p className="text-sm text-red-600 dark:text-red-400 font-medium">
                  Hành động này không thể hoàn tác!
                </p>
              </div>

              {error && (
                <div className="mb-4 p-3 bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 rounded-md">
                  <p className="text-sm text-red-800 dark:text-red-300">{error}</p>
                </div>
              )}

              <div className="flex gap-3">
                <button
                  onClick={() => setDeleteDialog({ isOpen: false, prompt: null })}
                  className="flex-1 px-4 py-2.5 text-dim bg-surface-3 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition font-medium"
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
