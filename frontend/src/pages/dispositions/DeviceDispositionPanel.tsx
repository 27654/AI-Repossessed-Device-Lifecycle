import { useEffect, useState } from 'react'
import { useAuth } from '../../auth/useAuth'
import { AttachmentList, AttachmentUpload } from '../../components/Attachments'
import ConfirmDialog from '../../components/ConfirmDialog'
import { Card, Detail } from '../../components/Details'
import { primaryButtonClass, secondaryButtonClass } from '../../components/form'
import { ErrorMessage, Loading } from '../../components/PageState'
import StatusBadge from '../../components/StatusBadge'
import { DISPOSITION_BADGE_CLASSES, DISPOSITION_FIELD_LABELS, DISPOSITION_TYPES } from '../../config/disposition'
import { Perm } from '../../config/permissions'
import { dispositionApi, errorMessage, fieldErrors, type Device, type Disposition } from '../../lib/api'
import { date, dateTime, rwf } from '../../lib/format'
import DispositionForm from './DispositionForm'

interface DeviceDispositionPanelProps {
  device: Device
  // Called after confirmation (the device status has changed).
  onLifecycleChange: (message: string) => void
  // Called after evidence is uploaded (it also appears in the device's attachments).
  onEvidenceAdded: () => void
}

const CLOSED = ['REALLOCATED', 'RESOLD', 'UNABLE_TO_REPAIR']

function DispositionHeader({ disposition }: { disposition: Disposition }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <h4 className="font-medium">{disposition.reference}</h4>
      <StatusBadge status={disposition.disposition_type} label={disposition.disposition_type_label} palette={DISPOSITION_BADGE_CLASSES} />
      <StatusBadge status={disposition.status} label={disposition.status_label} palette={DISPOSITION_BADGE_CLASSES} />
    </div>
  )
}

function DispositionDetails({ disposition }: { disposition: Disposition }) {
  const resale = disposition.disposition_type === 'RESALE'
  return (
    <dl className="grid gap-4 sm:grid-cols-3">
      <Detail label="Date">{date(disposition.disposition_date)}</Detail>
      <Detail label="Responsible">{disposition.responsible_user.full_name}</Detail>
      {resale ? (
        <>
          <Detail label="Sale price">
            {disposition.sale_price_rwf !== null && <span className="font-semibold">{rwf(disposition.sale_price_rwf)}</span>}
          </Detail>
          <Detail label="Buyer reference">{disposition.buyer_reference}</Detail>
        </>
      ) : (
        <>
          <Detail label="Destination">{disposition.destination}</Detail>
          <Detail label="Recipient reference">{disposition.recipient_reference}</Detail>
        </>
      )}
      <div className="sm:col-span-3">
        <Detail label="Notes">{disposition.notes && <span className="whitespace-pre-line">{disposition.notes}</span>}</Detail>
      </div>
      {disposition.confirmed_at && (
        <div className="sm:col-span-3">
          <Detail label="Confirmed">
            {dateTime(disposition.confirmed_at)} by {disposition.confirmed_by?.full_name}
          </Detail>
        </div>
      )}
    </dl>
  )
}

export default function DeviceDispositionPanel({ device, onLifecycleChange, onEvidenceAdded }: DeviceDispositionPanelProps) {
  const { hasPermission } = useAuth()
  const canManage = hasPermission(Perm.DISPOSITION_CREATE)

  const [reloadKey, setReloadKey] = useState(0)
  const [result, setResult] = useState<{ items?: Disposition[]; error?: string } | null>(null)
  const [mode, setMode] = useState<'view' | 'create' | 'edit'>('view')
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [confirmError, setConfirmError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    dispositionApi
      .list({ device: String(device.id) })
      .then((page) => !cancelled && setResult({ items: page.results }))
      .catch((err) => !cancelled && setResult({ error: errorMessage(err, 'Could not load dispositions.') }))
    return () => {
      cancelled = true
    }
  }, [device.id, reloadKey])

  const reload = () => setReloadKey((k) => k + 1)

  if (result?.error) {
    return (
      <Card title="Reallocation / Resale">
        <ErrorMessage message={result.error} onRetry={reload} />
      </Card>
    )
  }
  if (!result?.items) {
    return (
      <Card title="Reallocation / Resale">
        <Loading label="Loading dispositions…" />
      </Card>
    )
  }

  const draft = result.items.find((d) => d.status === 'DRAFT')
  const confirmed = result.items.find((d) => d.status === 'CONFIRMED')
  const ready = device.status === 'READY_FOR_DISPOSITION'

  if (!ready && result.items.length === 0) {
    return (
      <Card title="Reallocation / Resale">
        <p className="text-sm text-slate-500">
          {CLOSED.includes(device.status)
            ? 'No disposition was recorded for this device.'
            : 'Reallocation or resale becomes available once the device is Ready for disposition.'}
        </p>
      </Card>
    )
  }

  async function confirm() {
    if (!draft) return
    setBusy(true)
    setConfirmError(null)
    try {
      const done = await dispositionApi.confirm(draft.id)
      setConfirming(false)
      const outcome = DISPOSITION_TYPES.find((t) => t.value === done.disposition_type)?.result
      onLifecycleChange(`${done.disposition_type_label} ${done.reference} confirmed. ${device.device_code} is now ${outcome}.`)
    } catch (err) {
      const fields = fieldErrors(err)
      const missing = Object.keys(fields).map((f) => DISPOSITION_FIELD_LABELS[f] ?? f)
      setConfirmError(missing.length ? `Complete these fields first: ${missing.join(', ')}.` : errorMessage(err, 'Could not confirm.'))
    } finally {
      setBusy(false)
    }
  }

  const target = draft ? DISPOSITION_TYPES.find((t) => t.value === draft.disposition_type) : undefined

  return (
    <Card title="Reallocation / Resale">
      {notice && <p className="mb-4 rounded-md bg-green-50 p-3 text-sm text-green-800">{notice}</p>}

      {ready && !draft && mode !== 'create' && (
        <div className="mb-4 rounded-md border border-teal-200 bg-teal-50 p-4">
          <p className="font-medium text-teal-900">This device is ready for reallocation or resale.</p>
          <p className="mt-1 text-sm text-teal-800">
            {canManage
              ? 'Draft the disposition, attach evidence (receipt or handover form), then confirm it.'
              : 'A Reallocation/Sales Officer records and confirms the disposition.'}
          </p>
          {canManage && (
            <button type="button" onClick={() => setMode('create')} className={`mt-3 ${primaryButtonClass}`}>
              Create disposition
            </button>
          )}
        </div>
      )}

      {mode === 'create' && (
        <div className="mb-4 rounded-md border border-slate-200 p-4">
          <h4 className="mb-3 font-medium">New disposition</h4>
          <DispositionForm
            submitLabel="Save draft"
            onCancel={() => setMode('view')}
            onSubmit={async (input) => {
              const created = await dispositionApi.create(device.id, input)
              setMode('view')
              setNotice(`Draft ${created.reference} saved. Attach evidence if needed, then confirm it.`)
              reload()
            }}
          />
        </div>
      )}

      {draft && (
        <div className="mb-4 space-y-4 rounded-md border border-amber-300 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <DispositionHeader disposition={draft} />
            {canManage && mode === 'view' && (
              <div className="flex gap-2">
                <button type="button" onClick={() => setMode('edit')} className={secondaryButtonClass}>
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setConfirmError(null)
                    setConfirming(true)
                  }}
                  className={primaryButtonClass}
                >
                  Confirm {draft.disposition_type_label.toLowerCase()}
                </button>
              </div>
            )}
          </div>
          {mode === 'edit' ? (
            <DispositionForm
              disposition={draft}
              submitLabel="Save changes"
              onCancel={() => setMode('view')}
              onSubmit={async (input) => {
                await dispositionApi.update(draft.id, input)
                setMode('view')
                setNotice(`Draft ${draft.reference} updated.`)
                reload()
              }}
            />
          ) : (
            <DispositionDetails disposition={draft} />
          )}
          <div>
            <p className="mb-2 text-sm font-medium text-slate-700">Evidence</p>
            <AttachmentList items={draft.attachments} emptyTitle="No evidence attached yet" />
            {canManage && (
              <AttachmentUpload
                title="Attach evidence (receipt, handover form)"
                onUpload={(file, description) => dispositionApi.uploadEvidence(draft.id, file, description)}
                onUploaded={() => {
                  reload()
                  onEvidenceAdded()
                }}
              />
            )}
          </div>

          <ConfirmDialog
            open={confirming}
            title={`Confirm ${draft.disposition_type_label.toLowerCase()} ${draft.reference}?`}
            confirmLabel={`Confirm ${draft.disposition_type_label.toLowerCase()}`}
            busy={busy}
            error={confirmError}
            onConfirm={confirm}
            onCancel={() => setConfirming(false)}
          >
            <p>
              <strong>{device.device_code}</strong> will move from <strong>Ready for disposition</strong> to{' '}
              <strong>{target?.result}</strong>
              {draft.disposition_type === 'RESALE' && draft.sale_price_rwf !== null && (
                <> at <strong>{rwf(draft.sale_price_rwf)}</strong></>
              )}
              .
            </p>
            <p className="mt-2 text-slate-600">
              This is the device’s final lifecycle step. The disposition becomes a permanent record and cannot be
              edited or reversed afterwards.
            </p>
          </ConfirmDialog>
        </div>
      )}

      {confirmed && (
        <div className="space-y-3 rounded-md border border-green-200 p-4">
          <DispositionHeader disposition={confirmed} />
          <DispositionDetails disposition={confirmed} />
          {confirmed.attachments.length > 0 && (
            <div>
              <p className="mb-2 text-xs uppercase tracking-wide text-slate-500">Evidence</p>
              <AttachmentList items={confirmed.attachments} />
            </div>
          )}
        </div>
      )}
    </Card>
  )
}
