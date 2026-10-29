# Urja Meter Ops REST API Service — Flock Energy Take-Home

A clean, production-grade, documented REST API service built over the legacy **Urja Meter Ops** portal (`https://urja-ops.flockenergy.tech`).

This service enables programmatic access to smart meter metadata, historical 30-minute consumption telemetries, Distribution Transformer (DT) associations, and a reconstructed 7-tier electrical distribution network hierarchy without direct manual interaction with the legacy web portal.

[![Test Suite](https://img.shields.io/badge/pytest-25%20passed-emerald)](tests/)
[![OpenAPI Spec](https://img.shields.io/badge/OpenAPI-3.1.0-blue)](openapi.json)
[![Python Version](https://img.shields.io/badge/python-3.14%2B-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-059669)](https://fastapi.tiangolo.com)

---

## 📑 Quick Links & Deliverables

- 📘 **[PROTOCOL.md](PROTOCOL.md)** — Detailed reverse-engineering write-up of the Urja Meter Ops portal (authentication, SvelteKit CSRF bypass, HMAC-SHA256 signing, endpoints, and data anomalies).
- 📜 **[openapi.json](openapi.json)** — Complete OpenAPI 3.1.0 specification describing all implemented routes, models, and error envelopes.
- 💡 **[REFLECTION.md](REFLECTION.md)** — In-depth answers to the five take-home reflection questions.


---

## 🚀 Key Implemented Capabilities

1. **Smart Meter Search & Multi-Attribute Filtering**:
   - Query across 403 smart meters by meter ID (`meter_id`) or hardware serial number (`serial_no`).
   - Filter by manufacturer (`HPL`, `Secure`, `Genus`, `L&T`, `Allied`), phase wiring (`single`, `three`), operational status (`Installed`, `Decommissioned`, `Faulty`), or transformer code (`DT-001`).
   - Full 1-based pagination.
2. **Geospatial Proximity Queries**:
   - Query smart meters within a given radius (`radius_km`) around specified latitude and longitude coordinates using great-circle distance (Haversine formula).
3. **Consumption Time-Series & Analytics**:
   - Fetches 30-minute interval readings for any meter.
   - Normalizes raw timestamps (`"23/06/2026 23:30"`) to ISO-8601 with Indian Standard Time offset (`2026-06-23T23:30:00+05:30`).
   - Normalizes string registers to floats; sanitizes non-numeric placeholders (`"—"`).
   - Computes interval summary metrics: reading count, time window, delta total kWh consumption, min/max/avg kWh, average RMS voltage, and active power factor ($\frac{\text{kWh}}{\text{kVAh}}$).
4. **Distribution Transformers (DTs)**:
   - Paginated listing of 40 distribution transformers across 11kV feeders.
   - Detail view attaching all connected smart meters.
5. **Reconstructed 7-Tier Grid Distribution Hierarchy**:
   - Assembles the complete utility hierarchy tree with aggregated meter counts:
     $$\text{Zone} \longrightarrow \text{Circle} \longrightarrow \text{Division} \longrightarrow \text{Subdivision} \longrightarrow \text{Substation} \longrightarrow \text{Feeder} \longrightarrow \text{Distribution Transformer (DT)}$$
6. **Resilient Upstream Integration & HMAC Bulk Sync**:
   - Automated SvelteKit CSRF header management (`Origin`, `Referer`).
   - Transparent re-authentication on token expiration or redirects.
   - Cryptographic HMAC-SHA256 signature generator for `/portal/export`, downloading all 403 meters in a single bulk call.
7. **Interactive Modern Web Dashboard**:
   - Single-page application served directly from `/dashboard` and `/` featuring search, live stats, Chart.js consumption charts, and an interactive grid hierarchy explorer.

---

## 🏗️ Architecture & Data Flow

```
                               ┌──────────────────────────────────────────────────────────┐
                               │                    FastAPI Service                       │
                               │                                                          │
  Incoming Client Request ───► │  [Routers]                                               │
  (e.g. GET /api/v1/meters)    │   ├── /health                                            │
                               │   ├── /api/v1/meters (search, filter, nearby, detail)    │
                               │   ├── /api/v1/meters/{id}/consumption                    │
                               │   ├── /api/v1/transformers (DTs, connected meters)       │
                               │   ├── /api/v1/hierarchy (7-tier grid topology)           │
                               │   └── /dashboard (Interactive Web Console)               │
                               │         │                                                │
                               │         ▼                                                │
                               │  [DataStore / Cache] ◄─── In-memory index & tree builder │
                               │         ▲                                                │
                               │         │                                                │
                               │  [UpstreamPortalClient]                                  │
                               │   ├── Auto-reauth & CSRF handling                        │
                               │   ├── HMAC-SHA256 signature generation                   │
                               │   └── HTTPX async connection pool                        │
                               └─────────┼────────────────────────────────────────────────┘
                                         │ HTTPS Requests (Origin, Referer, Cookies)
                                         ▼
                               ┌──────────────────────────────────────────────────────────┐
                               │       Legacy Urja Meter Ops Portal (SvelteKit)           │
                               │       https://urja-ops.flockenergy.tech                  │
                               └──────────────────────────────────────────────────────────┘
```

---

## 🛠️ Technology Stack & Rationale

- **Python 3.14**: Latest stable runtime with native async/await performance and proactor event loops.
- **FastAPI**: Modern, high-performance async web framework with automatic OpenAPI 3.1 generation and Pydantic validation.
- **HTTPX**: Async HTTP client with connection pooling, cookiejar handling, and timeout configurations.
- **Pydantic v2**: High-speed Rust-backed data validation and serialization.
- **Uvicorn**: Lightning-fast ASGI production web server.
- **Pytest & Pytest-Asyncio**: Comprehensive test runner for unit, integration, and live smoke testing.
- **Tailwind CSS & Chart.js**: Lightweight, dependency-free frontend console for visual validation.

---

## 📦 Installation & Setup

### Prerequisites
- Python 3.10+ (tested on Python 3.14)
- Git

### 1. Clone & Enter Repository
```bash
git clone <your-repo-url>
cd flock-urja-api
```

### 2. Create and Activate Virtual Environment
```bash
# On Windows
python -m venv venv
.\venv\Scripts\activate

# On Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Default `.env` settings:
```ini
PORTAL_BASE_URL=https://urja-ops.flockenergy.tech
PORTAL_USERNAME=operator@urja.local
PORTAL_PASSWORD=urja-ops-2026
API_PREFIX=/api/v1
HOST=0.0.0.0
PORT=8000
CACHE_TTL_SECONDS=900
AUTO_SYNC_ON_STARTUP=true
```

---

## 🏃 Running the Application

Start the API service using Uvicorn:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Once started:
- 🌐 **Modern Web Dashboard**: [http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard)
- 📖 **Interactive Swagger UI**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- 📚 **ReDoc Documentation**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- 📜 **Raw OpenAPI 3.1 Spec**: [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json)

---

## 🧪 Running Automated Tests

The test suite contains **25 automated tests** covering:
- Service health & degraded states
- Meter listing, pagination, query search, and multi-field filtering
- Meter detail resolution & hardware serial fallback
- Haversine geospatial proximity calculations
- Consumption time-series normalization, ISO timestamp parsing, delta kWh calculations, and power factor estimation
- Distribution transformer listing & connected meter aggregation
- 7-tier distribution hierarchy reconstruction
- Upstream HMAC signing & CSRF header validation
- Live, read-only smoke tests against the running portal

Execute the full suite:
```bash
pytest -v
```

### Actual Verification Results:
```
tests/test_consumption.py::test_get_consumption_success PASSED           [  4%]
tests/test_consumption.py::test_consumption_meter_not_found PASSED       [  8%]
tests/test_health.py::test_health_healthy PASSED                         [ 12%]
tests/test_health.py::test_health_degraded_when_portal_down PASSED       [ 16%]
tests/test_hierarchy.py::test_get_hierarchy_tree PASSED                  [ 20%]
tests/test_live_smoke.py::test_live_portal_smoke PASSED                  [ 24%]
tests/test_meters.py::test_list_meters_all PASSED                        [ 28%]
tests/test_meters.py::test_search_meter_by_id PASSED                     [ 32%]
tests/test_meters.py::test_search_meter_by_serial PASSED                 [ 36%]
tests/test_meters.py::test_filter_by_make PASSED                         [ 40%]
tests/test_meters.py::test_filter_by_phase PASSED                        [ 44%]
tests/test_meters.py::test_filter_by_status PASSED                       [ 48%]
tests/test_meters.py::test_filter_by_dt PASSED                           [ 52%]
tests/test_meters.py::test_pagination PASSED                             [ 56%]
tests/test_meters.py::test_get_meter_detail_success PASSED               [ 60%]
tests/test_meters.py::test_get_meter_by_serial_fallback PASSED           [ 64%]
tests/test_meters.py::test_get_meter_not_found PASSED                    [ 68%]
tests/test_meters.py::test_nearby_meters PASSED                          [ 72%]
tests/test_transformers.py::test_list_transformers PASSED                [ 76%]
tests/test_transformers.py::test_filter_by_feeder PASSED                 [ 80%]
tests/test_transformers.py::test_get_transformer_detail PASSED           [ 84%]
tests/test_transformers.py::test_transformer_not_found PASSED            [ 88%]
tests/test_upstream_client.py::test_haversine_distance_calculation PASSED [ 92%]
tests/test_upstream_client.py::test_hmac_signature_generation PASSED     [ 96%]
tests/test_upstream_client.py::test_client_headers PASSED                [100%]
======================== 25 passed in 2.12s ========================
```

---

## 🔍 Sample cURL Requests & Responses

### 1. Health Check
```bash
curl -X GET http://127.0.0.1:8000/health
```
**Response**:
```json
{
  "status": "ok",
  "service": "flock-urja-api",
  "version": "1.0.0",
  "portal_connected": true,
  "cache_synced": true,
  "timestamp": "2026-10-30T01:23:39.382732+00:00"
}
```

### 2. Search & Filter Meters
```bash
curl -X GET "http://127.0.0.1:8000/api/v1/meters?make=HPL&phase_type=single&page=1&page_size=2"
```
**Response**:
```json
{
  "items": [
    {
      "meter_id": "J100000",
      "serial_no": "SE33962",
      "make": "HPL",
      "phase_type": "single",
      "install_status": "Decommissioned",
      "dt_code": "DT-001",
      "install_type": "Whole Current",
      "build": "legacy"
    },
    {
      "meter_id": "J100008",
      "serial_no": "SE33970",
      "make": "HPL",
      "phase_type": "single",
      "install_status": "Installed",
      "dt_code": "DT-001",
      "install_type": "Whole Current",
      "build": "legacy"
    }
  ],
  "total": 41,
  "page": 1,
  "page_size": 2,
  "pages": 21
}
```

### 3. Meter Detail with Coordinates & Hierarchy
```bash
curl -X GET http://127.0.0.1:8000/api/v1/meters/J100000
```
**Response**:
```json
{
  "meter_id": "J100000",
  "serial_no": "SE33962",
  "make": "HPL",
  "phase_type": "single",
  "install_status": "Decommissioned",
  "dt_code": "DT-001",
  "install_type": "Whole Current",
  "build": "legacy",
  "geo": {
    "latitude": 26.938961002479868,
    "longitude": 75.83095696146852
  },
  "hierarchy": {
    "zone": { "name": "Jaipur Zone 1", "code": "Z-01" },
    "circle": { "name": "Circle 1", "code": "C-01" },
    "division": { "name": "Division 1", "code": "D-01" },
    "subdivision": { "name": "Subdivision 1", "code": "SD-01" },
    "substation": { "name": "Substation 1", "code": "SS-01" },
    "feeder": { "name": "Feeder 1", "code": "F-001" },
    "dt": { "name": "Malviya Nagar DT 1", "code": "DT-001" }
  },
  "extra_attributes": null
}
```

### 4. Consumption Analytics & Interval Readings
```bash
curl -X GET http://127.0.0.1:8000/api/v1/meters/J100000/consumption
```
**Response**:
```json
{
  "meter_id": "J100000",
  "summary": {
    "reading_count": 337,
    "period_start": "2026-06-23T23:30:00+05:30",
    "period_end": "2026-06-30T23:30:00+05:30",
    "total_kwh": 142.05,
    "avg_kwh": 48509.76,
    "min_kwh": 48438.74,
    "max_kwh": 48580.79,
    "avg_voltage_r": 229.8
  },
  "readings": [
    {
      "timestamp_iso": "2026-06-23T23:30:00+05:30",
      "timestamp_raw": "23/06/2026 23:30",
      "kwh": 48438.74,
      "kvah": 52313.84,
      "voltage_r": 226.0,
      "power_factor": 0.926
    }
  ]
}
```

### 5. Find Meters Nearby GPS Coordinates
```bash
curl -X GET "http://127.0.0.1:8000/api/v1/meters/nearby?latitude=26.9389&longitude=75.8309&radius_km=0.5"
```

### 6. Distribution Transformer with Connected Meters
```bash
curl -X GET http://127.0.0.1:8000/api/v1/transformers/DT-001
```

### 7. Reconstructed Grid Hierarchy Tree
```bash
curl -X GET http://127.0.0.1:8000/api/v1/hierarchy
```

---

## 📐 Assumptions, Trade-Offs, and Limitations

### Assumptions
- **Jaipur Location & IST (+05:30)**: Raw timestamps lack timezones; geographical coordinates and Indian utility nomenclature point to Indian Standard Time (`UTC+05:30`).
- **Cumulative Registers**: Increasing interval values represent continuous register readings; delta usage is computed as $\max(\text{kWh}) - \min(\text{kWh})$.
- **Cache Window**: Meter metadata updates infrequently relative to telemetry; a 15-minute TTL provides adequate freshness.

### Trade-Offs
- **In-Memory Store vs External Database**: In-memory indexing provides sub-millisecond query latencies and zero external service dependencies for 403 meters. In a distributed multi-worker deployment, this should transition to Redis + PostgreSQL/PostGIS.
- **On-Demand Consumption Fetching**: While metadata is indexed, consumption time-series are queried directly from the portal to preserve telemetry accuracy.

### Known Limitations
- The upstream portal only exposes single-phase voltage (`voltR`) even for three-phase units; Y and B phase voltages are not tracked upstream.
- Legacy meter nameplate details are represented inconsistently across hardware revisions (`classData` vs `detail.data`).

---

## 🔮 Future Improvements

1. **Persistent Time-Series Database**: Ingest interval telemetries into TimescaleDB or ClickHouse for long-term historical trend modeling.
2. **Anomaly Detection & Threshold Alerts**: Automated alerting for meter communication loss, sudden voltage sags, or low power factor ($< 0.85$).
3. **API Consumer Authentication**: Add OAuth2/JWT bearer tokens with role-based permissions (Field Tech vs Admin).
4. **WebSocket Telemetry Stream**: Real-time push notifications for new readings.

---

## 📝 Reflection

A complete reflection addressing all five prompt questions (Assumptions, Difficulties & Solutions, 1-Day Improvements, Mistakes Made, and Self-Critique) is available in **[REFLECTION.md](REFLECTION.md)**.
