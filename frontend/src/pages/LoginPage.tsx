import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'
import AuthCard from '../components/AuthCard'
import { inputClass, primaryButtonClass } from '../components/form'
import { authApi, errorMessage } from '../lib/api'

interface LoginLocationState {
  from?: string
  message?: string
}

export default function LoginPage() {
  const { status, sessionExpired, setUser } = useAuth()
  const navigate = useNavigate()
  const state = (useLocation().state ?? {}) as LoginLocationState
  const from = state.from && state.from !== '/login' ? state.from : '/dashboard'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (status === 'authenticated') return <Navigate to={from} replace />

  const notice = state.message ?? (sessionExpired ? 'Your session has ended. Please sign in again.' : null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const result = await authApi.login(email, password)
      if (result.mfa_required) {
        navigate('/login/mfa', { state: { from } })
      } else {
        setUser(result.user)
        navigate(from, { replace: true })
      }
    } catch (err) {
      setError(errorMessage(err))
      setPassword('')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthCard title="Staff sign in">
      <form className="space-y-4" onSubmit={handleSubmit}>
        {notice && !error && <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-800">{notice}</p>}
        {error && (
          <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
            {error}
          </p>
        )}
        <label className="block text-sm">
          <span className="text-slate-600">Email</span>
          <input
            type="email"
            required
            autoComplete="username"
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">Password</span>
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputClass}
          />
        </label>
        <button type="submit" disabled={submitting} className={`w-full ${primaryButtonClass}`}>
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="text-center text-xs text-slate-500">
          Accounts are created by your system administrator.
        </p>
      </form>
    </AuthCard>
  )
}
