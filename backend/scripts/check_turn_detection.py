
import inspect

from app.schemas.route_request import RouteRequest
from app.services.route_service import generate_osmnx_routes
from app.algorithms.turn_detector import detect_turn_points
from app.services.osm_client import (
    calculate_distance_between_points,
)


def to_dict(point):
    """Pydanticモデルと辞書の両方に対応"""
    if hasattr(point, "model_dump"):
        return point.model_dump()
    if isinstance(point, dict):
        return point
    return vars(point)


def main():
    print("=== 16.6.1 曲がり判定の診断 ===")

    # 1. 現在の判定関数を確認
    print("\n=== detect_turn_points の実装 ===")
    print(inspect.getsource(detect_turn_points))

    # 2. 実ルートを生成
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

    print("\n=== ルート別の曲がり地点 ===")

    for route in routes:
        coordinates = [
            to_dict(point)
            for point in route.coordinates
        ]

        turns = detect_turn_points(coordinates)

        print(
            f"\n{route.id} / "
            f"距離: {route.distance_km}km / "
            f"曲がり: {len(turns)}件"
        )

        previous = None

        for index, turn in enumerate(turns, start=1):
            turn = to_dict(turn)

            lat = turn["lat"]
            lon = turn["lon"]

            if previous is None:
                interval = None
            else:
                interval = calculate_distance_between_points(
                    previous["lat"],
                    previous["lon"],
                    lat,
                    lon,
                )

            interval_text = (
                "-"
                if interval is None
                else f"{interval:.1f}m"
            )

            print(
                f"{index:02d}: "
                f"lat={lat:.6f}, "
                f"lon={lon:.6f}, "
                f"前回から={interval_text}, "
                f"詳細={turn}"
            )

            previous = turn


if __name__ == "__main__":
    main()
