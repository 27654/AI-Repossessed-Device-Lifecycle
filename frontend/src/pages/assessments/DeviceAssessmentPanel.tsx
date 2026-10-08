import { useEffect, useState } from 'react'
import { useAuth } from '../../auth/useAuth'
import { AttachmentList, AttachmentUpload } from '../../components/Attachments'
import ConfirmDialog from '../../components/ConfirmDialog'
import { Card, Detail } from '../../components/Details'
import { primaryButtonClass, secondaryButtonClass } from '../../components/form'
import { ErrorMessage, Loading } from '../../components/PageState'
import StatusBadge from '../../components/StatusBadge'
import { ASSESSMENT_BADGE_CLASSES, ASSESSMENT_FIELD_LABELS } from '../../config/assessment'
import { Perm } from '../../config/permissions'
import { assessmentApi, errorMessage, fieldErrors, type Assessment, type Device } from '../../lib/api'
import { date, dateTime, rwf } from '../../lib/format'
import AIRecommendationCard from './AIRecommendationCard'
import AssessmentForm from './AssessmentForm'

interface DeviceAssessmentPanelProps {
  device: Device
  // Called after a lifecycle change (assessment submitted, final decision made).
  onLifecycleChange: (message: string) => void
  // Called after evidence is uploaded (it also appears in the device's attachments).
  onEvidenceAdded: () => void
}

const money = (value: number | null) => (value === null ? null : rwf(value))

function AssessmentDetails({ assessment }: { assessment: Assessment }) {
  return (
    <dl className="grid gap-4 sm:grid-cols-3">
      <Detail label="Physical condition">{assessment.physical_condition_label}</Detail>
      <Detail label="Cosmetic condition">{assessment.cosmetic_condition_label}</Detail>
      <Detail label="Screen">{assessment.screen_condition_label}</Detail>
      <Detail label="Battery">{assessment.battery_condition_label}</Detail>
      <Detail label="Functionality">{assessment.functional_status_label}</Detail>
      <Detail label="Accessories">{assessment.accessories_condition_label}</Detail>
      <div className="sm:col-span-3">
        <Detail label="Defects">{assessment.defect_labels.join(', ')}</Detail>
      </div>
      <Detail label="Estimated repair cost">{money(assessment.estimated_repair_cost_rwf)}</Detail>
      <Detail label="Estimated market value">{money(assessment.estimated_market_value_rwf)}</Detail>
      <Detail label="Assessment date">{date(assessment.assessment_date)}</Detail>
      <div className="sm:col-span-3">
        <Detail label="Notes">
          {assessment.assessment_notes && <span className="whitespace-pre-line">{assessment.assessment_notes}</span>}
        </Detail>
      </div>
    </dl>
  )
}

export default function DeviceAssessmentPanel({ device, onLifecycleChange, onEvidenceAdded }: DeviceAssessmentPanelProps) {
  const { hasPermission } = useAuth()
  const canAssess = hasPermission(Perm.ASSESSMENT_CREATE)

  const [reloadKey, setReloadKey] = useState(0)
  const requestKey = `${device.id}#${reloadKey}`
  const [result, setResult] = useState<{ key: string; items?: Assessment[]; error?: string } | null>(null)
  const [mode, setMode] = useState<'view' | 'create' | 'edit'>('view')
  const [confirming, setConfirming] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    assessmentApi
      .list({ device: String(device.id) })
      .then((page) => !cancelled && setResult({ key: requestKey, items: page.results }))
      .catch((err) => !cancelled && setResult({ key: requestKey, error: errorMessage(err, 'Could not load assessments.') }))
    return () => {
      cancelled = true
    }
  }, [device.id, requestKey])

  const reload = () => setReloadKey((k) => k + 1)
  const current = result?.key === requestKey ? result : null
  const awaitingAssessment = device.status === 'RECOVERED'

  if (current?.error) {
    return (
      <Card title="Condition Assessment">
        <ErrorMessage message={current.error} onRetry={reload} />
      </Card>
    )
  }
  if (!current?.items) {
    // Nothing to show for devices still in recovery; avoid a loading flash for them.
    if (device.status === 'IN_RECOVERY') return null
    return (
      <Card title="Condition Assessment">
        <Loading label="Loading assessment…" />
      </Card>
    )
  }

  const assessments = current.items
  const draft = assessments.find((a) => a.status === 'DRAFT')
  const submitted = assessments.find((a) => a.status === 'SUBMITTED')
  if (!awaitingAssessment && assessments.length === 0) return null

  async function submit() {
    if (!draft) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const done = await assessmentApi.submit(draft.id)
      setConfirming(false)
      onLifecycleChange(
        `Assessment ${done.reference} submitted. The device is now Assessed — request an AI recommendation next.`,
      )
    } catch (err) {
      const missing = Object.keys(fieldErrors(err))
      setSubmitError(
        missing.length
          ? `Complete these fields first: ${missing.map((f) => ASSESSMENT_FIELD_LABELS[f] ?? f).join(', ')}.`
          : errorMessage(err, 'Could not submit the assessment.'),
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card title="Condition Assessment">
      {notice && <p className="mb-4 rounded-md bg-green-50 p-3 text-sm text-green-800">{notice}</p>}

      {awaitingAssessment && !draft && mode !== 'create' && (
        <div className="mb-4 rounded-md border border-sky-200 bg-sky-50 p-4">
          <p className="font-medium text-sky-900">This device is ready for condition assessment.</p>
          <p className="mt-1 text-sm text-sky-800">
            {canAssess
              ? 'Record the device’s condition, attach evidence, then submit to move it to Assessed.'
              : 'A Device Assessor carries out the assessment.'}
          </p>
          {canAssess && (
            <button type="button" onClick={() => setMode('create')} className={`mt-3 ${primaryButtonClass}`}>
              Start Assessment
            </button>
          )}
        </div>
      )}

      {mode === 'create' && (
        <div className="mb-4 rounded-md border border-slate-200 p-4">
          <h4 className="mb-3 font-medium">New condition assessment</h4>
          <AssessmentForm
            submitLabel="Save draft"
            onCancel={() => setMode('view')}
            onSubmit={async (input) => {
              const created = await assessmentApi.create(device.id, input)
              setMode('view')
              setNotice(`Draft ${created.reference} saved. Add evidence if needed, then submit it.`)
              reload()
            }}
          />
        </div>
      )}

      {draft && (
        <div className="mb-4 rounded-md border border-amber-300 p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="font-medium">{draft.reference}</h4>
              <StatusBadge status="DRAFT" label={draft.status_label} palette={ASSESSMENT_BADGE_CLASSES} />
              <span className="text-sm text-slate-500">by {draft.assessor.full_name}</span>
            </div>
            {canAssess && mode === 'view' && (
              <div className="flex gap-2">
                <button type="button" onClick={() => setMode('edit')} className={secondaryButtonClass}>
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setSubmitError(null)
                    setConfirming(true)
                  }}
                  className={primaryButtonClass}
                >
                  Submit assessment
                </button>
              </div>
            )}
          </div>

          {mode === 'edit' ? (
            <AssessmentForm
              assessment={draft}
              submitLabel="Save changes"
              onCancel={() => setMode('view')}
              onSubmit={async (input) => {
                await assessmentApi.update(draft.id, input)
                setMode('view')
                setNotice(`Draft ${draft.reference} updated.`)
                reload()
              }}
            />
          ) : (
            <AssessmentDetails assessment={draft} />
          )}

          <div className="mt-4">
            <p className="mb-2 text-sm font-medium text-slate-700">Evidence</p>
            <AttachmentList items={draft.attachments} emptyTitle="No evidence attached yet" />
            {canAssess && (
              <AttachmentUpload
                title="Attach assessment evidence (photos, diagnostic reports)"
                onUpload={(file, description) => assessmentApi.uploadEvidence(draft.id, file, description)}
                onUploaded={() => {
                  reload()
                  onEvidenceAdded()
                }}
              />
            )}
          </div>

          <ConfirmDialog
            open={confirming}
            title={`Submit ${draft.reference}?`}
            confirmLabel="Submit assessment"
            busy={submitting}
            error={submitError}
            onConfirm={submit}
            onCancel={() => setConfirming(false)}
          >
            <p>
              <strong>{device.device_code}</strong> will move from <strong>Recovered</strong> to{' '}
              <strong>Assessed</strong>, and its condition rating will be set from this assessment.
            </p>
            <p className="mt-2 text-slate-500">A submitted assessment is kept as history and can no longer be edited.</p>
          </ConfirmDialog>
        </div>
      )}

      {submitted && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="font-medium">{submitted.reference}</h4>
            <StatusBadge status="SUBMITTED" label={submitted.status_label} palette={ASSESSMENT_BADGE_CLASSES} />
          </div>
          <dl className="grid gap-4 sm:grid-cols-3">
            <Detail label="Assessor">{submitted.assessor.full_name}</Detail>
            <Detail label="Assessment date">{date(submitted.assessment_date)}</Detail>
            <Detail label="Submitted">{submitted.submitted_at && dateTime(submitted.submitted_at)}</Detail>
          </dl>
          <AssessmentDetails assessment={submitted} />
          {submitted.attachments.length > 0 && (
            <div>
              <p className="mb-2 text-sm font-medium text-slate-700">Evidence</p>
              <AttachmentList items={submitted.attachments} />
            </div>
          )}
          <AIRecommendationCard
            key={submitted.id}
            assessment={submitted}
            device={device}
            onDecided={onLifecycleChange}
          />
        </div>
      )}
    </Card>
  )
}
