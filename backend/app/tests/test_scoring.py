from app.algorithms.scoring import calculate_total_score
from app.schemas.route_request import RoutePreferences


def test_total_score_returns_number():
    preferences = RoutePreferences(
        avoid_traffic=True,
        avoid_signals=True,
        avoid_intersections=True,
        elevation_mode="low",
    )

    score = calculate_total_score(
        target_distance_km=5.0,
        actual_distance_km=5.2,
        elevation_gain_m=20.0,
        signals=5,
        intersections=10,
        traffic_score=8.0,
        preferences=preferences,
    )

    assert isinstance(score, float)


def test_score_changes_by_preferences():
    low_elevation_preferences = RoutePreferences(
        avoid_traffic=True,
        avoid_signals=True,
        avoid_intersections=True,
        elevation_mode="low",
    )

    high_elevation_preferences = RoutePreferences(
        avoid_traffic=False,
        avoid_signals=False,
        avoid_intersections=False,
        elevation_mode="high",
    )

    low_score = calculate_total_score(
        target_distance_km=5.0,
        actual_distance_km=5.0,
        elevation_gain_m=40.0,
        signals=8,
        intersections=15,
        traffic_score=10.0,
        preferences=low_elevation_preferences,
    )

    high_score = calculate_total_score(
        target_distance_km=5.0,
        actual_distance_km=5.0,
        elevation_gain_m=40.0,
        signals=8,
        intersections=15,
        traffic_score=10.0,
        preferences=high_elevation_preferences,
    )

    assert low_score != high_score