import math
import networkx as nx
from collections import defaultdict

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
    target_distance_m: float | None = None,
    distance_tolerance_ratio: float = 0.25,
) -> list[tuple[int, int]]:
    """
    経由地点A・Bの組み合わせを生成する。

    target_distance_m=None:
        従来の方位角方式を使用。

    target_distance_mを指定:
        1. 方位角差を確認
        2. 最短道路距離から周回距離を推定
        3. 到達可能性と距離条件で絞り込む
        4. 出発方向を分散させて選択
    """


    # =====================================
    # STEP 16.28
    # 経由地点の近接グループ分布を調査
    # =====================================

    waypoint_groups = group_nearby_waypoints(
        graph=graph,
        candidate_nodes=candidate_nodes,
        threshold_m=15.0,
    )

    node_to_group = {}

    for group_id, nodes in enumerate(waypoint_groups):
        for node in nodes:
            node_to_group[node] = group_id

    print(
        "\n=== WAYPOINT CLUSTER DEBUG ===",
        flush=True,
    )

    print(
        "candidate_nodes =",
        len(candidate_nodes),
        "clusters =",
        len(waypoint_groups),
        flush=True,
    )

    for group_id, nodes in enumerate(waypoint_groups):
        if len(nodes) >= 2:
            print(
                "NEARBY CLUSTER:",
                "group =", group_id,
                "size =", len(nodes),
                "nodes =", nodes,
                flush=True,
            )

    print(
        "=== WAYPOINT CLUSTER DEBUG END ===",
        flush=True,
    )


    print(
        "\n=== STEP 16.12 FUNCTION ENTERED ===",
        "target_distance_m =", target_distance_m,
        "max_pairs =", max_pairs,
        flush=True,
    )

    if max_pairs <= 0:
        return []

    start_data = graph.nodes[start_node]
    start_lat = start_data["y"]
    start_lon = start_data["x"]

    # 重複とスタート地点を除外
    unique_nodes = list(dict.fromkeys(
        node for node in candidate_nodes
        if node != start_node
    ))

    candidate_info = []

    for node in unique_nodes:
        node_data = graph.nodes[node]

        bearing = calculate_bearing(
            start_lat,
            start_lon,
            node_data["y"],
            node_data["x"],
        )

        candidate_info.append({
            "node": node,
            "bearing": bearing,
            "sector": int(
                (bearing + 22.5) // 45
            ) % 8,
        })

    # 既存方式との互換性を維持
    if target_distance_m is None:

        waypoint_pairs = []

        for i in range(len(candidate_info)):
            for j in range(i + 1, len(candidate_info)):

                first = candidate_info[i]
                second = candidate_info[j]

                difference = calculate_bearing_difference(
                    first["bearing"],
                    second["bearing"],
                )

                if (
                    min_angle_difference
                    <= difference
                    <= max_angle_difference
                ):
                    waypoint_pairs.append((
                        first["node"],
                        second["node"],
                    ))

        return waypoint_pairs[:max_pairs]

    if target_distance_m <= 0:
        raise ValueError(
            "target_distance_mは正の値にしてください"
        )

    if distance_tolerance_ratio < 0:
        raise ValueError(
            "distance_tolerance_ratioは0以上にしてください"
        )

    max_distance_m = (
        target_distance_m
        * (1 + distance_tolerance_ratio)
    )

    # START -> 各ノードの最短道路距離
    start_distances = nx.single_source_dijkstra_path_length(
        graph,
        start_node,
        cutoff=max_distance_m,
        weight="length",
    )

    # 各ノード -> START の最短道路距離
    # 有向グラフのため逆向きグラフで計算
    reverse_graph = graph.reverse(copy=False)

    return_distances = nx.single_source_dijkstra_path_length(
        reverse_graph,
        start_node,
        cutoff=max_distance_m,
        weight="length",
    )

    # A -> Bの距離はAごとに1回だけ計算する
    between_distances = {}

    for first in candidate_info:

        node_a = first["node"]

        between_distances[node_a] = (
            nx.single_source_dijkstra_path_length(
                graph,
                node_a,
                cutoff=max_distance_m,
                weight="length",
            )
        )

    # 方向ごとのペア候補を保持
    sector_pairs = defaultdict(list)

    evaluated_pairs = 0
    distance_rejected = 0
    unreachable_pairs = 0

    # A -> BとB -> Aを別々に評価する
    for first in candidate_info:

        for second in candidate_info:

            node_a = first["node"]
            node_b = second["node"]

            if node_a == node_b:
                continue

            angle_difference = calculate_bearing_difference(
                first["bearing"],
                second["bearing"],
            )

            if not (
                min_angle_difference
                <= angle_difference
                <= max_angle_difference
            ):
                continue

            evaluated_pairs += 1

            d_start_a = start_distances.get(node_a)
            d_a_b = between_distances[node_a].get(node_b)
            d_b_start = return_distances.get(node_b)

            if (
                d_start_a is None
                or d_a_b is None
                or d_b_start is None
            ):
                unreachable_pairs += 1
                continue

            estimated_distance_m = (
                d_start_a
                + d_a_b
                + d_b_start
            )

            # 最短道路距離でも上限を超える場合、
            # 実際の周回も上限以内には収まらない
            if estimated_distance_m > max_distance_m:
                distance_rejected += 1
                continue

            distance_error_m = abs(
                estimated_distance_m
                - target_distance_m
            )

            # 距離誤差の小さい組を優先する
            sector_pairs[first["sector"]].append({
                "pair": (node_a, node_b),
                "error": distance_error_m,
                "estimated_distance_m": estimated_distance_m,
            })

    # 各方向で距離誤差が小さい順に並べる
    for sector in range(8):
        sector_pairs[sector].sort(
            key=lambda item: (
                item["error"],
                str(item["pair"][0]),
                str(item["pair"][1]),
            )
        )

    # 8方向から1組ずつ選ぶ操作を繰り返す
    selected_pairs = []
    indexes = {sector: 0 for sector in range(8)}

    while len(selected_pairs) < max_pairs:

        added = False

        for sector in range(8):

            index = indexes[sector]
            bucket = sector_pairs[sector]

            if index >= len(bucket):
                continue

            selected_pairs.append(
                bucket[index]["pair"]
            )

            indexes[sector] += 1
            added = True

            if len(selected_pairs) >= max_pairs:
                break

        if not added:
            break

    print(
        "\n=== WAYPOINT PAIR SELECTION DEBUG ===",
        flush=True,
    )

    print(
        "evaluated_pairs =", evaluated_pairs,
        "unreachable =", unreachable_pairs,
        "distance_rejected =", distance_rejected,
        "selected =", len(selected_pairs),
        flush=True,
    )

    for sector in range(8):
        print(
            f"sector_{sector} =",
            len(sector_pairs[sector]),
            flush=True,
        )

    print(
        "=== WAYPOINT PAIR SELECTION DEBUG END ===",
        flush=True,
    )

    return selected_pairs

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


def group_nearby_waypoints(
    graph,
    candidate_nodes,
    threshold_m=15.0,
):
    """
    近接する経由地点候補をグループ化する。

    注意：
    - グラフのノードは変更しない
    - 直線距離に基づく暫定グルーピング
    - この段階では経路生成には適用しない
    """

    import math

    nodes = list(dict.fromkeys(candidate_nodes))
    parent = {node: node for node in nodes}

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a, b):
        root_a = find(a)
        root_b = find(b)

        if root_a != root_b:
            parent[root_b] = root_a

    def distance_m(a, b):
        node_a = graph.nodes[a]
        node_b = graph.nodes[b]

        lat1 = math.radians(node_a["y"])
        lat2 = math.radians(node_b["y"])

        dlat = lat2 - lat1
        dlon = math.radians(
            node_b["x"] - node_a["x"]
        )

        value = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1)
            * math.cos(lat2)
            * math.sin(dlon / 2) ** 2
        )

        return (
            6371000.0
            * 2
            * math.asin(min(1.0, math.sqrt(value)))
        )

    for i, node_a in enumerate(nodes):
        for node_b in nodes[i + 1:]:
            if distance_m(node_a, node_b) <= threshold_m:
                union(node_a, node_b)

    groups = {}

    for node in nodes:
        root = find(node)
        groups.setdefault(root, []).append(node)

    return list(groups.values())
