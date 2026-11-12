
from app.schemas.route_request import RouteRequest
from app.services.route_service import (
    generate_osmnx_routes,
)
from app.services.elevation_client import (
    get_route_elevation_gain,
    sample_route_points,
)


def main():

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

    routes = generate_osmnx_routes(request)

    print("\n=== 16.4 ルート標高テスト ===")

    if not routes:
        print("ルート候補がありません")
        return

    for route in routes:

        coordinates = [
            {
                "lat": point.lat,
                "lon": point.lon,
            }
            for point in route.coordinates
        ]

        sampled = sample_route_points(coordinates)

        print(
            f"\n{route.id}",
            f"distance={route.distance_km}km",
            f"sample_points={len(sampled)}",
            flush=True,
        )

        gain = get_route_elevation_gain(
            coordinates
        )

        print(
            f"elevation_gain={gain:.2f}m",
            flush=True,
        )


if __name__ == "__main__":
    main()
