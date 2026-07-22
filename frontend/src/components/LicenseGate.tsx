import { useCallback, useEffect, useState, type ReactNode } from 'react'
import axios from 'axios'
import { Loader2 } from 'lucide-react'
import ActivationPage from '../pages/ActivationPage'

interface LicenseStatus {
  activated: boolean
  enforced: boolean
  device_id?: string
}

/**
 * Wraps the whole app. On mount it asks the backend whether this machine is
 * activated. Until the answer arrives, a spinner is shown. If enforcement is
 * on and the machine is NOT activated, the activation screen replaces the app;
 * otherwise the app renders normally.
 */
export default function LicenseGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<LicenseStatus | null>(null)
  const [failed, setFailed] = useState(false)

  const check = useCallback(async () => {
    setFailed(false)
    try {
      const { data } = await axios.get('/api/v1/license/status')
      setStatus(data)
    } catch {
      // Backend unreachable — fail open would defeat the gate, so show a retry.
      setStatus(null)
      setFailed(true)
    }
  }, [])

  useEffect(() => { check() }, [check])

  if (failed) {
    return (
      <div className="min-h-screen grid place-items-center p-6 text-center">
        <div>
          <p className="text-dim mb-4">Không kết nối được với dịch vụ. Vui lòng thử lại.</p>
          <button onClick={check} className="btn-primary">Thử lại</button>
        </div>
      </div>
    )
  }

  if (!status) {
    return (
      <div className="min-h-screen grid place-items-center">
        <Loader2 size={28} className="animate-spin text-faint" />
      </div>
    )
  }

  // Not enforced (dev), or already activated -> run the app.
  if (!status.enforced || status.activated) {
    return <>{children}</>
  }

  return <ActivationPage deviceId={status.device_id} onActivated={check} />
}
