import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'

interface HeaderProps {
  onMenuClick: () => void
}

export default function Header({ onMenuClick }: HeaderProps) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [signingOut, setSigningOut] = useState(false)

  async function handleLogout() {
    setSigningOut(true)
    try {
      await logout()
      navigate('/login', { replace: true })
    } finally {
      setSigningOut(false)
    }
  }

  return (
    <header className="flex h-16 items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 md:px-6">
      <div className="flex min-w-0 items-center gap-3">
        <button
          type="button"
          onClick={onMenuClick}
          className="rounded-md p-2 text-slate-600 hover:bg-slate-100 md:hidden"
          aria-label="Open navigation"
        >
          ☰
        </button>
        <h1 className="truncate text-base font-semibold text-slate-900">AI-Enhanced Repossessed Device Lifecycle</h1>
      </div>
      {user && (
        <div className="flex shrink-0 items-center gap-3">
          <Link to="/account" className="hidden text-right leading-tight hover:underline sm:block">
            <span className="block text-sm font-medium text-slate-900">{user.full_name}</span>
            <span className="block text-xs text-slate-500">{user.role?.name ?? 'No role'}</span>
          </Link>
          <button
            type="button"
            onClick={handleLogout}
            disabled={signingOut}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          >
            Sign out
          </button>
        </div>
      )}
    </header>
  )
}
