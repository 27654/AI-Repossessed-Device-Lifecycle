// Sidebar navigation. Role-based filtering is added with authentication
// (phase 3); the backend enforces permissions regardless of what is shown here.

export interface NavItem {
  label: string
  path: string
}

export const navItems: NavItem[] = [
  { label: 'Dashboard', path: '/dashboard' },
  { label: 'Devices', path: '/devices' },
  { label: 'Recovery', path: '/recovery' },
  { label: 'Assessments', path: '/assessments' },
  { label: 'Refurbishment', path: '/refurbishment' },
  { label: 'Dispositions', path: '/dispositions' },
  { label: 'AI Recommendations', path: '/ai-recommendations' },
  { label: 'Analytics', path: '/analytics' },
  { label: 'Notifications', path: '/notifications' },
  { label: 'Users', path: '/admin/users' },
  { label: 'Audit Log', path: '/admin/audit-log' },
]
