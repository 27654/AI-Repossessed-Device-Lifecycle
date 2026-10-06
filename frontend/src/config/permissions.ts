// Permission codes, mirroring backend/accounts/rbac.py (Perm).
export const Perm = {
  DEVICE_VIEW: 'device.view',
  DEVICE_CREATE: 'device.create',
  DEVICE_UPDATE: 'device.update',
  RECOVERY_MANAGE: 'recovery.manage',
  ASSESSMENT_CREATE: 'assessment.create',
  REFURBISHMENT_MANAGE: 'refurbishment.manage',
  DISPOSITION_CREATE: 'disposition.create',
  AI_REQUEST: 'ai.request',
  AI_VIEW: 'ai.view',
  AI_DECIDE: 'ai.decide',
  AI_FEEDBACK: 'ai.feedback',
  ANALYTICS_VIEW: 'analytics.view',
  USER_MANAGE: 'user.manage',
  ROLE_MANAGE: 'role.manage',
  AUDIT_VIEW: 'audit.view',
  CONFIG_MANAGE: 'config.manage',
} as const
