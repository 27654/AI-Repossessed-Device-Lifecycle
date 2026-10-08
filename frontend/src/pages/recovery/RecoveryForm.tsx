import { useState, type FormEvent } from 'react'
import { inputClass, primaryButtonClass, secondaryButtonClass } from '../../components/form'
import { OUTCOMES_NEEDING_NOTES, RECOVERY_METHODS, RECOVERY_OUTCOMES } from '../../config/recovery'
import { errorMessage, fieldErrors, type Recovery, type RecoveryInput } from '../../lib/api'
import { fromLocalInput, toLocalInput } from '../../lib/format'

const selectClass = `${inputClass} bg-white`

function initialValues(recovery?: Recovery): RecoveryInput {
  return {
    recovered_at: toLocalInput(recovery?.recovered_at ?? new Date()),
    recovery_location: recovery?.recovery_location ?? '',
    recovery_method: recovery?.recovery_method ?? '',
    outcome: recovery?.outcome ?? '',
    condition_notes: recovery?.condition_notes ?? '',
    notes: recovery?.notes ?? '',
  }
}

interface RecoveryFormProps {
  recovery?: Recovery
  submitLabel: string
  onSubmit: (input: RecoveryInput) => Promise<unknown>
  onCancel: () => void
}

// Record or edit an in-progress recovery. The server validates everything again.
export default function RecoveryForm({ recovery, submitLabel, onSubmit, onCancel }: RecoveryFormProps) {
  const [values, setValues] = useState<RecoveryInput>(() => initialValues(recovery))
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  // Upper bound for the date picker, fixed when the form opens; the server re-checks.
  const [latestAllowed] = useState(() => toLocalInput(new Date()))

  const set = (field: keyof RecoveryInput) => (value: string) => setValues((v) => ({ ...v, [field]: value }))
  const notesRequired = OUTCOMES_NEEDING_NOTES.includes(values.outcome)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setErrors({})
    setFormError(null)
    setSaving(true)
    try {
      await onSubmit({ ...values, recovered_at: fromLocalInput(values.recovered_at) })
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
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      {formError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          {formError}
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="text-slate-600">Recovery date and time *</span>
          <input
            type="datetime-local"
            required
            max={latestAllowed}
            value={values.recovered_at}
            onChange={(e) => set('recovered_at')(e.target.value)}
            className={inputClass}
          />
          {fieldError('recovered_at')}
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">Recovery method *</span>
          <select
            required
            value={values.recovery_method}
            onChange={(e) => set('recovery_method')(e.target.value)}
            className={selectClass}
          >
            <option value="">Select…</option>
            {RECOVERY_METHODS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
          {fieldError('recovery_method')}
        </label>
        <label className="block text-sm sm:col-span-2">
          <span className="text-slate-600">Recovery location *</span>
          <input
            required
            maxLength={200}
            placeholder="e.g. Kimironko, Gasabo, Kigali"
            value={values.recovery_location}
            onChange={(e) => set('recovery_location')(e.target.value)}
            className={inputClass}
          />
          {fieldError('recovery_location')}
        </label>
        <label className="block text-sm sm:col-span-2">
          <span className="text-slate-600">Outcome</span>
          <select value={values.outcome} onChange={(e) => set('outcome')(e.target.value)} className={selectClass}>
            <option value="">Not decided yet</option>
            {RECOVERY_OUTCOMES.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <span className="mt-1 block text-xs text-slate-500">Required before the recovery can be completed.</span>
          {fieldError('outcome')}
        </label>
        <label className="block text-sm sm:col-span-2">
          <span className="text-slate-600">Condition at collection</span>
          <textarea
            rows={2}
            placeholder="Visible condition, accessories, packaging…"
            value={values.condition_notes}
            onChange={(e) => set('condition_notes')(e.target.value)}
            className={inputClass}
          />
          {fieldError('condition_notes')}
        </label>
        <label className="block text-sm sm:col-span-2">
          <span className="text-slate-600">
            Recovery notes{notesRequired && ' *'}
          </span>
          <textarea
            rows={3}
            placeholder={
              values.outcome === 'NOT_RECOVERED'
                ? 'Why was the device not recovered?'
                : values.outcome === 'RECOVERED_WITH_ISSUES'
                  ? 'Describe the issues found.'
                  : 'Anything the next stage should know.'
            }
            value={values.notes}
            onChange={(e) => set('notes')(e.target.value)}
            className={inputClass}
          />
          {notesRequired && !errors.notes && (
            <span className="mt-1 block text-xs text-slate-500">Required for this outcome before completing.</span>
          )}
          {fieldError('notes')}
        </label>
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
