// Native OS file/folder pickers, exposed by the desktop shell (PyWebView) as
// `window.pywebview.api`. When the app runs inside the packaged Windows app the
// real Windows Explorer dialog opens; in a plain browser (dev) these return
// `undefined` and callers fall back to the in-app HTML browser.

interface PywebviewApi {
  pick_folder: (start?: string) => Promise<string | null>
  pick_audio_file: (start?: string) => Promise<string | null>
  pick_image_file: (start?: string) => Promise<string | null>
}

declare global {
  interface Window {
    pywebview?: { api?: PywebviewApi }
  }
}

/** True only inside the packaged desktop app, where native dialogs exist. */
export function hasNativeDialogs(): boolean {
  return typeof window.pywebview?.api?.pick_folder === 'function'
}

async function call(
  fn: keyof PywebviewApi,
  start?: string,
): Promise<string | null> {
  const api = window.pywebview?.api
  if (!api || typeof api[fn] !== 'function') return null
  const result = await api[fn](start || '')
  return result || null
}

export const pickFolderNative = (start?: string) => call('pick_folder', start)
export const pickAudioFileNative = (start?: string) => call('pick_audio_file', start)
export const pickImageFileNative = (start?: string) => call('pick_image_file', start)
