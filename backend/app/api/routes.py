from fastapi import APIRouter, HTTPException

from app.core.config import ROUTE_ENGINE
from app.schemas.route_request import RouteRequest
from app.schemas.route_response import RouteResponse
from app.services.route_service import generate_mock_routes, generate_osmnx_routes
from app.services.elevation_client import (
    ElevationDataUnavailable,
)


router = APIRouter(prefix="/api", tags=["routes"])

@router.post("/routes/suggest", response_model=RouteResponse)
def suggest_routes(request: RouteRequest):
    if ROUTE_ENGINE == "osmnx":
        try:
            routes = generate_osmnx_routes(request)

        except ElevationDataUnavailable as error:
            raise HTTPException(
                status_code=503,
                detail=str(error),
            ) from error
    else:
        routes = generate_mock_routes(request)

    return RouteResponse(routes=routes)