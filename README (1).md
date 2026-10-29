# Urja Meter Ops API

A REST API service (FastAPI, Python) that sits in front of the legacy **Urja Meter Ops** web portal (`https://urja-ops.flockenergy.tech`) and exposes its data as clean, typed JSON: meter details, geolocation, 30-minute consumption readings, distribution transformers and the network hierarchy. A small single-page dashboard is served on top of the API.

**Live deployment:** https://flock-urja-api.vercel.app  (hosted on Vercel)
**Source:** https://github.com/nimish1511/flock-urja-api

| Live link | URL |
|---|---|
| Dashboard | [https://flock-urja-api.vercel.app/dashboard](https://flock-urja-api.vercel.app/dashboard) |
| Swagger UI | [https://flock-urja-api.vercel.app/docs](https://flock-urja-api.vercel.app/docs) |
| ReDoc | [https://flock-urja-api.vercel.app/redoc](https://flock-urja-api.vercel.app/redoc) |
| OpenAPI spec | [https://flock-urja-api.vercel.app/openapi.json](https://flock-urja-api.vercel.app/openapi.json) |
| Health check | [https://flock-urja-api.vercel.app/health](https://flock-urja-api.vercel.app/health) |
| API base | `https://flock-urja-api.vercel.app/api/v1` |

**Where to find everything**

| What | Where |
|---|---|
| How the portal actually works (auth, endpoints, signing, quirks) | [PROTOCOL.md](PROTOCOL.md) |
| OpenAPI 3.1 description of *this* API | [openapi.json](openapi.json) (also served live at `/openapi.json`, rendered at `/docs` and `/redoc`) |
| Reflection answers | [REFLECTION.md](REFLECTION.md) |
| Assumptions, trade-offs, skipped items, known issues, next steps | Sections below |

---

## 1. What I built and how it is structured

On startup (and whenever the cache is older than the TTL) the service logs into the portal, pulls the **full dataset in one signed bulk call** (`/portal/export`) plus the transformer list (`/portal/dts`), and builds an in-memory index. Metadata endpoints are answered from that index. Consumption readings are **not** cached: each call goes live to the portal.

```
app/
  main.py              FastAPI app, lifespan (startup sync), error handlers, dashboard route
  config.py            Settings from env / .env (pydantic-settings)
  core/
    upstream_client.py Portal client: login, CSRF headers, re-auth, HMAC signing, fetch helpers
    cache.py           In-memory DataStore: sync, indexes, filtering, nearby search, hierarchy tree
  models/
    schemas.py         Pydantic response models (these drive openapi.json)
    errors.py          Upstream exception types and the JSON error envelope
  routers/
    meters.py          list/search, nearby, detail, consumption (+ timestamp/number normalisation)
    transformers.py    list, detail with connected meters
    hierarchy.py       hierarchy tree
    admin.py           sync status, forced sync
    health.py          health check
  static/dashboard.html  single-page UI
tests/                 pytest suite (mocked upstream) + one live smoke test
```

### Endpoints

| Method & path | Purpose |
|---|---|
| `GET /health` | Service status, whether the portal is reachable, whether the cache is populated |
| `GET /api/v1/meters` | Paginated list. `q` (substring of meter ID or serial), `make`, `phase_type`, `install_status`, `dt_code`, `page`, `page_size` (default 20, max 100) |
| `GET /api/v1/meters/nearby` | Meters within `radius_km` (0.01 to 50, default 1) of `latitude`/`longitude`, sorted by distance (Haversine) |
| `GET /api/v1/meters/{meter_id}` | Meter detail with coordinates and hierarchy. Also accepts a hardware serial number |
| `GET /api/v1/meters/{meter_id}/consumption` | Readings with ISO-8601 timestamps and numeric values, plus a summary |
| `GET /api/v1/transformers` | Paginated list, optional `feeder_code` filter |
| `GET /api/v1/transformers/{code}` | Transformer with its connected meters |
| `GET /api/v1/hierarchy` | Zone → Circle → Division → Subdivision → Substation → Feeder → DT tree with meter counts |
| `GET /api/v1/sync/status` | Cache age, counts, staleness |
| `POST /api/v1/sync` | Force a cache refresh |
| `GET /` and `/dashboard` | Web dashboard |

Errors use one envelope: `{"error": {"code": "...", "message": "...", "details": ...}}`. Portal-side failures map to 404 (not found), 504 (timeout), 502 (portal auth failure) or the upstream status.

### Dashboard

`app/static/dashboard.html` is one file served by the API. It has a searchable/filterable meters table with pagination, a transformers table, a hierarchy tree view, and a meter detail modal with a Chart.js consumption chart and readings table. It loads Tailwind, Chart.js and Font Awesome **from public CDNs**, so it needs internet access in the browser. It has no map and no UI for the nearby search.

---

## 2. Try it live, or install and run locally

### Live (no setup)

The service is deployed at **https://flock-urja-api.vercel.app**. For example:

```bash
curl "https://flock-urja-api.vercel.app/health"
curl "https://flock-urja-api.vercel.app/api/v1/meters?page=1&page_size=2"
curl "https://flock-urja-api.vercel.app/api/v1/hierarchy"
```

Or open the [dashboard](https://flock-urja-api.vercel.app/dashboard) or [Swagger UI](https://flock-urja-api.vercel.app/docs) in a browser.

### Local

Requires Python 3.10+ (developed and tested on newer versions).

```bash
git clone https://github.com/nimish1511/flock-urja-api.git
cd flock-urja-api

python3 -m venv venv
source venv/bin/activate            # Windows: .\venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                # then set PORTAL_PASSWORD (see below)
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open:
- Dashboard: http://127.0.0.1:8000/dashboard
- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc
- Spec: http://127.0.0.1:8000/openapi.json

### Configuration (environment variables or `.env`)

| Variable | Default | Meaning |
|---|---|---|
| `PORTAL_BASE_URL` | `https://urja-ops.flockenergy.tech` | Portal to wrap |
| `PORTAL_USERNAME` | `operator@urja.local` | Portal login |
| `PORTAL_PASSWORD` | the assignment password (see `app/config.py`) | Portal password. `.env.example` contains a placeholder; replace it, or the placeholder string will be used and login will fail |
| `API_PREFIX` | `/api/v1` | Route prefix |
| `CACHE_TTL_SECONDS` | `900` | Cache age after which the next request triggers a refresh |
| `AUTO_SYNC_ON_STARTUP` | `true` | Sync at boot. If it fails, the service still starts and retries on the first request |
| `UPSTREAM_TIMEOUT_SECONDS` | `15.0` | Per-request timeout to the portal |
| `UPSTREAM_MAX_RETRIES` | `3` | **Declared but not currently used by any code** |
| `HOST`, `PORT`, `DEBUG` | `0.0.0.0`, `8000`, `false` | Server settings |

### Tests

```bash
pytest -v
```

25 tests are collected. 24 run fully offline against a mocked portal client (meters, filters, pagination, nearby, consumption, transformers, hierarchy, health). The 25th (`tests/test_live_smoke.py`) calls the real portal read-only; it is skipped if the portal is unreachable. Note that the mocked tests use a 4-meter fixture, and one test (`test_hmac_signature_generation`) re-implements the signing formula inline rather than calling the client.

---

## 3. Sample requests

Replace `http://127.0.0.1:8000` with `https://flock-urja-api.vercel.app` to run these against the deployed service.

```bash
curl "http://127.0.0.1:8000/api/v1/meters?make=HPL&phase_type=single&page=1&page_size=2"
```
```json
{
  "items": [
    {"meter_id": "J100000", "serial_no": "SE33962", "make": "HPL", "phase_type": "single",
     "install_status": "Decommissioned", "dt_code": "DT-001",
     "install_type": "Whole Current", "build": "legacy"}
  ],
  "total": 41, "page": 1, "page_size": 2, "pages": 21
}
```

```bash
curl http://127.0.0.1:8000/api/v1/meters/J100000
curl http://127.0.0.1:8000/api/v1/meters/J100000/consumption
curl "http://127.0.0.1:8000/api/v1/meters/nearby?latitude=26.9389&longitude=75.8309&radius_km=0.5"
curl http://127.0.0.1:8000/api/v1/transformers/DT-001
curl http://127.0.0.1:8000/api/v1/hierarchy
```

(Example values are from a previous run against the live portal; actual numbers depend on portal data.)

---

## 4. How the portal works (summary)

Full detail is in [PROTOCOL.md](PROTOCOL.md). In short: the portal is a SvelteKit app with cookie-session login (`POST /login` as form data, which needs an `Origin` header or SvelteKit's CSRF check returns 403). Behind the UI are JSON endpoints under `/portal/` for meter search, DTs, per-meter geo and per-meter energy. A signing secret from `/portal/keys` is used to HMAC-SHA256 sign requests to `/portal/export`, which returns every meter with its hierarchy and coordinates, avoiding one request per meter.

---

## 5. Assumptions

1. **Timezone is IST (UTC+05:30).** Portal timestamps (`DD/MM/YYYY HH:MM`) carry no timezone. Coordinates are around Jaipur and the hierarchy uses Indian DISCOM terms, so I attach `+05:30`. This is an inference, not something the portal states.
2. **`kwh` and `kvah` are cumulative registers**, because values increase over time. I did not independently confirm this beyond the data pattern.
3. **Meter metadata changes slowly**, so a 15-minute TTL is an acceptable freshness trade-off. Consumption is treated as live and fetched per request.
4. **The portal is read-only for me.** The service only issues the login POST and GET requests.
5. **The export returns the full dataset in one response** (`page=1`), based on observed behaviour (403 meters). The code requests only `page=1` and does not check for further pages.
6. **Placeholder values** (`""`, `"—"`, `null`) in numeric fields mean "missing" and are returned as `null`.

---

## 5a. Deployment notes (Vercel)

- The app is deployed on Vercel at https://flock-urja-api.vercel.app. Configuration (`PORTAL_USERNAME`, `PORTAL_PASSWORD`, etc.) is set as Vercel environment variables, not committed to the repo.
- **The cache is in-memory per instance.** On serverless hosting, instances can be started and stopped at any time, so the cache may be rebuilt on a cold start (the first request after idle can be slower while it syncs with the portal) and is not shared between instances.
- The 15-minute TTL and the on-miss forced sync described below still apply per instance.
- The dashboard loads from the same origin, so it works against the live API without extra configuration.

---

## 6. Design decisions and trade-offs

- **Bulk export instead of per-meter calls.** One signed request replaces hundreds. Trade-off: the signing scheme was reverse-engineered from the portal's JS and could change without notice.
- **In-memory store, no database.** Zero dependencies and fast at ~400 meters. Trade-off: state is per process, lost on restart, not shared between workers.
- **Lazy TTL refresh.** The cache is refreshed by whichever request first finds it stale (guarded by an `asyncio.Lock` with a re-check, and swapped in atomically). There is no background refresher, and if a refresh fails the request fails rather than serving the old data.
- **Cache-miss behaviour.** A lookup of an unknown meter ID or transformer code triggers a forced re-sync before returning 404, so newly added items are found without waiting for the TTL. Trade-off: see known issues, this can be abused to hammer the portal.
- **Consumption passes through live.** Always current, but adds load on the portal and latency per call, and is not cached.
- **Local search and filtering** over the cached data rather than calling the portal's search, which allows multi-attribute filters and nearby search that the portal does not offer.
- **Normalised output.** snake_case fields, floats instead of strings, ISO-8601 timestamps with offset, one error envelope.
- **Session handling.** The client logs in lazily; on a 401/403 or a redirect to `/login` it re-authenticates and retries the request once.

---

## 7. What I intentionally skipped, and why

- **Authentication on this API.** Out of scope for the exercise; it means anyone who can reach the service can read utility data and call `POST /api/v1/sync`. CORS is also fully open (`*`).
- **A database / persistent store and time-series storage.** Not needed at this data size; consumption is not stored.
- **Background refresh, webhooks or streaming.** Adds moving parts beyond the brief.
- **Meter nameplate attributes.** The portal's meter detail page carries extra nameplate fields in two different shapes (see PROTOCOL.md). The API has an `extra_attributes` field in its schema, but **it is never populated and is always `null`**.
- **Retries and backoff for 5xx or network errors.** Only the single re-auth retry exists.
- **Pagination of the bulk export.** Only page 1 is fetched.
- **A map view, anomaly/health summaries and a UI for nearby search** in the dashboard.
- **Rate limiting and caching of consumption responses.**

---

## 8. Known issues and limitations (found in review)

I would rather list these than have them discovered:

1. **Consumption summary is partly misleading.** `min_kwh`, `max_kwh` and `avg_kwh` are computed over the *cumulative register values*, so `avg_kwh` is a register average, not average consumption. `total_kwh` is `max − min` over the window, which is wrong if a meter register resets or rolls over. Per-interval deltas are not computed.
2. **`power_factor` is kWh ÷ kVAh of the cumulative registers** (capped at 1.0), i.e. a lifetime-style ratio, not an interval power factor.
3. **Forced sync on every miss** (unknown meter ID or transformer code) bypasses the TTL and can generate repeated bulk-export calls to the portal.
4. **`POST /api/v1/sync` is unauthenticated** and forces a refresh.
5. **Serial-number lookups on the consumption endpoint.** Meter detail accepts a serial number, but the consumption route passes the raw input to the portal's energy endpoint instead of the resolved meter ID, so a serial lookup will not return readings.
6. **Hierarchy is built only from each meter's embedded hierarchy and is not validated.** Meters with no zone are left out of the tree; meters with a missing level stop at that level (so a parent's count can exceed the sum of its children); nodes are keyed by code (or name), and if the same code appears with different names the first name wins. The `feederCode` on `/portal/dts` is not reconciled against the feeder in each meter's hierarchy. No data-quality report is produced.
6. **Auth handling is basic.** Login failure is detected by looking for the word `failure` in the response body; a missing session cookie only logs a warning; there is no lock around concurrent re-authentication; the cached signing secret is not cleared on auth errors; `UPSTREAM_MAX_RETRIES` is unused.
7. **Scale:** filtering, nearby search and transformer lookup are linear scans over in-memory lists. Fine for ~400 meters and 40 transformers; there is no benchmark beyond that.
8. **Dashboard depends on public CDNs** (Tailwind, an unpinned Chart.js, Font Awesome).
9. **Credentials:** the assignment's portal credentials are hardcoded as defaults in `app/config.py` and appear in the docs.

### Where the approach would struggle at larger scale

Roughly: the full-export-into-memory approach is fine into the low tens of thousands of meters. Beyond that the refresh time, memory per worker, and O(n) scans would hurt. I would then move to a database (PostgreSQL with PostGIS or a spatial index for "nearby"), refresh incrementally in a background job, and share state across workers. I have not measured where the actual limit is.

---

## 9. What I would improve with more time

1. Compute per-interval kWh deltas (handling gaps and resets) and drop the cumulative avg/min/max; compute interval power factor.
2. Add a cooldown on forced syncs, protect `/sync`, and serve stale data if a refresh fails.
3. Loop over export pages until `total` is reached and verify the count.
4. Add a hierarchy data-quality report (orphans, partial paths, code/name conflicts, feeder mismatches) and expose unassigned meters.
5. Parse and expose nameplate attributes.
6. Real retry/backoff with jitter and a circuit breaker; guard re-auth with a lock.
7. API authentication, tighter CORS, secrets only via environment.
8. Tests for session expiry, login failure, malformed data and export paging; make the signing test call the client code.
9. Vendor the dashboard assets, add a map and a nearby-search UI.
10. A short-lived consumption cache and a concurrency limit towards the portal.

---

## Reflection

Answers to the five reflection questions are in [REFLECTION.md](REFLECTION.md).
