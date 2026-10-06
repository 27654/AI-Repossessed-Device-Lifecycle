import { Link } from 'react-router-dom'

export default function NotFoundPage() {
  return (
    <div className="space-y-2">
      <h2 className="text-xl font-semibold">Page not found</h2>
      <Link to="/dashboard" className="text-sm text-brand-600 underline">
        Back to dashboard
      </Link>
    </div>
  )
}
