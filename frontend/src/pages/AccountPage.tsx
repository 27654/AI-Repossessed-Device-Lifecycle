import { QRCodeSVG } from 'qrcode.react'
import { useState, type FormEvent } from 'react'
import { useAuth } from '../auth/useAuth'
import { inputClass, primaryButtonClass, secondaryButtonClass } from '../components/form'
import { authApi, errorMessage, type MfaSetup } from '../lib/api'

function Feedback({ error, success }: { error: string | null; success: string | null }) {
  if (error) return <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>
  if (success) return <p className="rounded-md bg-green-50 p-3 text-sm text-green-800">{success}</p>
  return null
}

function ChangePasswordSection() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSuccess(null)
    if (next !== confirm) {
      setError('The new passwords do not match.')
      return
    }
    setSubmitting(true)
    try {
      await authApi.changePassword(current, next)
      setSuccess('Password changed. Other signed-in sessions have been ended.')
      setCurrent('')
      setNext('')
      setConfirm('')
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <h3 className="mb-3 font-medium">Change password</h3>
      <form className="max-w-sm space-y-3" onSubmit={handleSubmit}>
        <Feedback error={error} success={success} />
        <label className="block text-sm">
          <span className="text-slate-600">Current password</span>
          <input type="password" required autoComplete="current-password" value={current}
            onChange={(e) => setCurrent(e.target.value)} className={inputClass} />
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">New password</span>
          <input type="password" required minLength={10} autoComplete="new-password" value={next}
            onChange={(e) => setNext(e.target.value)} className={inputClass} />
          <span className="mt-1 block text-xs text-slate-500">At least 10 characters, not common or all numbers.</span>
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">Confirm new password</span>
          <input type="password" required autoComplete="new-password" value={confirm}
            onChange={(e) => setConfirm(e.target.value)} className={inputClass} />
        </label>
        <button type="submit" disabled={submitting} className={primaryButtonClass}>
          {submitting ? 'Saving…' : 'Change password'}
        </button>
      </form>
    </section>
  )
}

function MfaSection() {
  const { user, setUser } = useAuth()
  const [setup, setSetup] = useState<MfaSetup | null>(null)
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(action: () => Promise<void>) {
    setError(null)
    setSuccess(null)
    setBusy(true)
    try {
      await action()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const startSetup = () => run(async () => setSetup(await authApi.setupMfa()))

  const confirmSetup = (e: FormEvent) => {
    e.preventDefault()
    return run(async () => {
      setUser(await authApi.confirmMfa(code))
      setSetup(null)
      setCode('')
      setSuccess('Two-step verification is on. You will be asked for a code each time you sign in.')
    })
  }

  const disable = (e: FormEvent) => {
    e.preventDefault()
    return run(async () => {
      setUser(await authApi.disableMfa(password, code))
      setPassword('')
      setCode('')
      setSuccess('Two-step verification is off.')
    })
  }

  const codeInput = (
    <label className="block text-sm">
      <span className="text-slate-600">6-digit code</span>
      <input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required value={code}
        onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} className={inputClass} />
    </label>
  )

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <h3 className="mb-1 font-medium">Two-step verification (authenticator app)</h3>
      <p className="mb-3 text-sm text-slate-600">
        Status:{' '}
        <span className={user?.mfa_enabled ? 'font-medium text-green-700' : 'font-medium text-slate-700'}>
          {user?.mfa_enabled ? 'On' : 'Off'}
        </span>
      </p>
      <div className="max-w-sm space-y-3">
        <Feedback error={error} success={success} />

        {!user?.mfa_enabled && !setup && (
          <button type="button" onClick={startSetup} disabled={busy} className={primaryButtonClass}>
            Set up two-step verification
          </button>
        )}

        {!user?.mfa_enabled && setup && (
          <form className="space-y-3" onSubmit={confirmSetup}>
            <p className="text-sm text-slate-600">
              Scan this QR code with an authenticator app (Google Authenticator, Microsoft Authenticator, Authy…),
              then enter the code it shows.
            </p>
            <div className="inline-block rounded-md border border-slate-200 bg-white p-3">
              <QRCodeSVG value={setup.otpauth_uri} size={176} />
            </div>
            <p className="text-xs text-slate-500">
              Can't scan? Enter this key manually:{' '}
              <code className="break-all rounded bg-slate-100 px-1 py-0.5 text-slate-800">{setup.secret}</code>
            </p>
            {codeInput}
            <div className="flex gap-2">
              <button type="submit" disabled={busy || code.length !== 6} className={primaryButtonClass}>
                Turn on
              </button>
              <button type="button" onClick={() => setSetup(null)} className={secondaryButtonClass}>
                Cancel
              </button>
            </div>
          </form>
        )}

        {user?.mfa_enabled && (
          <form className="space-y-3" onSubmit={disable}>
            <p className="text-sm text-slate-600">To turn it off, confirm your password and a current code.</p>
            <label className="block text-sm">
              <span className="text-slate-600">Password</span>
              <input type="password" required autoComplete="current-password" value={password}
                onChange={(e) => setPassword(e.target.value)} className={inputClass} />
            </label>
            {codeInput}
            <button type="submit" disabled={busy || code.length !== 6} className={secondaryButtonClass}>
              Turn off
            </button>
          </form>
        )}
      </div>
    </section>
  )
}

export default function AccountPage() {
  const { user } = useAuth()
  if (!user) return null

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">My account</h2>
      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <dl className="grid max-w-md grid-cols-[max-content_1fr] gap-x-6 gap-y-1 text-sm">
          <dt className="text-slate-500">Name</dt>
          <dd>{user.full_name}</dd>
          <dt className="text-slate-500">Email</dt>
          <dd className="break-all">{user.email}</dd>
          <dt className="text-slate-500">Employee ID</dt>
          <dd>{user.employee_id}</dd>
          <dt className="text-slate-500">Phone</dt>
          <dd>{user.phone || '—'}</dd>
          <dt className="text-slate-500">Role</dt>
          <dd>{user.role?.name ?? 'No role assigned'}</dd>
        </dl>
      </section>
      <ChangePasswordSection />
      <MfaSection />
    </div>
  )
}
