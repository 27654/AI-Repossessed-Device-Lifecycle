interface PlaceholderPageProps {
  title: string
}

// Stands in for module pages until their phase is implemented.
export default function PlaceholderPage({ title }: PlaceholderPageProps) {
  return (
    <div className="space-y-2">
      <h2 className="text-xl font-semibold">{title}</h2>
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
        This module has not been implemented yet.
      </div>
    </div>
  )
}
