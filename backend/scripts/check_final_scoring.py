
from app.algorithms.scoring import (
    calculate_final_route_score,
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
        "turn_density": 7.23,
        "short_turn_interval_count": 4,
        # 道路重複率はログから不明なので
        # 今回は仮に0.0として比較する
        "overlap_ratio": 0.0,
    }

    result = calculate_final_route_score(
        **route
    )

    print("=== 16.5.4 最終スコア ===")

    print(
        "基本スコア:",
        result["base_score"],
    )

    print(
        "品質ペナルティ:",
        result["quality_penalty"],
    )

    print(
        "総合スコア:",
        result["total_score"],
    )

    # 曲がり密度だけを改善した場合
    improved_route = route.copy()

    improved_route["turn_density"] = 3.0
    improved_route["short_turn_interval_count"] = 1

    improved_result = calculate_final_route_score(
        **improved_route
    )

    print("\n=== 曲がりを減らした場合 ===")

    print(
        "改善前:",
        result["total_score"],
    )

    print(
        "改善後:",
        improved_result["total_score"],
    )

    assert (
        improved_result["total_score"]
        < result["total_score"]
    )


if __name__ == "__main__":
    main()
