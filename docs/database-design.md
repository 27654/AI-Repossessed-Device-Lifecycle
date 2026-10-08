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
| device_code | varchar(20), unique | Human-readable ID, e.g. `YRW-2026-00042`, numbered by the `devices_device_code_seq` sequence |
| imei | varchar(15), unique, nullable | 15 digits (CHECK constraint), Luhn-validated by the API. Null for devices without an IMEI. |
| serial_number | varchar(80), unique, nullable | Stored upper-case without spaces |
| make | varchar(60) | indexed |
| model | varchar(80) | indexed |
| device_type | enum | `SMARTPHONE`, `FEATURE_PHONE`, `TABLET`, `LAPTOP`, `TELEVISION`, `SOLAR_HOME_SYSTEM`, `OTHER` |
| color | varchar(40) | |
| storage_capacity_gb | int, nullable | Where applicable |
| operating_system | varchar(60) | |
| status | enum | `IN_RECOVERY`, `RECOVERED`, `ASSESSED`, `REFURBISHING`, `READY_FOR_DISPOSITION`, `REALLOCATED`, `RESOLD`, `UNABLE_TO_REPAIR`; indexed; CHECK constraint |
| current_condition | enum, nullable | `EXCELLENT`, `GOOD`, `FAIR`, `POOR`; set from the latest submitted assessment (read-only in the device API) |
| condition_summary | text | Free-text observations, e.g. on recovery |
| current_location | varchar(200) | Warehouse, branch or district |
| recovery_reference | varchar(60) | Repossession case / acquisition reference |
| recovery_date | date, nullable | indexed; used by the `recovered_from`/`recovered_to` filters |
| previous_owner_ref | varchar(60) | Pseudonymous Yellow account reference only (no names, national IDs or financial data) |
| notes | text | |
| created_by | FK → User | |
| created_at, updated_at | timestamptz | |

- CHECK: at least one of `imei` / `serial_number` is present.
- *Lifecycle stage* is derived from `status` (architecture.md §6) and returned by the API, not stored.
- `status` and `current_condition` are the only cached values on Device. They are written only by lifecycle services (`devices.services`), and the full history behind them lives in the related tables.
- **(Decision)** `recovery_reference` and `recovery_date` are captured at registration so devices can be filtered by recovery date before the Recovery module exists. The Recovery module keeps them in step with its records (see Recovery below).

### DeviceStatusChange (lifecycle history, append-only)
| Field | Type | Notes |
|---|---|---|
| device | FK → Device, `PROTECT` | indexed |
| from_status | enum, nullable | Null for the registration entry |
| to_status | enum | |
| changed_by | FK → User, `PROTECT` | |
| reason | varchar(255) | |
| source_type / source_id | varchar / bigint, nullable | The record that caused it (e.g. `recovery`, 12); `device_registration` for the first entry |
| changed_at | timestamptz | indexed |

A PostgreSQL trigger rejects `UPDATE` and `DELETE`. Used for the device history timeline and average lifecycle duration (first entry → `REALLOCATED`/`RESOLD`).

### Attachment
| Field | Type | Notes |
|---|---|---|
| device | FK → Device, `PROTECT` | Every file belongs to a device |
| recovery | FK → Recovery, nullable, `PROTECT` | Set when the file is evidence for a recovery (same device, checked in the service) |
| assessment | FK → Assessment, nullable, `PROTECT` | Set when the file is evidence for an assessment (same device, checked in the service) |
| refurbishment | FK → RefurbishmentWorkOrder, nullable, `PROTECT` | Set when the file is evidence for a work order (same device, checked in the service) |
| file | file path | `attachments/YYYY/MM/<uuid4>.<ext>` under `MEDIA_ROOT`; never returned by the API |
| original_name | varchar(255) | Base name only, sanitised |
| mime_type | varchar(50) | Detected from the file signature: JPEG, PNG, WebP, PDF |
| size_bytes | int | ≤ `MAX_UPLOAD_SIZE_MB` |
| description | varchar(255) | Optional |
| uploaded_by | FK → User | |
| created_at | timestamptz | |

**(Decision)** A lifecycle record links its evidence through a nullable foreign key on Attachment, one per module (`recovery`, `assessment`, `refurbishment`; disposition when that module is built). A CHECK constraint (`attachment_single_lifecycle_link_v2`) allows at most one of these links per file. This replaces the earlier generic `content_type` / `object_id` idea: real foreign keys give referential integrity and simple queries. All files keep the same upload checks, storage and authenticated download.

---

## Lifecycle records

### Recovery
One attempt to repossess a device. Kept as historical evidence.

| Field | Type | Notes |
|---|---|---|
| reference | varchar(20), unique | `RCV-<year>-<number>`, from the `recovery_recovery_reference_seq` sequence |
| device | FK → Device, `PROTECT` | |
| recovery_officer | FK → User, `PROTECT` | The officer who recorded it (the signed-in user) |
| recovered_at | timestamptz | When the device was recovered, or the attempt was made; not in the future |
| recovery_location | varchar(200) | e.g. sector / district |
| recovery_method | enum | **(Decision)** `FIELD_COLLECTION`, `CUSTOMER_SURRENDER`, `AGENT_DROP_OFF`, `OTHER` |
| outcome | enum, blank until known | `RECOVERED`, `RECOVERED_WITH_ISSUES`, `NOT_RECOVERED` |
| condition_notes | text | Visible condition at collection |
| notes | text | Required to complete with `RECOVERED_WITH_ISSUES` (the issues) or `NOT_RECOVERED` (why) |
| status | enum | `IN_PROGRESS` (editable) → `COMPLETED` (locked) |
| completed_by / completed_at | FK → User / timestamptz, nullable | Set on completion |
| created_at / updated_at | timestamptz | |

Constraints:
- At most one `IN_PROGRESS` recovery per device (partial unique index).
- At most one completed recovery with a successful outcome per device (partial unique index).
- A `COMPLETED` row must have an outcome, `completed_by` and `completed_at` (CHECK).
- A PostgreSQL trigger rejects `UPDATE` of a completed row and `DELETE` of any row.

Evidence photos and documents: Attachment rows with `recovery` set.

**(Decision)** The previous owner stays on Device (`previous_owner_ref`) and is not copied onto Recovery. Completing a successful recovery sets the device's `recovery_date` from `recovered_at`, and fills `recovery_reference` with the recovery's reference if it was empty, through `devices.services.update_device` (audited as a device update).

### Assessment (Phase 6)
A structured condition assessment of a Recovered device.

| Field | Type | Notes |
|---|---|---|
| reference | varchar(20), unique | `ASS-<year>-<number>`, from the `assessments_assessment_reference_seq` sequence |
| device | FK → Device, `PROTECT` | |
| assessor | FK → User, `PROTECT` | The signed-in Device Assessor who started it |
| assessment_date | date | Defaults to today (Africa/Kigali); not in the future |
| physical_condition | enum, blank in draft | `EXCELLENT`, `GOOD`, `FAIR`, `POOR`, `CRITICAL` |
| cosmetic_condition | enum, blank in draft | `EXCELLENT`, `GOOD`, `FAIR`, `POOR` |
| screen_condition | enum, blank in draft | `INTACT`, `MINOR_DAMAGE`, `MAJOR_DAMAGE`, `BROKEN` |
| battery_condition | enum, blank in draft | `EXCELLENT`, `GOOD`, `FAIR`, `POOR`, `FAILED` |
| functional_status | enum, blank in draft | `FULLY_FUNCTIONAL`, `PARTIALLY_FUNCTIONAL`, `NON_FUNCTIONAL` |
| accessories_condition | enum, blank in draft | `COMPLETE`, `PARTIAL`, `NONE` |
| defects | varchar[] (PostgreSQL array) | **(Decision)** checklist codes instead of free text: `CAMERA_FAULT`, `CHARGING_PORT_FAULT`, `SPEAKER_OR_MICROPHONE_FAULT`, `BUTTON_FAULT`, `NETWORK_OR_SIM_FAULT`, `SOFTWARE_ISSUE`, `ACCOUNT_OR_DEVICE_LOCK`, `WATER_DAMAGE`, `HOUSING_DAMAGE`, `OTHER`; de-duplicated and sorted |
| assessment_notes | text | |
| estimated_repair_cost_rwf | bigint (whole RWF), nullable in draft | ≥ 0, at most 100,000,000 |
| estimated_market_value_rwf | bigint (whole RWF), nullable in draft | > 0 to submit, at most 100,000,000 |
| status | enum | `DRAFT` (editable) → `SUBMITTED` (immutable) |
| submitted_at | timestamptz, nullable | |
| created_at / updated_at | timestamptz | |

Constraints:
- CHECK on every enum column and on the defect codes (`defects <@ ARRAY[...]`).
- A `SUBMITTED` row must have every condition field, the repair cost, a market value > 0 and `submitted_at` (CHECK).
- At most one `DRAFT` and at most one `SUBMITTED` assessment per device (partial unique indexes).
- A PostgreSQL trigger rejects `UPDATE` of a submitted row and `DELETE` of any row.

Evidence: Attachment rows with `assessment` set (uploads allowed while Draft; files stay downloadable afterwards).

**(Decision)** The device's 4-level `current_condition` is set on submission from `physical_condition` (`CRITICAL` → `POOR`). There is no separate "overall rating" field; the final route (refurbish / ready / unable to repair) is the human decision recorded on `AIRecommendation`.

### RefurbishmentWorkOrder (Phase 7)
| Field | Type | Notes |
|---|---|---|
| reference | varchar(20), unique | `REF-<year>-<number>`, from the `refurbishment_workorder_reference_seq` sequence |
| device | FK → Device, `PROTECT` | Device must be `REFURBISHING` when the work order is created |
| assigned_to | FK → User, nullable | An active user with `refurbishment.manage` (checked in the service); set to the starter if empty |
| created_by | FK → User | |
| status | enum | `OPEN`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED`; indexed |
| outcome | enum, blank unless completed | `REPAIRED`, `UNABLE_TO_REPAIR` |
| diagnosis / work_summary | text | Summary required to complete as repaired |
| estimated_cost_rwf | bigint (whole RWF) | ≥ 0, default 0 |
| labour_cost_rwf | bigint (whole RWF), nullable | Required to complete as repaired (0 allowed) |
| actual_cost_rwf | bigint (whole RWF), nullable | **(Decision)** calculated at closure = sum of item totals + labour, then frozen; never typed in |
| closure_reason | text | Required for `UNABLE_TO_REPAIR` and `CANCELLED` |
| started_at / completed_at | timestamptz, nullable | `completed_at ≥ started_at` (CHECK); `completed_at` is also the cancellation time |
| completed_by | FK → User, nullable | Who completed or cancelled |
| created_at / updated_at | timestamptz | |

Constraints:
- At most one active (`OPEN`/`IN_PROGRESS`) work order per device (partial unique index). Cancelled and completed ones are kept as history.
- CHECK: only `COMPLETED` has an outcome, and then it has `actual_cost_rwf`, `completed_at` and `completed_by`; `UNABLE_TO_REPAIR`/`CANCELLED` have a reason; `REPAIRED` has a work summary and labour cost.
- A PostgreSQL trigger rejects `UPDATE` of a completed or cancelled work order and `DELETE` of any work order.

**(Decision)** `CANCELLED` closes a work order opened in error and leaves the device `REFURBISHING`; it does not change the lifecycle.

### RefurbishmentStep (Phase 7)
| Field | Type | Notes |
|---|---|---|
| work_order | FK → RefurbishmentWorkOrder, `PROTECT` | |
| step_type | enum | `DIAGNOSIS`, `CLEANING`, `SCREEN_REPAIR`, `BATTERY_REPLACEMENT`, `SOFTWARE_RESET`, `SOFTWARE_REPAIR`, `HOUSING_REPAIR`, `PORT_REPAIR`, `FUNCTIONAL_TEST`, `QUALITY_CHECK`, `OTHER` |
| description | varchar(255) | |
| status | enum | `PENDING` → `IN_PROGRESS` → `COMPLETED`, or → `SKIPPED` (final states) |
| performed_by | FK → User, nullable | Who last moved the step |
| started_at / completed_at | timestamptz, nullable | Set by the server; CHECK ties them to the status (`PENDING`: none; `IN_PROGRESS`: started; `COMPLETED`: both, completed ≥ started, with performer; `SKIPPED`: completed) |
| notes | text | Required when `SKIPPED` (the reason; CHECK) |
| created_at / updated_at | timestamptz | |

A PostgreSQL trigger rejects changes to finished (`COMPLETED`/`SKIPPED`) steps, to any step of a closed work order, and all deletes.

**(Decision)** Every step on a work order must be completed or skipped before completion, and `FUNCTIONAL_TEST` and `QUALITY_CHECK` must each be completed at least once (they cannot be satisfied by skipping).

### RefurbishmentItem (Phase 7, parts/materials)
| Field | Type | Notes |
|---|---|---|
| work_order | FK → RefurbishmentWorkOrder, `PROTECT` | |
| item_name | varchar(120) | e.g. "Replacement screen" |
| part_number / supplier | varchar, blank allowed | Free text; no supplier integration |
| quantity | positive int | > 0 (CHECK), at most 1,000 via the API |
| unit_cost_rwf | bigint (whole RWF) | ≥ 0, at most 100,000,000 via the API |
| total_cost_rwf | bigint (whole RWF) | Calculated by the server; CHECK `total_cost_rwf = quantity × unit_cost_rwf` |
| notes | text | |
| created_by | FK → User | |
| created_at / updated_at | timestamptz | |

A PostgreSQL trigger rejects changes to items of a closed work order and all deletes (a wrong entry is corrected by editing it while the work order is active).

Evidence: Attachment rows with `refurbishment` set (uploads while the work order is active; files stay downloadable afterwards).

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

### AIRecommendation (Phase 6)
The rule engine's output for one submitted assessment, plus the human final decision in separate columns.

| Field | Type | Notes |
|---|---|---|
| assessment | OneToOne → Assessment, `PROTECT` | One recommendation per submitted assessment |
| recommendation | enum | `REFURBISH`, `READY_FOR_DISPOSITION`, `UNABLE_TO_REPAIR` |
| score | smallint | 0–100 (CHECK) |
| confidence | numeric(3,2) | 0–1 (CHECK); rule-based certainty, not a probability |
| reasons | jsonb | Plain-language reasons, ending with the deciding rule |
| factors | jsonb | Points per factor (score breakdown) |
| rule | varchar(40) | Which rule decided (e.g. `economic_repair`) |
| rule_version | varchar(20) | e.g. `rules-v1.0` |
| requested_by | FK → User | |
| generated_at | timestamptz | indexed |
| final_decision | enum, blank until decided | Same choices as `recommendation` |
| final_decision_by | FK → User, nullable | `ai.decide` holder |
| final_decision_at | timestamptz, nullable | |
| final_decision_reason | text | Required when `final_decision ≠ recommendation` (CHECK) |

Constraints: a decision always has who and when (CHECK). A PostgreSQL trigger keeps the AI columns immutable, allows the decision columns to be written only while `final_decision` is empty, and blocks deletes. *Accepted / overridden* is derived (`final_decision = recommendation`), not stored.

### AIFeedback (Phase 6)
| Field | Type | Notes |
|---|---|---|
| recommendation | FK → AIRecommendation, `PROTECT` | |
| user | FK → User | |
| verdict | enum | `ACCEPTED` (would accept), `OVERRIDDEN` (would override) |
| comment | varchar(500) | Optional |
| created_at | timestamptz | |

Unique on (`recommendation`, `user`). Append-only (PostgreSQL trigger).

### ReferencePrice (planned: pricing / disposition phase)
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

No `updated_at`. No update or delete through the API or admin; a PostgreSQL trigger rejects `UPDATE`/`DELETE` except the `ON DELETE SET NULL` of `user`.

---

## Indexes and constraints (summary)

- Unique: `user.email`, `user.employee_id`, `device.device_code`, `device.serial_number` (when not null), `device.imei` (when not null), `work_order_number`, `role.code`, `permission.code`, (`reference_price.make`, `model`), (`ai_feedback.recommendation`, `user`).
- Partial unique: one open work order per device; one confirmed disposition per device.
- Check: non-negative costs and prices, confidence 0–100, `override_justification` non-empty when `decision = OVERRIDDEN`, channel valid for decision type.
- Indexes on status, make/model, created_at, and the foreign keys used for filtering.
