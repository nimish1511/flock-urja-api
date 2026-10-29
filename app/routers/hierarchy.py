from fastapi import APIRouter, Depends

from app.core.cache import store
from app.core.upstream_client import UpstreamPortalClient
from app.models.schemas import HierarchyResponse

router = APIRouter(prefix="/hierarchy", tags=["Network Hierarchy"])


def get_upstream_client() -> UpstreamPortalClient:
    from app.main import portal_client
    return portal_client


@router.get(
    "",
    response_model=HierarchyResponse,
    summary="Get Grid Network Hierarchy",
    description="Retrieve the complete reconstructed 7-tier distribution hierarchy (Zone → Circle → Division → Subdivision → Substation → Feeder → DT) with aggregated meter counts.",
)
async def get_hierarchy(
    client: UpstreamPortalClient = Depends(get_upstream_client),
) -> HierarchyResponse:
    await store.sync(client)
    return store.build_hierarchy_tree()
