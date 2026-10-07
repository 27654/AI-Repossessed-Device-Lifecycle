// Device enumerations, mirroring backend/devices/models.py.

export const DEVICE_STATUSES = [
  { value: 'IN_RECOVERY', label: 'In recovery' },
  { value: 'RECOVERED', label: 'Recovered' },
  { value: 'ASSESSED', label: 'Assessed' },
  { value: 'REFURBISHING', label: 'Refurbishing' },
  { value: 'READY_FOR_DISPOSITION', label: 'Ready for disposition' },
  { value: 'REALLOCATED', label: 'Reallocated' },
  { value: 'RESOLD', label: 'Resold' },
  { value: 'UNABLE_TO_REPAIR', label: 'Unable to repair' },
]

// Statuses a new device may start in.
export const INITIAL_STATUSES = DEVICE_STATUSES.slice(0, 2)

export const DEVICE_TYPES = [
  { value: 'SMARTPHONE', label: 'Smartphone' },
  { value: 'FEATURE_PHONE', label: 'Feature phone' },
  { value: 'TABLET', label: 'Tablet' },
  { value: 'LAPTOP', label: 'Laptop' },
  { value: 'TELEVISION', label: 'Television' },
  { value: 'SOLAR_HOME_SYSTEM', label: 'Solar home system' },
  { value: 'OTHER', label: 'Other' },
]

export const DEVICE_CONDITIONS = [
  { value: 'EXCELLENT', label: 'Excellent' },
  { value: 'GOOD', label: 'Good' },
  { value: 'FAIR', label: 'Fair' },
  { value: 'POOR', label: 'Poor' },
]

export const conditionLabel = (value: string | null) =>
  DEVICE_CONDITIONS.find((c) => c.value === value)?.label ?? 'Not assessed'

export const STATUS_BADGE_CLASSES: Record<string, string> = {
  IN_RECOVERY: 'bg-amber-100 text-amber-800',
  RECOVERED: 'bg-sky-100 text-sky-800',
  ASSESSED: 'bg-indigo-100 text-indigo-800',
  REFURBISHING: 'bg-violet-100 text-violet-800',
  READY_FOR_DISPOSITION: 'bg-teal-100 text-teal-800',
  REALLOCATED: 'bg-green-100 text-green-800',
  RESOLD: 'bg-green-100 text-green-800',
  UNABLE_TO_REPAIR: 'bg-red-100 text-red-800',
}

// Mirrors MAX_UPLOAD_SIZE_MB and the allowed types; the server checks again.
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024
export const ACCEPTED_UPLOAD_TYPES = '.jpg,.jpeg,.png,.webp,.pdf,image/jpeg,image/png,image/webp,application/pdf'
