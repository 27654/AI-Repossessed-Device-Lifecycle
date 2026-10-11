// Disposition enumerations, mirroring backend/dispositions/models.py.

export const DISPOSITION_TYPES = [
  { value: 'REALLOCATION', label: 'Reallocation', result: 'Reallocated', hint: 'The device goes to a Yellow department, branch or partner.' },
  { value: 'RESALE', label: 'Resale', result: 'Resold', hint: 'The device is sold to a buyer.' },
] as const

export const DISPOSITION_STATUSES = [
  { value: 'DRAFT', label: 'Draft' },
  { value: 'CONFIRMED', label: 'Confirmed' },
]

export const DISPOSITION_BADGE_CLASSES: Record<string, string> = {
  DRAFT: 'bg-amber-100 text-amber-800',
  CONFIRMED: 'bg-green-100 text-green-800',
  REALLOCATION: 'bg-sky-100 text-sky-800',
  RESALE: 'bg-teal-100 text-teal-800',
}

export const DISPOSITION_FIELD_LABELS: Record<string, string> = {
  disposition_type: 'Type',
  disposition_date: 'Date',
  destination: 'Destination',
  recipient_reference: 'Recipient reference',
  sale_price_rwf: 'Sale price',
  buyer_reference: 'Buyer reference',
  device: 'Device',
}
