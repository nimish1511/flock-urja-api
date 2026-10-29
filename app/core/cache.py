import asyncio
from datetime import datetime, timezone
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.core.upstream_client import UpstreamPortalClient
from app.models.schemas import (
    GeoLocation,
    HierarchyLevel,
    HierarchyNode,
    HierarchyResponse,
    MeterDetail,
    MeterSummary,
    NearbyMeter,
    NearbyMetersResponse,
    NetworkHierarchy,
    Transformer,
    TransformerDetail,
)

logger = logging.getLogger("flock_urja.cache")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two geographic coordinates in kilometers."""
    radius_earth_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(radius_earth_km * c, 3)


class DataStore:
    """In-memory index and cache for Urja Meter Ops data.
    
    Provides:
    - Fast O(1) lookups by meterId, serialNo, and DT code
    - Complex multi-field filtering across makes, phases, statuses, and DTs
    - Reconstructed 7-tier electrical grid hierarchy tree
    - Geospatial proximity searches (meters within radius_km)
    - Staleness tracking and thread-safe atomic snapshot swapping
    """

    def __init__(self):
        self._meters_by_id: Dict[str, MeterDetail] = {}
        self._meters_by_serial: Dict[str, str] = {}
        self._transformers_by_code: Dict[str, Transformer] = {}
        self._meters_by_dt: Dict[str, List[str]] = {}
        self._last_synced_at: Optional[datetime] = None
        self._sync_lock = asyncio.Lock()
        self._is_syncing = False

    @property
    def last_synced_at(self) -> Optional[datetime]:
        return self._last_synced_at

    @property
    def total_meters(self) -> int:
        return len(self._meters_by_id)

    @property
    def total_transformers(self) -> int:
        return len(self._transformers_by_code)

    def is_stale(self) -> bool:
        """Check if cached data has exceeded configured TTL."""
        if self._last_synced_at is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_synced_at).total_seconds()
        return elapsed > settings.cache_ttl_seconds

    async def sync(self, client: UpstreamPortalClient, force: bool = False):
        """Fetch fresh metadata from upstream portal and rebuild in-memory indexes."""
        if not force and not self.is_stale() and len(self._meters_by_id) > 0:
            logger.debug("Cache is fresh (synced at %s), skipping sync", self._last_synced_at)
            return

        async with self._sync_lock:
            # Recheck after acquiring lock to prevent stampedes
            if not force and not self.is_stale() and len(self._meters_by_id) > 0:
                return

            self._is_syncing = True
            logger.info("Initiating metadata synchronization from upstream portal")

            try:
                # 1. Fetch DTs
                raw_dts = await client.fetch_all_dts()
                # 2. Fetch all meters via signed export
                raw_export = await client.fetch_bulk_export()
                raw_meters = raw_export.get("data", [])

                new_meters_by_id: Dict[str, MeterDetail] = {}
                new_meters_by_serial: Dict[str, str] = {}
                new_meters_by_dt: Dict[str, List[str]] = {}

                for m in raw_meters:
                    mid = m.get("meterId")
                    if not mid:
                        continue

                    # Parse geo coordinates
                    geo_obj = None
                    raw_geo = m.get("geo")
                    if raw_geo and "lat" in raw_geo and "lng" in raw_geo:
                        try:
                            geo_obj = GeoLocation(
                                latitude=float(raw_geo["lat"]),
                                longitude=float(raw_geo["lng"]),
                            )
                        except (ValueError, TypeError):
                            geo_obj = None

                    # Parse hierarchy
                    raw_h = m.get("hierarchy") or {}
                    hierarchy_obj = NetworkHierarchy(
                        zone=HierarchyLevel(**raw_h["zone"]) if raw_h.get("zone") else None,
                        circle=HierarchyLevel(**raw_h["circle"]) if raw_h.get("circle") else None,
                        division=HierarchyLevel(**raw_h["division"]) if raw_h.get("division") else None,
                        subdivision=HierarchyLevel(**raw_h["subdivision"]) if raw_h.get("subdivision") else None,
                        substation=HierarchyLevel(**raw_h["substation"]) if raw_h.get("substation") else None,
                        feeder=HierarchyLevel(**raw_h["feeder"]) if raw_h.get("feeder") else None,
                        dt=HierarchyLevel(**raw_h["dt"]) if raw_h.get("dt") else None,
                    )

                    dt_code = m.get("dtCode", "")

                    meter = MeterDetail(
                        meter_id=mid,
                        serial_no=m.get("serialNo", ""),
                        make=m.get("make", ""),
                        phase_type=m.get("phaseType", ""),
                        install_status=m.get("installStatus", ""),
                        dt_code=dt_code,
                        install_type=m.get("installType"),
                        build=m.get("build"),
                        geo=geo_obj,
                        hierarchy=hierarchy_obj,
                    )

                    new_meters_by_id[mid] = meter
                    if meter.serial_no:
                        new_meters_by_serial[meter.serial_no] = mid
                    if dt_code:
                        new_meters_by_dt.setdefault(dt_code, []).append(mid)

                # Process transformers and compute connected meters count
                new_transformers_by_code: Dict[str, Transformer] = {}
                for dt in raw_dts:
                    code = dt.get("code")
                    if not code:
                        continue
                    count = len(new_meters_by_dt.get(code, []))
                    new_transformers_by_code[code] = Transformer(
                        code=code,
                        name=dt.get("name", ""),
                        feeder_code=dt.get("feederCode", ""),
                        capacity_kva=int(dt.get("capacityKva", 0)),
                        connected_meters_count=count,
                    )

                # Atomic swap
                self._meters_by_id = new_meters_by_id
                self._meters_by_serial = new_meters_by_serial
                self._meters_by_dt = new_meters_by_dt
                self._transformers_by_code = new_transformers_by_code
                self._last_synced_at = datetime.now(timezone.utc)

                logger.info(
                    "Successfully synced cache: %d meters, %d transformers",
                    len(new_meters_by_id),
                    len(new_transformers_by_code),
                )

            except Exception as exc:
                logger.error("Failed to sync cache from upstream: %s", exc)
                raise
            finally:
                self._is_syncing = False

    def get_meter(self, meter_id: str) -> Optional[MeterDetail]:
        """Lookup meter by ID (or fallback hardware serial number)."""
        if meter_id in self._meters_by_id:
            return self._meters_by_id[meter_id]
        if meter_id in self._meters_by_serial:
            return self._meters_by_id[self._meters_by_serial[meter_id]]
        return None

    def query_meters(
        self,
        q: Optional[str] = None,
        make: Optional[str] = None,
        phase_type: Optional[str] = None,
        install_status: Optional[str] = None,
        dt_code: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[MeterSummary], int]:
        """Perform search and multi-attribute filtering on cached meters."""
        results = list(self._meters_by_id.values())

        # Substring search over meterId or serialNo
        if q:
            query_lower = q.strip().lower()
            results = [
                m for m in results
                if query_lower in m.meter_id.lower() or query_lower in m.serial_no.lower()
            ]

        # Attribute filters
        if make:
            make_lower = make.strip().lower()
            results = [m for m in results if m.make.lower() == make_lower]

        if phase_type:
            phase_lower = phase_type.strip().lower()
            results = [m for m in results if m.phase_type.lower() == phase_lower]

        if install_status:
            status_lower = install_status.strip().lower()
            results = [m for m in results if m.install_status.lower() == status_lower]

        if dt_code:
            dt_upper = dt_code.strip().upper()
            results = [m for m in results if m.dt_code.upper() == dt_upper]

        # Sort predictably by meter_id
        results.sort(key=lambda m: m.meter_id)

        total = len(results)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = results[start:end]

        # Convert to summaries
        summaries = [
            MeterSummary(
                meter_id=m.meter_id,
                serial_no=m.serial_no,
                make=m.make,
                phase_type=m.phase_type,
                install_status=m.install_status,
                dt_code=m.dt_code,
                install_type=m.install_type,
                build=m.build,
            )
            for m in page_items
        ]

        return summaries, total

    def find_nearby(self, latitude: float, longitude: float, radius_km: float) -> List[NearbyMeter]:
        """Find meters within radius_km of coordinates sorted by ascending distance."""
        nearby = []
        for m in self._meters_by_id.values():
            if not m.geo:
                continue
            dist = haversine_km(latitude, longitude, m.geo.latitude, m.geo.longitude)
            if dist <= radius_km:
                nearby.append(
                    NearbyMeter(
                        meter_id=m.meter_id,
                        serial_no=m.serial_no,
                        make=m.make,
                        phase_type=m.phase_type,
                        install_status=m.install_status,
                        dt_code=m.dt_code,
                        install_type=m.install_type,
                        build=m.build,
                        distance_km=dist,
                        geo=m.geo,
                    )
                )

        nearby.sort(key=lambda item: item.distance_km)
        return nearby

    def get_transformer(self, code: str) -> Optional[TransformerDetail]:
        """Lookup transformer and attach all connected meter summaries."""
        code_upper = code.strip().upper()
        # Case-insensitive lookup
        matched_key = None
        for k in self._transformers_by_code:
            if k.upper() == code_upper:
                matched_key = k
                break

        if not matched_key:
            return None

        dt = self._transformers_by_code[matched_key]
        connected_ids = self._meters_by_dt.get(matched_key, [])
        connected_meters = []
        for mid in connected_ids:
            m = self._meters_by_id.get(mid)
            if m:
                connected_meters.append(
                    MeterSummary(
                        meter_id=m.meter_id,
                        serial_no=m.serial_no,
                        make=m.make,
                        phase_type=m.phase_type,
                        install_status=m.install_status,
                        dt_code=m.dt_code,
                        install_type=m.install_type,
                        build=m.build,
                    )
                )

        connected_meters.sort(key=lambda m: m.meter_id)

        return TransformerDetail(
            code=dt.code,
            name=dt.name,
            feeder_code=dt.feeder_code,
            capacity_kva=dt.capacity_kva,
            connected_meters_count=len(connected_meters),
            meters=connected_meters,
        )

    def query_transformers(
        self,
        feeder_code: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Transformer], int]:
        """List transformers with optional feeder filtering and pagination."""
        items = list(self._transformers_by_code.values())
        if feeder_code:
            f_upper = feeder_code.strip().upper()
            items = [t for t in items if t.feeder_code.upper() == f_upper]

        items.sort(key=lambda t: t.code)
        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        return items[start:end], total

    def build_hierarchy_tree(self) -> HierarchyResponse:
        """Reconstruct full 7-tier distribution tree with aggregated meter counts."""
        # Levels: Zone -> Circle -> Division -> Subdivision -> Substation -> Feeder -> DT
        root_nodes: Dict[str, Dict[str, Any]] = {}

        for meter in self._meters_by_id.values():
            h = meter.hierarchy
            if not h or not h.zone:
                continue

            z_key = h.zone.code or h.zone.name
            z_node = root_nodes.setdefault(z_key, {
                "name": h.zone.name, "code": h.zone.code, "level": "zone",
                "count": 0, "children": {}
            })
            z_node["count"] += 1

            if not h.circle:
                continue
            c_key = h.circle.code or h.circle.name
            c_node = z_node["children"].setdefault(c_key, {
                "name": h.circle.name, "code": h.circle.code, "level": "circle",
                "count": 0, "children": {}
            })
            c_node["count"] += 1

            if not h.division:
                continue
            d_key = h.division.code or h.division.name
            d_node = c_node["children"].setdefault(d_key, {
                "name": h.division.name, "code": h.division.code, "level": "division",
                "count": 0, "children": {}
            })
            d_node["count"] += 1

            if not h.subdivision:
                continue
            sd_key = h.subdivision.code or h.subdivision.name
            sd_node = d_node["children"].setdefault(sd_key, {
                "name": h.subdivision.name, "code": h.subdivision.code, "level": "subdivision",
                "count": 0, "children": {}
            })
            sd_node["count"] += 1

            if not h.substation:
                continue
            ss_key = h.substation.code or h.substation.name
            ss_node = sd_node["children"].setdefault(ss_key, {
                "name": h.substation.name, "code": h.substation.code, "level": "substation",
                "count": 0, "children": {}
            })
            ss_node["count"] += 1

            if not h.feeder:
                continue
            f_key = h.feeder.code or h.feeder.name
            f_node = ss_node["children"].setdefault(f_key, {
                "name": h.feeder.name, "code": h.feeder.code, "level": "feeder",
                "count": 0, "children": {}
            })
            f_node["count"] += 1

            if not h.dt:
                continue
            dt_key = h.dt.code or h.dt.name
            dt_node = f_node["children"].setdefault(dt_key, {
                "name": h.dt.name, "code": h.dt.code, "level": "dt",
                "count": 0, "children": {}
            })
            dt_node["count"] += 1

        def dict_to_node(data: Dict[str, Any]) -> HierarchyNode:
            children_nodes = [
                dict_to_node(child_data)
                for child_data in sorted(data["children"].values(), key=lambda x: x["code"] or x["name"])
            ]
            return HierarchyNode(
                name=data["name"],
                code=data["code"],
                level=data["level"],
                meter_count=data["count"],
                children=children_nodes,
            )

        tree = [
            dict_to_node(data)
            for data in sorted(root_nodes.values(), key=lambda x: x["code"] or x["name"])
        ]

        return HierarchyResponse(
            total_meters=len(self._meters_by_id),
            total_transformers=len(self._transformers_by_code),
            tree=tree,
        )


# Global singleton instance
store = DataStore()
