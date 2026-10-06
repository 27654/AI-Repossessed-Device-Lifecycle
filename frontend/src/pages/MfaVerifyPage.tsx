import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'
import AuthCard from '../components/AuthCard'
import { inputClass, primaryButtonClass } from '../components/form'
import { ApiError, authApi, errorMessage } from '../lib/api'

// Second sign-in step. The server holds the pending login in the session;
// this page only collects the 6-digit code from the authenticator app.
export default function MfaVerifyPage() {
  const { status, setUser } = useAuth()
  const navigate = useNavigate()
  const from = ((useLocation().state ?? {}) as { from?: string }).from ?? '/dashboard'

  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (status === 'authenticated') return <Navigate to={from} replace />

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const { user } = await authApi.verifyMfa(code)
      setUser(user)
      navigate(from, { replace: true })
    } catch (err) {
      const reason = err instanceof ApiError ? (err.data as { code?: string } | null)?.code : undefined
      if (reason === 'mfa_not_pending' || reason === 'locked' || reason === 'inactive') {
        navigate('/login', { replace: true, state: { from, message: errorMessage(err) } })
        return
      }
      setError(errorMessage(err))
      setCode('')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthCard title="Verify it's you">
      <form className="space-y-4" onSubmit={handleSubmit}>
        <p className="text-sm text-slate-600">Enter the 6-digit code from your authenticator app.</p>
        {error && (
          <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
            {error}
          </p>
        )}
        <label className="block text-sm">
          <span className="text-slate-600">Verification code</span>
          <input
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]{6}"
            maxLength={6}
            required
            autoFocus
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
            className={`${inputClass} text-center text-lg tracking-[0.5em]`}
          />
        </label>
        <button type="submit" disabled={submitting || code.length !== 6} className={`w-full ${primaryButtonClass}`}>
          {submitting ? 'Verifying…' : 'Verify'}
        </button>
        <p className="text-center text-sm">
          <Link to="/login" className="text-slate-500 underline">
            Back to sign in
          </Link>
        </p>
      </form>
    </AuthCard>
  )
}
