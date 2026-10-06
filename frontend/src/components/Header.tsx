interface HeaderProps {
  onMenuClick: () => void
}

export default function Header({ onMenuClick }: HeaderProps) {
  return (
    <header className="flex h-16 items-center justify-between border-b border-slate-200 bg-white px-4 md:px-6">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onMenuClick}
          className="rounded-md p-2 text-slate-600 hover:bg-slate-100 md:hidden"
          aria-label="Open navigation"
        >
          ☰
        </button>
        <h1 className="text-base font-semibold text-slate-900">AI-Enhanced Repossessed Device Lifecycle</h1>
      </div>
      {/* Notifications bell and user menu are added in later phases. */}
    </header>
  )
}
