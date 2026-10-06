// Layout only. Session login and TOTP verification are wired up in phase 3.
export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 p-4">
      <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-6 flex items-center gap-2">
          <span className="h-7 w-7 rounded bg-brand-400" aria-hidden />
          <h1 className="text-lg font-semibold">Staff sign in</h1>
        </div>
        <form className="space-y-4" onSubmit={(e) => e.preventDefault()}>
          <label className="block text-sm">
            <span className="text-slate-600">Email</span>
            <input type="email" disabled className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2" />
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Password</span>
            <input type="password" disabled className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2" />
          </label>
          <button
            type="submit"
            disabled
            className="w-full rounded-md bg-brand-400 px-3 py-2 text-sm font-medium text-slate-900 disabled:opacity-60"
          >
            Sign in
          </button>
          <p className="text-center text-xs text-slate-500">Authentication is not enabled yet.</p>
        </form>
      </div>
    </div>
  )
}
