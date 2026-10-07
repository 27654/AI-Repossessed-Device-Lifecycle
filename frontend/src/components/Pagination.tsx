interface PaginationProps {
  page: number
  pageSize: number
  count: number
  onChange: (page: number) => void
}

export default function Pagination({ page, pageSize, count, onChange }: PaginationProps) {
  const pages = Math.max(1, Math.ceil(count / pageSize))
  if (count === 0) return null
  const first = (page - 1) * pageSize + 1
  const last = Math.min(page * pageSize, count)
  const button =
    'rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50'

  return (
    <nav className="flex flex-wrap items-center justify-between gap-2 text-sm text-slate-600" aria-label="Pagination">
      <span>
        {first}–{last} of {count}
      </span>
      <div className="flex items-center gap-2">
        <button type="button" className={button} disabled={page <= 1} onClick={() => onChange(page - 1)}>
          Previous
        </button>
        <span>
          Page {page} of {pages}
        </span>
        <button type="button" className={button} disabled={page >= pages} onClick={() => onChange(page + 1)}>
          Next
        </button>
      </div>
    </nav>
  )
}
