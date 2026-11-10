# PROJECT_ANALYSIS.md

Investigation of `New_devs_App` (PropertyFlow Revenue Dashboard). This report describes the existing system, its Docker environment, database, business logic and frontend, and maps the three reported issues to code evidence. No source code, database data or Docker configuration was modified.

---

## 1. Project overview

`New_devs_App` is a deliberately trimmed "PropertyFlow" revenue dashboard used as a debugging challenge. It is a multi-tenant property-management system that reports revenue derived from reservations. The shipped UI exposes a single per-property total revenue card; monthly/annual reporting is scaffolded in code but is not implemented end-to-end.

Two seeded tenants are used for the assignment:

- `tenant-a` — Sunset Properties (properties in `Europe/Paris`)
- `tenant-b` — Ocean Rentals (properties in `America/New_York`)

Each tenant has its own properties, except `prop-001`, which exists in both tenants with different names.

## 2. Technology stack

| Layer | Technology |
|---|---|
| Frontend | React 18 + TypeScript + Vite 6, Tailwind CSS, React Router 6, TanStack Query (persisted), custom `SecureAPI` client |
| Backend | FastAPI (Python 3.11), Uvicorn, Pydantic v2, python-jose (HS256 JWT), SQLAlchemy 2 + asyncpg |
| Database | PostgreSQL 15 (Alpine) |
| Cache | Redis (Alpine), plus in-memory auth/tenant caches and browser-side caches |
| Authentication | Custom JWT issued by `POST /api/v1/auth/login`; tenant claim in `app_metadata.tenant_id` |
| Runtime | Docker Compose: `frontend`, `backend`, `db`, `redis` |
| Tests | None present; `pytest` is configured in `pyproject.toml` but not installed or used |

## 3. Directory structure

```text
New_devs_App/
├── backend/
│   ├── Dockerfile                  Python 3.11 image, uvicorn --reload
│   ├── requirements.txt             runtime dependencies
│   ├── pyproject.toml              project metadata / pytest config (no tests)
│   └── app/
│       ├── main.py                 app bootstrap, routers, CORS, SPA static serving
│       ├── config.py               settings (DB/Redis/JWT/optional Supabase)
│       ├── database.py             Supabase wrapper + Challenge/Mock fallback
│       ├── models/auth.py          AuthenticatedUser, Permission
│       ├── api/v1/
│       │   ├── login.py            static credentials, JWT issuance
│       │   ├── auth_info.py        GET /auth/me, tenant refresh
│       │   ├── dashboard.py        GET /dashboard/summary
│       │   └── ...                users, cities, profile, bootstrap, health
│       ├── core/
│       │   ├── auth.py             JWT verification, auth cache, permissions
│       │   ├── tenant_resolver.py  tenant lookup by email
│       │   ├── tenant_context.py   request-scoped tenant/token context
│       │   ├── tenant_cache.py     in-memory tenant cache (not used by revenue)
│       │   ├── redis_client.py     Redis connection used by app bootstrap
│       │   └── database_pool.py    SQLAlchemy async engine for revenue SQL
│       └── services/
│           ├── cache.py            Redis revenue cache
│           ├── reservations.py     revenue aggregation + monthly stub
│           └── sync.py             placeholder reservation sync
├── database/
│   ├── schema.sql                  tenants, properties, reservations, RLS enablement
│   └── seed.sql                    tenants, properties, March 2024 reservations
├── frontend/
│   ├── Dockerfile                  node build stage -> nginx runtime stage
│   ├── nginx.conf                  SPA fallback (no API proxy)
│   ├── .env                        VITE_BACKEND_URL / VITE_API_URL
│   └── src/
│       ├── main.tsx, App.tsx       providers and routes
│       ├── lib/localAuthClient.ts  backend login + localStorage session
│       ├── lib/secureApi.ts        authenticated API client + client cache
│       ├── lib/supabase.ts         re-exports localAuthClient as `supabase`
│       ├── contexts/AuthContext.new.tsx
│       ├── components/Dashboard.tsx
│       ├── components/RevenueSummary.tsx
│       └── components/LoginPage.tsx
├── docker-compose.yml
├── Makefile
└── ASSIGNMENT.md
```

Important files and responsibilities:

- `backend/app/main.py` — application composition; mounts all routers; only `dashboard` is relevant to revenue.
- `backend/app/services/reservations.py` — SQL aggregation and the unused monthly calculation stub.
- `backend/app/services/cache.py` — Redis cache in front of revenue aggregation.
- `backend/app/api/v1/dashboard.py` — HTTP boundary that resolves tenant and converts money to float.
- `backend/app/core/database_pool.py` — SQLAlchemy engine construction for revenue queries.
- `database/schema.sql` / `database/seed.sql` — data model and challenge fixtures.
- `frontend/src/components/Dashboard.tsx` — hardcoded property selector.
- `frontend/src/components/RevenueSummary.tsx` — fetch and display of the revenue total.

## 4. Docker architecture

| Service | Image / build | Host:container port | Depends on |
|---|---|---|---|
| `backend` | `backend/Dockerfile` (python:3.11-slim) | 8000:8000 | db, redis |
| `frontend` | multi-stage node:18 build, then nginx:alpine | 3000:80 | backend |
| `db` | `postgres:15-alpine` | 5433:5432 | — |
| `redis` | `redis:alpine` | 6380:6379 | — |

- **Database initialization:** `database/schema.sql` and `database/seed.sql` are mounted read-only into `/docker-entrypoint-initdb.d/`, so they run only when the database cluster is first initialized.
- **Persistence:** the `pgdata` volume is declared but **not mounted** (commented out). Database files live in the container layer. `docker compose down` therefore destroys the data; the next start re-runs schema and seed. `docker compose stop` preserves containers and data.
- **Environment handling:** the backend receives `DATABASE_URL`, `REDIS_URL` and `SECRET_KEY` from Compose. Frontend `.env` values are baked into the Vite build at image-build time; the `environment:` block on the frontend service has no effect on the already-built static bundle.
- **Internal networking:** backend reaches `db:5432` and `redis:6379` by Compose service name. The browser reaches the backend directly at `http://localhost:8000`; nginx serves only the SPA and does not proxy `/api`.
- **Live reload:** `./backend:/app` is mounted and Uvicorn runs with `--reload`, so backend edits apply immediately. Frontend changes require rebuilding the frontend image.

### Commands

```bash
# Build
docker compose build

# Start all services
docker compose up -d

# Status
docker compose ps

# Logs
docker compose logs -f backend
docker compose logs -f db redis frontend

# Safe stop (keeps containers and the un-persisted DB)
docker compose stop

# WARNING: `docker compose down` deletes the DB container and its data.
# Do not use it unless a reseed is intended.

# Backend shell / commands
docker compose exec backend sh
docker compose exec backend python -c "import app.main"
docker compose exec backend pip list

# Database inspection (read-only queries only)
docker compose exec db psql -U postgres -d propertyflow -c "SELECT ..."

# Redis inspection
docker compose exec redis redis-cli -n 0 KEYS 'revenue:*'

# Rebuild only the frontend after source changes
docker compose build frontend && docker compose up -d frontend

# Frontend lint/build (final image is nginx-only, so use a Node container)
docker run --rm -v "${PWD}/frontend:/app" -w /app node:18-alpine sh -c "npm ci && npm run lint"
```

There is no test suite. `pytest` is not installed in the backend image. Frontend `npm run lint` / `npm run build` must be run through a Node container, not the nginx container.

## 5. Database schema overview

### `tenants`

| Column | Type / constraint |
|---|---|
| `id` | `TEXT PRIMARY KEY` |
| `name` | `TEXT NOT NULL` |
| `created_at` | `TIMESTAMPTZ DEFAULT NOW()` |

### `properties`

| Column | Type / constraint |
|---|---|
| `id` | `TEXT NOT NULL` |
| `tenant_id` | `TEXT REFERENCES tenants(id)` |
| `name` | `TEXT NOT NULL` |
| `timezone` | `TEXT NOT NULL DEFAULT 'UTC'` |
| `created_at` | `TIMESTAMPTZ DEFAULT NOW()` |
| Primary key | **`(id, tenant_id)`** |

Property IDs are **not globally unique**. `prop-001` exists in both `tenant-a` and `tenant-b`.

### `reservations`

| Column | Type / constraint |
|---|---|
| `id` | `TEXT PRIMARY KEY` |
| `property_id` | `TEXT` |
| `tenant_id` | `TEXT REFERENCES tenants(id)` |
| `check_in_date` | `TIMESTAMPTZ NOT NULL` |
| `check_out_date` | `TIMESTAMPTZ NOT NULL` |
| `total_amount` | `NUMERIC(10,3) NOT NULL` (3 decimals for sub-cent tracking) |
| `currency` | `TEXT DEFAULT 'USD'` |
| `created_at` | `TIMESTAMPTZ DEFAULT NOW()` |
| Foreign key | `(property_id, tenant_id) REFERENCES properties(id, tenant_id)` |

The composite foreign key prevents a reservation from referencing a property under a different tenant.

### Row-level security

RLS is enabled on `properties` and `reservations`, but **no policies are created**. The application connects as the seeded superuser/service role, which bypasses RLS. Multi-tenant isolation therefore depends entirely on application-level `tenant_id` filters.

### Seed data highlights

- Tenants: `tenant-a` (Sunset Properties), `tenant-b` (Ocean Rentals).
- Properties: `prop-001` exists in both tenants; `prop-002`/`prop-003` belong to `tenant-a`; `prop-004`/`prop-005` belong to `tenant-b`.
- `res-tz-1`: check-in `2024-02-29 23:30:00+00` — this is `2024-03-01 00:30` in `Europe/Paris`.
- `res-dec-1..3`: `333.333`, `333.333`, `333.334` — these sum to exactly `1000.000`, but per-row rounding to cents sums to `999.99`.
- Other reservations are March 2024 bookings with 2-decimal amounts.

## 6. Backend architecture

`app/main.py` mounts routers for login/auth, users, profile, dashboard, bootstrap, company settings, departments, cities and health. For revenue, the only route is:

```text
GET /api/v1/dashboard/summary?property_id=<id>
  -> app/api/v1/dashboard.py
  -> app/services/cache.get_revenue_summary(property_id, tenant_id)
  -> app/services/reservations.calculate_total_revenue(property_id, tenant_id)
```

Authentication is handled by `app/core/auth.authenticate_request`:

- Reads `Authorization: Bearer <token>`.
- Tries to decode a custom HS256 JWT with the configured secret and audience `authenticated`.
- If custom decoding fails, falls back to Supabase token verification.
- Loads permissions/cities from Supabase (which falls back to a file-local Challenge mock client because Supabase env vars are absent in Compose).
- Resolves tenant through `TenantResolver.resolve_tenant_id`.
- Returns a Pydantic `AuthenticatedUser` containing `tenant_id`.

The login endpoint issues static JWTs for the two assignment accounts. Tenant is placed in `app_metadata.tenant_id`.

## 7. Frontend architecture

`main.tsx` renders `App.tsx`, which wraps the application in `AuthProvider` (`contexts/AuthContext.new.tsx`), `AppProvider`, `ToastProvider` and a persisted TanStack `QueryClient`. Routes:

- `/login` — `LoginPage`
- `/dashboard`, `/properties`, `/reservations`, `/cleaning`, `/profile` — protected
- `/` — redirects to `/dashboard`

Relevant frontend flow:

- `lib/supabase.ts` re-exports `localAuthClient` as `supabase`.
- `localAuthClient` posts credentials to `/api/v1/auth/login`, stores the returned session in `localStorage['base360-auth-token']`, and validates it against `/api/v1/auth/me`.
- `AuthContext.new` enriches the user from the session and exposes `getAccessToken`.
- `SecureAPI` attaches the bearer token and maintains a short-lived request cache keyed by tenant.
- `Dashboard` hardcodes the five property IDs and passes the selection to `RevenueSummary`.
- `RevenueSummary` fetches `GET /api/v1/dashboard/summary`, sends an `X-Simulated-Tenant: candidate` header, and displays `total_revenue` after `Math.round(value * 100) / 100`.

## 8. Authentication and multi-tenancy flow

1. User submits credentials on `LoginPage`.
2. `localAuthClient.signInWithPassword` calls backend `POST /api/v1/auth/login`.
3. Backend matches the static assignment credentials and issues an HS256 JWT containing `app_metadata.tenant_id` (`tenant-a` or `tenant-b`).
4. Frontend stores the session and sends the JWT on every request.
5. `authenticate_request` decodes the JWT and builds `AuthenticatedUser` with the resolved tenant.
6. `dashboard` reads `current_user.tenant_id` (no request parameter can override it).
7. SQL is intended to filter by both `property_id` and `tenant_id`.

Findings:

- The `X-Simulated-Tenant` header is sent by the frontend but **never read by the backend**. It cannot override tenant context, but it is misleading and should not be relied on.
- `TenantResolver` falls back to `tenant-a` for any email it does not recognise. This is fail-open and can grant Sunset data to an unknown user.
- The dashboard does not verify that the requested `property_id` belongs to the authenticated tenant; ownership enforcement exists only inside the SQL filter.
- The frontend property selector exposes the names and IDs of properties that belong to the other tenant.

## 9. Revenue calculation flow

### Intended flow

1. Cache lookup by property.
2. On miss, execute `SUM(total_amount)` filtered by `property_id` and `tenant_id`.
3. Convert the numeric result to `Decimal`.
4. Cache the result for 5 minutes.
5. Return the value through the dashboard endpoint and display it.

### Actual runtime flow

1. `calculate_total_revenue` constructs a new `DatabasePool`.
2. `DatabasePool.initialize` builds a URL from `settings.supabase_db_user`, `settings.supabase_db_password`, `settings.supabase_db_host`, `settings.supabase_db_port` and `settings.supabase_db_name`.
3. Those settings do **not exist** in `app/config.py`; only `settings.database_url` exists. Compose supplies `DATABASE_URL`, but the code never uses it.
4. Initialization raises an `AttributeError`, which is caught, leaving `session_factory = None`.
5. `calculate_total_revenue` raises "Database pool not available".
6. The broad `except` returns hardcoded mock totals keyed only by `property_id`.

Consequence: the database and seed reservations are currently never queried for revenue. Both tenants receive the same fabricated per-property totals. This masks the other defects and is itself a data-integrity failure.

Additional findings:

- `calculate_total_revenue` creates a new `DatabasePool` on every request and never disposes it. Once the connection is fixed, this leaks engines/connections.
- Revenue is per-property total only. There is no month/year parameter, no date filtering and no currency conversion.
- `calculate_monthly_revenue` is an unused stub with no `tenant_id` parameter, an undefined `tenant_id` reference, naive `datetime()` boundaries and a hardcoded `Decimal('0')` return.
- `dashboard.py` converts the decimal string to `float` before returning it.

## 10. Caching implementation

| Cache | Key | TTL | Tenant-aware? | Invalidation |
|---|---|---|---|---|
| Redis revenue (`services/cache.py`) | `revenue:{property_id}` | 300 s | **No** | None |
| In-memory auth (`core/auth.py`) | token SHA-256 prefix | 1800 s | Per token | User invalidation/pub-sub |
| In-memory tenant cache (`core/tenant_cache.py`) | user/tenant keys | 300 s | Yes (unused by revenue) | Yes |
| SecureAPI request cache | method + path + params + tenant | 5 s | Intended yes | Token/tenant change |
| `FinanceCache` (localStorage, `lib/cache.ts`) | key + base64 filters | 3 h | **No** | Manual; class is unused |
| TanStack persisted query cache | query keys | 24 h | Not used by Dashboard | Provider only |

Confirmed defect: the revenue cache key omits `tenant_id`, while `property_id` is only tenant-unique. The first requester's payload is served to the other tenant for up to 5 minutes. There is no invalidation when reservations change, and mock/error results are cached like real results.

Frontend note: `SecureAPI.getTenantId` reads only `user_metadata.tenant_id` or a root `tenant_id`. Login JWTs place the tenant in `app_metadata.tenant_id`, so the client-side request cache is bypassed for the assignment accounts (`secureApi.ts`).

## 11. Timezone implementation

- Reservation timestamps are stored as `TIMESTAMPTZ`, normalized by PostgreSQL.
- `properties.timezone` exists in schema and seed (`Europe/Paris`, `America/New_York`) but is **never read by any backend code**.
- Monthly boundary code uses naive `datetime(year, month, 1)`, which PostgreSQL interprets in the session timezone (UTC in the container). Boundaries are therefore effectively UTC, not property-local.
- Example: `res-tz-1` checks in at `2024-02-29 23:30Z`, which is `2024-03-01 00:30` in Paris. Naive UTC boundaries put it in February; property-local boundaries put it in March.
- DST is not handled. A fixed offset would be wrong for Paris after 2024-03-31 and for New York after 2024-03-10. Correct handling requires `zoneinfo.ZoneInfo` and converting local month boundaries to UTC.
- The revenue recognition rule is undocumented. Current SQL uses `check_in_date`; an alternative policy would allocate stay nights across months.
- Reservations near local midnight and month boundaries are exactly the cases this schema seeds.

## 12. Potential and confirmed bugs

### Confirmed from source code

1. **Revenue cache cross-tenant leak** — `app/services/cache.py:13` uses `revenue:{property_id}`. `property_id` is only unique per tenant, TTL is 300 s, and there is no tenant component or invalidation.
2. **Revenue DB pool cannot initialize** — `app/core/database_pool.py:18` reads `settings.supabase_db_*`, which do not exist in `app/config.py`. `DATABASE_URL` is never used, so every revenue request falls into the mock branch.
3. **Fabricated financial data returned on error** — `app/services/reservations.py:87-110` returns hardcoded totals/counts when the database is unavailable, scoped only by `property_id`, with no tenant scoping and no explicit failure.
4. **No property ownership validation** — `app/api/v1/dashboard.py:8-16` accepts an arbitrary `property_id`; ownership is enforced only by the SQL tenant filter. Combined with the mock fallback, `tenant-b` can receive `tenant-a` property figures today.
5. **Cross-tenant property exposure in UI** — `frontend/src/components/Dashboard.tsx:4-10` hardcodes all five properties for every tenant.
6. **Monthly revenue not implemented** — `calculate_monthly_revenue` (`app/services/reservations.py:5-32`) has no tenant parameter, references an undefined `tenant_id`, uses naive boundaries, returns `0`, and is not routed.
7. **Property timezone unused** — no backend code reads `properties.timezone`; monthly boundaries are effectively UTC.
8. **Floating-point/rounding risk** — `app/api/v1/dashboard.py:18` casts decimal money to `float`; `RevenueSummary.tsx:64` rounds after receiving a float. Seed rows prove per-row cent rounding yields `999.99` for values that sum to exactly `1000.000`.
9. **Finance API missing** — `SecureAPI.getFinancialData` and `getRevenueReport` (`frontend/src/lib/secureApi.ts:1832-1852`) call `/api/v1/finance/summary` and `/api/v1/finance/revenue`, but no finance router exists in `app/main.py`.
10. **Fail-open tenant resolution** — `app/core/tenant_resolver.py:90` defaults unknown users to `tenant-a`.
11. **Per-request database engine leak** — `calculate_total_revenue` constructs a new `DatabasePool` each call and never disposes it (`app/services/reservations.py:39-42`).
12. **Frontend tenant extraction mismatch** — `frontend/src/lib/secureApi.ts:189` ignores `app_metadata.tenant_id`, so `getTenantId()` returns `null` for assignment tokens and SecureAPI caching is bypassed (performance/log noise, not a leak).

### Unverified hypotheses / risks

- The exact March delta of `1250.00` assumes monthly reporting is intended to use property-local `check_in` boundaries. No monthly endpoint exists to reproduce the symptom end-to-end.
- The "occasionally sees another company's data after refresh" symptom depends on Redis TTL and request order. The current DB mock masks the cache leak for `prop-001`.
- The "few cents" symptom depends on the intended aggregation/rounding strategy. The current API returns a single total, so no multi-row finance report exists to observe it directly.
- RLS is enabled without policies and the application uses a privileged role, so any missing `tenant_id` filter is a full data leak.
- There is no index on `reservations(tenant_id, property_id, check_in_date)` (performance risk).

### Assignment issue mapping

| Field | Sunset Properties incorrect March revenue |
|---|---|
| Issue | March revenue totals do not match Sunset's internal records |
| Relevant files | `backend/app/services/reservations.py` (`calculate_monthly_revenue`), `database/schema.sql`, `database/seed.sql` |
| Root cause | Confirmed code defects: monthly function is a broken stub; month boundaries are naive/UTC and ignore `properties.timezone`. Runtime March mismatch is not reproducible because no monthly endpoint exists. |
| Evidence | `res-tz-1` is `2024-02-29 23:30Z` = `2024-03-01 00:30` Europe/Paris. Tenant-a March total is `13326.000` with local boundaries vs `12076.000` with naive UTC. |
| Impact | Sunset's March board reporting is understated by `1250.00` if the reservation is misclassified. |
| Proposed fix | Read `properties.timezone`, build local month boundaries with `zoneinfo.ZoneInfo`, convert to UTC, use a half-open interval, add `tenant_id` to the monthly function, and wire a monthly endpoint. |
| Test strategy | Compare SQL totals using local-boundary conversion; assert `13326.00` for tenant-a and `5032.50` for tenant-b for March 2024. |

| Field | Ocean Rentals sees another company's revenue after refresh |
|---|---|
| Issue | Refreshing occasionally shows revenue belonging to another company |
| Relevant files | `backend/app/services/cache.py`, `frontend/src/components/Dashboard.tsx`, `backend/app/api/v1/dashboard.py`, `backend/app/services/reservations.py` |
| Root cause | Confirmed code defects: cache key lacks tenant id; mock fallback is property-keyed only; no ownership validation; static property list spans tenants. Live cache leak is masked by the DB mock failure. |
| Evidence | `cache_key = f"revenue:{property_id}"`; `prop-001` exists in both tenants; TTL 300 s with no invalidation. |
| Impact | Privacy breach and incorrect financials for the affected tenant. |
| Proposed fix | Use `revenue:{tenant_id}:{property_id}:{period}`; invalidate on reservation changes; remove or explicitly gate the mock fallback; return 403/404 when the property is not owned by the tenant; scope the property list by tenant. |
| Test strategy | Log in as Sunset, request `prop-001`, log in as Ocean, request `prop-001`; assert distinct payloads and two Redis keys. Request `prop-002` as Ocean; assert 403/404. |

| Field | Finance reports off by a few cents |
|---|---|
| Issue | Revenue totals differ by small cent amounts between reports |
| Relevant files | `backend/app/api/v1/dashboard.py`, `frontend/src/components/RevenueSummary.tsx`, `backend/app/services/reservations.py` |
| Root cause | Confirmed precision risk: decimal money is cast to `float` at the API boundary, and per-row rounding is not specified. No finance report endpoint is implemented. |
| Evidence | `333.333 + 333.333 + 333.334 = 1000.000`; rounding each row to cents gives `999.99`. `dashboard.py:18` returns `float(...)`; `RevenueSummary.tsx:64` rounds a float. |
| Impact | Cent-level reconciliation failures with finance records. |
| Proposed fix | Keep `Decimal` end-to-end: `SUM` over `NUMERIC`, quantize once at final output with an explicit rounding mode, return a decimal string or integer minor units; avoid money arithmetic in the frontend. |
| Test strategy | Assert the seed aggregate is `1000.000` and its final 2-decimal value is `1000.00`; verify the frontend renders the exact server-supplied value without recomputation. |

## 13. Relevant source file references

- `backend/app/services/cache.py:9-27`
- `backend/app/services/reservations.py:5-32, 34-110`
- `backend/app/api/v1/dashboard.py:8-25`
- `backend/app/core/database_pool.py:11-36`
- `backend/app/core/auth.py:55-110, 260-300`
- `backend/app/core/tenant_resolver.py:72-92`
- `backend/app/api/v1/login.py:35-90`
- `backend/app/config.py:8-20, 186-236`
- `backend/app/database.py:278-380`
- `backend/app/main.py:130-180` (router registration)
- `database/schema.sql`
- `database/seed.sql`
- `docker-compose.yml`
- `backend/Dockerfile`
- `frontend/Dockerfile`
- `frontend/nginx.conf`
- `frontend/.env`
- `frontend/src/components/Dashboard.tsx:4-10, 40-50`
- `frontend/src/components/RevenueSummary.tsx:17-64`
- `frontend/src/lib/secureApi.ts:165-215, 535-590, 1455-1468, 1832-1852`
- `frontend/src/lib/localAuthClient.ts`
- `frontend/src/contexts/AuthContext.new.tsx`
- `frontend/src/lib/supabase.ts`

## 14. Recommended debugging sequence

1. `docker compose up --build -d`; confirm all services are running.
2. Check backend logs for `Database pool initialization failed` and `Challenge Mode (Mock Client)`; this establishes that revenue is currently mock data.
3. Log in as Sunset and Ocean through `/api/v1/auth/login`; decode JWTs and confirm `tenant-a` / `tenant-b`.
4. Call `/api/v1/dashboard/summary?property_id=prop-001` with each token.
5. Inspect Redis with `KEYS 'revenue:*'` before and after each call; verify the key count and payload identity.
6. Query PostgreSQL directly for per-tenant March totals using property-local month boundaries; compare with naive UTC totals.
7. Compare `SUM(total_amount)` with `SUM(ROUND(total_amount, 2))` for `res-dec-*` to confirm the cent behavior.
8. Only after reproducing each issue, implement the minimal fixes listed above and verify with the same steps.

## Summary

### What the system does

It authenticates a tenant user, resolves the tenant from a custom JWT, and returns a revenue total for a requested property. Revenue is cached in Redis. The data model supports multiple tenants and timezone-aware property locations.

### Most important files for debugging

1. `backend/app/services/cache.py`
2. `backend/app/services/reservations.py`
3. `backend/app/api/v1/dashboard.py`
4. `backend/app/core/database_pool.py`
5. `backend/app/core/tenant_resolver.py`
6. `database/schema.sql` and `database/seed.sql`
7. `frontend/src/components/Dashboard.tsx`
8. `frontend/src/components/RevenueSummary.tsx`
9. `frontend/src/lib/secureApi.ts`

### Confirmed vs unverified

- **Confirmed:** cache key leak, DB pool misconfiguration, mock financial fallback, missing ownership check, static cross-tenant property list, broken/unwired monthly function, unused timezone, float money conversion, missing finance endpoints, fail-open tenant default.
- **Unverified:** exact runtime March delta, the "occasional" cross-tenant display, and the exact cent discrepancy in a finance report. These require running the stack and, for monthly/finance reporting, implementing or locating the missing endpoint.

### Minimal fixes (not implemented)

1. Add tenant and reporting period to the revenue cache key; invalidate on writes.
2. Make the revenue DB pool use `settings.database_url` (converted to asyncpg) and reuse one global pool.
3. Remove or explicitly gate the mock fallback; never return fabricated financial data silently.
4. Validate property ownership in the dashboard endpoint and filter the frontend property list by tenant.
5. Implement timezone-aware monthly boundaries using `properties.timezone`.
6. Keep decimal money end-to-end; quantize once and return a string or minor units.
7. Remove the fail-open `tenant-a` default in `TenantResolver`.
8. Either implement the finance endpoints or remove the unused client methods.

### Docker commands for testing

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f backend
docker compose stop
docker compose exec backend sh
docker compose exec db psql -U postgres -d propertyflow -c "SELECT 1"
docker compose exec redis redis-cli -n 0 KEYS 'revenue:*'
docker compose build frontend && docker compose up -d frontend
```
