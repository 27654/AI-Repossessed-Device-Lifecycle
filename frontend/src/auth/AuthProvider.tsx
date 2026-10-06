import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ApiError, authApi, UNAUTHORIZED_EVENT, type CurrentUser } from '../lib/api'
import { AuthContext, type AuthContextValue, type AuthStatus } from './context'

// Holds the signed-in user. The server session is the source of truth: on load
// the provider asks /auth/me/, and any 401 later signs the UI out.
export default function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [user, setUserState] = useState<CurrentUser | null>(null)
  const [sessionExpired, setSessionExpired] = useState(false)

  useEffect(() => {
    let cancelled = false
    authApi
      .csrf()
      .then(() => authApi.me())
      .then((me) => {
        if (cancelled) return
        setUserState(me)
        setStatus('authenticated')
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (!(err instanceof ApiError && err.status === 401)) console.error('Could not load the current user', err)
        setStatus('anonymous')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const signedIn = user !== null
  useEffect(() => {
    const onUnauthorized = () => {
      if (signedIn) setSessionExpired(true)
      setUserState(null)
      setStatus('anonymous')
    }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [signedIn])

  const setUser = useCallback((next: CurrentUser) => {
    setUserState(next)
    setSessionExpired(false)
    setStatus('authenticated')
  }, [])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch (err) {
      // Already signed out on the server (e.g. expired session): nothing to undo.
      if (!(err instanceof ApiError && err.status === 401)) throw err
    }
    setUserState(null)
    setSessionExpired(false)
    setStatus('anonymous')
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      sessionExpired,
      setUser,
      logout,
      hasPermission: (code: string) => user?.permissions.includes(code) ?? false,
    }),
    [status, user, sessionExpired, setUser, logout],
  )

  return <AuthContext value={value}>{children}</AuthContext>
}
