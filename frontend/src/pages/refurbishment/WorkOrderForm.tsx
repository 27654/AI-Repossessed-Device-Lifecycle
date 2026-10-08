import { useEffect, useState, type FormEvent } from 'react'
import { inputClass, primaryButtonClass, secondaryButtonClass } from '../../components/form'
import { errorMessage, fieldErrors, refurbishmentApi, type UserLabel, type WorkOrder, type WorkOrderInput } from '../../lib/api'

interface WorkOrderFormProps {
  workOrder?: WorkOrder
  submitLabel: string
  onSubmit: (input: WorkOrderInput) => Promise<unknown>
  onCancel: () => void
}

// Plan or edit an active work order: assignee, diagnosis, estimate (and, when editing, summary and labour).
export default function WorkOrderForm({ workOrder, submitLabel, onSubmit, onCancel }: WorkOrderFormProps) {
  const [technicians, setTechnicians] = useState<UserLabel[]>([])
  const [assignedTo, setAssignedTo] = useState(workOrder?.assigned_to?.id ? String(workOrder.assigned_to.id) : '')
  const [diagnosis, setDiagnosis] = useState(workOrder?.diagnosis ?? '')
  const [estimate, setEstimate] = useState(String(workOrder?.estimated_cost_rwf ?? ''))
  const [summary, setSummary] = useState(workOrder?.work_summary ?? '')
  const [labour, setLabour] = useState(workOrder?.labour_cost_rwf === null || !workOrder ? '' : String(workOrder.labour_cost_rwf))
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    refurbishmentApi.technicians().then(setTechnicians).catch(() => setTechnicians([]))
  }, [])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setErrors({})
    setFormError(null)
    setSaving(true)
    const input: WorkOrderInput = {
      assigned_to: assignedTo ? Number(assignedTo) : null,
      diagnosis,
      estimated_cost_rwf: estimate === '' ? 0 : Number(estimate),
    }
    if (workOrder) {
      input.work_summary = summary
      input.labour_cost_rwf = labour === '' ? null : Number(labour)
    }
    try {
      await onSubmit(input)
    } catch (err) {
      const fields = fieldErrors(err)
      setErrors(fields)
      setFormError(Object.keys(fields).length ? 'Please correct the highlighted fields.' : errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const fieldError = (field: string) =>
    errors[field] && <span className="mt-1 block text-xs text-red-600">{errors[field]}</span>

  return (
    <form onSubmit={handleSubmit} className="space-y-3" noValidate>
      {formError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          {formError}
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="text-slate-600">Assigned technician</span>
          <select value={assignedTo} onChange={(e) => setAssignedTo(e.target.value)} className={`${inputClass} bg-white`}>
            <option value="">Unassigned (whoever starts the work)</option>
            {technicians.map((t) => (
              <option key={t.id} value={t.id}>
                {t.full_name}
              </option>
            ))}
          </select>
          {fieldError('assigned_to')}
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">Estimated cost (RWF)</span>
          <input
            type="number"
            inputMode="numeric"
            min={0}
            step={1}
            value={estimate}
            onChange={(e) => setEstimate(e.target.value)}
            className={inputClass}
          />
          {fieldError('estimated_cost_rwf')}
        </label>
        <label className="block text-sm sm:col-span-2">
          <span className="text-slate-600">Diagnosis</span>
          <textarea
            rows={2}
            placeholder="What needs fixing, from the assessment and your own inspection."
            value={diagnosis}
            onChange={(e) => setDiagnosis(e.target.value)}
            className={inputClass}
          />
          {fieldError('diagnosis')}
        </label>
        {workOrder && (
          <>
            <label className="block text-sm sm:col-span-2">
              <span className="text-slate-600">Work summary</span>
              <textarea rows={2} value={summary} onChange={(e) => setSummary(e.target.value)} className={inputClass} />
              {fieldError('work_summary')}
            </label>
            <label className="block text-sm">
              <span className="text-slate-600">Labour cost (RWF)</span>
              <input
                type="number"
                inputMode="numeric"
                min={0}
                step={1}
                value={labour}
                onChange={(e) => setLabour(e.target.value)}
                className={inputClass}
              />
              {fieldError('labour_cost_rwf')}
            </label>
          </>
        )}
      </div>
      <div className="flex gap-2">
        <button type="submit" disabled={saving} className={primaryButtonClass}>
          {saving ? 'Saving…' : submitLabel}
        </button>
        <button type="button" onClick={onCancel} disabled={saving} className={secondaryButtonClass}>
          Cancel
        </button>
      </div>
    </form>
  )
}
