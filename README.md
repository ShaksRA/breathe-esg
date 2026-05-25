# Breathe ESG — Emissions Ingestion & Review Platform

A Django REST + React prototype for ingesting carbon emissions data from three enterprise source types, normalising it, and surfacing an analyst review workflow before audit lock.

**Live demo:** https://spectacular-paletas-4b50a8.netlify.app/

**Credentials:**
- Analyst: `analyst` / `demo1234`
- Admin: `admin` / `admin1234`

---

## What it does

Three source types are supported:

| Source | Format | Scope | Sample data |
|--------|--------|-------|-------------|
| SAP fuel & procurement | Tab-separated flat file (ME2N/ME2L export) | 1 | 16 rows, diesel/petrol/gas/LPG, 4 plants |
| Utility electricity | Portal CSV (EDF/Octopus format) | 2 | 14 rows, 4 meters, 3 months |
| Corporate travel | Concur v3 JSON export | 3 | 14 entries, flights/hotel/rail/taxi |

Uploaded files are parsed, normalised to kgCO2e, and written to the `EmissionRecord` table. Anomalies (statistical outliers, estimated reads, missing fields) are auto-flagged. Analysts then review: approve, reject, or flag with notes. Every state change is appended to an audit log.

---

## Repository structure

```
breathe-esg/
├── backend/                    # Django application
│   ├── breathe_esg/            # Django project settings, URLs, WSGI
│   ├── ingestion/              # Core app
│   │   ├── models.py           # Data model (see docs/MODEL.md)
│   │   ├── services.py         # Ingestion orchestrator
│   │   ├── views.py            # REST API views
│   │   ├── serializers.py      # DRF serializers
│   │   ├── urls.py             # API URL routing
│   │   ├── parsers/
│   │   │   ├── sap_parser.py   # SAP flat-file parser
│   │   │   ├── utility_parser.py  # Utility CSV parser
│   │   │   └── travel_parser.py   # Concur JSON parser
│   │   └── management/commands/seed_demo.py  # Demo data seeder
│   └── requirements.txt
├── frontend/                   # React single-page app
│   ├── src/App.js              # Full SPA (auth, dashboard, records, upload)
│   └── package.json
├── docs/
│   ├── MODEL.md                # Data model design decisions
│   ├── DECISIONS.md            # Every ambiguity resolved
│   ├── TRADEOFFS.md            # Three deliberate omissions
│   └── SOURCES.md              # Per-source research and failure modes
├── build.sh                    # Build script (React → Django static)
├── render.yaml                 # Render deployment config
└── Procfile                    # Heroku/Railway process definition
```

---

## Local development

### Prerequisites

- Python 3.11+
- Node 18+

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py seed_demo   # Creates users, org, and loads sample data

python manage.py runserver   # Starts on http://localhost:8000
```

### Frontend (development)

```bash
cd frontend
npm install
REACT_APP_API_URL=http://localhost:8000 npm start
# Opens http://localhost:3000
```

The frontend proxies API calls to the Django backend during development. In production, both are served from the same origin (Django serves the built React app via whitenoise).

---

## API endpoints

```
POST   /api/auth/login/              Login, returns token
POST   /api/auth/logout/             Invalidate token
GET    /api/auth/me/                 Current user + org

POST   /api/upload/                  Upload a file (multipart: file, source_type)
GET    /api/batches/                 List upload batches
GET    /api/batches/{id}/            Batch detail + source rows

GET    /api/records/                 List emission records (filterable)
GET    /api/records/{id}/            Record detail with audit trail
PATCH  /api/records/{id}/            Edit a record (analyst)
POST   /api/records/{id}/review/     Approve / reject / flag
POST   /api/records/bulk-review/     Bulk review action

GET    /api/dashboard/               Aggregated stats, scope breakdown, trend
GET    /api/audit-log/               Full audit log for the org
GET    /api/facilities/              List/create facility lookup entries
```

### Authentication

All endpoints except `/api/auth/login/` require `Authorization: Token <token>`.

### Filtering `/api/records/`

| Param | Example | Notes |
|-------|---------|-------|
| `scope` | `scope=1` | 1, 2, or 3 |
| `category` | `category=fuel_diesel` | See model categories |
| `review_status` | `review_status=pending` | pending/flagged/approved/rejected/locked |
| `is_flagged` | `is_flagged=true` | Anomaly-flagged records |
| `year` | `year=2024` | Filter by activity year |
| `batch_id` | `batch_id=<uuid>` | Records from a specific upload |
| `search` | `search=Frankfurt` | Searches description, facility, supplier, ref |
| `page` | `page=2` | Page number |
| `page_size` | `page_size=100` | Default 50 |

---

## Deployment (Render)

1. Fork or clone this repository
2. Create a new Web Service on [Render](https://render.com)
3. Connect your repository
4. Render will auto-detect `render.yaml` and configure the service
5. The build script (`build.sh`) will:
   - Install Python dependencies
   - Build the React frontend
   - Copy the React build into Django's static directory
   - Run database migrations
   - Run `seed_demo` to create demo users and data
6. Set `SECRET_KEY` as an environment variable (Render can generate one)

**Alternative (Railway):**

```bash
railway login
railway init
railway up
```

Set environment variables: `SECRET_KEY`, `DEBUG=False`.

---

## Design documentation

The docs directory contains the full design reasoning:

- **[MODEL.md](docs/MODEL.md)** — data model design, three-layer architecture, scope classification, unit normalisation
- **[DECISIONS.md](docs/DECISIONS.md)** — every source format choice justified, PM questions, architecture decisions
- **[TRADEOFFS.md](docs/TRADEOFFS.md)** — RBAC, emission factor versioning, async ingestion — why they were cut
- **[SOURCES.md](docs/SOURCES.md)** — per-source research, sample data rationale, real-world failure modes

---

## Emission factors used

All from **DEFRA 2023 conversion factors** (UK Government GHG Conversion Factors for Company Reporting):

| Category | Factor | Unit |
|----------|--------|------|
| Diesel | 2.68 | kgCO2e/litre |
| Petrol | 2.31 | kgCO2e/litre |
| Natural gas | 0.202 | kgCO2e/kWh |
| LPG | 1.554 | kgCO2e/litre |
| Electricity (UK grid, location-based) | 0.207 | kgCO2e/kWh |
| Flight short-haul economy | 0.255 | kgCO2e/passenger-km |
| Flight long-haul economy | 0.195 | kgCO2e/passenger-km |
| Business class multiplier | 2.0× | — |
| First class multiplier | 2.9× | — |
| Rail | 0.041 | kgCO2e/km |
| Taxi | 0.148 | kgCO2e/km |
| Rental car | 0.168 | kgCO2e/km |
| Hotel stay | 31.0 | kgCO2e/room-night |
