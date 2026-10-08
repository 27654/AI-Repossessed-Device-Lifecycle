import { useState, type FormEvent, type ReactNode } from 'react'
import { inputClass, primaryButtonClass, secondaryButtonClass } from '../../components/form'
import {
  ACCESSORIES_CONDITIONS,
  ASSESSMENT_FIELD_LABELS,
  BATTERY_CONDITIONS,
  COSMETIC_CONDITIONS,
  DEFECTS,
  FUNCTIONAL_STATUSES,
  PHYSICAL_CONDITIONS,
  SCREEN_CONDITIONS,
} from '../../config/assessment'
import { errorMessage, fieldErrors, type Assessment, type AssessmentInput } from '../../lib/api'

type ChoiceField =
  | 'physical_condition'
  | 'cosmetic_condition'
  | 'screen_condition'
  | 'battery_condition'
  | 'functional_status'
  | 'accessories_condition'

function todayLocal() {
  const d = new Date()
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
}

function initialValues(assessment?: Assessment): AssessmentInput {
  return {
    assessment_date: assessment?.assessment_date ?? todayLocal(),
    physical_condition: assessment?.physical_condition ?? '',
    cosmetic_condition: assessment?.cosmetic_condition ?? '',
    screen_condition: assessment?.screen_condition ?? '',
    battery_condition: assessment?.battery_condition ?? '',
    functional_status: assessment?.functional_status ?? '',
    accessories_condition: assessment?.accessories_condition ?? '',
    defects: assessment?.defects ?? [],
    assessment_notes: assessment?.assessment_notes ?? '',
    estimated_repair_cost_rwf: assessment?.estimated_repair_cost_rwf ?? null,
    estimated_market_value_rwf: assessment?.estimated_market_value_rwf ?? null,
  }
}

function Section({ number, title, children }: { number: number; title: string; children: ReactNode }) {
  return (
    <fieldset className="rounded-md border border-slate-200 p-3">
      <legend className="px-1 text-sm font-medium text-slate-800">
        <span className="mr-1 text-slate-400">{number}.</span>
        {title}
      </legend>
      {children}
    </fieldset>
  )
}

function ChoiceGroup({
  name,
  options,
  value,
  onChange,
}: {
  name: string
  options: { value: string; label: string }[]
  value: string
  onChange: (value: string) => void
}) {
  return (
    <div role="radiogroup" aria-label={name} className="flex flex-wrap gap-2">
      {options.map((option) => {
        const selected = value === option.value
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(selected ? '' : option.value)}
            className={`rounded-full border px-3 py-1 text-sm ${
              selected
                ? 'border-brand-500 bg-brand-100 font-medium text-slate-900'
                : 'border-slate-300 text-slate-700 hover:bg-slate-50'
            }`}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

interface AssessmentFormProps {
  assessment?: Assessment
  submitLabel: string
  onSubmit: (input: AssessmentInput) => Promise<unknown>
  onCancel: () => void
}

// Record or edit a draft assessment. Any field may be left for later; all are
// required before submission. The server validates everything again.
export default function AssessmentForm({ assessment, submitLabel, onSubmit, onCancel }: AssessmentFormProps) {
  const [values, setValues] = useState<AssessmentInput>(() => initialValues(assessment))
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [latestDate] = useState(todayLocal)

  const setChoice = (field: ChoiceField) => (value: string) => setValues((v) => ({ ...v, [field]: value }))
  const setAmount = (field: 'estimated_repair_cost_rwf' | 'estimated_market_value_rwf') => (raw: string) =>
    setValues((v) => ({ ...v, [field]: raw === '' ? null : Number(raw) }))
  const toggleDefect = (code: string) =>
    setValues((v) => ({
      ...v,
      defects: v.defects.includes(code) ? v.defects.filter((d) => d !== code) : [...v.defects, code],
    }))

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setErrors({})
    setFormError(null)
    setSaving(true)
    try {
      await onSubmit(values)
    } catch (err) {
      const fields = fieldErrors(err)
      setErrors(fields)
      setFormError(
        Object.keys(fields).length
          ? `Please correct: ${Object.keys(fields)
              .map((f) => ASSESSMENT_FIELD_LABELS[f] ?? f)
              .join(', ')}.`
          : errorMessage(err),
      )
    } finally {
      setSaving(false)
    }
  }

  const fieldError = (field: string) =>
    errors[field] && <span className="mt-1 block text-xs text-red-600">{errors[field]}</span>

  const choice = (number: number, title: string, field: ChoiceField, options: { value: string; label: string }[]) => (
    <Section number={number} title={title}>
      <ChoiceGroup name={title} options={options} value={values[field]} onChange={setChoice(field)} />
      {fieldError(field)}
    </Section>
  )

  return (
    <form onSubmit={handleSubmit} className="space-y-3" noValidate>
      {formError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          {formError}
        </p>
      )}
      <label className="block max-w-xs text-sm">
        <span className="text-slate-600">Assessment date</span>
        <input
          type="date"
          max={latestDate}
          value={values.assessment_date}
          onChange={(e) => setValues((v) => ({ ...v, assessment_date: e.target.value }))}
          className={inputClass}
        />
        {fieldError('assessment_date')}
      </label>

      {choice(1, 'Physical condition', 'physical_condition', PHYSICAL_CONDITIONS)}
      {choice(2, 'Cosmetic condition', 'cosmetic_condition', COSMETIC_CONDITIONS)}
      {choice(3, 'Screen', 'screen_condition', SCREEN_CONDITIONS)}
      {choice(4, 'Battery', 'battery_condition', BATTERY_CONDITIONS)}
      {choice(5, 'Functionality', 'functional_status', FUNCTIONAL_STATUSES)}
      {choice(6, 'Accessories', 'accessories_condition', ACCESSORIES_CONDITIONS)}

      <Section number={7} title="Defects">
        <div className="grid gap-2 sm:grid-cols-2">
          {DEFECTS.map((defect) => (
            <label key={defect.value} className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={values.defects.includes(defect.value)}
                onChange={() => toggleDefect(defect.value)}
                className="h-4 w-4 rounded border-slate-300"
              />
              {defect.label}
            </label>
          ))}
        </div>
        {fieldError('defects')}
      </Section>

      <div className="grid gap-3 sm:grid-cols-2">
        <Section number={8} title="Estimated repair cost">
          <div className="flex items-center gap-2">
            <input
              type="number"
              inputMode="numeric"
              min={0}
              step={1}
              placeholder="e.g. 18000"
              value={values.estimated_repair_cost_rwf ?? ''}
              onChange={(e) => setAmount('estimated_repair_cost_rwf')(e.target.value)}
              className={`${inputClass} mt-0`}
            />
            <span className="text-sm text-slate-500">RWF</span>
          </div>
          {fieldError('estimated_repair_cost_rwf')}
        </Section>
        <Section number={9} title="Estimated market value">
          <div className="flex items-center gap-2">
            <input
              type="number"
              inputMode="numeric"
              min={1}
              step={1}
              placeholder="e.g. 85000"
              value={values.estimated_market_value_rwf ?? ''}
              onChange={(e) => setAmount('estimated_market_value_rwf')(e.target.value)}
              className={`${inputClass} mt-0`}
            />
            <span className="text-sm text-slate-500">RWF</span>
          </div>
          {fieldError('estimated_market_value_rwf')}
        </Section>
      </div>

      <Section number={10} title="Notes">
        <textarea
          rows={3}
          placeholder="Observations, test results, anything the decision-maker should know."
          value={values.assessment_notes}
          onChange={(e) => setValues((v) => ({ ...v, assessment_notes: e.target.value }))}
          className={`${inputClass} mt-0`}
        />
        {fieldError('assessment_notes')}
      </Section>

      <p className="text-xs text-slate-500">
        You can save a draft with fields still open. Sections 1–6, 8 and 9 are required before submitting.
      </p>
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
