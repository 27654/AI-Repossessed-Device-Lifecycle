import { useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { inputClass, primaryButtonClass, secondaryButtonClass } from '../../components/form'
import { EmptyState, ErrorMessage, Loading } from '../../components/PageState'
import Pagination from '../../components/Pagination'
import StatusBadge from '../../components/StatusBadge'
import { conditionLabel } from '../../config/devices'
import { WORK_ORDER_BADGE_CLASSES, WORK_ORDER_STATUSES } from '../../config/refurbishment'
import {
  deviceApi,
  errorMessage,
  refurbishmentApi,
  type DeviceSummary,
  type Paginated,
  type WorkOrder,
  type WorkOrderFilters,
} from '../../lib/api'
import { dateTime, rwf } from '../../lib/format'

const PAGE_SIZE = 20
const FILTER_KEYS = ['search', 'status', 'assigned_to'] as const
const selectClass = `${inputClass} bg-white`
const th = 'px-4 py-3 font-medium'
const td = 'px-4 py-3'

// Devices in REFURBISHING: the refurbishment team's queue (with or without a work order yet).
function RefurbishingDevices() {
  const [result, setResult] = useState<{ data?: Paginated<DeviceSummary>; error?: string } | null>(null)

  useEffect(() => {
    let cancelled = false
    deviceApi
      .list({ status: 'REFURBISHING' })
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
          Devices in refurbishment{result?.data && <span className="text-slate-500"> ({result.data.count})</span>}
        </h3>
        {result?.data && result.data.count > result.data.results.length && (
          <Link to="/devices?status=REFURBISHING" className="text-sm text-slate-600 underline">
            View all
          </Link>
        )}
      </div>
      {result?.error && <ErrorMessage message={result.error} />}
      {!result && <Loading label="Loading devices…" />}
      {result?.data && result.data.count === 0 && <EmptyState title="No devices are in refurbishment" />}
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

export default function RefurbishmentListPage() {
  const [params, setParams] = useSearchParams()
  const filters: WorkOrderFilters = Object.fromEntries([...params.entries()])
  const page = Number(params.get('page') ?? '1') || 1
  const hasFilters = FILTER_KEYS.some((key) => params.get(key))
  const [draft, setDraft] = useState<WorkOrderFilters>(filters)
  const [reloadKey, setReloadKey] = useState(0)
  const query = params.toString()
  const requestKey = `${query}#${reloadKey}`

  const [result, setResult] = useState<{ key: string; data?: Paginated<WorkOrder>; error?: string } | null>(null)
  const current = result?.key === requestKey ? result : null
  const data = current?.data ?? null
  const error = current?.error ?? null

  useEffect(() => {
    let cancelled = false
    refurbishmentApi
      .list(Object.fromEntries(new URLSearchParams(query).entries()))
      .then((list) => !cancelled && setResult({ key: requestKey, data: list }))
      .catch((err) => !cancelled && setResult({ key: requestKey, error: errorMessage(err, 'Could not load work orders.') }))
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

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Refurbishment</h2>
        <p className="text-sm text-slate-600">
          Open a device to manage its work order. Completing a work order moves the device to Ready for disposition.
        </p>
      </div>

      <RefurbishingDevices />

      <section className="space-y-3">
        <h3 className="font-medium">Work orders</h3>
        <form onSubmit={applyFilters} className="grid gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-4">
          <label className="block text-sm sm:col-span-2">
            <span className="text-slate-600">Search</span>
            <input
              type="search"
              placeholder="Reference, device code, IMEI, serial, make or model"
              value={draft.search ?? ''}
              onChange={(e) => setDraft((d) => ({ ...d, search: e.target.value }))}
              className={inputClass}
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Status</span>
            <select
              value={draft.status ?? ''}
              onChange={(e) => setDraft((d) => ({ ...d, status: e.target.value }))}
              className={selectClass}
            >
              <option value="">All</option>
              {WORK_ORDER_STATUSES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Assigned</span>
            <select
              value={draft.assigned_to ?? ''}
              onChange={(e) => setDraft((d) => ({ ...d, assigned_to: e.target.value }))}
              className={selectClass}
            >
              <option value="">Anyone</option>
              <option value="me">Assigned to me</option>
            </select>
          </label>
          <div className="flex gap-2 sm:col-span-4">
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
        {!error && !data && <Loading label="Loading work orders…" />}
        {!error && data && data.count === 0 && (
          <EmptyState title={hasFilters ? 'No work orders match these filters' : 'No work orders yet'} />
        )}
        {!error && data && data.count > 0 && (
          <>
            <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
              <table className="w-full min-w-[860px] text-left text-sm">
                <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className={th}>Reference</th>
                    <th className={th}>Device</th>
                    <th className={th}>Status</th>
                    <th className={th}>Assigned to</th>
                    <th className={th}>Steps</th>
                    <th className={th}>Cost</th>
                    <th className={th}>Updated</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.results.map((w) => (
                    <tr key={w.id}>
                      <td className={`${td} font-medium`}>{w.reference}</td>
                      <td className={td}>
                        <Link to={`/devices/${w.device}`} className="font-medium text-slate-900 hover:underline">
                          {w.device_summary.device_code}
                        </Link>
                        <div className="text-xs text-slate-500">
                          {w.device_summary.make} {w.device_summary.model}
                        </div>
                      </td>
                      <td className={td}>
                        <div className="flex flex-wrap gap-1">
                          <StatusBadge status={w.status} label={w.status_label} palette={WORK_ORDER_BADGE_CLASSES} />
                          {w.outcome && w.outcome_label && (
                            <StatusBadge status={w.outcome} label={w.outcome_label} palette={WORK_ORDER_BADGE_CLASSES} />
                          )}
                        </div>
                      </td>
                      <td className={td}>{w.assigned_to?.full_name ?? <span className="text-slate-400">Unassigned</span>}</td>
                      <td className={td}>
                        {w.steps.filter((s) => s.status === 'COMPLETED' || s.status === 'SKIPPED').length}/{w.steps.length}
                      </td>
                      <td className={td}>{rwf(w.total_cost_rwf)}</td>
                      <td className={td}>{dateTime(w.updated_at)}</td>
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
