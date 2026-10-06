# Database design

PostgreSQL 16, database `repossessed_devices`. Proposed schema; tables are created phase by phase as each module is built.

Conventions:

- Every table has a `BIGINT` auto primary key `id` and, unless noted, `created_at` / `updated_at` timestamps.
- Money is whole **RWF** stored as `BIGINT` (no decimals).
- Enumerations are short uppercase text codes enforced by Django `choices` and database `CHECK` constraints.
- `FK → X` means a foreign key to table X. `ON DELETE PROTECT` is the default, so history rows can never be orphaned. Records are deactivated, not deleted.

---

## Accounts and RBAC

### Role
| Field | Type | Notes |
|---|---|---|
| code | varchar(40), unique | `RECOVERY_OFFICER`, `DEVICE_ASSESSOR`, `REFURBISHMENT_STAFF`, `SALES_OFFICER`, `OPERATIONS_MANAGER`, `SYSTEM_ADMIN` |
| name | varchar(80) | Display name |
| description | text | |
| permissions | M2M → Permission | via `role_permissions` join table |

### Permission
| Field | Type | Notes |
|---|---|---|
| code | varchar(60), unique | e.g. `device.create`, `ai.decide` (matrix in architecture.md §5) |
| description | varchar(200) | |

### User (`accounts_user`, extends Django `AbstractBaseUser` + `PermissionsMixin`)
| Field | Type | Notes |
|---|---|---|
| email | varchar, unique | Login identifier |
| full_name | varchar(150) | |
| phone | varchar(20) | |
| employee_id | varchar(30), unique | |
| role | FK → Role | One role per user |
| account_status | enum | `ACTIVE`, `SUSPENDED`, `DEACTIVATED` |
| password | varchar | Django hash, never exposed |
| mfa_enabled | bool | |
| mfa_secret | varchar(255), blank | TOTP secret, Fernet-encrypted, never serialized |
| mfa_last_used_step | bigint, nullable | Last accepted TOTP time step (replay protection) |
| failed_login_count | int | Reset on success |
| locked_until | timestamptz, nullable | Temporary lockout |
| is_staff, is_superuser | bool | Django admin access only; app permissions come from the role |
| last_login, created_at, updated_at | timestamptz | |

### LoginAttempt
| Field | Type | Notes |
|---|---|---|
| email_attempted | varchar | As typed |
| user | FK → User, nullable | Null if no such account |
| success | bool | |
| failure_reason | enum, nullable | `BAD_CREDENTIALS`, `LOCKED`, `INACTIVE`, `BAD_MFA_CODE` |
| ip_address | inet, nullable | |
| user_agent | varchar(255) | |
| created_at | timestamptz | indexed |

---

## Devices

### Device (central entity)
| Field | Type | Notes |
|---|---|---|
| device_code | varchar(20), unique | Human-readable ID, e.g. `YRW-2026-00042`, generated |
| make | varchar(60) | indexed |
| model | varchar(80) | indexed |
| serial_number | varchar(80), unique | |
| imei | varchar(15), unique, nullable | 15 digits, validated (Luhn). Nullable for devices without an IMEI. |
| previous_owner_ref | varchar(60) | Pseudonymous customer reference only |
| status | enum | `IN_RECOVERY`, `RECOVERED`, `ASSESSED`, `REFURBISHING`, `READY_FOR_DISPOSITION`, `REALLOCATED`, `RESOLD`, `UNABLE_TO_REPAIR`; indexed |
| current_condition | enum, nullable | `EXCELLENT`, `GOOD`, `FAIR`, `POOR`; set from the latest submitted assessment |
| created_by | FK → User | |
| created_at, updated_at | timestamptz | |

- *Lifecycle stage* is derived from `status` (architecture.md §6) and returned by the API, not stored.
- *Recovery date* and *recovery location* come from the device's Recovery record; the API returns them with the device.
- `status` and `current_condition` are the only cached values on Device. They are written only by lifecycle services, and the full history behind them lives in the related tables.

### DeviceStatusChange (lifecycle history)
| Field | Type | Notes |
|---|---|---|
| device | FK → Device | indexed |
| from_status | enum, nullable | Null for the first entry |
| to_status | enum | |
| changed_by | FK → User | |
| reason | varchar(255) | |
| source_type / source_id | varchar / bigint, nullable | The record that caused it (e.g. `assessment`, 12) |
| created_at | timestamptz | |

Used for the device history timeline and average lifecycle duration (first entry → `REALLOCATED`/`RESOLD`).

### Attachment
| Field | Type | Notes |
|---|---|---|
| device | FK → Device | Every file belongs to a device |
| content_type / object_id | FK → django_content_type / bigint, nullable | Optional link to a Recovery, Assessment, Work Order or Disposition |
| file | file path | Random name under `MEDIA_ROOT` |
| original_name | varchar(255) | |
| mime_type | varchar(50) | Validated: JPEG, PNG, WebP, PDF |
| size_bytes | int | ≤ `MAX_UPLOAD_SIZE_MB` |
| uploaded_by | FK → User | |
| created_at | timestamptz | |

---

## Lifecycle records

### Recovery
| Field | Type | Notes |
|---|---|---|
| device | FK → Device | |
| recovered_at | timestamptz | Recovery date + time |
| location | varchar(200) | e.g. district / sector |
| recovery_method | enum | **(Decision)** `FIELD_COLLECTION`, `CUSTOMER_SURRENDER`, `AGENT_DROP_OFF`, `OTHER` |
| previous_owner_ref | varchar(60) | Copied to Device on creation |
| condition_notes | text | |
| status | enum | `INITIATED`, `IN_TRANSIT`, `RECEIVED` |
| received_at | timestamptz, nullable | Set when status → `RECEIVED` |
| recorded_by | FK → User | |

Photo evidence: Attachment rows linked to the recovery.

### ConditionAssessment
| Field | Type | Notes |
|---|---|---|
| device | FK → Device | |
| assessor | FK → User | |
| physical_condition | enum | `EXCELLENT`, `GOOD`, `FAIR`, `POOR` |
| functionality | enum | `FULLY_FUNCTIONAL`, `PARTIALLY_FUNCTIONAL`, `NON_FUNCTIONAL` |
| screen_condition | enum | `NO_DAMAGE`, `MINOR_SCRATCHES`, `CRACKED`, `NOT_WORKING`, `NOT_APPLICABLE` |
| battery_condition | enum | `GOOD`, `FAIR`, `POOR`, `NOT_WORKING`, `NOT_APPLICABLE` |
| damage_notes | text | |
| overall_rating | enum | `EXCELLENT`, `GOOD`, `FAIR`, `POOR` (human decision) |
| conclusion | text | |
| recommended_action | enum | `NO_REFURBISHMENT_NEEDED`, `REFURBISH`, `UNABLE_TO_REPAIR` |
| ai_recommendation | FK → AIRecommendation, nullable | The suggestion the assessor saw, if any |
| assessed_at | timestamptz | |

Assessments are never overwritten. Modifying one is audited with before/after values. A re-assessment creates a new row, so the assessment history is kept.

### RefurbishmentWorkOrder
| Field | Type | Notes |
|---|---|---|
| work_order_number | varchar(20), unique | e.g. `WO-2026-0007`, generated |
| device | FK → Device | |
| assessment | FK → ConditionAssessment | The assessment that justified the work |
| assigned_technician | FK → User | Must have the Refurbishment Staff role |
| description | text | |
| labour_cost | bigint (RWF) | default 0 |
| status | enum | `PENDING`, `IN_PROGRESS`, `COMPLETED`, `UNABLE_TO_REPAIR` |
| started_at / completed_at | timestamptz, nullable | |
| technician_notes | text | |
| created_by | FK → User | |

Total cost = `labour_cost` + sum of item costs (computed, not stored). At most one open (`PENDING`/`IN_PROGRESS`) work order per device, enforced by a partial unique index.

### RefurbishmentStep
| Field | Type | Notes |
|---|---|---|
| work_order | FK → RefurbishmentWorkOrder | |
| step_type | enum | `CLEANING`, `PARTS_REPLACEMENT`, `SOFTWARE_RESET`, `TESTING`, `OTHER` |
| notes | text | |
| performed_by | FK → User | |
| performed_at | timestamptz | |

### RefurbishmentItem (parts/materials)
| Field | Type | Notes |
|---|---|---|
| work_order | FK → RefurbishmentWorkOrder | |
| name | varchar(120) | e.g. "Replacement screen" |
| quantity | positive int | |
| unit_cost | bigint (RWF) | |

### Disposition
| Field | Type | Notes |
|---|---|---|
| device | FK → Device | |
| decision_type | enum | `REALLOCATION`, `RESALE` |
| channel | enum | Reallocation: `INTERNAL_USE`, `PARTNER`, `OTHER_APPROVED`. Resale: `DIRECT`, `ONLINE`, `DEALER`. Checked against decision_type. |
| recipient_name | varchar(150) | Buyer or recipient |
| recipient_contact | varchar(100) | Shown only to roles with `disposition.create` or `analytics.view` |
| price | bigint (RWF), nullable | Required for resale. Nullable for reallocation. |
| disposition_date | date | |
| reason | text | |
| ai_recommendation | FK → AIRecommendation, nullable | The pricing/channel recommendation in force |
| status | enum | `PENDING_CONFIRMATION`, `CONFIRMED`, `CANCELLED` |
| confirmation_reference | varchar(60) | Receipt / handover reference |
| recorded_by / confirmed_by | FK → User | |
| confirmed_at | timestamptz, nullable | Confirming moves the device to `REALLOCATED`/`RESOLD` |

Only one `CONFIRMED` disposition per device (partial unique index). Cancelled rows are kept as history.

---

## AI decision support

### AIRecommendation
| Field | Type | Notes |
|---|---|---|
| device | FK → Device | |
| recommendation_type | enum | `CONDITION`, `PRICING_CHANNEL` |
| input_snapshot | jsonb | Exact inputs used, for reproducibility |
| recommended_condition | enum, nullable | CONDITION type |
| recommended_action | enum, nullable | CONDITION type |
| recommended_price | bigint (RWF), nullable | PRICING_CHANNEL type |
| recommended_decision_type / recommended_channel | enum, nullable | PRICING_CHANNEL type |
| confidence | smallint | 0–100 |
| explanation | text | Plain-language reasoning |
| factors | jsonb | Per-factor contributions, for display |
| price_basis | enum, nullable | `HISTORICAL_SALES`, `REFERENCE_PRICE` |
| rule_version | varchar(20) | Engine rules version |
| requested_by | FK → User | |
| decision | enum | `PENDING`, `ACCEPTED`, `OVERRIDDEN` |
| decided_by | FK → User, nullable | |
| decided_at | timestamptz, nullable | |
| override_values | jsonb, nullable | The human-chosen values |
| override_justification | text | Required when `OVERRIDDEN` |

### AIFeedback
| Field | Type | Notes |
|---|---|---|
| recommendation | FK → AIRecommendation | |
| user | FK → User | |
| helpful | bool | |
| comment | varchar(500) | |

Unique on (`recommendation`, `user`).

### ReferencePrice
| Field | Type | Notes |
|---|---|---|
| make, model | varchar | Unique together |
| base_price | bigint (RWF) | Price for a refurbished device in excellent condition |
| updated_by | FK → User | |

---

## Notifications and audit

### Notification
| Field | Type | Notes |
|---|---|---|
| recipient | FK → User | indexed with `is_read` |
| type | enum | `AWAITING_ASSESSMENT`, `ASSESSMENT_COMPLETED`, `REFURBISHMENT_ASSIGNED`, `REFURBISHMENT_COMPLETED`, `READY_FOR_DISPOSITION`, `AI_RECOMMENDATION`, `ANNOUNCEMENT` |
| title | varchar(150) | |
| message | text | |
| device | FK → Device, nullable | For deep links |
| is_read | bool | |
| read_at | timestamptz, nullable | |
| created_at | timestamptz | |

### AuditLog (append-only)
| Field | Type | Notes |
|---|---|---|
| user | FK → User, nullable, `ON DELETE SET NULL` | Null for failed logins with unknown email |
| user_label | varchar(150) | Email at the time of the action, kept if the user changes |
| action | varchar(50) | e.g. `LOGIN`, `DEVICE_CREATED`, `AI_OVERRIDDEN`; indexed |
| entity_type | varchar(50) | e.g. `device`; indexed |
| entity_id | varchar(40) | indexed with entity_type |
| previous_values | jsonb, nullable | Changed fields only |
| new_values | jsonb, nullable | |
| description | varchar(255) | |
| ip_address | inet, nullable | |
| user_agent | varchar(255) | |
| created_at | timestamptz | indexed |

No `updated_at`. No update or delete through the API or admin.

---

## Indexes and constraints (summary)

- Unique: `user.email`, `user.employee_id`, `device.device_code`, `device.serial_number`, `device.imei` (when not null), `work_order_number`, `role.code`, `permission.code`, (`reference_price.make`, `model`), (`ai_feedback.recommendation`, `user`).
- Partial unique: one open work order per device; one confirmed disposition per device.
- Check: non-negative costs and prices, confidence 0–100, `override_justification` non-empty when `decision = OVERRIDDEN`, channel valid for decision type.
- Indexes on status, make/model, created_at, and the foreign keys used for filtering.
