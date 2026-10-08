import { useEffect, useState } from 'react'
import { useAuth } from '../../auth/useAuth'
import { AttachmentList, AttachmentUpload } from '../../components/Attachments'
import ConfirmDialog from '../../components/ConfirmDialog'
import { Card, Detail } from '../../components/Details'
import { inputClass, primaryButtonClass, secondaryButtonClass } from '../../components/form'
import { ErrorMessage, Loading } from '../../components/PageState'
import StatusBadge from '../../components/StatusBadge'
import { Perm } from '../../config/permissions'
import { COMPLETION_FIELD_LABELS, REQUIRED_CHECKS, WORK_ORDER_BADGE_CLASSES } from '../../config/refurbishment'
import { errorMessage, fieldErrors, refurbishmentApi, type Device, type WorkOrder } from '../../lib/api'
import { dateTime, rwf } from '../../lib/format'
import WorkOrderForm from './WorkOrderForm'
import WorkOrderItems from './WorkOrderItems'
import WorkOrderSteps from './WorkOrderSteps'

interface DeviceRefurbishmentPanelProps {
  device: Device
  // Called after the device's status changed (completed, or unable to repair).
  onLifecycleChange: (message: string) => void
  // Called after evidence is uploaded (it also appears in the device's attachments).
  onEvidenceAdded: () => void
}

const BEFORE_REFURBISHMENT = ['IN_RECOVERY', 'RECOVERED', 'ASSESSED']
const money = (value: number | null) => (value === null ? null : rwf(value))

function CostSummary({ workOrder }: { workOrder: WorkOrder }) {
  const closed = workOrder.actual_cost_rwf !== null
  return (
    <dl className="grid gap-4 sm:grid-cols-4">
      <Detail label="Estimated cost">{rwf(workOrder.estimated_cost_rwf)}</Detail>
      <Detail label="Parts">{rwf(workOrder.parts_cost_rwf)}</Detail>
      <Detail label="Labour">{money(workOrder.labour_cost_rwf)}</Detail>
      <Detail label={closed ? 'Actual cost' : 'Total so far'}>
        <span className="font-semibold">{rwf(workOrder.total_cost_rwf)}</span>
      </Detail>
    </dl>
  )
}

function WorkOrderHeader({ workOrder }: { workOrder: WorkOrder }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <h4 className="font-medium">{workOrder.reference}</h4>
      <StatusBadge status={workOrder.status} label={workOrder.status_label} palette={WORK_ORDER_BADGE_CLASSES} />
      {workOrder.outcome && workOrder.outcome_label && (
        <StatusBadge status={workOrder.outcome} label={workOrder.outcome_label} palette={WORK_ORDER_BADGE_CLASSES} />
      )}
    </div>
  )
}

function WorkOrderDetails({ workOrder }: { workOrder: WorkOrder }) {
  return (
    <dl className="grid gap-4 sm:grid-cols-3">
      <Detail label="Assigned to">{workOrder.assigned_to?.full_name ?? 'Unassigned'}</Detail>
      <Detail label="Started">{workOrder.started_at && dateTime(workOrder.started_at)}</Detail>
      <Detail label={workOrder.status === 'CANCELLED' ? 'Cancelled' : 'Completed'}>
        {workOrder.completed_at && `${dateTime(workOrder.completed_at)} by ${workOrder.completed_by?.full_name ?? ''}`}
      </Detail>
      <div className="sm:col-span-3">
        <Detail label="Diagnosis">{workOrder.diagnosis && <span className="whitespace-pre-line">{workOrder.diagnosis}</span>}</Detail>
      </div>
      <div className="sm:col-span-3">
        <Detail label="Work summary">
          {workOrder.work_summary && <span className="whitespace-pre-line">{workOrder.work_summary}</span>}
        </Detail>
      </div>
      {workOrder.closure_reason && (
        <div className="sm:col-span-3">
          <Detail label="Reason">
            <span className="whitespace-pre-line">{workOrder.closure_reason}</span>
          </Detail>
        </div>
      )}
    </dl>
  )
}

// What still blocks completion, shown before the technician tries.
function Readiness({ workOrder }: { workOrder: WorkOrder }) {
  const done = (type: string) => workOrder.steps.some((s) => s.step_type === type && s.status === 'COMPLETED')
  const open = workOrder.steps.filter((s) => s.status === 'PENDING' || s.status === 'IN_PROGRESS').length
  const rows = [
    ...REQUIRED_CHECKS.map((c) => ({ label: `${c.label} completed`, ok: done(c.value) })),
    { label: open ? `${open} step(s) still open` : 'All steps finished or skipped', ok: open === 0 },
  ]
  return (
    <ul className="space-y-1 text-sm">
      {rows.map((row) => (
        <li key={row.label} className={row.ok ? 'text-green-700' : 'text-slate-500'}>
          <span aria-hidden>{row.ok ? '✓' : '○'}</span> {row.label}
        </li>
      ))}
    </ul>
  )
}

type CloseAction = 'complete' | 'unable' | 'cancel' | 'start' | null

export default function DeviceRefurbishmentPanel({ device, onLifecycleChange, onEvidenceAdded }: DeviceRefurbishmentPanelProps) {
  const { hasPermission } = useAuth()
  const canManage = hasPermission(Perm.REFURBISHMENT_MANAGE)

  const [reloadKey, setReloadKey] = useState(0)
  const requestKey = `${device.id}#${reloadKey}`
  const [result, setResult] = useState<{ key: string; items?: WorkOrder[]; error?: string } | null>(null)
  const [mode, setMode] = useState<'view' | 'create' | 'edit'>('view')
  const [action, setAction] = useState<CloseAction>(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [summary, setSummary] = useState('')
  const [labour, setLabour] = useState('')
  const [reason, setReason] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    refurbishmentApi
      .list({ device: String(device.id) })
      .then((page) => !cancelled && setResult({ key: requestKey, items: page.results }))
      .catch((err) => !cancelled && setResult({ key: requestKey, error: errorMessage(err, 'Could not load work orders.') }))
    return () => {
      cancelled = true
    }
  }, [device.id, requestKey])

  const reload = () => setReloadKey((k) => k + 1)
  // Keep showing the last data while a reload is in flight, so forms do not flash.
  // (The page remounts this panel when it shows a different device.)
  const current = result

  if (current?.error) {
    return (
      <Card title="Refurbishment">
        <ErrorMessage message={current.error} onRetry={reload} />
      </Card>
    )
  }
  if (!current?.items) {
    return (
      <Card title="Refurbishment">
        <Loading label="Loading refurbishment…" />
      </Card>
    )
  }

  const workOrders = current.items
  const activeOrder = workOrders.find((w) => w.status === 'OPEN' || w.status === 'IN_PROGRESS')
  const closed = workOrders.filter((w) => w !== activeOrder)
  const refurbishing = device.status === 'REFURBISHING'

  if (workOrders.length === 0 && !refurbishing) {
    return (
      <Card title="Refurbishment">
        <p className="text-sm text-slate-500">
          {BEFORE_REFURBISHMENT.includes(device.status)
            ? 'Refurbishment becomes available after the condition assessment, when an Operations Manager decides Refurbish.'
            : 'No refurbishment was carried out for this device.'}
        </p>
      </Card>
    )
  }

  function openAction(next: CloseAction) {
    setActionError(null)
    if (activeOrder) {
      setSummary(activeOrder.work_summary)
      setLabour(activeOrder.labour_cost_rwf === null ? '' : String(activeOrder.labour_cost_rwf))
    }
    setReason('')
    setAction(next)
  }

  async function confirmAction() {
    if (!activeOrder || !action) return
    if (action === 'complete' && labour === '') {
      setActionError('Labour cost: enter the labour cost (0 if none).')
      return
    }
    setBusy(true)
    setActionError(null)
    try {
      if (action === 'start') {
        await refurbishmentApi.start(activeOrder.id)
        setAction(null)
        setNotice(`Work order ${activeOrder.reference} started.`)
        reload()
      } else if (action === 'cancel') {
        await refurbishmentApi.cancel(activeOrder.id, reason)
        setAction(null)
        setNotice(`Work order ${activeOrder.reference} cancelled. The device stays in refurbishment.`)
        reload()
      } else if (action === 'complete') {
        const done = await refurbishmentApi.complete(activeOrder.id, summary, Number(labour))
        setAction(null)
        onLifecycleChange(
          `Refurbishment ${done.reference} completed (actual cost ${rwf(done.actual_cost_rwf ?? 0)}). ` +
            `${device.device_code} is now Ready for disposition.`,
        )
      } else {
        await refurbishmentApi.unableToRepair(activeOrder.id, reason)
        setAction(null)
        onLifecycleChange(`Work order ${activeOrder.reference} closed: unable to repair. ${device.device_code} is now Unable to repair.`)
      }
    } catch (err) {
      const fields = fieldErrors(err)
      const messages = Object.entries(fields).map(([f, m]) => `${COMPLETION_FIELD_LABELS[f] ?? f}: ${m}`)
      setActionError(messages.length ? messages.join(' ') : errorMessage(err, 'The action could not be completed.'))
    } finally {
      setBusy(false)
    }
  }

  const dialogs: Record<Exclude<CloseAction, null>, { title: string; confirm: string }> = {
    start: { title: `Start ${activeOrder?.reference}?`, confirm: 'Start work' },
    complete: { title: 'Complete refurbishment and move device to Ready for disposition?', confirm: 'Complete refurbishment' },
    unable: { title: 'Mark device as unable to repair?', confirm: 'Mark unable to repair' },
    cancel: { title: `Cancel ${activeOrder?.reference}?`, confirm: 'Cancel work order' },
  }

  return (
    <Card title="Refurbishment">
      {notice && <p className="mb-4 rounded-md bg-green-50 p-3 text-sm text-green-800">{notice}</p>}

      {refurbishing && !activeOrder && mode !== 'create' && (
        <div className="mb-4 rounded-md border border-violet-200 bg-violet-50 p-4">
          <p className="font-medium text-violet-900">This device needs refurbishment.</p>
          <p className="mt-1 text-sm text-violet-800">
            {canManage
              ? 'Create a work order, record the steps and parts, then complete it to move the device to Ready for disposition.'
              : 'Refurbishment staff create and complete the work order.'}
          </p>
          {canManage && (
            <button type="button" onClick={() => setMode('create')} className={`mt-3 ${primaryButtonClass}`}>
              Create work order
            </button>
          )}
        </div>
      )}

      {mode === 'create' && (
        <div className="mb-4 rounded-md border border-slate-200 p-4">
          <h4 className="mb-3 font-medium">New work order</h4>
          <WorkOrderForm
            submitLabel="Create work order"
            onCancel={() => setMode('view')}
            onSubmit={async (input) => {
              const created = await refurbishmentApi.create(device.id, input)
              setMode('view')
              setNotice(`Work order ${created.reference} created. Start it when work begins.`)
              reload()
            }}
          />
        </div>
      )}

      {activeOrder && (
        <div className="mb-4 space-y-4 rounded-md border border-violet-300 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <WorkOrderHeader workOrder={activeOrder} />
            {canManage && mode === 'view' && (
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => setMode('edit')} className={secondaryButtonClass}>
                  Edit
                </button>
                {activeOrder.status === 'OPEN' && (
                  <button type="button" onClick={() => openAction('start')} className={primaryButtonClass}>
                    Start work
                  </button>
                )}
                {activeOrder.status === 'IN_PROGRESS' && (
                  <button type="button" onClick={() => openAction('complete')} className={primaryButtonClass}>
                    Complete refurbishment
                  </button>
                )}
                <button type="button" onClick={() => openAction('unable')} className={secondaryButtonClass}>
                  Unable to repair
                </button>
                <button type="button" onClick={() => openAction('cancel')} className={secondaryButtonClass}>
                  Cancel
                </button>
              </div>
            )}
          </div>

          {mode === 'edit' ? (
            <WorkOrderForm
              workOrder={activeOrder}
              submitLabel="Save changes"
              onCancel={() => setMode('view')}
              onSubmit={async (input) => {
                await refurbishmentApi.update(activeOrder.id, input)
                setMode('view')
                setNotice(`Work order ${activeOrder.reference} updated.`)
                reload()
              }}
            />
          ) : (
            <WorkOrderDetails workOrder={activeOrder} />
          )}
          <CostSummary workOrder={activeOrder} />
          <WorkOrderSteps workOrder={activeOrder} canManage={canManage} onChanged={reload} />
          <WorkOrderItems workOrder={activeOrder} canManage={canManage} onChanged={reload} />

          <div>
            <p className="mb-2 text-sm font-medium text-slate-700">Evidence</p>
            <AttachmentList items={activeOrder.attachments} emptyTitle="No refurbishment evidence yet" />
            {canManage && (
              <AttachmentUpload
                title="Attach refurbishment evidence (before/after photos, test reports)"
                onUpload={(file, description) => refurbishmentApi.uploadEvidence(activeOrder.id, file, description)}
                onUploaded={() => {
                  reload()
                  onEvidenceAdded()
                }}
              />
            )}
          </div>

          {activeOrder.status === 'IN_PROGRESS' && (
            <div className="rounded-md bg-slate-50 p-3">
              <p className="mb-1 text-sm font-medium text-slate-700">Ready to complete?</p>
              <Readiness workOrder={activeOrder} />
            </div>
          )}

          <ConfirmDialog
            open={action !== null}
            title={action ? dialogs[action].title : ''}
            confirmLabel={action ? dialogs[action].confirm : ''}
            busy={busy}
            error={actionError}
            onConfirm={confirmAction}
            onCancel={() => setAction(null)}
          >
            {action === 'start' && <p>The work order moves to In progress and its steps can be worked on.</p>}
            {action === 'complete' && (
              <div className="space-y-3">
                <p>
                  <strong>{device.device_code}</strong> will move from <strong>Refurbishing</strong> to{' '}
                  <strong>Ready for disposition</strong>. The work order becomes read-only.
                </p>
                <label className="block text-sm">
                  <span className="text-slate-600">Work summary *</span>
                  <textarea rows={2} value={summary} onChange={(e) => setSummary(e.target.value)} className={inputClass} />
                </label>
                <label className="block text-sm">
                  <span className="text-slate-600">Labour cost (RWF) *</span>
                  <input type="number" min={0} step={1} value={labour} onChange={(e) => setLabour(e.target.value)} className={inputClass} />
                </label>
                <p className="text-slate-600">
                  Actual cost = parts {rwf(activeOrder.parts_cost_rwf)} + labour{' '}
                  {labour === '' ? '—' : rwf(Number(labour))} ={' '}
                  <strong>{rwf(activeOrder.parts_cost_rwf + (labour === '' ? 0 : Number(labour)))}</strong>
                </p>
              </div>
            )}
            {(action === 'unable' || action === 'cancel') && (
              <div className="space-y-3">
                <p>
                  {action === 'unable' ? (
                    <>
                      <strong>{device.device_code}</strong> will move to <strong>Unable to repair</strong>. This cannot be
                      undone.
                    </>
                  ) : (
                    'The work order is closed without changing the device, which stays in refurbishment for a new work order.'
                  )}
                </p>
                <label className="block text-sm">
                  <span className="text-slate-600">Reason *</span>
                  <textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} className={inputClass} />
                </label>
              </div>
            )}
          </ConfirmDialog>
        </div>
      )}

      {closed.length > 0 && (
        <div>
          <p className="mb-2 text-sm font-medium text-slate-700">Refurbishment history</p>
          <ul className="space-y-3">
            {closed.map((workOrder) => (
              <li key={workOrder.id} className="space-y-3 rounded-md border border-slate-200 p-3">
                <WorkOrderHeader workOrder={workOrder} />
                <WorkOrderDetails workOrder={workOrder} />
                <CostSummary workOrder={workOrder} />
                <WorkOrderSteps workOrder={workOrder} canManage={false} onChanged={reload} />
                <WorkOrderItems workOrder={workOrder} canManage={false} onChanged={reload} />
                {workOrder.attachments.length > 0 && (
                  <div>
                    <p className="mb-2 text-xs uppercase tracking-wide text-slate-500">Evidence</p>
                    <AttachmentList items={workOrder.attachments} />
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  )
}
