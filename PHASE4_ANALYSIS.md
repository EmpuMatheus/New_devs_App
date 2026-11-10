# PHASE4_ANALYSIS.md

Phase 4 — Timezone & Financial Precision Analysis. This is an investigation report only: no source code, database records, migrations, or Docker configuration were modified. Phase 3 and Phase 3.1 fixes remain in place.

---

## 1. Executive Summary

- The database already has the right foundations: `TIMESTAMPTZ` for reservation dates, `NUMERIC(10,3)` for amounts, and a `timezone` column on `properties`.
- There is **no monthly or annual revenue endpoint**. The only revenue endpoint returns an all-time total per property, so the reported "March revenue" cannot currently be reproduced through the API.
- A monthly calculation stub exists in `reservations.py`. It is unused, has no tenant parameter, references an undefined `tenant_id`, uses naive UTC month boundaries, and always returns `Decimal('0')`.
- If a monthly report were wired to the current stub, `res-tz-1` (`2024-02-29 23:30Z`) would be assigned to February instead of March, understating Sunset's March `prop-001` revenue by `1250.000`.
- `properties.timezone` is never read anywhere. Zone conversion is therefore not performed at all.
- Financial values are aggregated correctly in PostgreSQL as `NUMERIC`, but the API converts the result to a Python `float` in `dashboard.py`, and the frontend treats it as a JavaScript `number` and re-rounds it with `Math.round`.
- The seed values `333.333 + 333.333 + 333.334` prove the precision risk: exact aggregation is `1000.000`, while rounding each row to two decimals and summing gives `999.99`.
- `TenantResolver.resolve_tenant_id` still fails open to `tenant-a` for unknown users, and it ignores the tenant claim already available in the token.
- Recommended direction: aggregate exact decimals in PostgreSQL, compute month boundaries with `zoneinfo.ZoneInfo` from the property timezone, use half-open UTC intervals, round once at the presentation boundary, and transmit decimal values as strings that the frontend displays without arithmetic.

---

## 2. Current Revenue Calculation Flow

### Endpoint

`GET /api/v1/dashboard/summary?property_id=<id>`

Implementation: `backend/app/api/v1/dashboard.py`, function `get_dashboard_summary`.

```text
authenticate_request (JWT custom claims / email mapping)
  -> tenant_id from AuthenticatedUser
  -> get_revenue_summary(property_id, tenant_id)
       -> Redis key revenue:{tenant_id}:{property_id}
       -> calculate_total_revenue(property_id, tenant_id)
            -> SQL: properties LEFT JOIN reservations
            -> SUM(total_amount) over ALL reservations for that property
  -> float(revenue_data['total'])
  -> JSON numeric response
```

### What the SQL does today

`backend/app/services/reservations.py`, `calculate_total_revenue`:

```sql
SELECT
    p.id AS property_id,
    COALESCE(SUM(r.total_amount), 0) AS total_revenue,
    COUNT(r.id) AS reservation_count
FROM properties p
LEFT JOIN reservations r
    ON r.property_id = p.id AND r.tenant_id = p.tenant_id
WHERE p.id = :property_id AND p.tenant_id = :tenant_id
GROUP BY p.id
```

- Enforces tenant ownership via the join and `WHERE` clause.
- Returns `None` when the property is not owned by the tenant.
- Does **not** filter by date. The result is an all-time total.
- Aggregation is exact `NUMERIC`.
- `Decimal(str(row.total_revenue))` preserves the numeric value.
- The returned `total` is a string, e.g. `"2250.000"`.
- Redis caches the string; the cache key is tenant-aware.

### Current effective results

| Tenant | Property | Reservations | Revenue |
|---|---|---:|---:|
| tenant-a | prop-001 | 4 | 2250.000 |
| tenant-a | prop-002 | 4 | 4975.500 |
| tenant-a | prop-003 | 2 | 6100.500 |
| tenant-b | prop-001 | 0 | 0 |
| tenant-b | prop-004 | 4 | 1776.500 |
| tenant-b | prop-005 | 3 | 3256.000 |

### Monthly stub

`backend/app/services/reservations.py`, `calculate_monthly_revenue`:

- Signature: `(property_id, month, year, db_session=None)` — **no `tenant_id`**.
- SQL references `$2` / `tenant_id`, but `tenant_id` is undefined in the function.
- Uses `datetime(year, month, 1)` without `tzinfo`; PostgreSQL treats this in the session timezone (UTC in the container).
- Contains commented-out execution code.
- Always returns `Decimal('0')`.
- Is not imported or routed anywhere.

---

## 3. Timezone Problems and Root Causes

### TZ-1 — Monthly calculation is not implemented

- **File / function:** `backend/app/services/reservations.py` / `calculate_monthly_revenue`
- **Current behavior:** Returns `Decimal('0')`, is unused, and cannot accept a tenant ID.
- **Root cause:** Placeholder implementation left in the codebase; the SQL has placeholders for tenant but no parameter.
- **Expected behavior:** Calculate a tenant-scoped monthly total using the property's timezone.
- **Proposed fix:** Replace the stub with a shared period calculator (see Section 4).
- **Regression risk:** Low if the unused stub is replaced; the live dashboard endpoint does not call it.
- **Status:** Confirmed bug (dead/broken code).

### TZ-2 — Month boundaries are UTC, not property-local

- **File / function:** `backend/app/services/reservations.py` / `calculate_monthly_revenue`
- **Current behavior:** Naive `datetime(year, month, 1)` boundaries are interpreted as UTC by PostgreSQL.
- **Root cause:** No timezone conversion; `properties.timezone` is ignored.
- **Expected behavior:** A reservation belongs to the month in which its `check_in_date` falls **in the property's local timezone**, preserving the existing check-in recognition rule.
- **Proposed fix:** Build local start/end with `ZoneInfo`, convert to UTC, query `check_in_date >= start AND check_in_date < end`.
- **Regression risk:** Medium: historical monthly totals will change for reservations near month boundaries; this is the intended correction but must be confirmed by finance.
- **Status:** Confirmed code defect. The runtime symptom is not currently reproducible because no monthly endpoint exists.

### TZ-3 — Property timezone is unused

- **Files:** `database/schema.sql` (`properties.timezone`), `backend/app/services/reservations.py`
- **Current behavior:** The column exists and is seeded (`Europe/Paris`, `America/New_York`), but no backend code reads it. A grep of the backend finds no reference to `properties.timezone`.
- **Root cause:** Timezone support was never wired into the revenue path.
- **Expected behavior:** Every period calculation reads the property's timezone.
- **Proposed fix:** Select `p.timezone` in the ownership query and pass it to the period calculation.
- **Regression risk:** Low; read-only usage.
- **Status:** Confirmed bug.

### TZ-4 — Midnight and month-boundary case

- **Files:** `database/seed.sql`, `backend/app/services/reservations.py`
- **Test case:** `res-tz-1` = `2024-02-29 23:30:00+00`.
- **In `Europe/Paris`:** `2024-03-01 00:30:00+01:00` → belongs to **March**.
- **In UTC:** `2024-02-29 23:30:00+00` → belongs to **February**.
- **Current behavior:** No month filtering; if the naive stub were used, it would be February.
- **Expected behavior (check-in rule preserved):** March.
- **Impact:** Sunset `prop-001` March total:
  - property-local: `1250 + 333.333 + 333.333 + 333.334 = 2250.000`
  - naive UTC: `333.333 + 333.333 + 333.334 = 1000.000`
  - difference: `1250.000`
- **Status:** The data case is confirmed; the end-to-end monthly symptom is currently unobservable because the endpoint does not exist.

### TZ-5 — DST handling

- **Files:** `backend/app/services/reservations.py` (future implementation)
- **Current behavior:** No conversion at all, so no DST handling.
- **Risk if implemented with a fixed offset:** Paris is `+01:00` in March until 2024-03-31 and `+02:00` afterwards; New York is `-05:00` until 2024-03-10 and `-04:00` afterwards.
- **Expected behavior:** Use `ZoneInfo`/IANA rules; do not use fixed offsets.
- **Verified boundaries in the running backend image:**
  - `Europe/Paris`: March 2024 starts `2024-02-29T23:00:00Z`, April starts `2024-03-31T22:00:00Z`.
  - `America/New_York`: March 2024 starts `2024-03-01T05:00:00Z`, April starts `2024-04-01T04:00:00Z`.
- **Status:** Potential bug for a naive/fixed-offset implementation. `zoneinfo` is available and working in the current image (Python 3.11).

### UTC vs property-local month boundaries

- **UTC month:** `[YYYY-MM-01T00:00Z, next-month-01T00:00Z)`.
- **Property-local month:** `[YYYY-MM-01T00:00 local, next-month-01T00:00 local)` converted to UTC.
- With half-open intervals, every instant belongs to exactly one month: no gaps, no overlap.
- For Paris in March 2024, the local month is `2024-02-29T23:00Z` through `2024-03-31T22:00Z` (23 hours shorter/longer than 30 days due to DST, not a uniform duration).
- Reservations are compared on `check_in_date` only, preserving the existing revenue recognition rule.

---

## 4. Timezone Implementation Proposal

### Recommended approach

1. Load the property timezone and ownership in one query:
   ```sql
   SELECT p.id, p.timezone
   FROM properties p
   WHERE p.id = :property_id AND p.tenant_id = :tenant_id
   ```
   No row → return `None` (dashboard maps to 404).
2. Build local boundaries:
   ```python
   from datetime import datetime, timezone
   from zoneinfo import ZoneInfo

   tz = ZoneInfo(timezone_name)
   start_local = datetime(year, month, 1, tzinfo=tz)
   if month == 12:
       end_local = datetime(year + 1, 1, 1, tzinfo=tz)
   else:
       end_local = datetime(year, month + 1, 1, tzinfo=tz)
   start_utc = start_local.astimezone(timezone.utc)
   end_utc = end_local.astimezone(timezone.utc)
   ```
3. Query with a half-open interval:
   ```sql
   SELECT COALESCE(SUM(total_amount), 0) AS total,
          COUNT(*) AS count
   FROM reservations
   WHERE property_id = :property_id
     AND tenant_id = :tenant_id
     AND check_in_date >= :start_utc
     AND check_in_date < :end_utc
   ```
4. Use the same helper for annual revenue:
   - start: January 1 of the year at 00:00 local
   - end: January 1 of the next year at 00:00 local
5. Keep `check_in_date` as the revenue recognition field. Do not switch to checkout or nightly allocation without business approval.

### Why this avoids the edge cases

- **Double counting:** half-open intervals share only the boundary instant; `>= start` and `< end` assigns it to exactly one month.
- **Missing reservations around midnight:** conversion is done on the whole instant, not by truncating the date string; `res-tz-1` is correctly included in March for Paris.
- **Incorrect month classification:** boundaries are derived from IANA timezone rules, including DST transitions.
- **Index use:** converting boundaries in Python and comparing `TIMESTAMPTZ` columns keeps the query sargable and index-friendly, unlike applying functions to the column.

### Minimum code changes

| File | Change |
|---|---|
| `backend/app/services/reservations.py` | Replace the stub with `calculate_revenue_for_period(property_id, tenant_id, start_utc, end_utc)`; add `calculate_monthly_revenue(property_id, tenant_id, year, month)`; optionally `calculate_annual_revenue`. Load property timezone with ownership. |
| `backend/app/api/v1/dashboard.py` | Keep existing total endpoint; add monthly/annual endpoints or extend with optional period parameters. |
| `backend/app/services/cache.py` | Include period and timezone-relevant identifier in the cache key. |
| `frontend/src/lib/secureApi.ts` | Add client methods for the new period endpoints when they are introduced. |
| No schema change | `timezone`, `TIMESTAMPTZ`, and `NUMERIC(10,3)` already exist. |

No new dependency is required; `zoneinfo` is in the Python standard library and the current image resolves `Europe/Paris` and `America/New_York` successfully. If the base image changes to one without system tzdata, add the `tzdata` OS package (not a Python library).

---

## 5. Financial Precision Problems and Root Causes

### PREC-1 — API converts decimal money to float

- **File / function:** `backend/app/api/v1/dashboard.py` / `get_dashboard_summary`, line 31
- **Current behavior:** `total_revenue_float = float(revenue_data['total'])` and the JSON response sends a numeric value.
- **Root cause:** Python `float` is IEEE-754 binary floating point and cannot represent all decimal fractions exactly.
- **Expected behavior:** Keep the exact decimal representation through serialization.
- **Proposed fix:** Do not cast to `float`; return a string (for example `"2250.00"`) or a pre-quantized decimal string. JSON has no decimal type, so string is the safe representation.
- **Regression risk:** Type change for API consumers; frontend must be updated in the same release. Old clients expecting a number would break.
- **Status:** Confirmed bug (precision loss at API boundary).

### PREC-2 — Frontend re-rounds with JavaScript numbers

- **File / function:** `frontend/src/components/RevenueSummary.tsx`, lines 4-8, 59, 76, 102
- **Current behavior:**
  - Type: `total_revenue: number`.
  - `const displayTotal = Math.round(data.total_revenue * 100) / 100;`
  - `toLocaleString` formats the JavaScript number.
  - A "Precision Mismatch" check compares the original number to the rounded number with an epsilon.
- **Root cause:** Financial values are treated as binary floating point and recalculated in the browser.
- **Expected behavior:** The frontend displays the backend's canonical value and performs no financial arithmetic.
- **Proposed fix:** Type the field as `string`; remove `Math.round`; display the string directly or use a string-only grouping helper; remove the epsilon comparison.
- **Regression risk:** Low if done with the backend change; display formatting must still show two decimals.
- **Status:** Confirmed bug.

### PREC-3 — Per-row rounding can change the total

- **Files:** `database/seed.sql`, any future report implementation
- **Test data:** `333.333 + 333.333 + 333.334`
- **Exact aggregation:** `1000.000`
- **Per-row rounding (half-up to cents):** `333.33 + 333.33 + 333.33 = 999.99`
- **Root cause:** Rounding before aggregation discards sub-cent information that only becomes material after summing.
- **Expected behavior:** Aggregate exact `NUMERIC` values first; round once at the presentation boundary.
- **Proposed fix:** `SUM(total_amount)` in SQL, keep `Decimal`, then `quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)` exactly once.
- **Regression risk:** Low; this is the intended financial behavior.
- **Status:** Confirmed mathematical risk. The current total endpoint does not round per row, but the stub/older mock path used approximations and future reports could repeat the mistake.

### PREC-4 — Decimal JSON serialization

- **File / function:** `backend/app/services/cache.py`, `backend/app/api/v1/dashboard.py`
- **Current behavior:** The service stores `total` as a string, so `json.dumps` works; the API then converts it to `float`.
- **Root cause:** JSON has no decimal type; mixing `Decimal`, `float`, and strings creates ambiguity.
- **Expected behavior:** Use one canonical representation: decimal string.
- **Proposed fix:** All revenue responses expose the amount as a string. If a numeric field is required for legacy compatibility, document it as display-only and never use it for further arithmetic.
- **Status:** Recommendation / potential issue.

### Confirmed vs potential

| Item | Status |
|---|---|
| `float()` conversion at API boundary | Confirmed |
| Frontend `Math.round` and `number` type | Confirmed |
| Per-row rounding producing 999.99 | Confirmed mathematical behavior; not currently executed by the total endpoint |
| Decimal JSON ambiguity | Potential / design recommendation |

---

## 6. Decimal Implementation Proposal

### Canonical rules

1. **Storage:** keep `NUMERIC(10,3)` for sub-cent precision tracking. No migration.
2. **Aggregation:** `SUM(total_amount)` in PostgreSQL over `NUMERIC`. Never cast to `double precision`.
3. **Python:** keep `Decimal` from the driver; do not convert through `float`.
4. **Rounding:** once, at the presentation boundary:
   ```python
   from decimal import Decimal, ROUND_HALF_UP
   display_total = Decimal(total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
   ```
5. **Serialization:** return strings:
   ```json
   {
     "property_id": "prop-001",
     "total_revenue": "2250.00",
     "currency": "USD",
     "reservations_count": 4
   }
   ```
   If full precision is useful for auditing, also return `"total_revenue_exact": "2250.000"`; do not expose a float field.
6. **Caching:** store the exact string. Cache keys include tenant, property, and period.
7. **Frontend:** treat `total_revenue` as a string; no `Number`, `parseFloat`, `Math.round`, or arithmetic. Display the string directly, optionally grouping the integer part with a string-only helper.

### Why not round every row

Sub-cent values are intentionally stored (`333.333`, `333.334`). Rounding each reservation before summing changes the reported total. Financial reports should round only the final aggregated amount, using a documented rounding mode.

### Why `ROUND_HALF_UP`

It is the common financial convention. `ROUND_HALF_EVEN` is also defensible, but must be chosen explicitly and documented. Python's default `Decimal` context is `ROUND_HALF_EVEN`; relying on the default is not a documented business rule.

---

## 7. Frontend Financial Display Review

### Findings

- `RevenueSummary.tsx` declares `total_revenue: number`.
- It recomputes a display value with `Math.round(data.total_revenue * 100) / 100`.
- It formats using `toLocaleString` on a JavaScript `number`.
- It contains a "Precision Mismatch Detected" check based on an epsilon comparison.
- `Dashboard.tsx` does not calculate revenue; it only selects a property and renders the summary.
- `SecureAPI.getDashboardSummary` has no response transformation; it returns the JSON as-is.
- No other revenue formatting exists in the dashboard path.

### Recommended minimum frontend changes

1. Change the interface to `total_revenue: string`.
2. Remove `displayTotal` and `Math.round`.
3. Render the backend value directly, for example:
   ```tsx
   {data.currency} {data.total_revenue}
   ```
4. Remove the epsilon precision warning, or compare the exact response string to an optional `display_total` field if the backend provides one.
5. If thousands separators are required, implement a string-based formatter that splits on `"."` and groups the integer digits. Do not convert to `number`.
6. When the backend later adds monthly/annual endpoints, reuse the same string contract and component.

### Backward compatibility

Changing the API field from number to string is a breaking contract change. Backend and frontend must be released together. An alternative is to add a new field (`total_revenue_display`) while retaining the numeric one, but that preserves the precision hazard and should be avoided for new endpoints.

---

## 8. Tenant Resolver Security Review

### SEC-1 — Fail-open default tenant

- **File / function:** `backend/app/core/tenant_resolver.py` / `TenantResolver.resolve_tenant_id`
- **Current behavior:** After matching known assignment emails, it returns `"tenant-a"` for every other user.
- **Root cause:** A convenience fallback left in the challenge scaffold.
- **Exposure:** Any authentication path that accepts an unknown/other user and reaches this resolver can obtain Sunset Properties data. The static assignment logins are explicitly mapped and unaffected, but the general login path calls this resolver for non-static users.
- **Expected behavior:** Fail closed. Unknown users should receive no tenant and be rejected by tenant-scoped endpoints.
- **Proposed fix (separate from timezone/precision):**
  - Return `Optional[str]`.
  - First use the tenant claim from the token (`app_metadata.tenant_id`, `user_metadata.tenant_id`, or root `tenant_id`).
  - Then use an authoritative tenant membership lookup if one is available.
  - Return `None` if no valid tenant is found.
  - `dashboard.py` and `properties.py` already return 403 when `tenant_id` is missing.
- **Regression risk:** Medium. Other endpoints may assume a non-null tenant. They must be audited to return 401/403 instead of querying with `"tenant-a"`. The two assignment accounts remain mapped and continue to work.
- **Status:** Confirmed security bug.

### SEC-2 — Resolver ignores the token claim

- **File / function:** `tenant_resolver.py` / `resolve_tenant_id`; called from `backend/app/core/auth.py`
- **Current behavior:** `authenticate_request` successfully decodes the custom JWT with `app_metadata.tenant_id`, but resolution is done by email mapping rather than using the claim. `resolve_tenant_from_token` exists but is not used by `resolve_tenant_id`.
- **Root cause:** The token-based helper and the email-based resolver are disconnected.
- **Expected behavior:** Prefer signed token claims; use email/membership only as a fallback.
- **Proposed fix:** Use `resolve_tenant_from_token(token_payload)` first, then membership, then `None`; remove the catch-all.
- **Regression risk:** Low for assignment accounts (claims are present and correct); other users need valid claims or memberships.
- **Status:** Confirmed design/security gap.

These resolver changes should be implemented separately from the timezone and precision work.

---

## 9. Monthly and Annual Revenue Endpoint Review

### Current state

- No monthly endpoint exists.
- No annual endpoint exists.
- No finance router exists in `backend/app/main.py`.
- `SecureAPI.getFinancialData` and `getRevenueReport` call `/api/v1/finance/summary` and `/api/v1/finance/revenue`, which are not implemented.
- Only `GET /api/v1/dashboard/summary` exists; it returns an all-time total.
- `calculate_monthly_revenue` is dead code; there is no annual calculation.
- There is no duplicated live calculation logic; the only duplication risk is between the dead stub and the total query.

### Recommended pattern (do not implement yet)

- Introduce one shared period calculator:
  ```text
  calculate_revenue_for_period(property_id, tenant_id, start_utc, end_utc)
  ```
- Have monthly and annual wrappers compute UTC bounds from the property timezone and call it.
- Keep the existing all-time endpoint unchanged for backward compatibility.
- Add explicit endpoints:
  - `GET /api/v1/revenue/monthly?property_id=&year=&month=`
  - `GET /api/v1/revenue/annual?property_id=&year=`
  - Alternatively extend `/dashboard/summary` with optional `period`, but a separate route avoids changing the existing response contract.
- Reuse the existing auth dependency, tenant ownership check, 404/503 mapping, Redis caching, and decimal string contract.
- Cache key pattern:
  ```text
  revenue:{tenant_id}:{property_id}:month:{year}-{month:02d}
  revenue:{tenant_id}:{property_id}:year:{year}
  ```
  For the existing all-time endpoint, keep `revenue:{tenant_id}:{property_id}` (or add an explicit `all` segment when keys are next revised).
- Do not cache a failed or `None` lookup.

---

## 10. Files That Need Modification

| File | Purpose | Phase |
|---|---|---|
| `backend/app/services/reservations.py` | Replace monthly stub; add timezone-aware period calculator; keep exact Decimal | Phase 4 |
| `backend/app/api/v1/dashboard.py` | Remove `float()`; return decimal string; map errors | Phase 4 |
| `backend/app/services/cache.py` | Period-aware cache keys; keep tenant isolation; cache only successful results | Phase 4 |
| `frontend/src/components/RevenueSummary.tsx` | String type; no `Math.round`; no numeric recalculation | Phase 4 |
| `frontend/src/lib/secureApi.ts` | Response types; remove unused simulated-tenant option; add period methods later | Phase 4 / 4.1 |
| `backend/app/api/v1/properties.py` | Already returns `timezone`; no change required unless used by frontend | — |
| `backend/app/core/tenant_resolver.py` | Fail closed; prefer token claims | Separate security fix |
| `backend/app/core/auth.py` | Pass token payload/claims to resolver and handle `None` | Separate security fix |
| New revenue router (optional) | Monthly/annual endpoints | Future phase |
| `database/schema.sql` | No change; types and timezone column already correct | — |
| `database/seed.sql` | No change; fixtures already cover the boundary case | — |

---

## 11. Proposed Implementation Steps

1. **Confirm business rules** (Section 14) before changing monthly logic.
2. Add a shared, tenant-scoped period query in `reservations.py`:
   - load property timezone and ownership;
   - accept UTC start/end;
   - aggregate exact `NUMERIC` and return `Decimal`.
3. Implement `calculate_monthly_revenue(property_id, tenant_id, year, month)` using `ZoneInfo` and half-open UTC bounds.
4. Implement `calculate_annual_revenue` with the same helper and local year boundaries.
5. Delete or replace the broken stub; remove the undefined `tenant_id` and placeholder SQL.
6. Change the API boundary:
   - keep exact Decimal;
   - quantize once to 2 decimals with an explicit rounding mode;
   - return the amount as a string.
7. Update `RevenueSummary.tsx` to consume and display the string without arithmetic; remove the precision-warning workaround.
8. Update `secureApi.ts` types and remove the unused `simulatedTenant` option.
9. Add period-aware cache keys; preserve tenant isolation and do not cache failures.
10. Add monthly/annual endpoints only after the helper and precision contract are stable.
11. Separately, fix `TenantResolver` to fail closed and prefer token claims; audit all callers.
12. Rebuild backend and frontend, then run the regression plan.

---

## 12. Regression Test Plan

### Existing security and integrity tests (must remain green)

| Test | Expected |
|---|---|
| Sunset `GET /api/v1/properties` | only `prop-001`, `prop-002`, `prop-003` |
| Ocean `GET /api/v1/properties` | only `prop-001`, `prop-004`, `prop-005` |
| Sunset `prop-001` total | 200, `2250.000` / 4 |
| Ocean `prop-001` total | 200, `0` / 0 |
| Ocean `prop-002` | 404 |
| Unauthenticated `/api/v1/properties` | 401 |
| Redis keys | include `tenant-a` / `tenant-b` |
| Database failure | 503, no fabricated value, no cache entry |
| Cache failure handling | failed requests not cached |

### Timezone tests

Using March 2024 and `check_in_date` recognition:

| Test | Expected |
|---|---|
| tenant-a `prop-001` March, property-local Paris | `2250.000`, 4 reservations |
| tenant-a `prop-001` March, naive UTC (control) | `1000.000`, 3 reservations |
| tenant-a `prop-002` March | `4975.500`, 4 |
| tenant-a `prop-003` March | `6100.500`, 2 |
| tenant-a March total | `13326.000` |
| tenant-b `prop-004` March, New York | `1776.500`, 4 |
| tenant-b `prop-005` March | `3256.000`, 3 |
| tenant-b March total | `5032.500` |
| tenant-b `prop-001` March | `0.000`, 0 |
| April 2024 Paris | starts `2024-03-31T22:00Z`; no April check-ins in seed |
| `res-tz-1` classification | March for Paris properties, not February |

Verify the same values with direct SQL using explicit UTC bounds.

### Precision tests

| Test | Expected |
|---|---|
| `SUM(333.333, 333.333, 333.334)` | `1000.000` exact |
| Final 2-decimal display | `1000.00` |
| Per-row rounding control | `999.99` (shows why it must be avoided) |
| API serialization | string, not float |
| Frontend display | exactly the backend string; no `Math.round` |
| Large value | no drift beyond final rounding |

### Failure and isolation tests

- Stop the database, request an uncached property → 503; no Redis key created.
- Start the database, repeat → correct value; data unchanged.
- Sunset and Ocean request the same `prop-001` → distinct responses and distinct cache keys.

---

## 13. Risks and Backward Compatibility

| Risk | Impact | Mitigation |
|---|---|---|
| API `total_revenue` changes number → string | Existing clients may parse it as a number | Update frontend in the same release; document contract |
| Historical monthly totals change | Finance figures differ from previous reports | Confirm local-month rule; provide before/after evidence |
| DST transitions | Wrong boundary if fixed offsets are used | Use `ZoneInfo`; test March/November transitions |
| Timezone data absent in a future image | `ZoneInfoNotFoundError` | Keep system tzdata or add the `tzdata` OS package |
| Rounding mode convention | Half-up vs half-even differences | Document and test; use `ROUND_HALF_UP` explicitly |
| Fail-closed resolver | Other endpoints may 403/500 for users without a tenant | Audit all callers; keep explicit mapping for assignment accounts |
| Cache key changes | Old keys remain until TTL expires | Do not delete Redis data; new keys coexist until natural expiry |
| Currency diversity | `currency` column exists but no conversion | Do not aggregate across currencies until rules are defined |
| Multi-timezone tenants | Monthly totals may differ by property | Define whether reports aggregate property-local months or a chosen reporting timezone |

Phase 3/3.1 behavior must not be weakened: all period queries must retain `tenant_id` and property ownership checks.

---

## 14. Questions Requiring Business Confirmation

1. **Revenue recognition:** Is revenue recognized entirely on `check_in_date`, including stays crossing months? (Current code uses check-in; must be confirmed before changing monthly logic.)
2. **Timezone source:** Should reporting use the property's timezone (`properties.timezone`) rather than the user's browser or tenant's timezone? (Recommended: property timezone.)
3. **Tenant with multiple timezones:** If one tenant has properties in Paris and New York, should each property report in its own local month, or should all be converted to one tenant reporting timezone?
4. **Rounding mode:** Is `ROUND_HALF_UP` to two decimals the required financial convention, or `ROUND_HALF_EVEN`? Where should rounding occur—only at display, or also in stored report snapshots?
5. **Sub-cent data:** Should the API expose the exact 3-decimal value (`2250.000`) in addition to the 2-decimal display value?
6. **Currency:** Are all reports in USD? If not, what exchange-rate source and date should be used? The seed only uses USD.
7. **Annual definition:** Is the annual period the calendar year in the property timezone?
8. **Unknown tenant:** Confirm that users without a valid tenant should be denied (401/403) rather than mapped to a default tenant.
9. **Migration of historical reports:** Should previously issued monthly/UTC-based figures be restated, or only future reports use property-local boundaries?
10. **DST policy:** Confirm that month boundaries must follow IANA timezone rules including DST, not fixed UTC offsets.

---

## Confirmed Findings Summary

- Confirmed: monthly calculation stub is broken and unused.
- Confirmed: property timezone is stored but never used.
- Confirmed: naive UTC boundaries misclassify `res-tz-1` by `1250.000`.
- Confirmed: API converts decimal money to `float`.
- Confirmed: frontend recalculates and rounds with JavaScript numbers.
- Confirmed: per-row rounding of the seed values yields `999.99` instead of `1000.00`.
- Confirmed: no monthly/annual revenue endpoints exist.
- Confirmed: tenant resolver still fails open to `tenant-a` and ignores token claims.
- Potential: DST errors if `zoneinfo` is not used.
- Potential: cache collisions if period is added without a period-aware key.
- Potential: API contract break if `total_revenue` changes from number to string.

## Files that would need modification

`backend/app/services/reservations.py`, `backend/app/api/v1/dashboard.py`, `backend/app/services/cache.py`, `frontend/src/components/RevenueSummary.tsx`, and `frontend/src/lib/secureApi.ts`. The tenant-resolver security fix additionally touches `backend/app/core/tenant_resolver.py` and `backend/app/core/auth.py`. No schema or Docker changes are required.

## Proposed implementation steps

Confirm business rules; add a shared tenant-scoped period calculator; implement monthly/annual wrappers with `ZoneInfo` and half-open UTC bounds; preserve `check_in_date`; quantize once with an explicit rounding mode; return decimal strings; update the frontend to display without arithmetic; make cache keys period-aware; then add monthly/annual endpoints. Fix the tenant resolver separately.

## Business decisions requiring confirmation

Revenue recognition date, property-vs-tenant timezone, multi-timezone aggregation, rounding mode, sub-cent exposure, currency handling, annual definition, unknown-tenant denial, historical restatement, and DST policy.

No implementation was performed. Stopping here for approval.
