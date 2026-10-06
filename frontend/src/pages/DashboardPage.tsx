import { useEffect, useState } from 'react'
import { getHealth, type HealthStatus } from '../lib/api'

export default function DashboardPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((err: Error) => setError(err.message))
  }, [])

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Dashboard</h2>
      <p className="text-sm text-slate-600">Role-specific dashboards are added in a later phase.</p>

      <section className="max-w-md rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="mb-2 text-sm font-medium text-slate-500">Backend status</h3>
        {!health && !error && <p className="text-sm text-slate-500">Checking…</p>}
        {error && <p className="text-sm text-red-600">Backend unreachable: {error}</p>}
        {health && (
          <dl className="grid grid-cols-2 gap-y-1 text-sm">
            <dt className="text-slate-500">API</dt>
            <dd className={health.status === 'ok' ? 'text-green-700' : 'text-amber-700'}>{health.status}</dd>
            <dt className="text-slate-500">Database</dt>
            <dd>
              {health.database} ({health.database_engine})
            </dd>
            <dt className="text-slate-500">Currency</dt>
            <dd>{health.currency}</dd>
          </dl>
        )}
      </section>
    </div>
  )
}
