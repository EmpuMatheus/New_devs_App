# PHASE4_FINAL_AUDIT.md

Final Phase 4 audit of the implemented timezone, precision, tenant-security, and revenue-report changes. No source code, database records, Docker configuration, or volumes were modified during this audit. The only file created is this report.

Audit date: 2026-11-10 (local). Containers were already running; read-only queries and API GETs were used. API GETs may have refreshed Redis cache entries but did not delete them or change PostgreSQL data.

---

## 1. Currency behavior

### 1.1 Zero-reservation property

**Code:** `backend/app/services/reservations.py`, `_load_property_context` (around lines 60-93).

The property lookup uses a `LEFT JOIN` to reservations. When a property exists but has no reservations:

- `COUNT(DISTINCT r.currency)` is `0`.
- `MIN(r.currency)` is `NULL`.
- The result sets `"currency": row.currency or "USD"`.

**Verified via API** for Ocean `prop-001` (property exists under `tenant-b`, zero reservations):

```text
zero-res all-time Ocean prop-001 | HTTP 200 | exact=0.000 display=0.00 count=0 currency=USD
zero-res monthly Ocean prop-001 2024-03 | HTTP 200 | exact=0.000 display=0.00 count=0 currency=USD
```

**Finding:** A zero-revenue response returns a syntactically valid currency (`USD`).

**Risk:** `USD` is a fallback, not an authoritative property-level value. A property whose real currency is EUR but which has no reservations yet will be reported as USD. The schema has no `properties.currency` column; currency is derived from reservation rows only.

### 1.2 Currency source

**Code:** `_load_property_context` selects:

```sql
COUNT(DISTINCT r.currency) AS currency_count,
MIN(r.currency) AS currency
```

**Finding:** Currency is derived from reservation records, not from an authoritative property-level source. There is no property currency column. The frontend/API correctly includes the derived `currency`, and no conversion is performed.

### 1.3 Mixed-currency reservations

**Code:** `_load_property_context` raises `RevenueConfigurationError` when `currency_count > 1`. The error occurs before the period aggregation, so no mixed-currency total is returned. The API maps this to HTTP 500 with the generic detail `Revenue configuration error`; the exception is logged server-side, not exposed to the client. The cache helper is never reached with a result, so nothing is cached.

**Status:** Safe by code inspection; **not executed end-to-end** because the seed contains only USD reservations and database records must not be modified.

**Confirmed edge-case risk (NULL currency):**

- `COUNT(DISTINCT r.currency)` and `MIN(r.currency)` ignore `NULL`.
- The aggregation filter uses `COALESCE(currency, 'USD') = :currency`.
- Consequence: if a property has one `NULL`-currency reservation and one `EUR` reservation, the context resolves to `EUR` and the `NULL` row is excluded from the total rather than treated as USD.
- All seeded rows have `USD`, so this is not observable in the current data.

**Recommended fix:** Use `COALESCE(r.currency, 'USD')` consistently in the `COUNT(DISTINCT ...)`, `MIN(...)`, and filter, or make currency `NOT NULL` with a property-level source.

---

## 2. Frontend manual verification

No browser automation tool is available and no manual browser session was performed. Verification was by source inspection plus a production build and bundle checks. This limitation is explicit.

### 2.1 Monthly and annual controls

`frontend/src/components/Dashboard.tsx`:

- Report selector: All time / Monthly / Annual.
- Year input is rendered for Monthly and Annual, `min=1900`, `max=2100`.
- Month selector is rendered for Monthly.
- Property selector remains tenant-scoped via `GET /api/v1/properties`.
- `period` is constructed from `reportType`, `year`, and `month` and passed to `RevenueSummary`.

### 2.2 Loading, error, and empty states

`frontend/src/components/RevenueSummary.tsx`:

- **Loading:** skeleton card while `loading` is true.
- **Error:** red error card with `Failed to load revenue data`.
- **Empty/null:** `No revenue data available`.
- **Zero revenue:** valid success state; displays `0.00` rather than treating zero as empty.
- **Dashboard empty property list:** `No properties are available for your account`.
- **Dashboard property-fetch error:** `Failed to load your properties`.

### 2.3 Property/period request behavior

`RevenueSummary` effect dependencies: `propertyId`, `periodType`, `periodYear`, `periodMonth`.

Changing property or report parameters triggers a new request to the correct endpoint:

- Monthly: `SecureAPI.getMonthlyRevenue(propertyId, year, month)`.
- Annual: `SecureAPI.getAnnualRevenue(propertyId, year)`.
- All time: `SecureAPI.getDashboardSummary(propertyId, ...)`.

A `cancelled` flag in the effect cleanup prevents a late response from an old request from updating state after the inputs change.

### 2.4 Stale-data risk (confirmed by code inspection)

`RevenueSummary` does **not** clear `data` at the start of the effect. It sets `loading` inside the effect (after the render). On a property/period change, React renders once with the old `data` and the new period label/property selector before the effect runs and shows the loading state. This can display the previous revenue value for one paint under the new label.

Out-of-order network results are prevented by the `cancelled` flag, but the pre-effect render is not prevented.

**Recommended fix:** set `setData(null)` before/at the start of the request, or remount the component with a key derived from property + period.

### 2.5 String-only financial display

- `RevenueSummaryResponse.total_revenue` and `total_revenue_exact` are typed as `string`.
- Display uses `formatAmount(data.total_revenue)` and `formatAmount(data.total_revenue_exact)` with string splitting/grouping.
- No `Math.round`, `Number`, or `parseFloat` is applied to revenue.
- The only `Math.round` in `secureApi.ts` is the retry delay, not money.

**Verified source grep:**

```text
no mock_data
no fabricated
no X-Simulated-Tenant
no simulatedTenant
Math.round only in SecureAPI retry-delay logging
```

---

## 3. Invalid timezone

### 3.1 Unit test inspected

`backend/tests/test_revenue_period.py`:

```python
def test_invalid_timezone_is_controlled_error(self):
    with self.assertRaises(RevenueConfigurationError):
        month_bounds_utc(2024, 3, "Not/A_Timezone")
    with self.assertRaises(RevenueConfigurationError):
        month_bounds_utc(2024, 3, "")
```

Executed:

```text
test_invalid_timezone_is_controlled_error ... ok
Ran 1 test ... OK
```

### 3.2 No silent UTC fallback

`get_timezone` in `backend/app/services/reservations.py`:

- Rejects missing/blank/non-string values.
- Calls `ZoneInfo(timezone_name)`.
- Catches any exception and raises `RevenueConfigurationError` with the invalid identifier.
- There is no `except: return ZoneInfo("UTC")` or similar fallback.

The API catches `RevenueConfigurationError` separately and returns HTTP 500 with `Revenue configuration error`; it does not return UTC data.

### 3.3 Failed results are not cached

`backend/app/services/cache.py`, `_cached`:

- Cache is read first.
- `calculate()` runs and any exception propagates.
- `setex` is only called after a successful, non-`None` result.

Executed with a monkeypatched property context returning `{"timezone": "Not/A_Timezone", "currency": "USD"}` (no DB writes):

```text
error_type RevenueConfigurationError
error_message_has_timezone True
cache_key_exists 0
```

This confirms the invalid timezone raises and creates no cache entry.

**Limitation:** No database property has an invalid timezone and records must not be modified, so the endpoint-level 500 path was verified by code inspection, not by an invalid-timezone database fixture.

---

## 4. API contract

Executed against the running backend.

### 4.1 Monthly response

```json
{
  "property_id": "prop-001",
  "year": 2024,
  "month": 3,
  "timezone": "Europe/Paris",
  "currency": "USD",
  "total_revenue_exact": "2250.000",
  "total_revenue": "2250.00",
  "reservations_count": 4,
  "period_start": "2024-02-29T23:00:00+00:00",
  "period_end": "2024-03-31T22:00:00+00:00"
}
```

### 4.2 Annual response

```json
{
  "property_id": "prop-001",
  "year": 2024,
  "timezone": "Europe/Paris",
  "currency": "USD",
  "total_revenue_exact": "2250.000",
  "total_revenue": "2250.00",
  "reservations_count": 4,
  "period_start": "2023-12-31T23:00:00+00:00",
  "period_end": "2024-12-31T23:00:00+00:00"
}
```

### 4.3 Executed contract results

| Test | HTTP | Exact | Display | Count | Currency | Types |
|---|---:|---|---|---:|---|---|
| Zero-reservation Ocean `prop-001` all-time | 200 | `0.000` | `0.00` | 0 | USD | String/String |
| Zero-reservation Ocean `prop-001` monthly 2024-03 | 200 | `0.000` | `0.00` | 0 | USD | String/String |
| Sunset `prop-001` monthly 2024-03 | 200 | `2250.000` | `2250.00` | 4 | USD | String/String |
| Sunset `prop-001` annual 2024 | 200 | `2250.000` | `2250.00` | 4 | USD | String/String |
| Ocean foreign `prop-002` monthly | 404 | — | — | — | — | — |
| Invalid month `0` | 422 | — | — | — | — | — |
| Invalid month `13` | 422 | — | — | — | — | — |
| Invalid year `1800` | 422 | — | — | — | — | — |
| Invalid year `2101` | 422 | — | — | — | — | — |
| Unauthenticated monthly | 401 | — | — | — | — | — |

### 4.4 Tenant and property isolation

```text
Sunset properties: prop-001, prop-002, prop-003
Ocean properties:  prop-001, prop-004, prop-005
Ocean foreign monthly prop-002: HTTP 404
```

The same `prop-001` ID remains isolated by tenant:

- Sunset `prop-001` monthly 2024-03: `2250.000` / 4.
- Ocean `prop-001` monthly 2024-03: `0.000` / 0.

Cache keys remain tenant-specific:

```text
revenue:v2:tenant-a:prop-001:month:2024-03
revenue:v2:tenant-b:prop-001:month:2024-03
```

---

## 5. Regression

### 5.1 Phase 3 and 3.1 behavior

| Check | Result |
|---|---|
| Sunset property list | `prop-001, prop-002, prop-003` |
| Ocean property list | `prop-001, prop-004, prop-005` |
| Sunset `prop-001` revenue | `2250.000` / `2250.00` / 4 |
| Ocean `prop-001` revenue | `0.000` / `0.00` / 0 |
| Ocean foreign `prop-002` | 404 |
| Unauthenticated tenant-scoped endpoint | 401 |
| No mock/fabricated revenue | Source grep: none |
| No simulated tenant authorization | Source grep: none |
| Tenant-aware cache keys | Verified |
| Failed requests not cached | Invalid-timezone direct test: key absent |

### 5.2 Database records

Read-only query:

```text
reservations | tenants | tenant_properties
17           | 2       | 5
```

Per tenant/property totals match the seed:

```text
tenant-a prop-001  4  2250.000
tenant-a prop-002  4  4975.500
tenant-a prop-003  2  6100.500
tenant-b prop-004  4  1776.500
tenant-b prop-005  3  3256.000
```

No rows were inserted, updated, deleted, reset, or reseeded.

### 5.3 Docker volumes

- `docker volume ls` shows one anonymous PostgreSQL volume:
  `2478d8c86ce8eed31435a7f21c0b17f158758e4eb6e7bf3739daa495dce9d1aa`
- `new_devs_app-db-1` mounts it at `/var/lib/postgresql/data`.
- Redis has no volume (in-memory cache).
- No volume was removed.

No Docker configuration files were modified; `docker compose down` / `down -v` was not run.

### 5.4 Tests executed

```text
docker compose exec -T backend python -m unittest discover -s tests -v
Ran 17 tests in 0.158s
OK
```

The suite includes timezone/DST boundaries, December rollover, invalid timezone/month, precision, resolver security, and a seeded-database integration test for March/February/all-time revenue and foreign-property denial.

---

## Verified findings summary

| # | Finding | Status |
|---|---|---|
| 1 | Zero-reservation property returns `0.000` / `0.00` / 0 with a valid currency (`USD`) | Verified via API |
| 2 | Currency is derived from reservation rows, not a property-level source | Verified by code inspection |
| 3 | No-reservation/default currency is `USD`, which may not match the real property currency | Confirmed risk |
| 4 | Mixed non-null currencies are rejected with a controlled configuration error | Verified by code inspection; not fixture-tested |
| 5 | NULL + single non-USD currency can exclude NULL-currency rows | Confirmed code-level edge case |
| 6 | Monthly/annual controls and endpoint selection are correct | Verified by source inspection/build |
| 7 | Loading/error/empty states exist; zero is displayed as a valid amount | Verified by source inspection |
| 8 | Old response data cannot overwrite new data after cancellation | Verified by code inspection |
| 9 | One pre-effect render may show old data under a new label | Confirmed minor stale-render risk |
| 10 | All financial display values are backend-provided strings; no float arithmetic | Verified by source grep and API type checks |
| 11 | Invalid timezone raises a controlled error; no UTC fallback | Unit test + code inspection + direct execution |
| 12 | Invalid timezone/failures create no cache entry | Direct execution (`cache_key_exists 0`) |
| 13 | Monthly/annual contracts return exact/display strings, timezone, bounds | Verified via API |
| 14 | Invalid month/year → 422; foreign/unknown property → 404; unauthenticated → 401 | Verified via API |
| 15 | Tenant/property isolation and tenant-specific cache keys remain intact | Verified |
| 16 | Phase 3/3.1 behavior intact | Verified |
| 17 | Database has 17 unchanged reservations and matching totals | Verified |
| 18 | PostgreSQL volume exists and was not removed | Verified |

---

## Remaining risks

1. **No authoritative property currency.** Zero-reservation properties default to USD, and a property whose real currency differs can be mislabeled. Requires a property-level currency column or configuration.
2. **NULL currency inconsistency.** `COUNT`/`MIN` ignore NULL while the filter uses `COALESCE(..., 'USD')`. A property with NULL + EUR can silently omit the NULL row.
3. **Mixed-currency rejection is conservative and untested with fixtures.** Any historical mixed currency on a property blocks every period, even if the requested period is single-currency. The behavior is safe (no mixing) but may surprise users. No seed/fixture exercises it.
4. **One-frame stale UI render.** `RevenueSummary` does not clear `data` before the effect runs, so a property/period change can briefly show the previous value under the new label. Network-race staleness is prevented.
5. **No browser E2E/MANUAL click-through.** Controls and states were verified by code inspection and production build, not by a headless browser.
6. **Invalid-timezone endpoint integration is not fixture-tested.** Only the helper/unit and direct service path are tested because records cannot be modified.
7. **Configuration errors return HTTP 500.** This is generic and safe, but a deliberate 409/422 contract might be preferable for finance clients.
8. **Year input range is enforced mainly server-side.** The UI sets min/max, but typed out-of-range values reach the API and produce 422.
9. **SecureAPI client cache still ignores `app_metadata` tenant claims**, so its short-lived request cache is bypassed for these tokens (performance only, no data leak).
10. **Cache invalidation on reservation writes is still absent**; TTL 300 s bounds staleness. No write endpoints exist in this trimmed app.

---

## Recommended fixes (not implemented)

1. Add an authoritative property-level currency (column or configuration) and validate reservation currencies against it. Use it for zero-reservation responses.
2. Normalize NULL currency consistently:
   ```sql
   COUNT(DISTINCT COALESCE(r.currency, 'USD')) AS currency_count,
   MIN(COALESCE(r.currency, 'USD')) AS currency
   ```
   Keep the aggregation filter as `COALESCE(currency, 'USD') = :currency`.
3. In `RevenueSummary`, clear `data` at request start or key the component by property + period to eliminate the one-frame stale render.
4. Add a mixed-currency and NULL-currency fixture in a future test database, then verify the endpoint returns the controlled error and no cache entry.
5. Add a browser E2E test for property/report switching, loading/error/empty states, and string formatting.
6. Decide whether mixed-currency configuration errors should be 409/422 instead of 500, and document the contract.
7. Optionally clamp the year input client-side to 1900-2100 for immediate feedback.

---

## Audit caveats

- No source code was modified during this audit.
- No PostgreSQL records were modified; no reset/reseed was performed.
- No Docker configuration was modified; no volumes were removed; `docker compose down` was not run.
- API GET requests may have created/refreshed Redis cache entries under `revenue:v2:*`; no Redis keys were deleted.
- The audit was not a browser-driven manual test; all frontend findings are from source inspection, the successful production build, and bundle checks.