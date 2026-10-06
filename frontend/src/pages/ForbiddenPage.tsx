import { Link } from 'react-router-dom'

export default function ForbiddenPage() {
  return (
    <div className="space-y-2">
      <h2 className="text-xl font-semibold">Access denied</h2>
      <p className="text-sm text-slate-600">Your role does not give you access to this page.</p>
      <Link to="/dashboard" className="text-sm text-brand-600 underline">
        Back to dashboard
      </Link>
    </div>
  )
}
