import { useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { inputClass, primaryButtonClass, secondaryButtonClass } from '../../components/form'
import { EmptyState, ErrorMessage, Loading } from '../../components/PageState'
import Pagination from '../../components/Pagination'
import StatusBadge from '../../components/StatusBadge'
import { ASSESSMENT_BADGE_CLASSES, ASSESSMENT_STATUSES } from '../../config/assessment'
import {
  assessmentApi,
  deviceApi,
  errorMessage,
  type Assessment,
  type AssessmentFilters,
  type DeviceSummary,
  type Paginated,
} from '../../lib/api'
import { date, dateTime } from '../../lib/format'

const PAGE_SIZE = 20
const FILTER_KEYS = ['search', 'status'] as const
const selectClass = `${inputClass} bg-white`
const th = 'px-4 py-3 font-medium'
const td = 'px-4 py-3'

// Recovered devices: the Device Assessor's work queue.
function AwaitingAssessment() {
  const [result, setResult] = useState<{ data?: Paginated<DeviceSummary>; error?: string } | null>(null)

  useEffect(() => {
    let cancelled = false
    deviceApi
      .list({ status: 'RECOVERED' })
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
          Devices awaiting assessment{result?.data && <span className="text-slate-500"> ({result.data.count})</span>}
        </h3>
        {result?.data && result.data.count > result.data.results.length && (
          <Link to="/devices?status=RECOVERED" className="text-sm text-slate-600 underline">
            View all
          </Link>
        )}
      </div>
      {result?.error && <ErrorMessage message={result.error} />}
      {!result && <Loading label="Loading devices…" />}
      {result?.data && result.data.count === 0 && <EmptyState title="No recovered devices are waiting for assessment" />}
      {result?.data && result.data.count > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className={th}>Device</th>
                <th className={th}>Make / model</th>
                <th className={th}>IMEI / serial</th>
                <th className={th}>Recovered</th>
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
                  <td className={`${td} font-mono text-xs`}>{device.imei ?? device.serial_number}</td>
                  <td className={td}>{device.recovery_date ? date(device.recovery_date) : '—'}</td>
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

export default function AssessmentListPage() {
  const [params, setParams] = useSearchParams()
  const filters: AssessmentFilters = Object.fromEntries([...params.entries()])
  const page = Number(params.get('page') ?? '1') || 1
  const hasFilters = FILTER_KEYS.some((key) => params.get(key))
  const [draft, setDraft] = useState<AssessmentFilters>(filters)
  const [reloadKey, setReloadKey] = useState(0)
  const query = params.toString()
  const requestKey = `${query}#${reloadKey}`

  const [result, setResult] = useState<{ key: string; data?: Paginated<Assessment>; error?: string } | null>(null)
  const current = result?.key === requestKey ? result : null
  const data = current?.data ?? null
  const error = current?.error ?? null

  useEffect(() => {
    let cancelled = false
    assessmentApi
      .list(Object.fromEntries(new URLSearchParams(query).entries()))
      .then((list) => !cancelled && setResult({ key: requestKey, data: list }))
      .catch((err) => !cancelled && setResult({ key: requestKey, error: errorMessage(err, 'Could not load assessments.') }))
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
        <h2 className="text-xl font-semibold">Condition assessments</h2>
        <p className="text-sm text-slate-600">
          Open a recovered device to assess it. Submitting an assessment moves the device to Assessed.
        </p>
      </div>

      <AwaitingAssessment />

      <section className="space-y-3">
        <h3 className="font-medium">Assessment records</h3>
        <form onSubmit={applyFilters} className="grid gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-3">
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
              {ASSESSMENT_STATUSES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <div className="flex gap-2 sm:col-span-3">
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
        {!error && !data && <Loading label="Loading assessments…" />}
        {!error && data && data.count === 0 && (
          <EmptyState title={hasFilters ? 'No assessments match these filters' : 'No assessments recorded yet'} />
        )}
        {!error && data && data.count > 0 && (
          <>
            <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
              <table className="w-full min-w-[820px] text-left text-sm">
                <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className={th}>Reference</th>
                    <th className={th}>Device</th>
                    <th className={th}>Physical / function</th>
                    <th className={th}>Status</th>
                    <th className={th}>Assessor</th>
                    <th className={th}>Updated</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.results.map((a) => (
                    <tr key={a.id}>
                      <td className={`${td} font-medium`}>{a.reference}</td>
                      <td className={td}>
                        <Link to={`/devices/${a.device}`} className="font-medium text-slate-900 hover:underline">
                          {a.device_summary.device_code}
                        </Link>
                        <div className="text-xs text-slate-500">
                          {a.device_summary.make} {a.device_summary.model}
                        </div>
                      </td>
                      <td className={td}>
                        {a.physical_condition_label || '—'}
                        <div className="text-xs text-slate-500">{a.functional_status_label || '—'}</div>
                      </td>
                      <td className={td}>
                        <StatusBadge status={a.status} label={a.status_label} palette={ASSESSMENT_BADGE_CLASSES} />
                      </td>
                      <td className={td}>{a.assessor.full_name}</td>
                      <td className={td}>{dateTime(a.updated_at)}</td>
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
