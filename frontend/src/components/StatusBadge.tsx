import { STATUS_BADGE_CLASSES } from '../config/devices'

export default function StatusBadge({ status, label }: { status: string; label: string }) {
  return (
    <span
      className={`inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${
        STATUS_BADGE_CLASSES[status] ?? 'bg-slate-100 text-slate-700'
      }`}
    >
      {label}
    </span>
  )
}
