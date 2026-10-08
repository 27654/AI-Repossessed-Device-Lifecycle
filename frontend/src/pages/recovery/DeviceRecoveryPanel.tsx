import { useEffect, useState } from 'react'
import { useAuth } from '../../auth/useAuth'
import { AttachmentList, AttachmentUpload } from '../../components/Attachments'
import ConfirmDialog from '../../components/ConfirmDialog'
import { Card, Detail } from '../../components/Details'
import { primaryButtonClass, secondaryButtonClass } from '../../components/form'
import { ErrorMessage, Loading } from '../../components/PageState'
import StatusBadge from '../../components/StatusBadge'
import { Perm } from '../../config/permissions'
import { RECOVERY_BADGE_CLASSES, SUCCESSFUL_OUTCOMES } from '../../config/recovery'
import { errorMessage, recoveryApi, type Device, type Recovery } from '../../lib/api'
import { date, dateTime } from '../../lib/format'
import RecoveryForm from './RecoveryForm'

interface DeviceRecoveryPanelProps {
  device: Device
  // Called after a recovery is completed (the device status may have changed).
  onCompleted: (message: string) => void
  // Called after evidence is uploaded (it also appears in the device's attachments).
  onEvidenceAdded: () => void
}

function OutcomeBadge({ recovery }: { recovery: Recovery }) {
  if (!recovery.outcome) return <span className="text-sm text-slate-400">Outcome not set</span>
  return <StatusBadge status={recovery.outcome} label={recovery.outcome_label} palette={RECOVERY_BADGE_CLASSES} />
}

function RecoveryDetails({ recovery }: { recovery: Recovery }) {
  return (
    <dl className="grid gap-4 sm:grid-cols-2">
      <Detail label="Recovered at">{dateTime(recovery.recovered_at)}</Detail>
      <Detail label="Method">{recovery.recovery_method_label}</Detail>
      <Detail label="Location">{recovery.recovery_location}</Detail>
      <Detail label="Recovery officer">{recovery.recovery_officer.full_name}</Detail>
      <div className="sm:col-span-2">
        <Detail label="Condition at collection">
          {recovery.condition_notes && <span className="whitespace-pre-line">{recovery.condition_notes}</span>}
        </Detail>
      </div>
      <div className="sm:col-span-2">
        <Detail label="Recovery notes">
          {recovery.notes && <span className="whitespace-pre-line">{recovery.notes}</span>}
        </Detail>
      </div>
      {recovery.completed_at && recovery.completed_by && (
        <div className="sm:col-span-2">
          <Detail label="Completed">
            {dateTime(recovery.completed_at)} by {recovery.completed_by.full_name}
          </Detail>
        </div>
      )}
    </dl>
  )
}

export default function DeviceRecoveryPanel({ device, onCompleted, onEvidenceAdded }: DeviceRecoveryPanelProps) {
  const { hasPermission } = useAuth()
  const canManage = hasPermission(Perm.RECOVERY_MANAGE)

  const [reloadKey, setReloadKey] = useState(0)
  const requestKey = `${device.id}#${reloadKey}`
  const [result, setResult] = useState<{ key: string; items?: Recovery[]; error?: string } | null>(null)
  const [mode, setMode] = useState<'view' | 'create' | 'edit'>('view')
  const [confirming, setConfirming] = useState(false)
  const [completing, setCompleting] = useState(false)
  const [completeError, setCompleteError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    recoveryApi
      .list({ device: String(device.id) })
      .then((page) => !cancelled && setResult({ key: requestKey, items: page.results }))
      .catch((err) => !cancelled && setResult({ key: requestKey, error: errorMessage(err, 'Could not load recoveries.') }))
    return () => {
      cancelled = true
    }
  }, [device.id, requestKey])

  const reload = () => setReloadKey((k) => k + 1)
  const current = result?.key === requestKey ? result : null

  const header = (
    <dl className="mb-4 grid gap-4 sm:grid-cols-3">
      <Detail label="Recovery reference">{device.recovery_reference}</Detail>
      <Detail label="Recovery date">{device.recovery_date && date(device.recovery_date)}</Detail>
      <Detail label="Yellow account reference">{device.previous_owner_ref}</Detail>
    </dl>
  )

  if (current?.error) {
    return (
      <Card title="Recovery">
        {header}
        <ErrorMessage message={current.error} onRetry={reload} />
      </Card>
    )
  }
  if (!current?.items) {
    return (
      <Card title="Recovery">
        {header}
        <Loading label="Loading recovery records…" />
      </Card>
    )
  }

  const recoveries = current.items
  const open = recoveries.find((r) => r.status === 'IN_PROGRESS')
  const past = recoveries.filter((r) => r.status === 'COMPLETED')
  const awaitingRecovery = device.status === 'IN_RECOVERY'

  async function complete() {
    if (!open) return
    setCompleting(true)
    setCompleteError(null)
    try {
      const done = await recoveryApi.complete(open.id)
      setConfirming(false)
      onCompleted(
        SUCCESSFUL_OUTCOMES.includes(done.outcome)
          ? `Recovery ${done.reference} completed. The device is now Recovered and ready for condition assessment.`
          : `Recovery ${done.reference} closed as Not recovered. The device stays In recovery for a new attempt.`,
      )
    } catch (err) {
      setCompleteError(errorMessage(err, 'Could not complete the recovery.'))
    } finally {
      setCompleting(false)
    }
  }

  return (
    <Card title="Recovery">
      {header}

      {notice && <p className="mb-4 rounded-md bg-green-50 p-3 text-sm text-green-800">{notice}</p>}

      {awaitingRecovery && !open && mode !== 'create' && (
        <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 p-4">
          <p className="font-medium text-amber-900">This device needs recovery.</p>
          <p className="mt-1 text-sm text-amber-800">
            {canManage
              ? 'Record the recovery, attach photo evidence, then complete it to move the device to Recovered.'
              : 'A Recovery Officer records and completes the recovery.'}
          </p>
          {canManage && (
            <button type="button" onClick={() => setMode('create')} className={`mt-3 ${primaryButtonClass}`}>
              Record recovery
            </button>
          )}
        </div>
      )}

      {mode === 'create' && (
        <div className="mb-4 rounded-md border border-slate-200 p-4">
          <h4 className="mb-3 font-medium">Record recovery</h4>
          <RecoveryForm
            submitLabel="Save recovery"
            onCancel={() => setMode('view')}
            onSubmit={async (input) => {
              const created = await recoveryApi.create(device.id, input)
              setMode('view')
              setNotice(`Recovery ${created.reference} saved. Add evidence if needed, then complete it.`)
              reload()
            }}
          />
        </div>
      )}

      {open && (
        <div className="mb-4 rounded-md border border-amber-300 p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="font-medium">{open.reference}</h4>
              <StatusBadge status="IN_PROGRESS" label={open.status_label} palette={RECOVERY_BADGE_CLASSES} />
              <OutcomeBadge recovery={open} />
            </div>
            {canManage && mode === 'view' && (
              <div className="flex gap-2">
                <button type="button" onClick={() => setMode('edit')} className={secondaryButtonClass}>
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setCompleteError(null)
                    setConfirming(true)
                  }}
                  className={primaryButtonClass}
                >
                  Complete recovery
                </button>
              </div>
            )}
          </div>

          {mode === 'edit' ? (
            <RecoveryForm
              recovery={open}
              submitLabel="Save changes"
              onCancel={() => setMode('view')}
              onSubmit={async (input) => {
                await recoveryApi.update(open.id, input)
                setMode('view')
                setNotice(`Recovery ${open.reference} updated.`)
                reload()
              }}
            />
          ) : (
            <RecoveryDetails recovery={open} />
          )}

          <div className="mt-4">
            <p className="mb-2 text-sm font-medium text-slate-700">Evidence</p>
            <AttachmentList items={open.attachments} emptyTitle="No evidence attached yet" />
            {canManage && (
              <AttachmentUpload
                title="Attach recovery evidence"
                onUpload={(file, description) => recoveryApi.uploadEvidence(open.id, file, description)}
                onUploaded={() => {
                  reload()
                  onEvidenceAdded()
                }}
              />
            )}
          </div>

          <ConfirmDialog
            open={confirming}
            title={`Complete ${open.reference}?`}
            confirmLabel="Complete recovery"
            busy={completing}
            error={completeError}
            onConfirm={complete}
            onCancel={() => setConfirming(false)}
          >
            {SUCCESSFUL_OUTCOMES.includes(open.outcome) ? (
              <p>
                The device <strong>{device.device_code}</strong> will move from <strong>In recovery</strong> to{' '}
                <strong>Recovered</strong>, ready for condition assessment.
              </p>
            ) : open.outcome === 'NOT_RECOVERED' ? (
              <p>
                This attempt will be closed as <strong>Not recovered</strong>. The device stays In recovery so a new
                attempt can be recorded.
              </p>
            ) : (
              <p>An outcome must be chosen before the recovery can be completed. Edit the record first.</p>
            )}
            <p className="mt-2 text-slate-500">A completed recovery is kept as history and can no longer be edited.</p>
          </ConfirmDialog>
        </div>
      )}

      {past.length > 0 && (
        <div>
          <p className="mb-2 text-sm font-medium text-slate-700">Recovery records</p>
          <ul className="space-y-3">
            {past.map((recovery) => (
              <li key={recovery.id} className="rounded-md border border-slate-200 p-3">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <span className="font-medium">{recovery.reference}</span>
                  <OutcomeBadge recovery={recovery} />
                </div>
                <RecoveryDetails recovery={recovery} />
                {recovery.attachments.length > 0 && (
                  <div className="mt-3">
                    <p className="mb-2 text-xs uppercase tracking-wide text-slate-500">Evidence</p>
                    <AttachmentList items={recovery.attachments} />
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {!awaitingRecovery && recoveries.length === 0 && (
        <p className="text-sm text-slate-500">
          No recovery record. This device was registered as already recovered.
        </p>
      )}
    </Card>
  )
}
