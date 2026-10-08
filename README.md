# AI-Enhanced Repossessed Device Lifecycle Management System

Final-year academic prototype for **Yellow (Rwanda)**. It tracks repossessed devices through
**Recovery → Condition Assessment → Refurbishment → Reallocation/Resale**, with role-based access control, a full audit trail, and transparent rule-based AI decision support. The AI only recommends; humans decide.

> **Status:** authentication, RBAC, audit, device management, recovery, condition assessment, AI decision support and refurbishment are implemented. Reallocation/resale (dispositions), pricing/channel recommendations, notifications and analytics are future phases. See [docs/architecture.md](docs/architecture.md).

## Tech stack

| Part | Technology |
|---|---|
| Backend | Python 3.12, Django 5.2, Django REST Framework, session auth, TOTP MFA (`pyotp`) |
| Database | PostgreSQL 16 (`repossessed_devices`) |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS 4, React Router, Recharts |

## Project structure

```text
AI-Repossessed-Device-Lifecycle/
├── backend/            Django project
│   ├── config/         settings, root URLs, health endpoint
│   ├── accounts/       users, roles, permissions, login, MFA
│   ├── devices/        device records and lifecycle state machine
│   ├── recovery/       recovery records
│   ├── assessments/    condition assessments
│   ├── refurbishment/  work orders, parts, costs
│   ├── dispositions/   reallocation and resale
│   ├── ai_engine/      rule-based recommendations
│   ├── notifications/  in-app notifications
│   ├── audit/          audit log
│   └── analytics/      KPIs and reports
├── frontend/           React + TypeScript SPA
├── docs/               architecture and database design
├── .env.example        environment variable template
└── README.md
```

## Prerequisites

- Python 3.12
- Node.js 20+ (developed on 24)
- PostgreSQL 16 running locally

## Setup (first time)

All commands run from the repository root.

**1. Environment variables**

```bash
cp .env.example .env
```

Edit `.env`:

- `DJANGO_SECRET_KEY`: generate one with
  `backend/.venv/bin/python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`
  (after step 3), or any long random string.
- `DB_USER` / `DB_PASSWORD`: your PostgreSQL credentials.

**2. Create the database**

```bash
createdb -h localhost -U postgres repossessed_devices
```

(or create it in pgAdmin). The database user also needs permission to create databases so Django can create a test database: `ALTER USER <user> CREATEDB;`.

**3. Backend**

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser   # first System Administrator (see First sign-in)
cd ..
```

**4. Frontend**

```bash
cd frontend
npm install
cd ..
```

## Running

Use two terminals.

**Backend** (http://127.0.0.1:8000):

```bash
cd backend && .venv/bin/python manage.py runserver
```

**Frontend** (http://localhost:5173):

```bash
cd frontend && npm run dev
```

Open http://localhost:5173. The dev server forwards `/api` requests to Django, and the dashboard shows the backend and database status.

Health check: http://127.0.0.1:8000/api/health/

### First sign-in

There is no public registration. Create the first System Administrator from the command line:

```bash
cd backend && .venv/bin/python manage.py createsuperuser
```

It asks for email, full name, employee ID and password. Sign in at http://localhost:5173/login, then turn on two-step verification under **My account** (click your name in the header). The administrator creates other staff accounts through `POST /api/users/` until the user-management screen is built.

## Tests and build

```bash
cd backend && .venv/bin/python manage.py test   # backend tests
cd frontend && npm run build                     # type-check + production build
cd frontend && npm run lint                      # lint
```

## Security notes

- Secrets live only in `.env`, which is git-ignored. Never commit it.
- Every API endpoint requires login by default (401 if not signed in, 403 if the role lacks the permission). Role permissions are enforced on the backend, not just hidden in the UI.
- TOTP secrets are encrypted at rest (`MFA_ENCRYPTION_KEY`, see `.env.example`).
- Device photos and documents are stored under `backend/media/` (git-ignored, `MEDIA_ROOT`) with random names and are downloadable only through the API by users with `device.view`. Only JPEG, PNG, WebP and PDF up to 5 MB are accepted.
- Previous device owners are recorded only as a pseudonymous Yellow account reference, never by name or ID number.
- The Django admin (`/admin/`) uses password-only login without MFA or audit, so it is mounted only when `DJANGO_DEBUG=true`.
- The AI component is a **prototype rule-based decision-support engine**, not a trained machine-learning model. Its recommendations never change a device's status on their own.

## Condition assessment and AI decision support

1. A **Device Assessor** opens a *Recovered* device, clicks **Start Assessment**, records the condition checklist, defects and RWF estimates (draft), attaches evidence, and submits. The device moves to *Assessed*.
2. A user with `ai.request` clicks **Request AI Recommendation**. The rule engine returns Refurbish / Ready for disposition / Unable to repair with a score (0–100), a confidence, the reasons and the rule version. Nothing on the device changes.
3. An **Operations Manager** reviews it on the device page (or at **AI Recommendations**, filter *Awaiting decision*) and makes the **final decision**: accept, or override with a reason. That human decision moves the device to *Refurbishing*, *Ready for disposition* or *Unable to repair*.
4. Assessors, refurbishment staff, sales officers and managers can record feedback (would accept / would override).

The current AI component is an explainable rule-based decision-support engine. Future versions could replace or augment it with a trained machine-learning model when sufficient historical device lifecycle data is available.

Scoring rules, thresholds and limitations: [docs/architecture.md §7](docs/architecture.md#7-ai-decision-support).

## Refurbishment

1. When the final decision is **Refurbish**, the device is *Refurbishing*. Refurbishment staff open it (or go to **Refurbishment**) and **create a work order**: assignee, diagnosis, estimated cost (RWF).
2. **Start work**, then add and work through **steps** (diagnosis, cleaning, screen repair, battery replacement, software reset, …). A step can be skipped only with a reason.
3. Record **parts and materials** (quantity × unit cost; totals are calculated by the server) and attach **evidence** (before/after photos, test reports).
4. **Complete refurbishment**: needs a work summary, the labour cost, every step finished or skipped, and a completed **Functional test** and **Quality check**. The actual cost (parts + labour) is calculated and the device moves to *Ready for disposition*.
5. If the device cannot be fixed, **Unable to repair** (reason required) closes the work order and moves the device to *Unable to repair*. **Cancel** closes a work order opened by mistake and leaves the device in refurbishment.

Closed work orders, steps and parts are kept as read-only history. Reallocation and resale of ready devices are a future phase.
