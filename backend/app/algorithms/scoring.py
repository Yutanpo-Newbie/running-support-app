from app.schemas.route_request import RoutePreferences

def calculate_total_score(
    target_distance_km: float,
    actual_distance_km: float,
    elevation_gain_m: float,
    signals: int,
    intersections: int,
    traffic_score: float,
    preferences: RoutePreferences,
) -> float:
    distance_penalty = abs(target_distance_km - actual_distance_km) * 5

    signal_weight = 3.0 if preferences.avoid_signals else 1.0
    intersection_weight = 3.0 if preferences.avoid_intersections else 0.8
    traffic_weight = 3.0 if preferences.avoid_traffic else 1.0

    if preferences.elevation_mode == "low":
        elevation_penalty = elevation_gain_m * 0.5
    elif preferences.elevation_mode == "high":
        elevation_penalty = elevation_gain_m * 0.2
    else:
        elevation_penalty = elevation_gain_m *0.2

    signal_penalty = signals * signal_weight
    intersection_penalty = intersections * intersection_weight
    traffic_penalty = traffic_score * traffic_weight

    total_score = (
        distance_penalty
        + elevation_penalty
        + signal_penalty
        + intersection_penalty
        + traffic_penalty
    )

    return round(total_score, 2)


# =====================================
# 16.5.2 正規化スコア（試験版）
# =====================================

def normalize_score(
    value: float,
    reference: float,
) -> float:
    """
    0〜1の範囲に正規化する。
    基準値以上は1.0とする。
    """

    if reference <= 0:
        raise ValueError(
            "reference must be positive"
        )

    return min(
        1.0,
        max(0.0, value / reference),
    )


def calculate_normalized_score(
    target_distance_km: float,
    actual_distance_km: float,
    elevation_gain_m: float,
    signals: int,
    intersections: int,
    traffic_score: float,
    preferences,
) -> float:
    """
    正規化した5項目でルートを評価する。
    小さいほど良い。
    """

    if target_distance_km <= 0:
        raise ValueError(
            "target_distance_km must be positive"
        )

    if actual_distance_km <= 0:
        raise ValueError(
            "actual_distance_km must be positive"
        )

    # 1. 距離誤差率
    distance_error_rate = abs(
        actual_distance_km - target_distance_km
    ) / target_distance_km

    distance_n = normalize_score(
        distance_error_rate,
        0.25,
    )

    # 2. 1km当たり信号数
    signal_density = signals / actual_distance_km

    signals_n = normalize_score(
        signal_density,
        3.0,
    )

    # 3. 1km当たり交差点数
    intersection_density = (
        intersections / actual_distance_km
    )

    intersections_n = normalize_score(
        intersection_density,
        25.0,
    )

    # 4. 車通り推定（すでに0〜10）
    traffic_n = normalize_score(
        traffic_score,
        10.0,
    )

    # 5. 1km当たり累積上昇量
    elevation_density = (
        elevation_gain_m / actual_distance_km
    )

    elevation_n = normalize_score(
        elevation_density,
        20.0,
    )

    # ユーザーの回避設定
    signal_weight = (
        20.0 if preferences.avoid_signals
        else 5.0
    )

    intersection_weight = (
        15.0 if preferences.avoid_intersections
        else 5.0
    )

    traffic_weight = (
        20.0 if preferences.avoid_traffic
        else 5.0
    )

    # 坂道設定
    if preferences.elevation_mode == "low":
        elevation_penalty = elevation_n * 20.0

    elif preferences.elevation_mode == "high":
        # 負荷重視：上昇量が大きいほど低ペナルティ
        elevation_penalty = (
            1.0 - elevation_n
        ) * 20.0

    else:
        # 高低差を特に重視しない設定
        elevation_penalty = elevation_n * 5.0

    total = (
        distance_n * 25.0
        + signals_n * signal_weight
        + intersections_n * intersection_weight
        + traffic_n * traffic_weight
        + elevation_penalty
    )

    return round(total, 2)


# =====================================
# 16.5.4 ルート品質ペナルティ
# =====================================

def calculate_route_quality_penalty(
    turn_density: float,
    short_turn_interval_count: int,
    overlap_ratio: float,
) -> float:
    """
    曲がり密度・短い間隔の曲がり・
    道路重複率を0〜50点で評価する。

    小さいほど良い。
    """

    turn_density_n = normalize_score(
        turn_density,
        8.0,
    )

    short_turn_n = normalize_score(
        short_turn_interval_count,
        4.0,
    )

    overlap_n = normalize_score(
        overlap_ratio,
        0.20,
    )

    penalty = (
        turn_density_n * 25.0
        + short_turn_n * 15.0
        + overlap_n * 10.0
    )

    return round(penalty, 2)


def calculate_final_route_score(
    target_distance_km: float,
    actual_distance_km: float,
    elevation_gain_m: float,
    signals: int,
    intersections: int,
    traffic_score: float,
    preferences,
    turn_density: float,
    short_turn_interval_count: int,
    overlap_ratio: float,
) -> dict:
    """
    基本スコアとルート品質を合計する。
    """

    base_score = calculate_normalized_score(
        target_distance_km=target_distance_km,
        actual_distance_km=actual_distance_km,
        elevation_gain_m=elevation_gain_m,
        signals=signals,
        intersections=intersections,
        traffic_score=traffic_score,
        preferences=preferences,
    )

    quality_penalty = calculate_route_quality_penalty(
        turn_density=turn_density,
        short_turn_interval_count=short_turn_interval_count,
        overlap_ratio=overlap_ratio,
    )

    total_score = round(
        base_score + quality_penalty,
        2,
    )

    return {
        "base_score": base_score,
        "quality_penalty": quality_penalty,
        "total_score": total_score,
    }
