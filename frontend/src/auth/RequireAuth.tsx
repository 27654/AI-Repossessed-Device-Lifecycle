import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import ForbiddenPage from '../pages/ForbiddenPage'
import { useAuth } from './useAuth'

interface RequireAuthProps {
  children: ReactNode
  // Permission code the route needs. UI convenience only: the API enforces it again.
  permission?: string
}

export default function RequireAuth({ children, permission }: RequireAuthProps) {
  const { status, hasPermission } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">Loading…</div>
  }
  if (status === 'anonymous') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (permission && !hasPermission(permission)) {
    return <ForbiddenPage />
  }
  return children
}
