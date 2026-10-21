from app.utils.geo import haversine_distance_m, calculate_route_distance_km


def test_same_point_distance_is_zero():
    distance = haversine_distance_m(
        lat1=35.8721,
        lon1=140.0106,
        lat2=35.8721,
        lon2=140.0106,
    )

    assert distance == 0


def test_different_points_distance_is_positive():
    distance = haversine_distance_m(
        lat1=35.8721,
        lon1=140.0106,
        lat2=35.8731,
        lon2=140.0116,
    )

    assert distance > 0


def test_route_distance_is_positive():
    coordinates = [
        {"lat": 35.8721, "lon": 140.0106},
        {"lat": 35.8731, "lon": 140.0116},
        {"lat": 35.8741, "lon": 140.0106},
        {"lat": 35.8721, "lon": 140.0106},
    ]

    distance_km = calculate_route_distance_km(coordinates)

    assert distance_km > 0