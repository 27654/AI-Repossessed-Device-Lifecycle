import { Perm } from './permissions'

// Sidebar navigation. Items with a `permission` are shown only to roles that
// have it. This is a convenience: the backend enforces every permission again.

export interface NavItem {
  label: string
  path: string
  permission?: string
}

export const navItems: NavItem[] = [
  { label: 'Dashboard', path: '/dashboard' },
  { label: 'Devices', path: '/devices', permission: Perm.DEVICE_VIEW },
  { label: 'Recovery', path: '/recovery', permission: Perm.RECOVERY_MANAGE },
  { label: 'Assessments', path: '/assessments', permission: Perm.ASSESSMENT_CREATE },
  { label: 'Refurbishment', path: '/refurbishments', permission: Perm.REFURBISHMENT_MANAGE },
  { label: 'Dispositions', path: '/dispositions', permission: Perm.DISPOSITION_CREATE },
  { label: 'AI Recommendations', path: '/ai-recommendations', permission: Perm.AI_VIEW },
  { label: 'Analytics', path: '/analytics', permission: Perm.ANALYTICS_VIEW },
  { label: 'Notifications', path: '/notifications' },
  { label: 'Users', path: '/admin/users', permission: Perm.USER_MANAGE },
  { label: 'Audit Log', path: '/admin/audit-log', permission: Perm.AUDIT_VIEW },
]
