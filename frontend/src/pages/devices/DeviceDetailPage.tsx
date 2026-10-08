import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { useAuth } from '../../auth/useAuth'
import { AttachmentList, AttachmentUpload } from '../../components/Attachments'
import { Card, Detail } from '../../components/Details'
import { primaryButtonClass } from '../../components/form'
import { ErrorMessage, Loading } from '../../components/PageState'
import StatusBadge from '../../components/StatusBadge'
import { conditionLabel } from '../../config/devices'
import { Perm } from '../../config/permissions'
import { deviceApi, errorMessage, type Attachment, type Device, type DeviceStatusChange } from '../../lib/api'
import { dateTime } from '../../lib/format'
import DeviceAssessmentPanel from '../assessments/DeviceAssessmentPanel'
import DeviceRecoveryPanel from '../recovery/DeviceRecoveryPanel'

function History({ entries }: { entries: DeviceStatusChange[] }) {
  if (entries.length === 0) return <p className="text-sm text-slate-500">No status changes recorded.</p>
  return (
    <ol className="space-y-4 border-l-2 border-slate-200 pl-4">
      {entries.map((entry) => (
        <li key={entry.id} className="relative">
          <span className="absolute -left-[1.4rem] top-1 h-3 w-3 rounded-full border-2 border-white bg-brand-500" aria-hidden />
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {entry.from_status_label ? (
              <>
                <span className="text-slate-500">{entry.from_status_label}</span>
                <span aria-hidden>→</span>
              </>
            ) : (
              <span className="text-slate-500">Registered as</span>
            )}
            <StatusBadge status={entry.to_status} label={entry.to_status_label} />
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {dateTime(entry.changed_at)} · {entry.changed_by.full_name}
          </p>
          {entry.reason && <p className="mt-1 text-sm text-slate-700">{entry.reason}</p>}
        </li>
      ))}
    </ol>
  )
}

export default function DeviceDetailPage() {
  const deviceId = Number(useParams().id)
  const saved = (useLocation().state as { saved?: string } | null)?.saved
  const { hasPermission } = useAuth()
  const canEdit = hasPermission(Perm.DEVICE_UPDATE)

  const [reloadKey, setReloadKey] = useState(0)
  const requestKey = `${deviceId}#${reloadKey}`
  // The latest response, tagged with the request it answers; anything else means "loading".
  const [result, setResult] = useState<{
    key: string
    device?: Device
    history?: DeviceStatusChange[]
    error?: string
  } | null>(null)
  const [attachments, setAttachments] = useState<Attachment[]>([])
  // Message from a lifecycle action (e.g. completing a recovery), shown after the reload.
  // Tagged with the device it belongs to, so it is not shown after navigating to another device.
  const [noticeFor, setNoticeFor] = useState<{ deviceId: number; text: string } | null>(null)
  const notice = noticeFor?.deviceId === deviceId ? noticeFor.text : null

  useEffect(() => {
    let cancelled = false
    Promise.all([deviceApi.get(deviceId), deviceApi.history(deviceId), deviceApi.attachments(deviceId)])
      .then(([device, history, files]) => {
        if (cancelled) return
        setAttachments(files)
        setResult({ key: requestKey, device, history })
      })
      .catch((err) => !cancelled && setResult({ key: requestKey, error: errorMessage(err, 'Could not load the device.') }))
    return () => {
      cancelled = true
    }
  }, [deviceId, requestKey])

  const reloadAttachments = () => {
    deviceApi.attachments(deviceId).then(setAttachments).catch(() => undefined)
  }

  const current = result?.key === requestKey ? result : null
  if (current?.error) return <ErrorMessage message={current.error} onRetry={() => setReloadKey((k) => k + 1)} />
  if (!current?.device) return <Loading label="Loading device…" />
  const { device, history = [] } = current

  return (
    <div className="space-y-4">
      <div>
        <Link to="/devices" className="text-sm text-slate-500 hover:underline">
          ← Devices
        </Link>
        <div className="mt-1 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-xl font-semibold">{device.device_code}</h2>
            <StatusBadge status={device.status} label={device.status_label} />
          </div>
          {canEdit && (
            <Link to={`/devices/${device.id}/edit`} className={primaryButtonClass}>
              Edit device
            </Link>
          )}
        </div>
        <p className="text-sm text-slate-600">
          {device.make} {device.model} · {device.device_type_label} · Stage: {device.lifecycle_stage}
        </p>
      </div>

      {notice && <p className="rounded-md bg-green-50 p-3 text-sm text-green-800">{notice}</p>}

      {saved && !notice && (
        <p className="rounded-md bg-green-50 p-3 text-sm text-green-800">
          Device {saved === 'created' ? 'registered' : 'updated'}.
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Device information">
            <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <Detail label="IMEI">{device.imei && <span className="font-mono">{device.imei}</span>}</Detail>
              <Detail label="Serial number">
                {device.serial_number && <span className="font-mono">{device.serial_number}</span>}
              </Detail>
              <Detail label="Type">{device.device_type_label}</Detail>
              <Detail label="Color">{device.color}</Detail>
              <Detail label="Storage">{device.storage_capacity_gb !== null && `${device.storage_capacity_gb} GB`}</Detail>
              <Detail label="Operating system">{device.operating_system}</Detail>
            </dl>
          </Card>

          <Card title="Condition and location">
            <dl className="grid gap-4 sm:grid-cols-2">
              <Detail label="Condition rating">{conditionLabel(device.current_condition)}</Detail>
              <Detail label="Current location">{device.current_location}</Detail>
              <div className="sm:col-span-2">
                <Detail label="Condition summary">
                  {device.condition_summary && <span className="whitespace-pre-line">{device.condition_summary}</span>}
                </Detail>
              </div>
            </dl>
          </Card>

          <DeviceRecoveryPanel
            device={device}
            onCompleted={(message) => {
              setNoticeFor({ deviceId: device.id, text: message })
              setReloadKey((k) => k + 1)
            }}
            onEvidenceAdded={reloadAttachments}
          />

          <DeviceAssessmentPanel
            device={device}
            onLifecycleChange={(message) => {
              setNoticeFor({ deviceId: device.id, text: message })
              setReloadKey((k) => k + 1)
            }}
            onEvidenceAdded={reloadAttachments}
          />

          <Card title="Attachments">
            <AttachmentList items={attachments} />
            {canEdit && (
              <AttachmentUpload
                onUpload={(file, description) => deviceApi.uploadAttachment(device.id, file, description)}
                onUploaded={reloadAttachments}
              />
            )}
          </Card>
        </div>

        <div className="space-y-4">
          <Card title="Lifecycle history">
            <History entries={history} />
          </Card>
          <Card title="Record">
            <dl className="space-y-3">
              <Detail label="Registered by">{device.created_by.full_name}</Detail>
              <Detail label="Registered">{dateTime(device.created_at)}</Detail>
              <Detail label="Last updated">{dateTime(device.updated_at)}</Detail>
              {device.notes && (
                <Detail label="Notes">
                  <span className="whitespace-pre-line">{device.notes}</span>
                </Detail>
              )}
            </dl>
          </Card>
        </div>
      </div>
    </div>
  )
}
