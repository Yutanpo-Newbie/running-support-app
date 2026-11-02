import osmnx as ox
import networkx as nx
from app.algorithms.scoring import calculate_total_score
from app.schemas.route_request import RoutePreferences
from app.utils.geo import convert_to_geojson_linestring

from pathlib import Path
import math
import json
import time

GRAPH_CACHE_DIR = Path("data/graph_cache")

GRAPH_CACHE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

def calculate_distance_between_points(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:

    earth_radius = 6371000

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)

    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad)
        * math.cos(lat2_rad)
        * math.sin(delta_lon / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )

    return earth_radius * c

def get_road_graph(
    lat: float,
    lon: float,
    dist_m: int = 1000,
):
    """
    指定地点周辺の道路ネットワークを取得する。

    保存済みの道路グラフが使える場合は
    Overpass APIへ問い合わせずキャッシュを利用する。

    キャッシュが存在しない場合のみ、
    Overpass APIから取得してGraphMLとして保存する。
    """

    # 実際に必要な範囲より広めに取得しておく
    cache_radius_m = max(
        dist_m + 1500,
        3000,
    )

    # -----------------------------
    # 1. 既存キャッシュを探す
    # -----------------------------

    for metadata_file in GRAPH_CACHE_DIR.glob("*.json"):

        try:
            with open(
                metadata_file,
                "r",
                encoding="utf-8",
            ) as file:

                metadata = json.load(file)

            cache_lat = metadata["lat"]
            cache_lon = metadata["lon"]
            cached_radius = metadata["radius_m"]
            graph_file_name = metadata["graph_file"]

            distance_from_cache_center = (
                calculate_distance_between_points(
                    lat,
                    lon,
                    cache_lat,
                    cache_lon,
                )
            )

            # 現在地点から必要な範囲が
            # キャッシュ内に収まるか確認
            usable_radius = (
                cached_radius - dist_m
            )

            if (
                distance_from_cache_center
                <= usable_radius
            ):

                graph_file = (
                    GRAPH_CACHE_DIR
                    / graph_file_name
                )

                if graph_file.exists():

                    print(
                        f"OSM graph cache HIT: "
                        f"{graph_file_name}"
                    )

                    graph = ox.load_graphml(
                        graph_file
                    )

                    return graph

        except Exception as e:
            print(
                f"Cache check failed: {e}"
            )

    # -----------------------------
    # 2. キャッシュなし
    #    → Overpass APIから取得
    # -----------------------------

    print(
        "OSM graph cache MISS "
        "→ Overpass APIから取得"
    )

    graph = ox.graph_from_point(
        center_point=(lat, lon),
        dist=cache_radius_m,
        network_type="walk",
        simplify=True,
    )

    # -----------------------------
    # 3. GraphMLとして保存
    # -----------------------------

    timestamp = int(time.time())

    graph_file_name = (
        f"graph_{timestamp}.graphml"
    )

    metadata_file_name = (
        f"graph_{timestamp}.json"
    )

    graph_file = (
        GRAPH_CACHE_DIR
        / graph_file_name
    )

    metadata_file = (
        GRAPH_CACHE_DIR
        / metadata_file_name
    )

    ox.save_graphml(
        graph,
        graph_file,
    )

    metadata = {
        "lat": lat,
        "lon": lon,
        "radius_m": cache_radius_m,
        "graph_file": graph_file_name,
    }

    with open(
        metadata_file,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            metadata,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(
        f"OSM graph cache SAVED: "
        f"{graph_file_name}"
    )

    return graph


def get_graph_summary(graph) -> dict:
    """
    取得した道路グラフの概要を返す。
    """

    return {
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
    }

def get_nearest_node(
    graph,
    lat: float,
    lon: float,
):
    """
    指定した緯度経度に最も近い道路ノードを取得する。

    OSMnxの nearest_nodes は、X=経度, Y=緯度 の順番で指定する点に注意。
    """

    node_id = ox.distance.nearest_nodes(
        graph,
        X=lon,
        Y=lat,
    )

    return node_id


def get_node_coordinates(graph, node_id) -> dict:
    """
    ノードIDから、そのノードの緯度経度を取得する。
    """

    node_data = graph.nodes[node_id]

    return {
        "node_id": node_id,
        "lat": node_data["y"],
        "lon": node_data["x"],
    }

def get_candidate_nodes_by_distance(
    graph,
    start_node,
    target_distance_m: float,
    tolerance_m: float = 200,
    max_candidates: int = 10,
) -> list[dict]:
    """
    start_node から道路距離で target_distance_m 前後にある候補ノードを取得する。

    Parameters
    ----------
    graph:
        OSMnxで取得した道路グラフ
    start_node:
        開始ノードID
    target_distance_m:
        探したい距離。単位はメートル。
    tolerance_m:
        許容誤差。単位はメートル。
    max_candidates:
        最大候補数

    Returns
    -------
    list[dict]
        候補ノード情報のリスト
    """

    min_distance_m = target_distance_m - tolerance_m
    max_distance_m = target_distance_m + tolerance_m

    # start_node から各ノードまでの最短道路距離を計算する
    lengths = nx.single_source_dijkstra_path_length(
        graph,
        source=start_node,
        cutoff=max_distance_m,
        weight="length",
    )

    candidates = []

    for node_id, distance_m in lengths.items():
        if min_distance_m <= distance_m <= max_distance_m:
            node_data = graph.nodes[node_id]

            candidates.append(
                {
                    "node_id": node_id,
                    "lat": node_data["y"],
                    "lon": node_data["x"],
                    "distance_m": round(distance_m, 2),
                    "distance_error_m": round(abs(target_distance_m - distance_m), 2),
                }
            )

    candidates.sort(key=lambda node: node["distance_error_m"])

    return candidates[:max_candidates]

def get_shortest_path(
    graph,
    start_node,
    end_node,
) -> list:
    """
    start_node から end_node までの最短経路ノード列を取得する。
    """

    path = nx.shortest_path(
        graph,
        source=start_node,
        target=end_node,
        weight="length",
    )

    return path

def convert_path_to_coordinates(graph, path: list) -> list[dict]:
    """
    経路ノード列を lat/lon の座標列に変換する。
    """

    coordinates = []

    for node_id in path:
        node_data = graph.nodes[node_id]

        coordinates.append(
            {
                "lat": node_data["y"],
                "lon": node_data["x"],
            }
        )

    return coordinates

def create_loop_path(
    outbound_path: list,
    return_path: list,
) -> list:
    """
    行きルートと帰りルートを結合して、周回ルートのノード列を作る。

    return_path の先頭は candidate_node で outbound_path の末尾と重複するため、
    return_path[1:] を結合する。
    """

    return outbound_path + return_path[1:]

def create_multi_waypoint_loop(
    graph,
    start_node: int,
    waypoint_a: int,
    waypoint_b: int,
) -> list[int] | None:
    """
    START
      ↓
    waypoint A
      ↓
    waypoint B
      ↓
    START

    の周回経路を生成する。
    """

    path_start_to_a = (
        ox.routing.shortest_path(
            graph,
            start_node,
            waypoint_a,
            weight="length",
        )
    )

    if not path_start_to_a:
        return None


    path_a_to_b = (
        ox.routing.shortest_path(
            graph,
            waypoint_a,
            waypoint_b,
            weight="length",
        )
    )

    if not path_a_to_b:
        return None


    path_b_to_start = (
        ox.routing.shortest_path(
            graph,
            waypoint_b,
            start_node,
            weight="length",
        )
    )

    if not path_b_to_start:
        return None


    loop_path = (
        path_start_to_a
        + path_a_to_b[1:]
        + path_b_to_start[1:]
    )


    return loop_path

def calculate_edge_overlap_ratio(
    path: list[int],
) -> float:
    """
    ルート内で同じ道路区間を
    繰り返している割合を計算する。

    0.0 = 重複なし
    1.0に近いほど重複が多い
    """

    if len(path) < 2:
        return 0.0


    edges = []

    for i in range(
        len(path) - 1
    ):

        node_a = path[i]
        node_b = path[i + 1]


        # 徒歩グラフでは、
        # A→B と B→A は
        # 同じ道路として扱う
        edge = tuple(
            sorted(
                (
                    node_a,
                    node_b,
                )
            )
        )

        edges.append(edge)


    total_edges = len(edges)

    unique_edges = len(
        set(edges)
    )


    if total_edges == 0:
        return 0.0


    duplicated_edges = (
        total_edges
        - unique_edges
    )


    return (
        duplicated_edges
        / total_edges
    )

def generate_multi_waypoint_route_candidates(
    graph,
    start_node: int,
    candidate_nodes,
    target_distance_km: float,
    preferences: RoutePreferences,
    max_routes: int = 5,
):
    """
    START → A → B → START の周回候補を生成する。

    評価するもの：
    - 目標距離との差
    - 道路重複率

    曲がり回数の評価は次段階で追加する。
    """

    from app.algorithms.waypoint_generator import (
        generate_waypoint_pairs,
    )

    # -------------------------------------
    # candidate_nodes を node ID の一覧に統一
    # -------------------------------------

    normalized_nodes = []

    for candidate in candidate_nodes:

        # candidate_nodes が int のリストの場合
        if isinstance(candidate, int):
            normalized_nodes.append(candidate)

        # dictの場合
        elif isinstance(candidate, dict):

            if "node_id" in candidate:
                normalized_nodes.append(
                    candidate["node_id"]
                )

            elif "node" in candidate:
                normalized_nodes.append(
                    candidate["node"]
                )


    if len(normalized_nodes) < 2:
        return []


    # -------------------------------------
    # 方位角を考慮した waypoint A / B
    # の組み合わせを作る
    # -------------------------------------

    waypoint_pairs = generate_waypoint_pairs(
        graph=graph,
        start_node=start_node,
        candidate_nodes=normalized_nodes,
        min_angle_difference=60.0,
        max_angle_difference=160.0,
        max_pairs=40,
    )


    route_candidates = []


    # -------------------------------------
    # START → A → B → START
    # -------------------------------------

    for waypoint_a, waypoint_b in waypoint_pairs:

        try:

            path = create_multi_waypoint_loop(
                graph=graph,
                start_node=start_node,
                waypoint_a=waypoint_a,
                waypoint_b=waypoint_b,
            )

        except Exception as error:

            print(
                "multi waypoint route error:",
                waypoint_a,
                waypoint_b,
                error,
            )

            continue


        if not path:
            continue


        # ---------------------------------
        # 実際の道路距離
        # ---------------------------------

        distance_km = (
            calculate_path_length_km(
                graph,
                path,
            )
        )


        # ---------------------------------
        # 極端に距離が違う候補を除外
        # ---------------------------------

        distance_error_km = abs(
            distance_km
            - target_distance_km
        )


        # 最初は ±25% まで許容
        allowed_error_km = (
            target_distance_km
            * 0.25
        )


        if (
            distance_error_km
            >
            allowed_error_km
        ):
            continue


        # ---------------------------------
        # 道路重複率
        # ---------------------------------

        overlap_ratio = (
            calculate_edge_overlap_ratio(
                path
            )
        )


        # 50%以上同じ道路なら除外
        if overlap_ratio >= 0.50:
            continue


        # ---------------------------------
        # 座標変換
        # ---------------------------------

        coordinates = (
            convert_path_to_coordinates(
                graph,
                path,
            )
        )


        # ---------------------------------
        # 仮スコア
        #
        # 今は
        # 距離誤差 + 重複率
        # だけで評価する。
        #
        # 小さい方が良い。
        # ---------------------------------

        distance_penalty = (
            distance_error_km
            * 100
        )

        overlap_penalty = (
            overlap_ratio
            * 100
        )


        preliminary_score = (
            distance_penalty
            +
            overlap_penalty
        )


        loop_geometry = convert_to_geojson_linestring(
            coordinates
        )

        # 現段階では既存実装と同様に仮値
        elevation_gain_m = 0.0
        signals = 0
        intersections = max(
            0,
            len(path) - 2,
        )
        traffic_score = 0.0


        # 既存のスコア計算をそのまま利用
        base_score = calculate_total_score(
            target_distance_km=target_distance_km,
            actual_distance_km=distance_km,
            elevation_gain_m=elevation_gain_m,
            signals=signals,
            intersections=intersections,
            traffic_score=traffic_score,
            preferences=preferences,
        )


        # 道路重複を追加ペナルティにする
        overlap_penalty = (
            overlap_ratio * 100
        )


        total_score = (
            base_score
            + overlap_penalty
        )


        route_candidates.append(
            {
                "path": path,

                "coordinates":
                    coordinates,

                "geometry":
                    loop_geometry,

                "distance_km":
                    distance_km,

                "distance_m":
                    round(
                        distance_km * 1000,
                        2,
                    ),

                "distance_error_m":
                    round(
                        distance_error_km * 1000,
                        2,
                    ),

                "path_nodes":
                    len(path),

                "waypoint_a":
                    waypoint_a,

                "waypoint_b":
                    waypoint_b,

                "overlap_ratio":
                    overlap_ratio,

                "elevation_gain_m":
                    elevation_gain_m,

                "signals":
                    signals,

                "intersections":
                    intersections,

                "traffic_score":
                    traffic_score,

                "total_score":
                    total_score,
            }
        )


    # -------------------------------------
    # 良い順
    # -------------------------------------

    route_candidates.sort(
        key=lambda route:
            route[
                "total_score"
            ]
    )


    return route_candidates[
        :max_routes
    ]

def calculate_path_length_m(
    graph,
    path: list,
) -> float:
    """
    経路ノード列の道路距離を計算する。
    """

    total_length_m = 0.0

    for i in range(len(path) - 1):
        edge_data = graph.get_edge_data(path[i], path[i + 1])

        if edge_data is None:
            continue

        # MultiDiGraphなので、同じノード間に複数エッジがある可能性がある
        shortest_edge = min(
            edge_data.values(),
            key=lambda edge: edge.get("length", 0),
        )

        total_length_m += shortest_edge.get("length", 0)

    return round(total_length_m, 2)


def calculate_path_length_km(
    graph,
    path: list,
) -> float:
    """
    経路ノード列の道路距離をkm単位で計算する。
    """

    return round(calculate_path_length_m(graph, path) / 1000, 2)

def generate_loop_route_candidates(
    graph,
    start_node,
    candidate_nodes: list[dict],
    target_distance_km: float,
    preferences: RoutePreferences,
    max_routes: int = 5,
) -> list[dict]:
    """
    候補ノードを使って、start → candidate → start の
    往復型ループルート候補を複数生成する。
    """

    route_candidates = []

    for candidate in candidate_nodes[:max_routes]:
        candidate_node = candidate["node_id"]

        try:
            outbound_path = get_shortest_path(
                graph=graph,
                start_node=start_node,
                end_node=candidate_node,
            )

            return_path = get_shortest_path(
                graph=graph,
                start_node=candidate_node,
                end_node=start_node,
            )

            loop_path = create_loop_path(
                outbound_path=outbound_path,
                return_path=return_path,
            )

            loop_coordinates = convert_path_to_coordinates(
                graph=graph,
                path=loop_path,
            )

            loop_geometry = convert_to_geojson_linestring(loop_coordinates)

            loop_length_m = calculate_path_length_m(
                graph=graph,
                path=loop_path,
            )

            distance_error_m = abs(loop_length_m - target_distance_km * 1000)

            loop_length_km = calculate_path_length_km(
                graph=graph,
                path=loop_path,
            )

            # 現段階では仮データ
            elevation_gain_m = 0.0
            signals = 0
            intersections = max(0, len(loop_path) - 2)
            traffic_score = 0.0

            total_score = calculate_total_score(
                target_distance_km=target_distance_km,
                actual_distance_km=loop_length_km,
                elevation_gain_m=elevation_gain_m,
                signals=signals,
                intersections=intersections,
                traffic_score=traffic_score,
                preferences=preferences,
            )

            route_candidates.append(
                {
                    "candidate_node_id": candidate_node,
                    "distance_m": loop_length_m,
                    "distance_km": loop_length_km,
                    "distance_error_m": distance_error_m,
                    "path_nodes": len(loop_path),
                    "coordinates": loop_coordinates,
                    "geometry": loop_geometry,
                    "elevation_gain_m": elevation_gain_m,
                    "signals": signals,
                    "intersections": intersections,
                    "traffic_score": traffic_score,
                    "total_score": total_score,
                }
            )

        except Exception as e:
            print(f"Failed to generate route for candidate {candidate_node}: {e}")
    
    route_candidates.sort(key=lambda route: route["total_score"])

    return route_candidates