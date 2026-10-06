import { createContext } from 'react'
import type { CurrentUser } from '../lib/api'

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

export interface AuthContextValue {
  status: AuthStatus
  user: CurrentUser | null
  // Set when the session ended on its own (timeout, suspension) rather than by logout.
  sessionExpired: boolean
  setUser: (user: CurrentUser) => void
  logout: () => Promise<void>
  hasPermission: (code: string) => boolean
}

export const AuthContext = createContext<AuthContextValue | null>(null)
