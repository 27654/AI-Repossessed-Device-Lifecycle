import { useState, type FormEvent } from 'react'
import ConfirmDialog from '../../components/ConfirmDialog'
import { inputClass, secondaryButtonClass } from '../../components/form'
import StatusBadge from '../../components/StatusBadge'
import { STEP_BADGE_CLASSES, STEP_TYPES } from '../../config/refurbishment'
import { errorMessage, refurbishmentApi, type RefurbishmentStep, type StepStatus, type WorkOrder } from '../../lib/api'
import { dateTime } from '../../lib/format'

const smallButton = 'rounded-md border border-slate-300 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60'

interface WorkOrderStepsProps {
  workOrder: WorkOrder
  canManage: boolean
  onChanged: () => void
}

// Steps of a work order. Finished steps (completed or skipped) are history and show no actions.
export default function WorkOrderSteps({ workOrder, canManage, onChanged }: WorkOrderStepsProps) {
  const active = workOrder.status === 'OPEN' || workOrder.status === 'IN_PROGRESS'
  const started = workOrder.status === 'IN_PROGRESS'
  const [stepType, setStepType] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [skipping, setSkipping] = useState<RefurbishmentStep | null>(null)
  const [skipReason, setSkipReason] = useState('')

  async function run(action: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await action()
      onChanged()
      return true
    } catch (err) {
      setError(errorMessage(err, 'Could not update the step.'))
      return false
    } finally {
      setBusy(false)
    }
  }

  async function add(e: FormEvent) {
    e.preventDefault()
    if (!stepType) return
    if (await run(() => refurbishmentApi.addStep(workOrder.id, stepType, description))) {
      setStepType('')
      setDescription('')
    }
  }

  const move = (step: RefurbishmentStep, status: StepStatus) => run(() => refurbishmentApi.updateStep(step.id, { status }))

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-slate-700">Work steps</p>
      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-2 text-sm text-red-700">
          {error}
        </p>
      )}
      {workOrder.steps.length === 0 ? (
        <p className="text-sm text-slate-500">No steps yet.</p>
      ) : (
        <ol className="divide-y divide-slate-100 rounded-md border border-slate-200">
          {workOrder.steps.map((step) => (
            <li key={step.id} className="flex flex-wrap items-start justify-between gap-2 p-3 text-sm">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-slate-900">{step.step_type_label}</span>
                  <StatusBadge status={step.status} label={step.status_label} palette={STEP_BADGE_CLASSES} />
                </div>
                {step.description && <p className="text-slate-600">{step.description}</p>}
                {step.notes && <p className="text-slate-500">Notes: {step.notes}</p>}
                {step.performed_by && (
                  <p className="text-xs text-slate-500">
                    {step.performed_by.full_name}
                    {step.completed_at ? ` · ${dateTime(step.completed_at)}` : step.started_at ? ` · started ${dateTime(step.started_at)}` : ''}
                  </p>
                )}
              </div>
              {canManage && active && (step.status === 'PENDING' || step.status === 'IN_PROGRESS') && (
                <div className="flex shrink-0 gap-1">
                  {step.status === 'PENDING' && (
                    <button type="button" disabled={busy || !started} onClick={() => move(step, 'IN_PROGRESS')} className={smallButton}>
                      Start
                    </button>
                  )}
                  <button type="button" disabled={busy || !started} onClick={() => move(step, 'COMPLETED')} className={smallButton}>
                    Complete
                  </button>
                  <button
                    type="button"
                    disabled={busy || !started}
                    onClick={() => {
                      setSkipReason('')
                      setSkipping(step)
                    }}
                    className={smallButton}
                  >
                    Skip
                  </button>
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
      {canManage && active && !started && workOrder.steps.length > 0 && (
        <p className="text-xs text-slate-500">Start the work order to work on its steps.</p>
      )}

      {canManage && active && (
        <form onSubmit={add} className="flex flex-wrap items-end gap-2">
          <label className="block text-sm">
            <span className="text-slate-600">Add step</span>
            <select value={stepType} onChange={(e) => setStepType(e.target.value)} className={`${inputClass} bg-white`}>
              <option value="">Choose…</option>
              {STEP_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block min-w-48 flex-1 text-sm">
            <span className="text-slate-600">Description (optional)</span>
            <input value={description} maxLength={255} onChange={(e) => setDescription(e.target.value)} className={inputClass} />
          </label>
          <button type="submit" disabled={busy || !stepType} className={secondaryButtonClass}>
            Add step
          </button>
        </form>
      )}

      <ConfirmDialog
        open={skipping !== null}
        title={`Skip ${skipping?.step_type_label ?? 'step'}?`}
        confirmLabel="Skip step"
        busy={busy}
        error={skipping && error}
        onConfirm={async () => {
          if (!skipping) return
          if (!skipReason.trim()) {
            setError('Give a reason for skipping this step.')
            return
          }
          if (await run(() => refurbishmentApi.updateStep(skipping.id, { status: 'SKIPPED', notes: skipReason.trim() }))) {
            setSkipping(null)
          }
        }}
        onCancel={() => {
          setError(null)
          setSkipping(null)
        }}
      >
        <label className="block text-sm">
          <span className="text-slate-600">Reason *</span>
          <textarea rows={2} value={skipReason} onChange={(e) => setSkipReason(e.target.value)} className={inputClass} />
        </label>
        <p className="mt-2 text-slate-500">A skipped step is final. Functional tests and quality checks must be completed, not skipped.</p>
      </ConfirmDialog>
    </div>
  )
}
