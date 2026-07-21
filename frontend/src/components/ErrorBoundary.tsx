import { Component, ErrorInfo, ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  message: string
}

/**
 * App-wide error boundary. Without this, a single render that throws (e.g. an
 * API returning an unexpected object where a string is expected) unmounts the
 * whole React tree and leaves a blank white screen. Here we catch it and show a
 * recoverable fallback instead.
 */
class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: '' }

  static getDerivedStateFromError(error: unknown): State {
    const message = error instanceof Error ? error.message : String(error)
    return { hasError: true, message }
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error('Unhandled UI error:', error, info)
  }

  handleReset = () => {
    this.setState({ hasError: false, message: '' })
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div className="min-h-[60vh] flex items-center justify-center p-6">
        <div className="max-w-md w-full text-center space-y-4">
          <div className="text-4xl">⚠️</div>
          <h1 className="text-lg font-semibold text-slate-800">
            Đã xảy ra lỗi hiển thị
          </h1>
          <p className="text-sm text-slate-500 break-words">
            {this.state.message || 'Lỗi không xác định.'}
          </p>
          <div className="flex gap-2 justify-center">
            <button
              onClick={this.handleReset}
              className="px-4 py-2 rounded-lg bg-amber-500 text-white text-sm font-medium hover:bg-amber-600"
            >
              Thử lại
            </button>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 rounded-lg border border-slate-300 text-slate-700 text-sm font-medium hover:bg-slate-50"
            >
              Tải lại trang
            </button>
          </div>
        </div>
      </div>
    )
  }
}

export default ErrorBoundary
