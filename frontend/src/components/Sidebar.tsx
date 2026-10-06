import { NavLink } from 'react-router-dom'
import { navItems } from '../config/navigation'

interface SidebarProps {
  open: boolean
  onNavigate: () => void
}

export default function Sidebar({ open, onNavigate }: SidebarProps) {
  return (
    <aside
      className={`fixed inset-y-0 left-0 z-30 w-64 transform bg-slate-900 text-slate-100 transition-transform md:static md:translate-x-0 ${
        open ? 'translate-x-0' : '-translate-x-full'
      }`}
    >
      <div className="flex h-16 items-center gap-2 border-b border-slate-800 px-5">
        <span className="h-6 w-6 rounded bg-brand-400" aria-hidden />
        <span className="font-semibold">Device Lifecycle</span>
      </div>
      <nav className="space-y-1 p-3">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            onClick={onNavigate}
            className={({ isActive }) =>
              `block rounded-md px-3 py-2 text-sm ${
                isActive ? 'bg-brand-400 font-medium text-slate-900' : 'text-slate-300 hover:bg-slate-800'
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
