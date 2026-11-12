
from app.algorithms.scoring import (
    calculate_normalized_score,
)
from app.schemas.route_request import RoutePreferences


# 距離・信号・交差点・交通量・標高が異なる
# 比較用の仮想ルート
ROUTES = [
    {
        "name": "A: 信号が少ない",
        "actual_distance_km": 2.0,
        "signals": 1,
        "intersections": 30,
        "traffic_score": 5.0,
        "elevation_gain_m": 20.0,
    },
    {
        "name": "B: 車通りが少ない",
        "actual_distance_km": 2.0,
        "signals": 4,
        "intersections": 30,
        "traffic_score": 1.0,
        "elevation_gain_m": 20.0,
    },
    {
        "name": "C: 坂道が多い",
        "actual_distance_km": 2.0,
        "signals": 2,
        "intersections": 30,
        "traffic_score": 3.0,
        "elevation_gain_m": 50.0,
    },
]


def compare_routes(label, preferences):

    results = []

    for route in ROUTES:
        score = calculate_normalized_score(
            target_distance_km=2.0,
            actual_distance_km=route[
                "actual_distance_km"
            ],
            elevation_gain_m=route[
                "elevation_gain_m"
            ],
            signals=route["signals"],
            intersections=route["intersections"],
            traffic_score=route["traffic_score"],
            preferences=preferences,
        )

        results.append(
            (route["name"], score)
        )

    results.sort(key=lambda x: x[1])

    print(f"\n=== {label} ===")

    for rank, (name, score) in enumerate(
        results, start=1
    ):
        print(
            f"{rank}位: {name} / {score:.2f}点"
        )


def main():

    # ケース1：信号を避ける
    compare_routes(
        "信号を避ける",
        RoutePreferences(
            avoid_signals=True,
            avoid_traffic=False,
            avoid_intersections=False,
            elevation_mode="low",
        ),
    )

    # ケース2：車通りを避ける
    compare_routes(
        "車通りを避ける",
        RoutePreferences(
            avoid_signals=False,
            avoid_traffic=True,
            avoid_intersections=False,
            elevation_mode="low",
        ),
    )

    # ケース3：坂道が少ないルート
    compare_routes(
        "坂道を避ける",
        RoutePreferences(
            avoid_signals=False,
            avoid_traffic=False,
            avoid_intersections=False,
            elevation_mode="low",
        ),
    )

    # ケース4：坂道が多いルート
    compare_routes(
        "坂道を重視する",
        RoutePreferences(
            avoid_signals=False,
            avoid_traffic=False,
            avoid_intersections=False,
            elevation_mode="high",
        ),
    )


if __name__ == "__main__":
    main()
