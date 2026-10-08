import { STATUS_BADGE_CLASSES } from '../config/devices'

interface StatusBadgeProps {
  status: string
  label: string
  // Colour per status value; device statuses by default.
  palette?: Record<string, string>
}

export default function StatusBadge({ status, label, palette = STATUS_BADGE_CLASSES }: StatusBadgeProps) {
  return (
    <span
      className={`inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${
        palette[status] ?? 'bg-slate-100 text-slate-700'
      }`}
    >
      {label}
    </span>
  )
}
