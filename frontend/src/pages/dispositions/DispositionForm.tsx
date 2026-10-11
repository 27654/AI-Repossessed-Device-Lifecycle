import { useState, type FormEvent } from 'react'
import { inputClass, primaryButtonClass, secondaryButtonClass } from '../../components/form'
import { DISPOSITION_FIELD_LABELS, DISPOSITION_TYPES } from '../../config/disposition'
import { errorMessage, fieldErrors, type Disposition, type DispositionInput, type DispositionType } from '../../lib/api'
import { rwf } from '../../lib/format'

function todayLocal() {
  const d = new Date()
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
}

interface DispositionFormProps {
  disposition?: Disposition
  submitLabel: string
  onSubmit: (input: DispositionInput) => Promise<unknown>
  onCancel: () => void
}

// Draft or edit a reallocation / resale. Only the chosen type's fields are shown and sent.
export default function DispositionForm({ disposition, submitLabel, onSubmit, onCancel }: DispositionFormProps) {
  const [type, setType] = useState<DispositionType | ''>(disposition?.disposition_type ?? '')
  const [date, setDate] = useState(disposition?.disposition_date ?? todayLocal())
  const [destination, setDestination] = useState(disposition?.destination ?? '')
  const [recipient, setRecipient] = useState(disposition?.recipient_reference ?? '')
  const [price, setPrice] = useState(disposition?.sale_price_rwf != null ? String(disposition.sale_price_rwf) : '')
  const [buyer, setBuyer] = useState(disposition?.buyer_reference ?? '')
  const [notes, setNotes] = useState(disposition?.notes ?? '')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [latestDate] = useState(todayLocal)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!type) {
      setErrors({ disposition_type: 'Choose reallocation or resale.' })
      return
    }
    setErrors({})
    setFormError(null)
    setSaving(true)
    const resale = type === 'RESALE'
    try {
      await onSubmit({
        disposition_type: type,
        disposition_date: date,
        destination: resale ? '' : destination,
        recipient_reference: resale ? '' : recipient,
        sale_price_rwf: resale && price !== '' ? Number(price) : null,
        buyer_reference: resale ? buyer : '',
        notes,
      })
    } catch (err) {
      const fields = fieldErrors(err)
      setErrors(fields)
      setFormError(
        Object.keys(fields).length
          ? `Please correct: ${Object.keys(fields)
              .map((f) => DISPOSITION_FIELD_LABELS[f] ?? f)
              .join(', ')}.`
          : errorMessage(err),
      )
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
      <fieldset>
        <legend className="text-sm text-slate-600">Disposition type *</legend>
        <div className="mt-1 grid gap-2 sm:grid-cols-2">
          {DISPOSITION_TYPES.map((option) => (
            <label
              key={option.value}
              className={`flex cursor-pointer gap-2 rounded-md border p-3 text-sm ${
                type === option.value ? 'border-brand-500 bg-brand-50' : 'border-slate-300 hover:bg-slate-50'
              }`}
            >
              <input
                type="radio"
                name="disposition_type"
                value={option.value}
                checked={type === option.value}
                onChange={() => setType(option.value)}
                className="mt-0.5 h-4 w-4"
              />
              <span>
                <span className="block font-medium text-slate-900">{option.label}</span>
                <span className="text-slate-600">{option.hint}</span>
              </span>
            </label>
          ))}
        </div>
        {fieldError('disposition_type')}
      </fieldset>

      {type && (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="text-slate-600">Disposition date *</span>
            <input type="date" max={latestDate} value={date} onChange={(e) => setDate(e.target.value)} className={inputClass} />
            {fieldError('disposition_date')}
          </label>

          {type === 'REALLOCATION' ? (
            <>
              <label className="block text-sm sm:col-span-2">
                <span className="text-slate-600">Destination (department, branch or partner) *</span>
                <input
                  value={destination}
                  maxLength={150}
                  placeholder="e.g. Musanze branch – field sales team"
                  onChange={(e) => setDestination(e.target.value)}
                  className={inputClass}
                />
                {fieldError('destination')}
              </label>
              <label className="block text-sm">
                <span className="text-slate-600">Recipient reference (optional)</span>
                <input
                  value={recipient}
                  maxLength={60}
                  placeholder="e.g. EMP-0451"
                  onChange={(e) => setRecipient(e.target.value)}
                  className={inputClass}
                />
                {fieldError('recipient_reference')}
              </label>
            </>
          ) : (
            <>
              <label className="block text-sm">
                <span className="text-slate-600">Sale price (RWF) *</span>
                <input
                  type="number"
                  inputMode="numeric"
                  min={1}
                  step={1}
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  className={inputClass}
                />
                {price !== '' && Number(price) > 0 && <span className="mt-1 block text-xs text-slate-500">{rwf(Number(price))}</span>}
                {fieldError('sale_price_rwf')}
              </label>
              <label className="block text-sm">
                <span className="text-slate-600">Buyer reference *</span>
                <input
                  value={buyer}
                  maxLength={60}
                  placeholder="e.g. BUY-2026-0042"
                  onChange={(e) => setBuyer(e.target.value)}
                  className={inputClass}
                />
                {fieldError('buyer_reference')}
              </label>
            </>
          )}
          <p className="text-xs text-slate-500 sm:col-span-2">
            Record people by reference only — never names or ID numbers.
          </p>
          <label className="block text-sm sm:col-span-2">
            <span className="text-slate-600">Notes</span>
            <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} className={inputClass} />
          </label>
        </div>
      )}

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
