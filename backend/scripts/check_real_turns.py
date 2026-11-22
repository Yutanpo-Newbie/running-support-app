
from unittest.mock import patch

from app.schemas.route_request import RouteRequest
from app.services.route_service import generate_osmnx_routes


request = RouteRequest(
    start={
        "lat": 35.8721,
        "lon": 140.0106,
    },
    distance_km=2.0,
    preferences={
        "avoid_traffic": True,
        "avoid_signals": True,
        "avoid_intersections": True,
        "elevation_mode": "low",
    },
)

# 標高取得だけをモックする
# 曲がり角検出・歩道フィルター・
# 周回ルート生成は実際の処理を使う
with patch(
    "app.services.osm_client.get_route_elevation_gain",
    return_value=10.0,
):
    routes = generate_osmnx_routes(request)

print("\n=== REAL TURN TEST RESULT ===")
print("routes =", len(routes))

for i, route in enumerate(routes, start=1):
    print(
        f"ROUTE {i}:",
        "distance =", route.distance_km,
        "turn_points =", len(route.turn_points),
        "traffic_score =", route.traffic_score,
        "total_score =", route.total_score,
    )
