import { useEffect, useState, type FormEvent } from 'react'
import { useAuth } from '../../auth/useAuth'
import ConfirmDialog from '../../components/ConfirmDialog'
import { Detail } from '../../components/Details'
import { inputClass, primaryButtonClass, secondaryButtonClass } from '../../components/form'
import { ErrorMessage, Loading } from '../../components/PageState'
import StatusBadge from '../../components/StatusBadge'
import { AI_DECISIONS, DECISION_BADGE_CLASSES, SCORE_FACTORS, decisionLabel } from '../../config/assessment'
import { Perm } from '../../config/permissions'
import {
  aiApi,
  errorMessage,
  type AIDecision,
  type AIFeedback,
  type AIRecommendation,
  type Assessment,
  type Device,
} from '../../lib/api'
import { dateTime } from '../../lib/format'

interface AIRecommendationCardProps {
  assessment: Assessment
  device: Device
  // Called after the final decision (the device status has changed).
  onDecided: (message: string) => void
}

function ScoreBar({ score }: { score: number }) {
  const colour = score >= 75 ? 'bg-green-500' : score >= 35 ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div className="h-2 w-full rounded-full bg-slate-200" aria-hidden>
      <div className={`h-2 rounded-full ${colour}`} style={{ width: `${score}%` }} />
    </div>
  )
}

function DecisionForm({
  recommendation,
  device,
  onDecided,
}: {
  recommendation: AIRecommendation
  device: Device
  onDecided: (message: string) => void
}) {
  const [choice, setChoice] = useState<AIDecision>(recommendation.recommendation)
  const [reason, setReason] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const overriding = choice !== recommendation.recommendation
  const target = AI_DECISIONS.find((d) => d.value === choice)

  function review(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (overriding && !reason.trim()) {
      setError('Explain why you are overriding the AI recommendation.')
      return
    }
    setConfirming(true)
  }

  async function decide() {
    setBusy(true)
    setError(null)
    try {
      await aiApi.decide(recommendation.assessment, choice, reason.trim())
      setConfirming(false)
      onDecided(
        `Final decision recorded: ${target?.label}${overriding ? ' (AI recommendation overridden)' : ''}. ` +
          `${device.device_code} is now ${target?.result}.`,
      )
    } catch (err) {
      setError(errorMessage(err, 'Could not record the decision.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={review} className="space-y-3 rounded-md border border-slate-200 bg-white p-3">
      <h5 className="font-medium text-slate-900">Make Final Decision</h5>
      <p className="text-xs text-slate-500">
        You are responsible for this decision. It moves the device to the chosen lifecycle status.
      </p>
      <div className="space-y-2" role="radiogroup" aria-label="Final decision">
        {AI_DECISIONS.map((option) => (
          <label key={option.value} className="flex items-center gap-2 text-sm text-slate-800">
            <input
              type="radio"
              name="final_decision"
              value={option.value}
              checked={choice === option.value}
              onChange={() => setChoice(option.value)}
              className="h-4 w-4"
            />
            {option.label}
            {option.value === recommendation.recommendation && (
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">AI recommendation</span>
            )}
          </label>
        ))}
      </div>
      <label className="block text-sm">
        <span className="text-slate-600">
          Reason{overriding ? ' * (required when overriding the AI)' : ' (optional)'}
        </span>
        <textarea
          rows={2}
          maxLength={1000}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className={inputClass}
        />
      </label>
      {error && !confirming && (
        <p role="alert" className="rounded-md bg-red-50 p-2 text-sm text-red-700">
          {error}
        </p>
      )}
      <button type="submit" className={primaryButtonClass}>
        {overriding ? 'Override and decide' : 'Accept recommendation'}
      </button>

      <ConfirmDialog
        open={confirming}
        title="Record final decision?"
        confirmLabel="Record decision"
        busy={busy}
        error={error}
        onConfirm={decide}
        onCancel={() => setConfirming(false)}
      >
        <dl className="grid grid-cols-2 gap-2">
          <Detail label="AI recommendation">{recommendation.recommendation_label}</Detail>
          <Detail label="Your decision">{target?.label}</Detail>
        </dl>
        <p className="mt-3">
          <strong>{device.device_code}</strong> will move from <strong>Assessed</strong> to{' '}
          <strong>{target?.result}</strong>. The decision cannot be changed afterwards.
        </p>
        {overriding && <p className="mt-2 text-slate-600">Reason: {reason.trim()}</p>}
      </ConfirmDialog>
    </form>
  )
}

function FeedbackSection({ recommendation, onSaved }: { recommendation: AIRecommendation; onSaved: () => void }) {
  const { user, hasPermission } = useAuth()
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const mine = recommendation.feedback.find((f) => f.user.id === user?.id)

  async function send(verdict: AIFeedback['verdict']) {
    setBusy(true)
    setError(null)
    try {
      await aiApi.feedback(recommendation.assessment, verdict, comment)
      setComment('')
      onSaved()
    } catch (err) {
      setError(errorMessage(err, 'Could not save your feedback.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-slate-700">Staff feedback on this recommendation</p>
      {recommendation.feedback.length === 0 ? (
        <p className="text-sm text-slate-500">No feedback yet.</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {recommendation.feedback.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center gap-2">
              <StatusBadge status={f.verdict} label={f.verdict === 'ACCEPTED' ? 'Would accept' : 'Would override'} palette={DECISION_BADGE_CLASSES} />
              <span className="text-slate-700">{f.user.full_name}</span>
              {f.comment && <span className="text-slate-500">— {f.comment}</span>}
            </li>
          ))}
        </ul>
      )}
      {hasPermission(Perm.AI_FEEDBACK) && !mine && (
        <div className="space-y-2 rounded-md border border-slate-200 bg-white p-3">
          <p className="text-sm text-slate-700">Would you accept or override this recommendation?</p>
          <input
            placeholder="Comment (optional)"
            maxLength={500}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            className={inputClass}
          />
          {error && (
            <p role="alert" className="text-sm text-red-700">
              {error}
            </p>
          )}
          <div className="flex gap-2">
            <button type="button" disabled={busy} onClick={() => send('ACCEPTED')} className={secondaryButtonClass}>
              Accept
            </button>
            <button type="button" disabled={busy} onClick={() => send('OVERRIDDEN')} className={secondaryButtonClass}>
              Override
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function AIRecommendationCard({ assessment, device, onDecided }: AIRecommendationCardProps) {
  const { hasPermission } = useAuth()
  const canView = hasPermission(Perm.AI_VIEW)
  const canRequest = hasPermission(Perm.AI_REQUEST)
  const canDecide = hasPermission(Perm.AI_DECIDE)

  const [reloadKey, setReloadKey] = useState(0)
  // Latest loaded recommendation (kept while a reload is in flight).
  const [result, setResult] = useState<{ data?: AIRecommendation; error?: string } | null>(null)
  // A recommendation generated in this view; shown even to users who may request but not view.
  const [generated, setGenerated] = useState<AIRecommendation | null>(null)
  const [requesting, setRequesting] = useState(false)
  const [requestError, setRequestError] = useState<string | null>(null)
  const exists = assessment.has_ai_recommendation || generated !== null
  const shouldLoad = canView && exists

  useEffect(() => {
    if (!shouldLoad) return
    let cancelled = false
    aiApi
      .get(assessment.id)
      .then((data) => !cancelled && setResult({ data }))
      .catch((err) => !cancelled && setResult({ error: errorMessage(err, 'Could not load the recommendation.') }))
    return () => {
      cancelled = true
    }
  }, [assessment.id, reloadKey, shouldLoad])

  if (!canView && !canRequest) return null

  const recommendation = result?.data ?? generated
  const loading = shouldLoad && !result && !generated

  async function request() {
    setRequesting(true)
    setRequestError(null)
    try {
      setGenerated(await aiApi.generate(assessment.id))
    } catch (err) {
      setRequestError(errorMessage(err, 'Could not generate the recommendation.'))
    } finally {
      setRequesting(false)
    }
  }

  const header = (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h4 className="font-semibold text-slate-900">AI Decision Support</h4>
      <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-800">
        Explainable rule-based · not machine learning
      </span>
    </div>
  )

  return (
    <section className="space-y-3 rounded-lg border-2 border-dashed border-indigo-200 bg-indigo-50/40 p-4">
      {header}

      {result?.error && !recommendation && (
        <ErrorMessage message={result.error} onRetry={() => setReloadKey((k) => k + 1)} />
      )}
      {loading && <Loading label="Loading AI recommendation…" />}

      {!loading && !result?.error && !recommendation && (
        <div className="space-y-2">
          <p className="text-sm text-slate-700">
            The rule engine scores the submitted assessment and suggests Refurbish, Ready for disposition or Unable to
            repair, with its reasons. It does not change the device; an Operations Manager makes the final decision.
          </p>
          {requestError && (
            <p role="alert" className="rounded-md bg-red-50 p-2 text-sm text-red-700">
              {requestError}
            </p>
          )}
          {canRequest ? (
            <button type="button" onClick={request} disabled={requesting} className={primaryButtonClass}>
              {requesting ? 'Generating…' : 'Request AI Recommendation'}
            </button>
          ) : (
            <p className="text-sm text-slate-500">No recommendation has been requested yet.</p>
          )}
        </div>
      )}

      {recommendation && (
        <>
          <p className="rounded-md bg-amber-50 px-3 py-2 text-sm font-medium text-amber-900">
            {recommendation.final_decision
              ? 'AI recommendation — the human final decision is shown below.'
              : 'AI recommendation — human decision required'}
          </p>

          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-500">Recommendation</p>
              <p className="mt-1">
                <StatusBadge
                  status={recommendation.recommendation}
                  label={recommendation.recommendation_label}
                  palette={DECISION_BADGE_CLASSES}
                />
              </p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-500">Score</p>
              <p className="mt-1 text-lg font-semibold text-slate-900">{recommendation.score}/100</p>
              <ScoreBar score={recommendation.score} />
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-500">Confidence</p>
              <p className="mt-1 text-lg font-semibold text-slate-900">{Math.round(recommendation.confidence * 100)}%</p>
              <p className="text-xs text-slate-500">Distance from the nearest rule threshold, not a probability.</p>
            </div>
          </div>

          <div>
            <p className="mb-1 text-sm font-medium text-slate-700">Reasons</p>
            <ul className="list-disc space-y-1 pl-5 text-sm text-slate-800">
              {recommendation.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </div>

          <details className="text-sm">
            <summary className="cursor-pointer text-slate-600">How the score was calculated</summary>
            <table className="mt-2 w-full max-w-sm text-left">
              <tbody className="divide-y divide-slate-200">
                {SCORE_FACTORS.map((factor) => (
                  <tr key={factor.key}>
                    <td className="py-1 text-slate-600">{factor.label}</td>
                    <td className="py-1 text-right font-mono">{recommendation.factors[factor.key] ?? 0}</td>
                  </tr>
                ))}
                <tr>
                  <td className="py-1 font-medium">Score (0–100)</td>
                  <td className="py-1 text-right font-mono font-medium">{recommendation.score}</td>
                </tr>
              </tbody>
            </table>
          </details>

          <dl className="grid gap-3 text-sm sm:grid-cols-3">
            <Detail label="Rule version">{recommendation.rule_version}</Detail>
            <Detail label="Generated">{dateTime(recommendation.generated_at)}</Detail>
            <Detail label="Requested by">{recommendation.requested_by.full_name}</Detail>
          </dl>

          <div className="border-t border-indigo-100 pt-3">
            {recommendation.final_decision ? (
              <div className="space-y-2 rounded-md border border-slate-200 bg-white p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <h5 className="font-medium text-slate-900">Final decision (human)</h5>
                  {recommendation.decision_outcome && (
                    <StatusBadge
                      status={recommendation.decision_outcome}
                      label={recommendation.decision_outcome === 'ACCEPTED' ? 'AI accepted' : 'AI overridden'}
                      palette={DECISION_BADGE_CLASSES}
                    />
                  )}
                </div>
                <dl className="grid gap-3 sm:grid-cols-2">
                  <Detail label="AI recommendation">{recommendation.recommendation_label}</Detail>
                  <Detail label="Final decision">{decisionLabel(recommendation.final_decision)}</Detail>
                  <Detail label="Decision by">{recommendation.final_decision_by?.full_name}</Detail>
                  <Detail label="Decision date">
                    {recommendation.final_decision_at && dateTime(recommendation.final_decision_at)}
                  </Detail>
                  <div className="sm:col-span-2">
                    <Detail label="Reason">
                      {recommendation.final_decision_reason && (
                        <span className="whitespace-pre-line">{recommendation.final_decision_reason}</span>
                      )}
                    </Detail>
                  </div>
                </dl>
              </div>
            ) : canDecide && device.status === 'ASSESSED' ? (
              <DecisionForm recommendation={recommendation} device={device} onDecided={onDecided} />
            ) : (
              <p className="text-sm text-slate-600">Awaiting the final decision by an Operations Manager.</p>
            )}
          </div>

          {canView && (
            <div className="border-t border-indigo-100 pt-3">
              <FeedbackSection recommendation={recommendation} onSaved={() => setReloadKey((k) => k + 1)} />
            </div>
          )}
        </>
      )}
    </section>
  )
}
