import math


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    緯度経度2点間の距離をメートルで計算する。
    Haversine formulaを使用。
    """

    earth_radius_m = 6371000  # 地球の平均半径[m]

    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    diff_lat = lat2_rad - lat1_rad
    diff_lon = lon2_rad - lon1_rad

    a = (
        math.sin(diff_lat / 2) ** 2
        + math.cos(lat1_rad)
        * math.cos(lat2_rad)
        * math.sin(diff_lon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return earth_radius_m * c


def calculate_route_distance_m(coordinates: list[dict]) -> float:
    """
    ルート座標列から、ルート全体の距離をメートルで計算する。

    coordinatesの例:
    [
        {"lat": 35.8721, "lon": 140.0106},
        {"lat": 35.8731, "lon": 140.0116}
    ]
    """

    if len(coordinates) < 2:
        return 0.0

    total_distance = 0.0

    for i in range(len(coordinates) - 1):
        current_point = coordinates[i]
        next_point = coordinates[i + 1]

        total_distance += haversine_distance_m(
            current_point["lat"],
            current_point["lon"],
            next_point["lat"],
            next_point["lon"],
        )

    return total_distance


def calculate_route_distance_km(coordinates: list[dict]) -> float:
    """
    ルート全体の距離をkmで返す。
    """

    return calculate_route_distance_m(coordinates) / 1000

def convert_to_geojson_linestring(coordinates: list[dict]) -> dict:
    """
    lat/lon形式の座標列をGeoJSON LineString形式に変換する。

    入力:
    [
        {"lat": 35.8721, "lon": 140.0106}
    ]

    出力:
    {
        "type": "LineString",
        "coordinates": [
            [140.0106, 35.8721]
        ]
    }

    GeoJSONでは [lon, lat] の順番になる点に注意。
    """

    return {
        "type": "LineString",
        "coordinates": [
            [point["lon"], point["lat"]]
            for point in coordinates
        ],
    }