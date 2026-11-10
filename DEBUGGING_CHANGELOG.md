# DEBUGGING_CHANGELOG.md

Phase 3 — Database and Revenue Integrity Fixes. All work was executed against the running Docker Compose stack. The database was not reset, recreated, or deleted; Redis data was not deleted; `docker compose down` was not used.

## 1. Files modified

| File | Change |
|---|---|
| `backend/requirements.txt` | `sqlalchemy>=2.0.0` → `sqlalchemy[asyncio]>=2.0.42,<2.2` |
| `backend/pyproject.toml` | Same SQLAlchemy asyncio declaration |
| `backend/app/core/database_pool.py` | Use `settings.database_url` via `make_url`; asyncpg driver; removed sync `QueuePool`; lazy, lock-protected initialization; global pool reuse; `close()` resets state; corrected `get_session` from async coroutine to session factory |
| `backend/app/services/reservations.py` | Removed fabricated mock revenue; uses global `db_pool`; joins `properties` + `reservations` to enforce ownership and tenant scope; returns `None` for unknown/foreign property; DB errors propagate |
| `backend/app/services/cache.py` | Cache key is now `revenue:{tenant_id}:{property_id}`; `None` results are not cached; DB failures propagate before caching |
| `backend/app/api/v1/dashboard.py` | Tenant must come from authenticated context; 403 without tenant; 404 for foreign/unknown property; 503 on revenue backend failure; generic client-facing error details |
| `backend/app/api/v1/properties.py` | New authenticated `GET /api/v1/properties`; tenant-scoped property list derived from the JWT |
| `backend/app/main.py` | Initializes the PostgreSQL pool at startup and disposes it at shutdown; registers the properties router |
| `frontend/src/components/Dashboard.tsx` | Loads the authenticated tenant's properties from the API; removes hardcoded property list; auto-selects the first property; loading/error/empty states |
| `frontend/src/components/RevenueSummary.tsx` | `propertyId` is now required; removed the hardcoded `prop-001` default and the unused simulated-tenant header |

## 2. Root causes fixed

1. **Missing greenlet** — Unpinned `sqlalchemy>=2.0.0` resolved to SQLAlchemy 2.1.8, where greenlet is an optional `[asyncio]` extra. The Dockerfile installs `requirements.txt`, not `uv.lock`, so the lock's greenlet was never installed.
2. **Missing settings attributes** — `DatabasePool` referenced `settings.supabase_db_user/password/host/port/name`, none of which exist. It now uses the Compose-provided `settings.database_url`.
3. **Wrong pool class** — A synchronous `QueuePool` was passed to `create_async_engine`; removed in favor of the async engine's default adapted pool.
4. **Per-request engine creation** — `calculate_total_revenue` constructed a new `DatabasePool` per request; it now uses the single global `db_pool`.
5. **Silent mock revenue** — The broad `except` that returned hardcoded financial totals was removed. Database failures propagate to the endpoint.
6. **Mock/error caching** — Failures are no longer converted to cacheable results; only successful aggregates (including legitimate zero) are cached.
7. **Tenant-less cache key** — `revenue:{property_id}` could return one tenant's data to another because `prop-001` exists in both tenants. Keys now include `tenant_id`.
8. **No ownership validation** — The aggregate query now joins `properties` on `id + tenant_id`; a property not owned by the authenticated tenant returns no row and the endpoint responds 404.
9. **HTTP 200 on failure** — Endpoint now maps backend failures to HTTP 503 with a generic message.
10. **Incidental coroutine bug found during verification** — `DatabasePool.get_session` was `async def` but returned an `AsyncSession`, so `async with db_pool.get_session()` raised `TypeError: 'coroutine' object does not support the asynchronous context manager protocol`. Changed it to a normal method returning the session.

The first verification run after the rebuild returned HTTP 503 for all properties because of item 10; after correcting `get_session`, the full regression passed.

## 3. Before/after behavior

| Scenario | Before | After |
|---|---|---|
| Backend startup | `Database pool initialization failed: 'Settings' object has no attribute ...` | `Database connection pool initialized` |
| SQLAlchemy async query | `ModuleNotFoundError: greenlet` | greenlet 3.5.6 installed; queries execute |
| Sunset `prop-001` | HTTP 200, mock `1000.00`, 3 bookings | HTTP 200, PostgreSQL `2250.0`, 4 bookings |
| Ocean `prop-001` | HTTP 200, same mock as Sunset | HTTP 200, PostgreSQL `0.0`, 0 bookings |
| Ocean `prop-002` | HTTP 200, fabricated Sunset property figure | HTTP 404 `Property not found` |
| Redis keys | `revenue:prop-001` (shared between tenants) | `revenue:tenant-a:prop-001`, `revenue:tenant-b:prop-001` |
| Database unavailable | HTTP 200 with fabricated revenue | HTTP 503 `Revenue service unavailable` |
| Failed request cache | Mock result cached for 300 s | Failure not cached; no key created |

## 4. Docker commands executed

```bash
docker compose exec -T backend python -m py_compile app/core/database_pool.py app/services/reservations.py app/services/cache.py app/api/v1/dashboard.py app/main.py

docker compose build backend

docker compose up -d backend

docker compose exec -T backend pip show sqlalchemy greenlet asyncpg
docker compose exec -T backend python -c "import greenlet; print('greenlet', greenlet.__version__)"

docker compose exec -T backend python -c "import asyncio; from app.services.reservations import calculate_total_revenue; print(asyncio.run(calculate_total_revenue('prop-001','tenant-a')))"

docker compose exec -T redis redis-cli -n 0 --scan --pattern 'revenue:*'
docker compose exec -T redis redis-cli -n 0 GET revenue:tenant-a:prop-001
docker compose exec -T redis redis-cli -n 0 GET revenue:tenant-b:prop-001
docker compose exec -T redis redis-cli -n 0 TTL revenue:tenant-a:prop-001

docker compose stop db
docker compose start db
docker compose exec -T db pg_isready -U postgres -d propertyflow

docker compose exec -T db psql -U postgres -d propertyflow -c "SELECT tenant_id, property_id, COUNT(*) AS cnt, SUM(total_amount) AS total FROM reservations GROUP BY tenant_id, property_id ORDER BY tenant_id, property_id;"

docker logs new_devs_app-backend-1
```

API requests were executed from the host with PowerShell `Invoke-RestMethod` against `http://localhost:8000` using the assignment credentials. Tokens were not printed or recorded.

No `docker compose down`, database reset, container removal, or Redis deletion was performed.

## 5. Test results (actually executed)

### Dependencies

| Package | Version |
|---|---|
| SQLAlchemy | 2.1.8 |
| greenlet | 3.5.6 |
| asyncpg | 0.32.0 |

`import greenlet` succeeded inside the backend container.

### Startup logs

- `INFO:app.core.database_pool:Database connection pool initialized`
- `INFO:app.core.redis_client: Redis connection established with connection pooling`
- Supabase pool still reports `supabase_url is required` — expected Challenge Mode behavior, unrelated to PostgreSQL revenue.

### Revenue regression

| Tenant | Property | HTTP | Revenue | Reservations | Expected |
|---|---|---:|---:|---:|---|
| tenant-a | prop-001 | 200 | 2250.0 | 4 | 2250.000 / 4 |
| tenant-a | prop-002 | 200 | 4975.5 | 4 | 4975.500 / 4 |
| tenant-a | prop-003 | 200 | 6100.5 | 2 | 6100.500 / 2 |
| tenant-b | prop-001 | 200 | 0.0 | 0 | 0.000 / 0 |
| tenant-b | prop-004 | 200 | 1776.5 | 4 | 1776.500 / 4 |
| tenant-b | prop-005 | 200 | 3256.0 | 3 | 3256.000 / 3 |
| tenant-b | prop-002 (foreign) | 404 | — | — | denied |

### Database cross-check

Read-only `psql` aggregate matched the API values exactly:

```text
 tenant_id | property_id | cnt |  total
-----------+-------------+-----+-----------
 tenant-a  | prop-001    |   4 | 2250.000
 tenant-a  | prop-002    |   4 | 4975.500
 tenant-a  | prop-003    |   2 | 6100.500
 tenant-b  | prop-004    |   4 | 1776.500
 tenant-b  | prop-005    |   3 | 3256.000
```

### Redis verification

Keys after the successful requests:

```text
revenue:tenant-a:prop-001
revenue:tenant-a:prop-002
revenue:tenant-a:prop-003
revenue:tenant-b:prop-001
revenue:tenant-b:prop-004
revenue:tenant-b:prop-005
```

Cached values:

```json
{"property_id": "prop-001", "tenant_id": "tenant-a", "total": "2250.000", "currency": "USD", "count": 4}
{"property_id": "prop-001", "tenant_id": "tenant-b", "total": "0", "currency": "USD", "count": 0}
```

`TTL revenue:tenant-a:prop-001` → `294` (300-second TTL preserved).

The old tenant-less keys observed during Phase 2 had expired naturally before this verification; they were not deleted.

### Database failure behavior

- `docker compose stop db`
- Sunset request for uncached `prop-999` → **HTTP 503**
- `revenue:tenant-a:prop-999` was not created in Redis
- `docker compose start db`, `pg_isready` → accepting connections
- Same regression table re-run → all expected 200/404 results above
- Reservation grouping query re-run → identical counts and totals (no data loss)

## 6. Phase 3.1 — Frontend property selector

### Implementation

- Inspected existing backend routes: no authenticated `/properties` endpoint existed. The existing property queries were Supabase-based and unavailable in Challenge Mode.
- Added `GET /api/v1/properties` in `backend/app/api/v1/properties.py`.
  - Requires `authenticate_request`.
  - Reads `tenant_id` from the authenticated server-side context only.
  - Queries `properties` with `WHERE tenant_id = :tenant_id ORDER BY id`, using the existing PostgreSQL pool.
  - Returns `{"items": [{"id", "name", "timezone"}], "total": n}`.
  - Returns 403 without tenant context and 503 on database failure.
- Registered the router in `backend/app/main.py`.
- Rewrote `Dashboard.tsx`:
  - Fetches properties with `SecureAPI.getProperties({ page_size: 1000 })`.
  - Builds the selector only from the API response.
  - Auto-selects the first property.
  - Shows loading, error, and empty states.
  - Renders `RevenueSummary` only when a valid property is selected.
- Updated `RevenueSummary.tsx`:
  - Removed the hardcoded `prop-001` default.
  - Removed the unused `debugTenant` option and `X-Simulated-Tenant` header.

### Tests executed

```bash
docker compose build frontend
docker compose up -d frontend
```

API results:

| Check | Result |
|---|---|
| Sunset `GET /api/v1/properties` | `prop-001, prop-002, prop-003` (tenant-a only) |
| Ocean `GET /api/v1/properties` | `prop-001, prop-004, prop-005` (tenant-b only) |
| Sunset `prop-001` revenue | HTTP 200, `2250.0`, 4 bookings |
| Ocean `prop-001` revenue | HTTP 200, `0.0`, 0 bookings |
| Ocean `prop-002` revenue | HTTP 404 |
| Unauthenticated `GET /api/v1/properties` | HTTP 401 |
| Frontend container | HTTP 200 |
| Built bundle | Contains `api/v1/properties`; no hardcoded property names |

Frontend verification was performed through a successful production build, bundle inspection, and the underlying API calls. No browser automation tool is available in the environment, so the UI was not driven end-to-end by a headless browser.

## 7. Remaining known issues

1. **Timezone-aware monthly revenue** — `calculate_monthly_revenue` is still an unused stub with naive UTC boundaries; `properties.timezone` is still unused. Deferred to Phase 4.
2. **Financial precision** — `dashboard.py` still converts the decimal string to `float`, and the frontend rounds with `Math.round`. Deferred to Phase 4.
3. **Monthly/annual endpoints** — still not implemented.
4. **Fail-open tenant default** — `TenantResolver.resolve_tenant_id` still defaults unknown users to `tenant-a`. Not changed in this phase.
5. **Cache invalidation** — there are no reservation write endpoints in this trimmed app. Staleness is bounded by the 300-second TTL. An invalidation hook is required if write endpoints are added.
6. **Supabase pool** — remains unconfigured by design in Challenge Mode; the PostgreSQL revenue pool is independent and working.
7. **No automated tests** — verification was manual/executed via API, SQL, Redis and logs. No test framework was added.
8. **Frontend SecureAPI tenant extraction** — still ignores `app_metadata.tenant_id`, so its 5-second request cache is bypassed for these custom tokens. Not changed.
9. **Finance endpoints** — `getFinancialData` / `getRevenueReport` client methods still point at routes that do not exist.

## 8. Phase 4 — Timezone, precision, tenant security and reports

Full details: `PHASE4_IMPLEMENTATION.md`.

### Implemented

- Replaced the broken `calculate_monthly_revenue` stub with a shared tenant-scoped period calculator.
- Added property-local `ZoneInfo` month/year boundaries converted to UTC; half-open `check_in_date` intervals.
- Revenue is aggregated as PostgreSQL `NUMERIC` / Python `Decimal`; API returns `total_revenue_exact` (3dp) and `total_revenue` (2dp, `ROUND_HALF_UP`) as strings.
- Removed the `float()` conversion from the dashboard response.
- Added `GET /api/v1/revenue/monthly` and `GET /api/v1/revenue/annual`.
- Cache keys are now `revenue:v2:{tenant}:{property}:{all|month:YYYY-MM|year:YYYY}`; failures and missing properties are not cached.
- Tenant resolution fails closed: trusted root/app_metadata claims, explicit assignment mappings, otherwise no tenant. `user_metadata` is not trusted.
- `authenticate_request` rejects missing tenant context with 403; non-static login rejects users without a tenant.
- Frontend consumes string amounts without `Math.round`, `Number`, or `parseFloat` financial transformations; added report-type/year/month controls and monthly/annual API methods.

### Verified

- 17 stdlib `unittest` tests pass (timezone/DST, precision, resolver security, seeded-database revenue/ownership).
- Sunset `prop-001` March 2024: exact `2250.000`, display `2250.00`, 4 bookings.
- Naive UTC control: exact `1000.000`, 3 bookings (proves `res-tz-1` correction).
- New York March tenant-b: `5032.500`, 7 bookings.
- Ocean `prop-004` March: `1776.500` / `1776.50` / 4.
- Ocean monthly `prop-002` (foreign): 404.
- Invalid month/year: 422; unauthenticated: 401; unknown property: 404.
- Missing/invalid/untrusted tenant identity: 403; trusted claims resolve to the claimed tenant.
- Cache keys separate by tenant/property/period; cache hits preserve TTL; DB failure returns 503 and creates no cache entry.
- Frontend build succeeds; bundle contains the monthly endpoint and no hardcoded property names.

### Remaining after Phase 4

1. Property currency has no dedicated column; it is derived from reservations, and mixed-currency properties are rejected with 500.
2. No headless-browser end-to-end run was possible; frontend verification used build, bundle inspection, and API calls.
3. Invalid-timezone behavior is unit-tested; no invalid-timezone database fixture exists (records were not modified).
4. SecureAPI's own short-lived request cache still bypasses `app_metadata` tenant extraction (performance only).
5. Finance endpoints `/api/v1/finance/*` remain unimplemented.
6. No automated browser test framework; backend tests use stdlib `unittest`.
7. Cache invalidation on reservation writes still needs a hook when write endpoints are added; TTL is 300 s.