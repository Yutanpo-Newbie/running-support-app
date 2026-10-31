import math


def calculate_bearing(lat1, lon1, lat2, lon2):
    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)

    diff_lon = math.radians(lon2 - lon1)

    x = math.sin(diff_lon) * math.cos(lat2)

    y = (
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1)
        * math.cos(lat2)
        * math.cos(diff_lon)
    )

    bearing = math.degrees(
        math.atan2(x, y)
    )

    return (bearing + 360) % 360


def normalize_angle(angle):
    return (angle + 180) % 360 - 180


def detect_turn_points(coordinates):
    turn_points = []

    if len(coordinates) < 3:
        return turn_points

    for i in range(1, len(coordinates) - 1):

        prev_point = coordinates[i - 1]
        current_point = coordinates[i]
        next_point = coordinates[i + 1]

        bearing_before = calculate_bearing(
            prev_point["lat"],
            prev_point["lon"],
            current_point["lat"],
            current_point["lon"],
        )

        bearing_after = calculate_bearing(
            current_point["lat"],
            current_point["lon"],
            next_point["lat"],
            next_point["lon"],
        )

        angle_difference = normalize_angle(
            bearing_after - bearing_before
        )

        if angle_difference > 30:
            direction = "right"

        elif angle_difference < -30:
            direction = "left"

        else:
            continue

        turn_points.append(
            {
                "lat": current_point["lat"],
                "lon": current_point["lon"],
                "direction": direction,
                "angle": round(
                    angle_difference,
                    1,
                ),
            }
        )

    return turn_points