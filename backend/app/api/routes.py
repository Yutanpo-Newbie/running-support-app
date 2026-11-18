from fastapi import APIRouter, HTTPException
from threading import Lock

from app.core.config import ROUTE_ENGINE
from app.schemas.route_request import RouteRequest
from app.schemas.route_response import RouteResponse
from app.services.route_service import generate_mock_routes, generate_osmnx_routes
from app.services.elevation_client import (
    ElevationDataUnavailable,
)


router = APIRouter(prefix="/api", tags=["routes"])
# ルート計算は同時に1件だけ実行
route_generation_lock = Lock()

@router.post("/routes/suggest", response_model=RouteResponse)
def suggest_routes(request: RouteRequest):
    if ROUTE_ENGINE == "osmnx":
        try:
            # 別のルート計算が実行中なら即座に拒否
            if not route_generation_lock.acquire(blocking=False):
                raise HTTPException(
                    status_code=429,
                    detail="ルート計算が混雑しています。少し待って再試行してください。",
                )

            try:
                routes = generate_osmnx_routes(request)

            finally:
                route_generation_lock.release()

        except ElevationDataUnavailable as error:
            raise HTTPException(
                status_code=503,
                detail=str(error),
            ) from error
    else:
        routes = generate_mock_routes(request)

    return RouteResponse(routes=routes)