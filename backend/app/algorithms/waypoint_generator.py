import math

def calculate_bearing(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
) -> float:
    """
    start地点からend地点への方位角を返す。
    0° = 北
    90° = 東
    180° = 南
    270° = 西
    """

    lat1 = math.radians(start_lat)
    lat2 = math.radians(end_lat)

    delta_lon = math.radians(
        end_lon - start_lon
    )

    x = math.sin(delta_lon) * math.cos(lat2)

    y = (
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1)
        * math.cos(lat2)
        * math.cos(delta_lon)
    )

    bearing = math.degrees(
        math.atan2(x, y)
    )

    return (bearing + 360) % 360


def calculate_bearing_difference(
    bearing1: float,
    bearing2: float,
) -> float:
    """
    2つの方位角の最小角度差を返す。
    0〜180°。
    """

    difference = abs(
        bearing1 - bearing2
    )

    return min(
        difference,
        360 - difference
    )


def generate_waypoint_pairs(
    graph,
    start_node: int,
    candidate_nodes: list[int],
    min_angle_difference: float = 60.0,
    max_angle_difference: float = 160.0,
    max_pairs: int = 30,
) -> list[tuple[int, int]]:

    start_data = graph.nodes[start_node]

    start_lat = start_data["y"]
    start_lon = start_data["x"]

    candidate_info = []

    for node in candidate_nodes:

        if node == start_node:
            continue

        node_data = graph.nodes[node]

        bearing = calculate_bearing(
            start_lat,
            start_lon,
            node_data["y"],
            node_data["x"],
        )

        candidate_info.append(
            {
                "node": node,
                "bearing": bearing,
            }
        )


    waypoint_pairs = []


    for i in range(
        len(candidate_info)
    ):

        for j in range(
            i + 1,
            len(candidate_info)
        ):

            first = candidate_info[i]
            second = candidate_info[j]

            angle_difference = (
                calculate_bearing_difference(
                    first["bearing"],
                    second["bearing"],
                )
            )

            if (
                min_angle_difference
                <= angle_difference
                <= max_angle_difference
            ):

                waypoint_pairs.append(
                    (
                        first["node"],
                        second["node"],
                    )
                )


    return waypoint_pairs[
        :max_pairs
    ]

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