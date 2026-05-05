# SmartMonitor

SmartMonitor is a full-stack crowd monitoring system with:

- A Next.js frontend dashboard for live monitoring, analytics, settings, and user/session management
- Python AI backends for video processing, detection, tracking, and artifact generation

## Monorepo layout

- `frontend/` -> Next.js app (UI, auth, Prisma, API routes)
- `ai-exp-backend/` -> Primary FastAPI backend for processing and streaming
- `zero-crush-backend/` -> Alternative FastAPI backend variant

## High-level architecture

1. Frontend sends control commands to backend (`/api/start`, `/api/stop`) over HTTP.
2. Frontend polls backend status (`/api/status`) for live counters and pipeline state.
3. Frontend displays processed video from backend MJPEG stream (`/api/stream`).
4. Backend writes artifacts and summary data; frontend stores session records via its own API routes.

## Prerequisites

- Node.js 20+
- pnpm 10+
- Python 3.10+
- PostgreSQL (for frontend Prisma models)

## 1) Frontend setup

From repo root:

```powershell
cd frontend
pnpm install
```

Create `frontend/.env` (required by current build script) with at least:

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DB_NAME
NEXTAUTH_SECRET=replace-with-a-strong-random-secret
```

Optional mail variables (login email notifications):

```env
EMAIL=your-gmail@gmail.com
EMAILPASSWORD=your-app-password
MAIL_FROM_NAME=SmartMonitor
MAIL_FROM_ADDRESS=your-gmail@gmail.com
```

Run database migration and start frontend:

```powershell
pnpm exec prisma migrate deploy
pnpm dev
```

Frontend runs at `http://localhost:3000`.

## 2) Backend setup (primary: ai-exp-backend)

From repo root:

```powershell
cd ai-exp-backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python api.py
```

Backend default URL: `http://localhost:8000`

### Key backend endpoints

- `GET /api/status`
- `POST /api/start`
- `POST /api/stop`
- `POST /api/upload`
- `GET /api/stream` (MJPEG)
- `GET /api/logs/crowd`
- `GET /api/logs/events`
- `GET /api/session-summary`
- `GET/POST /api/config`

## 3) Optional backend variant (zero-crush-backend)

If you want to run the alternative backend implementation:

```powershell
cd zero-crush-backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python api.py
```

Use whichever backend URL you set in frontend settings.

## Build

Frontend production build:

```powershell
cd frontend
pnpm run build
```

Current build flow runs Prisma migrate deploy before Next.js build.

## Common issues

### Cannot find .env during build

The frontend build script currently runs with `node --env-file=.env`.
Create `frontend/.env` before running `pnpm run build`.

### Prisma DATABASE_URL errors

Ensure `DATABASE_URL` is present in `frontend/.env` and points to a reachable PostgreSQL instance.

### Backend not reachable from frontend

Set the backend URL in the Settings tab to your running backend, typically `http://localhost:8000`.

## Notes

- Frontend session persistence is database-backed via frontend API routes.
- Live monitoring currently uses HTTP polling + MJPEG stream transport.
- Both backend variants include YOLO-based crowd/violation analytics and artifact generation.
