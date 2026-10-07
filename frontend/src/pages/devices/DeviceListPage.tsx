import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../auth/useAuth'
import { inputClass, primaryButtonClass, secondaryButtonClass } from '../../components/form'
import { EmptyState, ErrorMessage, Loading } from '../../components/PageState'
import Pagination from '../../components/Pagination'
import StatusBadge from '../../components/StatusBadge'
import { conditionLabel, DEVICE_CONDITIONS, DEVICE_STATUSES, DEVICE_TYPES } from '../../config/devices'
import { Perm } from '../../config/permissions'
import { deviceApi, errorMessage, type DeviceFilters, type DeviceSummary, type Paginated } from '../../lib/api'

const PAGE_SIZE = 20
const FILTER_KEYS = ['search', 'status', 'make', 'device_type', 'condition', 'recovered_from', 'recovered_to'] as const

const selectClass = `${inputClass} bg-white`

export default function DeviceListPage() {
  const { hasPermission } = useAuth()
  const navigate = useNavigate()
  // Filters live in the URL so they survive reloads and the back button.
  const [params, setParams] = useSearchParams()
  const filters: DeviceFilters = Object.fromEntries([...params.entries()])
  const page = Number(params.get('page') ?? '1') || 1
  const hasFilters = FILTER_KEYS.some((key) => params.get(key))

  const [draft, setDraft] = useState<DeviceFilters>(filters)
  const [reloadKey, setReloadKey] = useState(0)
  const query = params.toString()
  const requestKey = `${query}#${reloadKey}`

  // The latest response, tagged with the request it answers; anything else means "loading".
  const [result, setResult] = useState<{ key: string; data?: Paginated<DeviceSummary>; error?: string } | null>(null)
  const current = result?.key === requestKey ? result : null
  const data = current?.data ?? null
  const error = current?.error ?? null

  useEffect(() => {
    let cancelled = false
    deviceApi
      .list(Object.fromEntries(new URLSearchParams(query).entries()))
      .then((list) => !cancelled && setResult({ key: requestKey, data: list }))
      .catch((err) => !cancelled && setResult({ key: requestKey, error: errorMessage(err, 'Could not load devices.') }))
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

  function clearFilters() {
    setDraft({})
    setParams(new URLSearchParams())
  }

  function goToPage(next: number) {
    const updated = new URLSearchParams(params)
    updated.set('page', String(next))
    setParams(updated)
  }

  const setField = (key: keyof DeviceFilters) => (value: string) => setDraft((d) => ({ ...d, [key]: value }))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">Devices</h2>
        {hasPermission(Perm.DEVICE_CREATE) && (
          <Link to="/devices/new" className={primaryButtonClass}>
            Add device
          </Link>
        )}
      </div>

      <form onSubmit={applyFilters} className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
        <label className="block text-sm">
          <span className="text-slate-600">Search</span>
          <input
            type="search"
            placeholder="Device code, IMEI, serial number, make, model or account reference"
            value={draft.search ?? ''}
            onChange={(e) => setField('search')(e.target.value)}
            className={inputClass}
          />
        </label>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <label className="block text-sm">
            <span className="text-slate-600">Status</span>
            <select value={draft.status ?? ''} onChange={(e) => setField('status')(e.target.value)} className={selectClass}>
              <option value="">All statuses</option>
              {DEVICE_STATUSES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Condition</span>
            <select
              value={draft.condition ?? ''}
              onChange={(e) => setField('condition')(e.target.value)}
              className={selectClass}
            >
              <option value="">Any condition</option>
              {DEVICE_CONDITIONS.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Type</span>
            <select
              value={draft.device_type ?? ''}
              onChange={(e) => setField('device_type')(e.target.value)}
              className={selectClass}
            >
              <option value="">All types</option>
              {DEVICE_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Make</span>
            <input value={draft.make ?? ''} onChange={(e) => setField('make')(e.target.value)} className={inputClass} />
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Recovered from</span>
            <input
              type="date"
              value={draft.recovered_from ?? ''}
              onChange={(e) => setField('recovered_from')(e.target.value)}
              className={inputClass}
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Recovered to</span>
            <input
              type="date"
              value={draft.recovered_to ?? ''}
              onChange={(e) => setField('recovered_to')(e.target.value)}
              className={inputClass}
            />
          </label>
        </div>
        <div className="flex gap-2">
          <button type="submit" className={primaryButtonClass}>
            Apply
          </button>
          {hasFilters && (
            <button type="button" onClick={clearFilters} className={secondaryButtonClass}>
              Clear filters
            </button>
          )}
        </div>
      </form>

      {error && <ErrorMessage message={error} onRetry={() => setReloadKey((k) => k + 1)} />}
      {!error && !data && <Loading label="Loading devices…" />}
      {!error && data && data.count === 0 && (
        <EmptyState title={hasFilters ? 'No devices match these filters' : 'No devices registered yet'}>
          {hasFilters
            ? 'Try a different search or clear the filters.'
            : hasPermission(Perm.DEVICE_CREATE) && 'Use “Add device” to register the first one.'}
        </EmptyState>
      )}
      {!error && data && data.count > 0 && (
        <>
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3 font-medium">Device</th>
                  <th className="px-4 py-3 font-medium">Make / model</th>
                  <th className="px-4 py-3 font-medium">IMEI / serial</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Condition</th>
                  <th className="px-4 py-3 font-medium">Location</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.results.map((device) => (
                  <tr
                    key={device.id}
                    onClick={() => navigate(`/devices/${device.id}`)}
                    className="cursor-pointer hover:bg-slate-50"
                  >
                    <td className="px-4 py-3">
                      <Link
                        to={`/devices/${device.id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="font-medium text-slate-900 hover:underline"
                      >
                        {device.device_code}
                      </Link>
                      <div className="text-xs text-slate-500">{device.device_type_label}</div>
                    </td>
                    <td className="px-4 py-3">
                      {device.make} {device.model}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">
                      {device.imei ?? <span className="font-sans text-slate-400">No IMEI</span>}
                      {device.serial_number && <div className="text-slate-500">{device.serial_number}</div>}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={device.status} label={device.status_label} />
                    </td>
                    <td className="px-4 py-3">{conditionLabel(device.current_condition)}</td>
                    <td className="px-4 py-3">{device.current_location || <span className="text-slate-400">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pageSize={PAGE_SIZE} count={data.count} onChange={goToPage} />
        </>
      )}
    </div>
  )
}
