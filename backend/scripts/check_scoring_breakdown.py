
from app.algorithms.scoring import calculate_total_score
from app.schemas.route_request import RoutePreferences


def main():

    # 16.4で確認したルート①の実データ
    target_distance_km = 2.0
    actual_distance_km = 2.49
    elevation_gain_m = 16.1
    signals = 2
    intersections = 51
    traffic_score = 4.64

    preferences = RoutePreferences(
        avoid_traffic=True,
        avoid_signals=True,
        avoid_intersections=True,
        elevation_mode="low",
    )

    values = {
        "actual_distance_km": actual_distance_km,
        "elevation_gain_m": elevation_gain_m,
        "signals": signals,
        "intersections": intersections,
        "traffic_score": traffic_score,
    }

    def score(**overrides):
        current = values.copy()
        current.update(overrides)

        return calculate_total_score(
            target_distance_km=target_distance_km,
            preferences=preferences,
            **current,
        )

    full_score = score()

    # 評価項目を個別に取り除いた際の差分
    # 厳密な寄与度として解釈するには、
    # スコア関数の加法性を確認する必要がある
    breakdown = {
        "距離誤差": full_score - score(
            actual_distance_km=target_distance_km
        ),
        "信号数": full_score - score(
            signals=0
        ),
        "交差点数": full_score - score(
            intersections=0
        ),
        "車通り": full_score - score(
            traffic_score=0.0
        ),
        "累積上昇量": full_score - score(
            elevation_gain_m=0.0
        ),
    }

    print("=== 16.5 スコア内訳 ===")
    print(f"基本スコア合計: {full_score:.2f}")

    for name, value in breakdown.items():
        print(f"{name}: {value:.2f} 点")

    print("\n=== 基準値の確認 ===")
    print(
        "全項目を基準値にしたスコア:",
        round(
            score(
                actual_distance_km=target_distance_km,
                signals=0,
                intersections=0,
                traffic_score=0.0,
                elevation_gain_m=0.0,
            ),
            2,
        ),
    )


if __name__ == "__main__":
    main()
