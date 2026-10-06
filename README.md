# AI-Enhanced Repossessed Device Lifecycle Management System

Final-year academic prototype for **Yellow (Rwanda)**. It tracks repossessed devices through
**Recovery → Condition Assessment → Refurbishment → Reallocation/Resale**, with role-based access control, a full audit trail, and transparent rule-based AI decision support. The AI only recommends; humans decide.

> **Status:** project scaffold. Business modules are added phase by phase. See [docs/architecture.md](docs/architecture.md).

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
- The Django admin (`/admin/`) uses password-only login without MFA or audit, so it is mounted only when `DJANGO_DEBUG=true`.
- The AI component is a **prototype rule-based decision-support engine**, not a trained machine-learning model. Its recommendations never change a device's status on their own.
