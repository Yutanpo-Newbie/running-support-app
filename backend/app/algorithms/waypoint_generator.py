import math

def offset_lat_lon(
    lat: float,
    lon: float,
    north_m: float,
    east_m: float,
) -> dict:
    """
    指定した緯度経度から、北方向・東方向に何m移動した地点を返す。

    north_m:
        北方向への移動距離[m]
        マイナスなら南方向

    east_m:
        東方向への移動距離[m]
        マイナスなら西方向
    """

    earth_radius_m = 6371000

    new_lat = lat + (north_m / earth_radius_m) * (180 / math.pi)

    new_lon = lon + (
        east_m / (earth_radius_m * math.cos(math.radians(lat)))
    ) * (180 / math.pi)

    return {
        "lat": new_lat,
        "lon": new_lon,
    }


def generate_loop_coordinates(
    start_lat: float,
    start_lon: float,
    distance_km: float,
) -> list[list[dict]]:
    """
    スタート地点と希望距離をもとに、仮の周回ルート座標を複数生成する。

    現段階では道路ネットワークは考慮せず、
    三角形・四角形に近い仮ルートを作る。
    """

    # 希望距離に応じて、ルートの広がりを調整する
    # 5km指定なら、おおよそ1000〜1500m程度の広がりを作る
    base_m = max(distance_km * 250, 300)

    # ルート1：北東方向に広がる三角形
    route_1 = [
        {"lat": start_lat, "lon": start_lon},
        offset_lat_lon(start_lat, start_lon, north_m=base_m, east_m=base_m),
        offset_lat_lon(start_lat, start_lon, north_m=base_m * 2, east_m=0),
        {"lat": start_lat, "lon": start_lon},
    ]

    # ルート2：東側に広がる四角形
    route_2 = [
        {"lat": start_lat, "lon": start_lon},
        offset_lat_lon(start_lat, start_lon, north_m=base_m, east_m=base_m),
        offset_lat_lon(start_lat, start_lon, north_m=0, east_m=base_m * 2),
        offset_lat_lon(start_lat, start_lon, north_m=-base_m, east_m=base_m),
        {"lat": start_lat, "lon": start_lon},
    ]

    # ルート3：西側に広がる四角形
    route_3 = [
        {"lat": start_lat, "lon": start_lon},
        offset_lat_lon(start_lat, start_lon, north_m=base_m, east_m=-base_m),
        offset_lat_lon(start_lat, start_lon, north_m=0, east_m=-base_m * 2),
        offset_lat_lon(start_lat, start_lon, north_m=-base_m, east_m=-base_m),
        {"lat": start_lat, "lon": start_lon},
    ]

    return [route_1, route_2, route_3]