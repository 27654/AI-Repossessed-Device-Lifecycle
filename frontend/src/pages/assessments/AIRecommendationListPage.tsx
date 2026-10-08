import { useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { inputClass, primaryButtonClass, secondaryButtonClass } from '../../components/form'
import { EmptyState, ErrorMessage, Loading } from '../../components/PageState'
import Pagination from '../../components/Pagination'
import StatusBadge from '../../components/StatusBadge'
import { AI_DECISIONS, DECISION_BADGE_CLASSES, decisionLabel } from '../../config/assessment'
import { aiApi, errorMessage, type AIRecommendation, type AIRecommendationFilters, type Paginated } from '../../lib/api'
import { dateTime } from '../../lib/format'

const PAGE_SIZE = 20
const FILTER_KEYS = ['search', 'decision', 'recommendation', 'outcome'] as const
const selectClass = `${inputClass} bg-white`
const th = 'px-4 py-3 font-medium'
const td = 'px-4 py-3'

// AI recommendation history, and the Operations Manager's queue of decisions to make.
export default function AIRecommendationListPage() {
  const [params, setParams] = useSearchParams()
  const filters: AIRecommendationFilters = Object.fromEntries([...params.entries()])
  const page = Number(params.get('page') ?? '1') || 1
  const hasFilters = FILTER_KEYS.some((key) => params.get(key))
  const [draft, setDraft] = useState<AIRecommendationFilters>(filters)
  const [reloadKey, setReloadKey] = useState(0)
  const query = params.toString()
  const requestKey = `${query}#${reloadKey}`

  const [result, setResult] = useState<{ key: string; data?: Paginated<AIRecommendation>; error?: string } | null>(null)
  const current = result?.key === requestKey ? result : null
  const data = current?.data ?? null
  const error = current?.error ?? null

  useEffect(() => {
    let cancelled = false
    aiApi
      .list(Object.fromEntries(new URLSearchParams(query).entries()))
      .then((list) => !cancelled && setResult({ key: requestKey, data: list }))
      .catch((err) =>
        !cancelled && setResult({ key: requestKey, error: errorMessage(err, 'Could not load AI recommendations.') }),
      )
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

  const set = (key: keyof AIRecommendationFilters) => (value: string) => setDraft((d) => ({ ...d, [key]: value }))

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold">AI recommendations</h2>
        <p className="text-sm text-slate-600">
          Explainable rule-based recommendations for submitted assessments. The AI only recommends; the final decision
          is made by an Operations Manager on the device page.
        </p>
      </div>

      <form onSubmit={applyFilters} className="grid gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-4">
        <label className="block text-sm">
          <span className="text-slate-600">Search</span>
          <input
            type="search"
            placeholder="Assessment reference or device code"
            value={draft.search ?? ''}
            onChange={(e) => set('search')(e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">Decision</span>
          <select value={draft.decision ?? ''} onChange={(e) => set('decision')(e.target.value)} className={selectClass}>
            <option value="">All</option>
            <option value="pending">Awaiting decision</option>
            <option value="decided">Decided</option>
          </select>
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">AI recommendation</span>
          <select
            value={draft.recommendation ?? ''}
            onChange={(e) => set('recommendation')(e.target.value)}
            className={selectClass}
          >
            <option value="">All</option>
            {AI_DECISIONS.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">Outcome</span>
          <select value={draft.outcome ?? ''} onChange={(e) => set('outcome')(e.target.value)} className={selectClass}>
            <option value="">All</option>
            <option value="ACCEPTED">Accepted</option>
            <option value="OVERRIDDEN">Overridden</option>
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
      {!error && !data && <Loading label="Loading AI recommendations…" />}
      {!error && data && data.count === 0 && (
        <EmptyState title={hasFilters ? 'No recommendations match these filters' : 'No AI recommendations yet'} />
      )}
      {!error && data && data.count > 0 && (
        <>
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className={th}>Device / assessment</th>
                  <th className={th}>AI recommendation</th>
                  <th className={th}>Score</th>
                  <th className={th}>Confidence</th>
                  <th className={th}>Final decision</th>
                  <th className={th}>Generated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.results.map((r) => (
                  <tr key={r.id}>
                    <td className={td}>
                      <Link to={`/devices/${r.device_summary.id}`} className="font-medium text-slate-900 hover:underline">
                        {r.device_summary.device_code}
                      </Link>
                      <div className="text-xs text-slate-500">
                        {r.assessment_reference} · {r.device_summary.make} {r.device_summary.model}
                      </div>
                    </td>
                    <td className={td}>
                      <StatusBadge status={r.recommendation} label={r.recommendation_label} palette={DECISION_BADGE_CLASSES} />
                    </td>
                    <td className={td}>{r.score}/100</td>
                    <td className={td}>{Math.round(r.confidence * 100)}%</td>
                    <td className={td}>
                      {r.final_decision ? (
                        <>
                          {decisionLabel(r.final_decision)}
                          <div className="mt-1">
                            <StatusBadge
                              status={r.decision_outcome ?? ''}
                              label={r.decision_outcome === 'ACCEPTED' ? 'AI accepted' : 'AI overridden'}
                              palette={DECISION_BADGE_CLASSES}
                            />
                          </div>
                        </>
                      ) : (
                        <StatusBadge status="PENDING" label="Awaiting decision" palette={DECISION_BADGE_CLASSES} />
                      )}
                    </td>
                    <td className={td}>{dateTime(r.generated_at)}</td>
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
