# Smart Real-Time Monitoring & Inspection Mobile App (SIH 2026 — PS 26095)

Centralized platform for real-time monitoring, surprise inspections, CCTV
surveillance integration, and random inspection assignment for
projects/institutes/NGOs running under DoSJE schemes.

This scaffold is the **core foundation**: auth, database models, and a
working project list end to end. Feature modules (random assignment
engine, live CCTV integration, geo-tagged mobile inspection flow, AI
anomaly analytics) build on top of this.

## Stack

- **Backend:** Python + FastAPI + SQLAlchemy
- **Database:** PostgreSQL
- **Frontend:** HTML / CSS / vanilla JS (talks to the API over fetch)

## Project structure

```
sih2026/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, router wiring, startup
│   │   ├── config.py          # Settings (reads .env)
│   │   ├── database.py        # SQLAlchemy engine/session
│   │   ├── models/            # ORM models: User, Project, Inspection
│   │   ├── schemas/           # Pydantic request/response schemas
│   │   ├── core/security.py   # Password hashing + JWT
│   │   └── api/
│   │       ├── deps.py        # get_db, get_current_user, require_roles
│   │       └── routes/        # auth, users, projects, inspections
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── login.html / register.html / index.html
│   ├── css/style.css
│   └── js/api.js, login.js, register.js, main.js
├── docker-compose.yml
└── README.md
```

## Data model so far

- **User** — `admin`, `department_official`, `pmu_inspector`, `project_incharge` roles
- **Project** — a project / institute / NGO, with lat/lng and a CCTV feed URL slot
- **Inspection** — linked to a project + inspector, has a status, an
  `ai_assigned` flag (ready for the random-assignment engine), and geo-tagged
  report fields
- **InspectionEvidence** — photo/video evidence rows attached to an inspection

## Running it locally

### Option A — Docker (recommended, gets you Postgres for free)

```bash
cd sih2026
cp backend/.env.example backend/.env
docker compose up --build
```

API will be live at `http://localhost:8000` (docs at `/docs`).

### Option B — Manual

```bash
# 1. Postgres — create a database named sih_monitoring locally, then:
cd backend
cp .env.example .env        # edit DATABASE_URL if needed
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Tables are auto-created on startup from the SQLAlchemy models (fine for a
hackathon build — swap to Alembic migrations once the schema stabilizes).

### Frontend

The frontend is static — no build step. Just open `frontend/login.html`
in a browser, or serve the folder (e.g. VS Code "Live Server", or
`python -m http.server 5500` from inside `frontend/`). It expects the API
at `http://localhost:8000` — change `API_BASE` in `frontend/js/api.js` if
you're running the backend elsewhere.

## Try it end to end

1. Start the backend (see above).
2. Open `frontend/register.html`, create an `admin` account.
3. Sign in — you land on the dashboard (currently: projects list).
4. Use the interactive API docs at `http://localhost:8000/docs` to `POST
   /api/projects` a test project/institute — it'll show up in the dashboard
   table on refresh.

## What's next

Pick from the problem statement's remaining modules and we build on this
same base:
- Random inspection assignment engine (`ai_assigned` field is already on
  the `Inspection` model, ready to be populated by a scheduler/algorithm)
- Live CCTV feed integration on the monitoring dashboard
- Mobile-friendly inspection flow with geo-tagged photo/video capture
- Random VC connectivity with project incharge/staff/beneficiaries
- AI-based anomaly and attendance analytics
