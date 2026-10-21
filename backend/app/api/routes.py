from fastapi import APIRouter

from app.core.config import ROUTE_ENGINE
from app.schemas.route_request import RouteRequest
from app.schemas.route_response import RouteResponse
from app.services.route_service import generate_mock_routes, generate_osmnx_routes

router = APIRouter(prefix="/api", tags=["routes"])

@router.post("/routes/suggest", response_model=RouteResponse)
def suggest_routes(request: RouteRequest):
    if ROUTE_ENGINE == "osmnx":
        routes = generate_osmnx_routes(request)
    else:
        routes = generate_mock_routes(request)

    return RouteResponse(routes=routes)