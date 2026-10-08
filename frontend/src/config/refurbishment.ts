// Refurbishment enumerations, mirroring backend/refurbishment/models.py.

export const STEP_TYPES = [
  { value: 'DIAGNOSIS', label: 'Diagnosis' },
  { value: 'CLEANING', label: 'Cleaning' },
  { value: 'SCREEN_REPAIR', label: 'Screen repair' },
  { value: 'BATTERY_REPLACEMENT', label: 'Battery replacement' },
  { value: 'SOFTWARE_RESET', label: 'Software reset' },
  { value: 'SOFTWARE_REPAIR', label: 'Software repair' },
  { value: 'HOUSING_REPAIR', label: 'Housing repair' },
  { value: 'PORT_REPAIR', label: 'Port repair' },
  { value: 'FUNCTIONAL_TEST', label: 'Functional test' },
  { value: 'QUALITY_CHECK', label: 'Quality check' },
  { value: 'OTHER', label: 'Other' },
]

// Checks that must be completed (not skipped) before a device is declared repaired.
export const REQUIRED_CHECKS = [
  { value: 'FUNCTIONAL_TEST', label: 'Functional test' },
  { value: 'QUALITY_CHECK', label: 'Quality check' },
]

export const WORK_ORDER_STATUSES = [
  { value: 'ACTIVE', label: 'Active (open or in progress)' },
  { value: 'OPEN', label: 'Open' },
  { value: 'IN_PROGRESS', label: 'In progress' },
  { value: 'COMPLETED', label: 'Completed' },
  { value: 'CANCELLED', label: 'Cancelled' },
]

export const WORK_ORDER_BADGE_CLASSES: Record<string, string> = {
  OPEN: 'bg-amber-100 text-amber-800',
  IN_PROGRESS: 'bg-violet-100 text-violet-800',
  COMPLETED: 'bg-green-100 text-green-800',
  CANCELLED: 'bg-slate-200 text-slate-700',
  REPAIRED: 'bg-green-100 text-green-800',
  UNABLE_TO_REPAIR: 'bg-red-100 text-red-800',
}

export const STEP_BADGE_CLASSES: Record<string, string> = {
  PENDING: 'bg-slate-100 text-slate-700',
  IN_PROGRESS: 'bg-violet-100 text-violet-800',
  COMPLETED: 'bg-green-100 text-green-800',
  SKIPPED: 'bg-amber-100 text-amber-800',
}

// Field names shown when the server reports what still blocks completion.
export const COMPLETION_FIELD_LABELS: Record<string, string> = {
  work_summary: 'Work summary',
  labour_cost_rwf: 'Labour cost',
  steps: 'Steps',
  checks: 'Required checks',
}
