// Recovery enumerations, mirroring backend/recovery/models.py.

export const RECOVERY_METHODS = [
  { value: 'FIELD_COLLECTION', label: 'Field collection' },
  { value: 'CUSTOMER_SURRENDER', label: 'Customer surrender' },
  { value: 'AGENT_DROP_OFF', label: 'Agent drop-off' },
  { value: 'OTHER', label: 'Other' },
]

export const RECOVERY_OUTCOMES = [
  { value: 'RECOVERED', label: 'Recovered' },
  { value: 'RECOVERED_WITH_ISSUES', label: 'Recovered with issues' },
  { value: 'NOT_RECOVERED', label: 'Not recovered' },
]

export const RECOVERY_STATUSES = [
  { value: 'IN_PROGRESS', label: 'In progress' },
  { value: 'COMPLETED', label: 'Completed' },
]

// Outcomes that move the device to Recovered when the record is completed.
export const SUCCESSFUL_OUTCOMES = ['RECOVERED', 'RECOVERED_WITH_ISSUES']

// Outcomes that need an explanation in the notes before completing.
export const OUTCOMES_NEEDING_NOTES = ['RECOVERED_WITH_ISSUES', 'NOT_RECOVERED']

export const RECOVERY_BADGE_CLASSES: Record<string, string> = {
  IN_PROGRESS: 'bg-amber-100 text-amber-800',
  RECOVERED: 'bg-green-100 text-green-800',
  RECOVERED_WITH_ISSUES: 'bg-orange-100 text-orange-800',
  NOT_RECOVERED: 'bg-red-100 text-red-800',
}
