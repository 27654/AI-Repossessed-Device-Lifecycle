// Thin fetch wrapper for the Django REST API.
// Session cookies carry authentication; unsafe methods send Django's CSRF token.

// Fired when the server answers 401 to a normal request: the session ended
// (logout elsewhere, idle timeout, account suspended). AuthProvider listens.
export const UNAUTHORIZED_EVENT = 'auth:unauthorized'

export class ApiError extends Error {
  status: number
  data: unknown

  constructor(status: number, message: string, data: unknown) {
    super(message)
    this.status = status
    this.data = data
  }
}

function getCookie(name: string): string | undefined {
  return document.cookie
    .split('; ')
    .find((row) => row.startsWith(`${name}=`))
    ?.split('=')[1]
}

const SAFE_METHODS = ['GET', 'HEAD', 'OPTIONS']

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase()
  const headers = new Headers(options.headers)

  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  if (!SAFE_METHODS.includes(method)) {
    const csrfToken = getCookie('csrftoken')
    if (csrfToken) headers.set('X-CSRFToken', csrfToken)
  }

  const response = await fetch(`/api${path}`, {
    ...options,
    method,
    headers,
    credentials: 'same-origin',
  })

  const data = response.status === 204 ? null : await response.json().catch(() => null)

  if (response.status === 401 && !path.startsWith('/auth/')) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  }
  if (!response.ok) {
    const detail = (data as { detail?: string } | null)?.detail
    throw new ApiError(response.status, detail ?? `Request failed (${response.status})`, data)
  }
  return data as T
}

export interface HealthStatus {
  status: 'ok' | 'degraded'
  database: 'ok' | 'unavailable'
  database_engine: string
  currency: string
}

export const getHealth = () => apiRequest<HealthStatus>('/health/')

// --- Authentication ---

export interface Role {
  code: string
  name: string
}

export interface CurrentUser {
  id: number
  full_name: string
  email: string
  phone: string
  employee_id: string
  role: Role | null
  permissions: string[]
  account_status: 'ACTIVE' | 'SUSPENDED' | 'DEACTIVATED'
  mfa_enabled: boolean
  last_login: string | null
  created_at: string
}

export type LoginResponse = { mfa_required: true } | { mfa_required: false; user: CurrentUser }

export interface MfaSetup {
  secret: string
  otpauth_uri: string
}

const post = <T>(path: string, body?: unknown) =>
  apiRequest<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const authApi = {
  csrf: () => apiRequest<{ detail: string }>('/auth/csrf/'),
  me: () => apiRequest<CurrentUser>('/auth/me/'),
  login: (email: string, password: string) => post<LoginResponse>('/auth/login/', { email, password }),
  verifyMfa: (code: string) => post<{ user: CurrentUser }>('/auth/mfa/verify/', { code }),
  logout: () => post<null>('/auth/logout/'),
  changePassword: (current_password: string, new_password: string) =>
    post<{ detail: string }>('/auth/change-password/', { current_password, new_password }),
  setupMfa: () => post<MfaSetup>('/auth/mfa/setup/'),
  confirmMfa: (code: string) => post<CurrentUser>('/auth/mfa/confirm/', { code }),
  disableMfa: (password: string, code: string) => post<CurrentUser>('/auth/mfa/disable/', { password, code }),
}

// First error message from a DRF error body: `detail`, or the first field error.
export function errorMessage(err: unknown, fallback = 'Something went wrong. Please try again.'): string {
  if (!(err instanceof ApiError)) return fallback
  const data = err.data as Record<string, unknown> | null
  if (data && typeof data.detail === 'string') return data.detail
  if (data) {
    for (const value of Object.values(data)) {
      if (Array.isArray(value) && typeof value[0] === 'string') return value[0]
      if (typeof value === 'string') return value
    }
  }
  return err.message || fallback
}

// Field errors from a DRF 400 body, first message per field.
export function fieldErrors(err: unknown): Record<string, string> {
  if (!(err instanceof ApiError) || err.status !== 400 || !err.data || typeof err.data !== 'object') return {}
  const errors: Record<string, string> = {}
  for (const [field, value] of Object.entries(err.data as Record<string, unknown>)) {
    if (Array.isArray(value) && typeof value[0] === 'string') errors[field] = value[0]
    else if (typeof value === 'string') errors[field] = value
  }
  return errors
}

// --- Devices ---

export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export interface UserLabel {
  id: number
  full_name: string
}

export interface DeviceSummary {
  id: number
  device_code: string
  imei: string | null
  serial_number: string | null
  make: string
  model: string
  device_type: string
  device_type_label: string
  status: string
  status_label: string
  lifecycle_stage: string
  current_condition: string | null
  current_location: string
  recovery_date: string | null
  created_at: string
}

export interface Device extends DeviceSummary {
  color: string
  storage_capacity_gb: number | null
  operating_system: string
  condition_summary: string
  recovery_reference: string
  previous_owner_ref: string
  notes: string
  created_by: UserLabel
  attachment_count: number
  updated_at: string
}

// Fields a user may send when creating or editing a device.
export interface DeviceInput {
  imei: string
  serial_number: string
  make: string
  model: string
  device_type: string
  color: string
  storage_capacity_gb: number | null
  operating_system: string
  condition_summary: string
  current_location: string
  recovery_reference: string
  recovery_date: string | null
  previous_owner_ref: string
  notes: string
  initial_status?: string
}

export interface DeviceStatusChange {
  id: number
  from_status: string | null
  from_status_label: string | null
  to_status: string
  to_status_label: string
  changed_by: UserLabel
  changed_at: string
  reason: string
  source_type: string
  source_id: number | null
}

export interface Attachment {
  id: number
  original_name: string
  mime_type: string
  size_bytes: number
  description: string
  uploaded_by: UserLabel
  created_at: string
  download_url: string
  // Set when the file is evidence for a recovery record or an assessment.
  recovery: number | null
  recovery_reference: string | null
  assessment: number | null
  assessment_reference: string | null
  refurbishment: number | null
  refurbishment_reference: string | null
}

export type DeviceFilters = Partial<
  Record<'search' | 'status' | 'make' | 'device_type' | 'condition' | 'recovered_from' | 'recovered_to' | 'page', string>
>

function queryString(params: Record<string, string | undefined>): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) if (value) query.set(key, value)
  const text = query.toString()
  return text ? `?${text}` : ''
}

export const deviceApi = {
  list: (filters: DeviceFilters) => apiRequest<Paginated<DeviceSummary>>(`/devices/${queryString(filters)}`),
  get: (id: number) => apiRequest<Device>(`/devices/${id}/`),
  create: (input: DeviceInput) => post<Device>('/devices/', input),
  update: (id: number, input: Partial<DeviceInput>) =>
    apiRequest<Device>(`/devices/${id}/`, { method: 'PATCH', body: JSON.stringify(input) }),
  history: (id: number) => apiRequest<DeviceStatusChange[]>(`/devices/${id}/history/`),
  attachments: (id: number) => apiRequest<Attachment[]>(`/devices/${id}/attachments/`),
  uploadAttachment: (id: number, file: File, description: string) => {
    const body = new FormData()
    body.append('file', file)
    body.append('description', description)
    return apiRequest<Attachment>(`/devices/${id}/attachments/`, { method: 'POST', body })
  },
}

// --- Recovery ---

export interface Recovery {
  id: number
  reference: string
  device: number
  device_summary: {
    id: number
    device_code: string
    make: string
    model: string
    status: string
    status_label: string
  }
  recovery_officer: UserLabel
  recovered_at: string
  recovery_location: string
  recovery_method: string
  recovery_method_label: string
  outcome: string
  outcome_label: string
  condition_notes: string
  notes: string
  status: 'IN_PROGRESS' | 'COMPLETED'
  status_label: string
  completed_by: UserLabel | null
  completed_at: string | null
  attachments: Attachment[]
  created_at: string
  updated_at: string
}

// Fields an officer may set while a recovery is in progress.
export interface RecoveryInput {
  recovered_at: string
  recovery_location: string
  recovery_method: string
  outcome: string
  condition_notes: string
  notes: string
}

export type RecoveryFilters = Partial<Record<'device' | 'status' | 'outcome' | 'search' | 'page', string>>

export const recoveryApi = {
  list: (filters: RecoveryFilters) => apiRequest<Paginated<Recovery>>(`/recoveries/${queryString(filters)}`),
  get: (id: number) => apiRequest<Recovery>(`/recoveries/${id}/`),
  create: (device: number, input: RecoveryInput) => post<Recovery>('/recoveries/', { device, ...input }),
  update: (id: number, input: Partial<RecoveryInput>) =>
    apiRequest<Recovery>(`/recoveries/${id}/`, { method: 'PATCH', body: JSON.stringify(input) }),
  complete: (id: number) => post<Recovery>(`/recoveries/${id}/complete/`),
  uploadEvidence: (id: number, file: File, description: string) => {
    const body = new FormData()
    body.append('file', file)
    body.append('description', description)
    return apiRequest<Attachment>(`/recoveries/${id}/attachments/`, { method: 'POST', body })
  },
}

// --- Condition assessment ---

export interface DeviceLabel {
  id: number
  device_code: string
  make: string
  model: string
  status: string
  status_label: string
}

export interface Assessment {
  id: number
  reference: string
  device: number
  device_summary: DeviceLabel
  assessor: UserLabel
  assessment_date: string
  physical_condition: string
  physical_condition_label: string
  cosmetic_condition: string
  cosmetic_condition_label: string
  screen_condition: string
  screen_condition_label: string
  battery_condition: string
  battery_condition_label: string
  functional_status: string
  functional_status_label: string
  accessories_condition: string
  accessories_condition_label: string
  defects: string[]
  defect_labels: string[]
  assessment_notes: string
  estimated_repair_cost_rwf: number | null
  estimated_market_value_rwf: number | null
  status: 'DRAFT' | 'SUBMITTED'
  status_label: string
  submitted_at: string | null
  has_ai_recommendation: boolean
  attachments: Attachment[]
  created_at: string
  updated_at: string
}

// Fields an assessor may set while the assessment is a draft.
export interface AssessmentInput {
  assessment_date: string
  physical_condition: string
  cosmetic_condition: string
  screen_condition: string
  battery_condition: string
  functional_status: string
  accessories_condition: string
  defects: string[]
  assessment_notes: string
  estimated_repair_cost_rwf: number | null
  estimated_market_value_rwf: number | null
}

export type AssessmentFilters = Partial<Record<'device' | 'status' | 'search' | 'page', string>>

export const assessmentApi = {
  list: (filters: AssessmentFilters) => apiRequest<Paginated<Assessment>>(`/assessments/${queryString(filters)}`),
  get: (id: number) => apiRequest<Assessment>(`/assessments/${id}/`),
  create: (device: number, input: AssessmentInput) => post<Assessment>('/assessments/', { device, ...input }),
  update: (id: number, input: Partial<AssessmentInput>) =>
    apiRequest<Assessment>(`/assessments/${id}/`, { method: 'PATCH', body: JSON.stringify(input) }),
  submit: (id: number) => post<Assessment>(`/assessments/${id}/submit/`),
  uploadEvidence: (id: number, file: File, description: string) => {
    const body = new FormData()
    body.append('file', file)
    body.append('description', description)
    return apiRequest<Attachment>(`/assessments/${id}/attachments/`, { method: 'POST', body })
  },
}

// --- AI decision support ---

export type AIDecision = 'REFURBISH' | 'READY_FOR_DISPOSITION' | 'UNABLE_TO_REPAIR'

export interface AIFeedback {
  id: number
  user: UserLabel
  verdict: 'ACCEPTED' | 'OVERRIDDEN'
  verdict_label: string
  comment: string
  created_at: string
}

export interface AIRecommendation {
  id: number
  assessment: number
  assessment_reference: string
  device_summary: DeviceLabel
  recommendation: AIDecision
  recommendation_label: string
  score: number
  confidence: number
  reasons: string[]
  factors: Record<string, number>
  rule_version: string
  method: string
  requested_by: UserLabel
  generated_at: string
  final_decision: AIDecision | null
  final_decision_label: string | null
  final_decision_by: UserLabel | null
  final_decision_at: string | null
  final_decision_reason: string
  decision_outcome: 'ACCEPTED' | 'OVERRIDDEN' | null
  feedback: AIFeedback[]
}

export type AIRecommendationFilters = Partial<
  Record<'decision' | 'recommendation' | 'outcome' | 'search' | 'page', string>
>

export const aiApi = {
  list: (filters: AIRecommendationFilters) =>
    apiRequest<Paginated<AIRecommendation>>(`/ai-recommendations/${queryString(filters)}`),
  get: (assessmentId: number) => apiRequest<AIRecommendation>(`/assessments/${assessmentId}/ai-recommendation/`),
  generate: (assessmentId: number) => post<AIRecommendation>(`/assessments/${assessmentId}/ai-recommendation/`),
  decide: (assessmentId: number, final_decision: AIDecision, reason: string) =>
    post<AIRecommendation>(`/assessments/${assessmentId}/decision/`, { final_decision, reason }),
  feedback: (assessmentId: number, verdict: AIFeedback['verdict'], comment: string) =>
    post<AIFeedback>(`/assessments/${assessmentId}/ai-feedback/`, { verdict, comment }),
}

// --- Refurbishment ---

export type WorkOrderStatus = 'OPEN' | 'IN_PROGRESS' | 'COMPLETED' | 'CANCELLED'
export type StepStatus = 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'SKIPPED'

export interface RefurbishmentStep {
  id: number
  work_order: number
  step_type: string
  step_type_label: string
  description: string
  status: StepStatus
  status_label: string
  performed_by: UserLabel | null
  started_at: string | null
  completed_at: string | null
  notes: string
  created_at: string
  updated_at: string
}

export interface RefurbishmentItem {
  id: number
  work_order: number
  item_name: string
  part_number: string
  quantity: number
  unit_cost_rwf: number
  total_cost_rwf: number
  supplier: string
  notes: string
  created_by: UserLabel
  created_at: string
  updated_at: string
}

export interface WorkOrder {
  id: number
  reference: string
  device: number
  device_summary: DeviceLabel
  assigned_to: UserLabel | null
  created_by: UserLabel
  status: WorkOrderStatus
  status_label: string
  outcome: '' | 'REPAIRED' | 'UNABLE_TO_REPAIR'
  outcome_label: string | null
  diagnosis: string
  work_summary: string
  estimated_cost_rwf: number
  labour_cost_rwf: number | null
  parts_cost_rwf: number
  total_cost_rwf: number
  actual_cost_rwf: number | null
  closure_reason: string
  started_at: string | null
  completed_at: string | null
  completed_by: UserLabel | null
  steps: RefurbishmentStep[]
  items: RefurbishmentItem[]
  attachments: Attachment[]
  created_at: string
  updated_at: string
}

// Planning fields of an active work order.
export interface WorkOrderInput {
  assigned_to: number | null
  diagnosis: string
  estimated_cost_rwf: number
  work_summary?: string
  labour_cost_rwf?: number | null
}

export interface ItemInput {
  item_name: string
  part_number: string
  quantity: number
  unit_cost_rwf: number
  supplier: string
  notes: string
}

export type WorkOrderFilters = Partial<Record<'device' | 'status' | 'assigned_to' | 'search' | 'page', string>>

const patch = <T>(path: string, body: unknown) =>
  apiRequest<T>(path, { method: 'PATCH', body: JSON.stringify(body) })

export const refurbishmentApi = {
  list: (filters: WorkOrderFilters) => apiRequest<Paginated<WorkOrder>>(`/refurbishments/${queryString(filters)}`),
  get: (id: number) => apiRequest<WorkOrder>(`/refurbishments/${id}/`),
  technicians: () => apiRequest<UserLabel[]>('/refurbishments/technicians/'),
  create: (device: number, input: WorkOrderInput) => post<WorkOrder>('/refurbishments/', { device, ...input }),
  update: (id: number, input: Partial<WorkOrderInput>) => patch<WorkOrder>(`/refurbishments/${id}/`, input),
  start: (id: number) => post<WorkOrder>(`/refurbishments/${id}/start/`),
  complete: (id: number, work_summary: string, labour_cost_rwf: number) =>
    post<WorkOrder>(`/refurbishments/${id}/complete/`, { work_summary, labour_cost_rwf }),
  unableToRepair: (id: number, reason: string) => post<WorkOrder>(`/refurbishments/${id}/unable-to-repair/`, { reason }),
  cancel: (id: number, reason: string) => post<WorkOrder>(`/refurbishments/${id}/cancel/`, { reason }),
  addStep: (id: number, step_type: string, description: string) =>
    post<RefurbishmentStep>(`/refurbishments/${id}/steps/`, { step_type, description }),
  updateStep: (stepId: number, input: Partial<Pick<RefurbishmentStep, 'status' | 'description' | 'notes'>>) =>
    patch<RefurbishmentStep>(`/refurbishment-steps/${stepId}/`, input),
  addItem: (id: number, input: ItemInput) => post<RefurbishmentItem>(`/refurbishments/${id}/items/`, input),
  updateItem: (itemId: number, input: Partial<ItemInput>) => patch<RefurbishmentItem>(`/refurbishment-items/${itemId}/`, input),
  uploadEvidence: (id: number, file: File, description: string) => {
    const body = new FormData()
    body.append('file', file)
    body.append('description', description)
    return apiRequest<Attachment>(`/refurbishments/${id}/attachments/`, { method: 'POST', body })
  },
}
