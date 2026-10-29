from datetime import datetime, timezone, timedelta
import logging
import math
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.cache import store
from app.core.upstream_client import UpstreamPortalClient
from app.models.errors import ErrorResponse, UpstreamNotFoundError
from app.models.schemas import (
    ConsumptionReading,
    ConsumptionSummary,
    MeterConsumptionResponse,
    MeterDetail,
    MeterListResponse,
    NearbyMetersResponse,
)

logger = logging.getLogger("flock_urja.routers.meters")
router = APIRouter(prefix="/meters", tags=["Meters"])

# IST timezone (+05:30) standard for Indian power distribution utilities
IST = timezone(timedelta(hours=5, minutes=30))


def get_upstream_client() -> UpstreamPortalClient:
    from app.main import portal_client
    return portal_client


def parse_timestamp_to_iso(raw_ts: str) -> str:
    """Parse upstream timestamp format (DD/MM/YYYY HH:MM) into ISO-8601 with IST offset."""
    raw_ts = raw_ts.strip()
    try:
        dt = datetime.strptime(raw_ts, "%d/%m/%Y %H:%M")
        dt_ist = dt.replace(tzinfo=IST)
        return dt_ist.isoformat()
    except Exception:
        # Fallback if already ISO or different format
        return raw_ts


def safe_float(val: Any) -> Optional[float]:
    """Parse string or number into float, returning None if missing, empty, or placeholder."""
    if val is None or val == "" or val == "—" or val == "-":
        return None
    try:
        f = float(val)
        return f if not math.isnan(f) else None
    except (ValueError, TypeError):
        return None


@router.get(
    "",
    response_model=MeterListResponse,
    summary="List and Search Smart Meters",
    description="Retrieve a paginated list of smart meters with optional query search and multi-attribute filters.",
    responses={
        200: {"description": "List of matching meters."},
    },
)
async def list_meters(
    q: Optional[str] = Query(None, description="Search term for meter ID or hardware serial number"),
    make: Optional[str] = Query(None, description="Filter by manufacturer (e.g. HPL, Secure, Genus, L&T, Allied)"),
    phase_type: Optional[str] = Query(None, description="Filter by phase type ('single' or 'three')"),
    install_status: Optional[str] = Query(None, description="Filter by operational status ('Installed', 'Decommissioned', 'Faulty')"),
    dt_code: Optional[str] = Query(None, description="Filter by Distribution Transformer code (e.g. 'DT-001')"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    client: UpstreamPortalClient = Depends(get_upstream_client),
) -> MeterListResponse:
    # Ensure cache is populated
    await store.sync(client)

    items, total = store.query_meters(
        q=q,
        make=make,
        phase_type=phase_type,
        install_status=install_status,
        dt_code=dt_code,
        page=page,
        page_size=page_size,
    )

    pages = math.ceil(total / page_size) if total > 0 else 1

    return MeterListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get(
    "/nearby",
    response_model=NearbyMetersResponse,
    summary="Find Meters Near Location",
    description="Spatial query returning smart meters within radius_km of specified latitude and longitude.",
)
async def get_nearby_meters(
    latitude: float = Query(..., description="Target latitude in decimal degrees", ge=-90.0, le=90.0),
    longitude: float = Query(..., description="Target longitude in decimal degrees", ge=-180.0, le=180.0),
    radius_km: float = Query(1.0, ge=0.01, le=50.0, description="Search radius in kilometers (max 50km)"),
    client: UpstreamPortalClient = Depends(get_upstream_client),
) -> NearbyMetersResponse:
    await store.sync(client)
    nearby_meters = store.find_nearby(latitude, longitude, radius_km)

    return NearbyMetersResponse(
        center_latitude=latitude,
        center_longitude=longitude,
        radius_km=radius_km,
        total=len(nearby_meters),
        meters=nearby_meters,
    )


@router.get(
    "/{meter_id}",
    response_model=MeterDetail,
    summary="Get Meter Details",
    description="Retrieve comprehensive details for a specific smart meter, including nameplate attributes, hierarchy, and coordinates.",
    responses={
        200: {"description": "Detailed meter information."},
        404: {"model": ErrorResponse, "description": "Meter not found."},
    },
)
async def get_meter(
    meter_id: str,
    client: UpstreamPortalClient = Depends(get_upstream_client),
) -> MeterDetail:
    await store.sync(client)
    meter = store.get_meter(meter_id)

    if not meter:
        # If not in cache, check if force sync finds it
        await store.sync(client, force=True)
        meter = store.get_meter(meter_id)

    if not meter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "METER_NOT_FOUND", "message": f"Meter with ID '{meter_id}' was not found in the utility system."},
        )

    return meter


@router.get(
    "/{meter_id}/consumption",
    response_model=MeterConsumptionResponse,
    summary="Get Meter Consumption Readings",
    description="Fetch historical 30-minute interval readings for a meter with normalized timestamps and summary statistics.",
    responses={
        200: {"description": "Historical readings and computed statistics."},
        404: {"model": ErrorResponse, "description": "Meter not found."},
    },
)
async def get_meter_consumption(
    meter_id: str,
    client: UpstreamPortalClient = Depends(get_upstream_client),
) -> MeterConsumptionResponse:
    # First verify meter exists
    await store.sync(client)
    meter = store.get_meter(meter_id)
    if not meter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "METER_NOT_FOUND", "message": f"Meter with ID '{meter_id}' was not found."},
        )

    try:
        raw_readings = await client.fetch_meter_energy(meter_id)
    except UpstreamNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "METER_NOT_FOUND", "message": f"Meter with ID '{meter_id}' was not found."},
        )

    normalized_readings: List[ConsumptionReading] = []
    kwh_values: List[float] = []
    voltage_values: List[float] = []

    for r in raw_readings:
        raw_ts = r.get("timestamp", "")
        ts_iso = parse_timestamp_to_iso(raw_ts)

        kwh = safe_float(r.get("kwh"))
        kvah = safe_float(r.get("kvah"))
        volt_r = safe_float(r.get("voltR"))

        if kwh is not None:
            kwh_values.append(kwh)
        if volt_r is not None:
            voltage_values.append(volt_r)

        # Estimate power factor
        pf = None
        if kwh is not None and kvah is not None and kvah > 0:
            pf = round(min(1.0, kwh / kvah), 3)

        normalized_readings.append(
            ConsumptionReading(
                timestamp_iso=ts_iso,
                timestamp_raw=raw_ts,
                kwh=kwh,
                kvah=kvah,
                voltage_r=volt_r,
                power_factor=pf,
            )
        )

    # Sort chronological by ISO timestamp
    normalized_readings.sort(key=lambda r: r.timestamp_iso)

    # Compute summary metrics
    reading_count = len(normalized_readings)
    period_start = normalized_readings[0].timestamp_iso if reading_count > 0 else None
    period_end = normalized_readings[-1].timestamp_iso if reading_count > 0 else None

    min_kwh = min(kwh_values) if kwh_values else None
    max_kwh = max(kwh_values) if kwh_values else None
    avg_kwh = round(sum(kwh_values) / len(kwh_values), 2) if kwh_values else None
    total_kwh = round(max_kwh - min_kwh, 2) if (max_kwh is not None and min_kwh is not None) else None
    avg_volt_r = round(sum(voltage_values) / len(voltage_values), 1) if voltage_values else None

    summary = ConsumptionSummary(
        reading_count=reading_count,
        period_start=period_start,
        period_end=period_end,
        total_kwh=total_kwh,
        avg_kwh=avg_kwh,
        min_kwh=min_kwh,
        max_kwh=max_kwh,
        avg_voltage_r=avg_volt_r,
    )

    return MeterConsumptionResponse(
        meter_id=meter_id,
        summary=summary,
        readings=normalized_readings,
    )
