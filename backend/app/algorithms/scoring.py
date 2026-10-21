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