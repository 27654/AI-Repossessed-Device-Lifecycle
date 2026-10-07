import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { inputClass, primaryButtonClass, secondaryButtonClass } from '../../components/form'
import { ErrorMessage, Loading } from '../../components/PageState'
import { DEVICE_TYPES, INITIAL_STATUSES } from '../../config/devices'
import { deviceApi, errorMessage, fieldErrors, type Device, type DeviceInput } from '../../lib/api'

// Form values are kept as strings and converted on submit.
type FormValues = Record<Exclude<keyof DeviceInput, 'storage_capacity_gb' | 'recovery_date'>, string> & {
  storage_capacity_gb: string
  recovery_date: string
}

const EMPTY: FormValues = {
  imei: '',
  serial_number: '',
  make: '',
  model: '',
  device_type: 'SMARTPHONE',
  color: '',
  storage_capacity_gb: '',
  operating_system: '',
  condition_summary: '',
  current_location: '',
  recovery_reference: '',
  recovery_date: '',
  previous_owner_ref: '',
  notes: '',
  initial_status: 'IN_RECOVERY',
}

function fromDevice(device: Device): FormValues {
  return {
    ...EMPTY,
    imei: device.imei ?? '',
    serial_number: device.serial_number ?? '',
    make: device.make,
    model: device.model,
    device_type: device.device_type,
    color: device.color,
    storage_capacity_gb: device.storage_capacity_gb?.toString() ?? '',
    operating_system: device.operating_system,
    condition_summary: device.condition_summary,
    current_location: device.current_location,
    recovery_reference: device.recovery_reference,
    recovery_date: device.recovery_date ?? '',
    previous_owner_ref: device.previous_owner_ref,
    notes: device.notes,
  }
}

function toInput(values: FormValues, isNew: boolean): DeviceInput {
  const { initial_status, storage_capacity_gb, recovery_date, ...rest } = values
  return {
    ...rest,
    storage_capacity_gb: storage_capacity_gb ? Number(storage_capacity_gb) : null,
    recovery_date: recovery_date || null,
    ...(isNew ? { initial_status } : {}),
  }
}

function Field({ label, error, hint, children }: { label: string; error?: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="text-slate-600">{label}</span>
      {children}
      {error ? (
        <span className="mt-1 block text-xs text-red-700">{error}</span>
      ) : (
        hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>
      )}
    </label>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="rounded-lg border border-slate-200 bg-white p-4">
      <legend className="px-1 text-sm font-medium text-slate-700">{title}</legend>
      <div className="grid gap-4 sm:grid-cols-2">{children}</div>
    </fieldset>
  )
}

// Add (/devices/new) and edit (/devices/:id/edit) share this form.
export default function DeviceFormPage() {
  const { id } = useParams()
  const deviceId = id ? Number(id) : null
  const isNew = deviceId === null
  const navigate = useNavigate()

  const [values, setValues] = useState<FormValues>(EMPTY)
  const [deviceCode, setDeviceCode] = useState<string | null>(null)
  const [loading, setLoading] = useState(!isNew)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (deviceId === null) return
    let cancelled = false
    deviceApi
      .get(deviceId)
      .then((device) => {
        if (cancelled) return
        setValues(fromDevice(device))
        setDeviceCode(device.device_code)
      })
      .catch((err) => !cancelled && setLoadError(errorMessage(err, 'Could not load the device.')))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [deviceId])

  const set = (key: keyof FormValues) => (e: { target: { value: string } }) =>
    setValues((v) => ({ ...v, [key]: e.target.value }))

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setErrors({})
    setFormError(null)
    setSaving(true)
    try {
      const input = toInput(values, isNew)
      const saved = deviceId === null ? await deviceApi.create(input) : await deviceApi.update(deviceId, input)
      navigate(`/devices/${saved.id}`, { state: { saved: isNew ? 'created' : 'updated' } })
    } catch (err) {
      const fields = fieldErrors(err)
      setErrors(fields)
      setFormError(
        Object.keys(fields).length && !fields.detail ? 'Please correct the highlighted fields.' : errorMessage(err),
      )
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Loading label="Loading device…" />
  if (loadError) return <ErrorMessage message={loadError} />

  const backTo = isNew ? '/devices' : `/devices/${deviceId}`

  return (
    <div className="space-y-4">
      <div>
        <Link to={backTo} className="text-sm text-slate-500 hover:underline">
          ← {isNew ? 'Devices' : deviceCode}
        </Link>
        <h2 className="mt-1 text-xl font-semibold">{isNew ? 'Add device' : `Edit ${deviceCode}`}</h2>
      </div>

      <form onSubmit={handleSubmit} className="max-w-4xl space-y-4" noValidate>
        {formError && (
          <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
            {formError}
          </p>
        )}

        <Section title="Identification">
          <Field label="IMEI" error={errors.imei} hint="15 digits. Leave empty for devices without an IMEI.">
            <input inputMode="numeric" value={values.imei} onChange={set('imei')} className={inputClass} />
          </Field>
          <Field label="Serial number" error={errors.serial_number} hint="An IMEI or a serial number is required.">
            <input value={values.serial_number} onChange={set('serial_number')} className={inputClass} />
          </Field>
        </Section>

        <Section title="Device">
          <Field label="Make *" error={errors.make}>
            <input required value={values.make} onChange={set('make')} className={inputClass} />
          </Field>
          <Field label="Model *" error={errors.model}>
            <input required value={values.model} onChange={set('model')} className={inputClass} />
          </Field>
          <Field label="Type *" error={errors.device_type}>
            <select value={values.device_type} onChange={set('device_type')} className={`${inputClass} bg-white`}>
              {DEVICE_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Color" error={errors.color}>
            <input value={values.color} onChange={set('color')} className={inputClass} />
          </Field>
          <Field label="Storage (GB)" error={errors.storage_capacity_gb} hint="Where applicable.">
            <input
              type="number"
              min={0}
              value={values.storage_capacity_gb}
              onChange={set('storage_capacity_gb')}
              className={inputClass}
            />
          </Field>
          <Field label="Operating system" error={errors.operating_system}>
            <input value={values.operating_system} onChange={set('operating_system')} className={inputClass} />
          </Field>
        </Section>

        <Section title="Status and location">
          {isNew && (
            <Field label="Initial status" error={errors.initial_status}>
              <select
                value={values.initial_status}
                onChange={set('initial_status')}
                className={`${inputClass} bg-white`}
              >
                {INITIAL_STATUSES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label="Current location" error={errors.current_location} hint="e.g. warehouse, branch or district.">
            <input value={values.current_location} onChange={set('current_location')} className={inputClass} />
          </Field>
          <div className="sm:col-span-2">
            <Field
              label="Condition summary"
              error={errors.condition_summary}
              hint="What was observed on recovery. The formal condition rating comes from the assessment."
            >
              <textarea
                rows={3}
                value={values.condition_summary}
                onChange={set('condition_summary')}
                className={inputClass}
              />
            </Field>
          </div>
        </Section>

        <Section title="Recovery">
          <Field label="Recovery reference" error={errors.recovery_reference} hint="Repossession case or acquisition number.">
            <input value={values.recovery_reference} onChange={set('recovery_reference')} className={inputClass} />
          </Field>
          <Field label="Recovery date" error={errors.recovery_date}>
            <input type="date" value={values.recovery_date} onChange={set('recovery_date')} className={inputClass} />
          </Field>
          <Field
            label="Previous owner (Yellow account reference)"
            error={errors.previous_owner_ref}
            hint="Account reference only, e.g. YA-0012345. Never a name or ID number."
          >
            <input value={values.previous_owner_ref} onChange={set('previous_owner_ref')} className={inputClass} />
          </Field>
        </Section>

        <fieldset className="rounded-lg border border-slate-200 bg-white p-4">
          <legend className="px-1 text-sm font-medium text-slate-700">Notes</legend>
          <Field label="Notes" error={errors.notes}>
            <textarea rows={3} value={values.notes} onChange={set('notes')} className={inputClass} />
          </Field>
        </fieldset>

        <div className="flex gap-2">
          <button type="submit" disabled={saving} className={primaryButtonClass}>
            {saving ? 'Saving…' : isNew ? 'Register device' : 'Save changes'}
          </button>
          <Link to={backTo} className={secondaryButtonClass}>
            Cancel
          </Link>
        </div>
      </form>
    </div>
  )
}
