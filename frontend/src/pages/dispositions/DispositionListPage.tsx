import { useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { inputClass, primaryButtonClass, secondaryButtonClass } from '../../components/form'
import { EmptyState, ErrorMessage, Loading } from '../../components/PageState'
import Pagination from '../../components/Pagination'
import StatusBadge from '../../components/StatusBadge'
import { conditionLabel } from '../../config/devices'
import { DISPOSITION_BADGE_CLASSES, DISPOSITION_STATUSES, DISPOSITION_TYPES } from '../../config/disposition'
import {
  deviceApi,
  dispositionApi,
  errorMessage,
  type DeviceSummary,
  type Disposition,
  type DispositionFilters,
  type Paginated,
} from '../../lib/api'
import { date, rwf } from '../../lib/format'

const PAGE_SIZE = 20
const FILTER_KEYS = ['search', 'type', 'status', 'date_from', 'date_to'] as const
const selectClass = `${inputClass} bg-white`
const th = 'px-4 py-3 font-medium'
const td = 'px-4 py-3'

// Devices that are Ready for disposition: the Reallocation/Sales Officer's queue.
function ReadyDevices() {
  const [result, setResult] = useState<{ data?: Paginated<DeviceSummary>; error?: string } | null>(null)

  useEffect(() => {
    let cancelled = false
    deviceApi
      .list({ status: 'READY_FOR_DISPOSITION' })
      .then((data) => !cancelled && setResult({ data }))
      .catch((err) => !cancelled && setResult({ error: errorMessage(err, 'Could not load devices.') }))
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-medium">
          Devices ready for disposition{result?.data && <span className="text-slate-500"> ({result.data.count})</span>}
        </h3>
        {result?.data && result.data.count > result.data.results.length && (
          <Link to="/devices?status=READY_FOR_DISPOSITION" className="text-sm text-slate-600 underline">
            View all
          </Link>
        )}
      </div>
      {result?.error && <ErrorMessage message={result.error} />}
      {!result && <Loading label="Loading devices…" />}
      {result?.data && result.data.count === 0 && <EmptyState title="No devices are ready for disposition" />}
      {result?.data && result.data.count > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className={th}>Device</th>
                <th className={th}>Make / model</th>
                <th className={th}>Condition</th>
                <th className={th} />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {result.data.results.map((device) => (
                <tr key={device.id}>
                  <td className={`${td} font-medium`}>{device.device_code}</td>
                  <td className={td}>
                    {device.make} {device.model}
                  </td>
                  <td className={td}>{conditionLabel(device.current_condition)}</td>
                  <td className={`${td} text-right`}>
                    <Link to={`/devices/${device.id}`} className={secondaryButtonClass}>
                      Open
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export default function DispositionListPage() {
  const [params, setParams] = useSearchParams()
  const filters: DispositionFilters = Object.fromEntries([...params.entries()])
  const page = Number(params.get('page') ?? '1') || 1
  const hasFilters = FILTER_KEYS.some((key) => params.get(key))
  const [draft, setDraft] = useState<DispositionFilters>(filters)
  const [reloadKey, setReloadKey] = useState(0)
  const query = params.toString()
  const requestKey = `${query}#${reloadKey}`

  const [result, setResult] = useState<{ key: string; data?: Paginated<Disposition>; error?: string } | null>(null)
  const current = result?.key === requestKey ? result : null
  const data = current?.data ?? null
  const error = current?.error ?? null

  useEffect(() => {
    let cancelled = false
    dispositionApi
      .list(Object.fromEntries(new URLSearchParams(query).entries()))
      .then((list) => !cancelled && setResult({ key: requestKey, data: list }))
      .catch((err) => !cancelled && setResult({ key: requestKey, error: errorMessage(err, 'Could not load dispositions.') }))
    return () => {
      cancelled = true
    }
  }, [query, requestKey])

  function applyFilters(e: FormEvent) {
    e.preventDefault()
    const next = new URLSearchParams()
    for (const key of FILTER_KEYS) {
      const value = draft[key]?.trim()
      if (value) next.set(key, value)
    }
    setParams(next)
  }

  function goToPage(next: number) {
    const updated = new URLSearchParams(params)
    updated.set('page', String(next))
    setParams(updated)
  }

  const set = (key: keyof DispositionFilters) => (value: string) => setDraft((d) => ({ ...d, [key]: value }))

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Reallocation and resale</h2>
        <p className="text-sm text-slate-600">
          Open a ready device to draft its disposition. Confirming moves the device to Reallocated or Resold.
        </p>
      </div>

      <ReadyDevices />

      <section className="space-y-3">
        <h3 className="font-medium">Dispositions</h3>
        <form onSubmit={applyFilters} className="grid gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-3 lg:grid-cols-5">
          <label className="block text-sm sm:col-span-3 lg:col-span-1">
            <span className="text-slate-600">Search</span>
            <input
              type="search"
              placeholder="Reference, device, buyer/recipient"
              value={draft.search ?? ''}
              onChange={(e) => set('search')(e.target.value)}
              className={inputClass}
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Type</span>
            <select value={draft.type ?? ''} onChange={(e) => set('type')(e.target.value)} className={selectClass}>
              <option value="">All</option>
              {DISPOSITION_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Status</span>
            <select value={draft.status ?? ''} onChange={(e) => set('status')(e.target.value)} className={selectClass}>
              <option value="">All</option>
              {DISPOSITION_STATUSES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">From</span>
            <input type="date" value={draft.date_from ?? ''} onChange={(e) => set('date_from')(e.target.value)} className={inputClass} />
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">To</span>
            <input type="date" value={draft.date_to ?? ''} onChange={(e) => set('date_to')(e.target.value)} className={inputClass} />
          </label>
          <div className="flex gap-2 sm:col-span-3 lg:col-span-5">
            <button type="submit" className={primaryButtonClass}>
              Apply
            </button>
            {hasFilters && (
              <button
                type="button"
                onClick={() => {
                  setDraft({})
                  setParams(new URLSearchParams())
                }}
                className={secondaryButtonClass}
              >
                Clear filters
              </button>
            )}
          </div>
        </form>

        {error && <ErrorMessage message={error} onRetry={() => setReloadKey((k) => k + 1)} />}
        {!error && !data && <Loading label="Loading dispositions…" />}
        {!error && data && data.count === 0 && (
          <EmptyState title={hasFilters ? 'No dispositions match these filters' : 'No dispositions recorded yet'} />
        )}
        {!error && data && data.count > 0 && (
          <>
            <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
              <table className="w-full min-w-[860px] text-left text-sm">
                <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className={th}>Reference</th>
                    <th className={th}>Device</th>
                    <th className={th}>Type / status</th>
                    <th className={th}>Destination / buyer</th>
                    <th className={th}>Price</th>
                    <th className={th}>Date</th>
                    <th className={th}>Responsible</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.results.map((d) => (
                    <tr key={d.id}>
                      <td className={`${td} font-medium`}>{d.reference}</td>
                      <td className={td}>
                        <Link to={`/devices/${d.device}`} className="font-medium text-slate-900 hover:underline">
                          {d.device_summary.device_code}
                        </Link>
                        <div className="text-xs text-slate-500">
                          {d.device_summary.make} {d.device_summary.model}
                        </div>
                      </td>
                      <td className={td}>
                        <div className="flex flex-wrap gap-1">
                          <StatusBadge status={d.disposition_type} label={d.disposition_type_label} palette={DISPOSITION_BADGE_CLASSES} />
                          <StatusBadge status={d.status} label={d.status_label} palette={DISPOSITION_BADGE_CLASSES} />
                        </div>
                      </td>
                      <td className={td}>{d.disposition_type === 'RESALE' ? d.buyer_reference : d.destination}</td>
                      <td className={td}>{d.sale_price_rwf !== null ? rwf(d.sale_price_rwf) : '—'}</td>
                      <td className={td}>{date(d.disposition_date)}</td>
                      <td className={td}>{d.responsible_user.full_name}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={page} pageSize={PAGE_SIZE} count={data.count} onChange={goToPage} />
          </>
        )}
      </section>
    </div>
  )
}
