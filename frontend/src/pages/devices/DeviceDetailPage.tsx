import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { useAuth } from '../../auth/useAuth'
import { inputClass, primaryButtonClass, secondaryButtonClass } from '../../components/form'
import { EmptyState, ErrorMessage, Loading } from '../../components/PageState'
import StatusBadge from '../../components/StatusBadge'
import { ACCEPTED_UPLOAD_TYPES, conditionLabel, MAX_UPLOAD_BYTES } from '../../config/devices'
import { Perm } from '../../config/permissions'
import {
  deviceApi,
  errorMessage,
  type Attachment,
  type Device,
  type DeviceStatusChange,
} from '../../lib/api'

const dateTime = (value: string) =>
  new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
const date = (value: string) => new Date(`${value}T00:00:00`).toLocaleDateString(undefined, { dateStyle: 'medium' })

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function Card({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="font-medium">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  )
}

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-0.5 break-words text-sm text-slate-900">{children || <span className="text-slate-400">—</span>}</dd>
    </div>
  )
}

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

function AttachmentUpload({ deviceId, onUploaded }: { deviceId: number; onUploaded: () => void }) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)

  function choose(selected: File | null) {
    setError(null)
    if (selected && selected.size > MAX_UPLOAD_BYTES) {
      setError('The file is larger than 5 MB.')
      selected = null
      if (fileInput.current) fileInput.current.value = ''
    }
    setFile(selected)
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!file) return
    setError(null)
    setUploading(true)
    try {
      await deviceApi.uploadAttachment(deviceId, file, description)
      setFile(null)
      setDescription('')
      if (fileInput.current) fileInput.current.value = ''
      onUploaded()
    } catch (err) {
      setError(errorMessage(err, 'Upload failed.'))
    } finally {
      setUploading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-4 space-y-3 border-t border-slate-100 pt-4">
      <p className="text-sm font-medium text-slate-700">Upload photo or document</p>
      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-2 text-sm text-red-700">
          {error}
        </p>
      )}
      <input
        ref={fileInput}
        type="file"
        accept={ACCEPTED_UPLOAD_TYPES}
        onChange={(e) => choose(e.target.files?.[0] ?? null)}
        className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-sm file:font-medium file:text-slate-700 hover:file:bg-slate-200"
      />
      <p className="text-xs text-slate-500">JPEG, PNG, WebP or PDF, up to 5 MB.</p>
      <input
        placeholder="Description (optional)"
        maxLength={255}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        className={inputClass}
      />
      <button type="submit" disabled={!file || uploading} className={secondaryButtonClass}>
        {uploading ? 'Uploading…' : 'Upload'}
      </button>
    </form>
  )
}

function Attachments({ items }: { items: Attachment[] }) {
  if (items.length === 0) return <EmptyState title="No attachments yet" />
  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {items.map((item) => (
        <li key={item.id} className="flex gap-3 rounded-md border border-slate-200 p-2">
          <a href={item.download_url} target="_blank" rel="noreferrer" className="shrink-0">
            {item.mime_type.startsWith('image/') ? (
              <img
                src={item.download_url}
                alt={item.description || item.original_name}
                className="h-16 w-16 rounded object-cover"
                loading="lazy"
              />
            ) : (
              <span className="flex h-16 w-16 items-center justify-center rounded bg-red-50 text-xs font-semibold text-red-700">
                PDF
              </span>
            )}
          </a>
          <div className="min-w-0 text-sm">
            <a
              href={item.download_url}
              target="_blank"
              rel="noreferrer"
              className="block truncate font-medium text-slate-900 hover:underline"
            >
              {item.original_name}
            </a>
            {item.description && <p className="truncate text-slate-600">{item.description}</p>}
            <p className="text-xs text-slate-500">
              {formatSize(item.size_bytes)} · {item.uploaded_by.full_name} · {dateTime(item.created_at)}
            </p>
          </div>
        </li>
      ))}
    </ul>
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

      {saved && (
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

          <Card title="Recovery">
            <dl className="grid gap-4 sm:grid-cols-3">
              <Detail label="Recovery reference">{device.recovery_reference}</Detail>
              <Detail label="Recovery date">{device.recovery_date && date(device.recovery_date)}</Detail>
              <Detail label="Yellow account reference">{device.previous_owner_ref}</Detail>
            </dl>
          </Card>

          <Card title="Attachments">
            <Attachments items={attachments} />
            {canEdit && <AttachmentUpload deviceId={device.id} onUploaded={reloadAttachments} />}
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
