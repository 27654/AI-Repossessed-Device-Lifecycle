import type { ReactNode } from 'react'

// Centered card used by the sign-in screens.
export default function AuthCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 p-4">
      <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-6 flex items-center gap-2">
          <span className="h-7 w-7 rounded bg-brand-400" aria-hidden />
          <h1 className="text-lg font-semibold">{title}</h1>
        </div>
        {children}
      </div>
    </div>
  )
}
