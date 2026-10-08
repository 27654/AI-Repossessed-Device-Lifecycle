// Assessment and AI enumerations, mirroring backend/assessments/models.py and backend/ai_engine/models.py.

type Option = { value: string; label: string }

export const PHYSICAL_CONDITIONS: Option[] = [
  { value: 'EXCELLENT', label: 'Excellent' },
  { value: 'GOOD', label: 'Good' },
  { value: 'FAIR', label: 'Fair' },
  { value: 'POOR', label: 'Poor' },
  { value: 'CRITICAL', label: 'Critical' },
]

export const COSMETIC_CONDITIONS: Option[] = PHYSICAL_CONDITIONS.slice(0, 4)

export const SCREEN_CONDITIONS: Option[] = [
  { value: 'INTACT', label: 'Intact' },
  { value: 'MINOR_DAMAGE', label: 'Minor damage' },
  { value: 'MAJOR_DAMAGE', label: 'Major damage' },
  { value: 'BROKEN', label: 'Broken' },
]

export const BATTERY_CONDITIONS: Option[] = [
  { value: 'EXCELLENT', label: 'Excellent' },
  { value: 'GOOD', label: 'Good' },
  { value: 'FAIR', label: 'Fair' },
  { value: 'POOR', label: 'Poor' },
  { value: 'FAILED', label: 'Failed' },
]

export const FUNCTIONAL_STATUSES: Option[] = [
  { value: 'FULLY_FUNCTIONAL', label: 'Fully functional' },
  { value: 'PARTIALLY_FUNCTIONAL', label: 'Partially functional' },
  { value: 'NON_FUNCTIONAL', label: 'Non-functional' },
]

export const ACCESSORIES_CONDITIONS: Option[] = [
  { value: 'COMPLETE', label: 'Complete' },
  { value: 'PARTIAL', label: 'Partial' },
  { value: 'NONE', label: 'None' },
]

export const DEFECTS: Option[] = [
  { value: 'CAMERA_FAULT', label: 'Camera fault' },
  { value: 'CHARGING_PORT_FAULT', label: 'Charging port fault' },
  { value: 'SPEAKER_OR_MICROPHONE_FAULT', label: 'Speaker or microphone fault' },
  { value: 'BUTTON_FAULT', label: 'Button fault' },
  { value: 'NETWORK_OR_SIM_FAULT', label: 'Network or SIM fault' },
  { value: 'SOFTWARE_ISSUE', label: 'Software issue' },
  { value: 'ACCOUNT_OR_DEVICE_LOCK', label: 'Account or device lock' },
  { value: 'WATER_DAMAGE', label: 'Water damage' },
  { value: 'HOUSING_DAMAGE', label: 'Housing or back cover damage' },
  { value: 'OTHER', label: 'Other (describe in notes)' },
]

export const ASSESSMENT_STATUSES: Option[] = [
  { value: 'DRAFT', label: 'Draft' },
  { value: 'SUBMITTED', label: 'Submitted' },
]

export const AI_DECISIONS: { value: 'REFURBISH' | 'READY_FOR_DISPOSITION' | 'UNABLE_TO_REPAIR'; label: string; result: string }[] = [
  { value: 'REFURBISH', label: 'Refurbish', result: 'Refurbishing' },
  { value: 'READY_FOR_DISPOSITION', label: 'Ready for disposition', result: 'Ready for disposition' },
  { value: 'UNABLE_TO_REPAIR', label: 'Unable to repair', result: 'Unable to repair' },
]

export const decisionLabel = (value: string | null) => AI_DECISIONS.find((d) => d.value === value)?.label ?? '—'

// Score breakdown rows, in display order.
export const SCORE_FACTORS: { key: string; label: string }[] = [
  { key: 'functionality', label: 'Functionality' },
  { key: 'physical', label: 'Physical condition' },
  { key: 'screen', label: 'Screen' },
  { key: 'battery', label: 'Battery' },
  { key: 'cosmetic', label: 'Cosmetic condition' },
  { key: 'accessories', label: 'Accessories' },
  { key: 'repair_economics', label: 'Repair cost vs value' },
  { key: 'defects', label: 'Defects' },
]

export const ASSESSMENT_BADGE_CLASSES: Record<string, string> = {
  DRAFT: 'bg-amber-100 text-amber-800',
  SUBMITTED: 'bg-indigo-100 text-indigo-800',
}

export const DECISION_BADGE_CLASSES: Record<string, string> = {
  REFURBISH: 'bg-violet-100 text-violet-800',
  READY_FOR_DISPOSITION: 'bg-teal-100 text-teal-800',
  UNABLE_TO_REPAIR: 'bg-red-100 text-red-800',
  ACCEPTED: 'bg-green-100 text-green-800',
  OVERRIDDEN: 'bg-orange-100 text-orange-800',
  PENDING: 'bg-amber-100 text-amber-800',
}

// Field names shown when the server reports missing information.
export const ASSESSMENT_FIELD_LABELS: Record<string, string> = {
  physical_condition: 'Physical condition',
  cosmetic_condition: 'Cosmetic condition',
  screen_condition: 'Screen',
  battery_condition: 'Battery',
  functional_status: 'Functionality',
  accessories_condition: 'Accessories',
  estimated_repair_cost_rwf: 'Estimated repair cost',
  estimated_market_value_rwf: 'Estimated market value',
  assessment_date: 'Assessment date',
  defects: 'Defects',
}
