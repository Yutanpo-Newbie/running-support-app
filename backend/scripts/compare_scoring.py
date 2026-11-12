
from app.algorithms.scoring import (
    calculate_total_score,
    calculate_normalized_score,
)

from app.schemas.route_request import RoutePreferences


def main():

    preferences = RoutePreferences(
        avoid_traffic=True,
        avoid_signals=True,
        avoid_intersections=True,
        elevation_mode="low",
    )

    route = {
        "target_distance_km": 2.0,
        "actual_distance_km": 2.49,
        "elevation_gain_m": 16.1,
        "signals": 2,
        "intersections": 51,
        "traffic_score": 4.64,
        "preferences": preferences,
    }

    old_score = calculate_total_score(**route)

    new_score = calculate_normalized_score(**route)

    print("=== 16.5 新旧スコア比較 ===")
    print(f"旧スコア: {old_score:.2f}")
    print(f"新スコア: {new_score:.2f}")


if __name__ == "__main__":
    main()
