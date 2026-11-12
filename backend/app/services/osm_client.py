import osmnx as ox
import networkx as nx
from app.schemas.route_request import RoutePreferences
from app.utils.geo import convert_to_geojson_linestring
from app.algorithms.turn_detector import detect_turn_points

from app.algorithms.turn_aware_router import (
    shortest_turn_aware_path,
    get_used_edges,
)

from app.services.elevation_client import (
    get_route_elevation_gain,
    ElevationDataUnavailable,
)
from app.algorithms.scoring import (
    calculate_total_score,
    calculate_final_route_score,
)

from pathlib import Path
import math
import json
import time
import traceback

GRAPH_CACHE_DIR = Path("data/graph_cache")


# =====================================
# 16.3 道路属性の取得設定
# =====================================

# 取得する道路属性の仕様バージョン
GRAPH_ATTRIBUTES_VERSION = 2

ADDITIONAL_WAY_TAGS = [
    "sidewalk",
    "sidewalk:left",
    "sidewalk:right",
    "sidewalk:both",
    "footway",
    "lanes",
    "maxspeed",
    "surface",
    "lit",
]

# OSMnxの既定の取得属性は維持し、
# 必要な属性だけ追加する
ox.settings.useful_tags_way = list(
    dict.fromkeys(
        ox.settings.useful_tags_way
        + ADDITIONAL_WAY_TAGS
    )
)


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


            # 古い属性仕様のキャッシュは利用しない
            cached_version = metadata.get(
                "attributes_version",
                1,
            )

            if cached_version != GRAPH_ATTRIBUTES_VERSION:
                continue


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
        "attributes_version": GRAPH_ATTRIBUTES_VERSION,
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


# =====================================
# 16.6.6 経由地点の行き止まり除外
# =====================================

def filter_through_waypoint_nodes(
    graph,
    candidate_nodes: list[int],
) -> list[int]:
    """
    隣接ノードが2つ以上ある地点のみを
    周回ルートの経由地点候補とする。

    行き止まりでの即時折り返しを防ぐ。
    """

    filtered_nodes = []

    for node_id in candidate_nodes:

        neighbors = (
            set(graph.predecessors(node_id))
            | set(graph.successors(node_id))
        )

        if len(neighbors) < 2:
            continue

        filtered_nodes.append(node_id)

    return filtered_nodes



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
    avoid_steps: bool = False,
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


    # =====================================
    # 16.7.2.3 階段を除外した道路距離で候補を選択
    # =====================================

    search_graph = graph

    if avoid_steps:

        def is_allowed_edge(u, v, key):
            edge_data = graph[u][v][key]
            highway = edge_data.get("highway", [])

            if isinstance(highway, str):
                highway_types = [highway]
            elif isinstance(highway, (list, tuple, set)):
                highway_types = highway
            else:
                highway_types = []

            return "steps" not in highway_types

        # 元のグラフは変更せず、
        # 階段エッジを除外したビューを作成
        search_graph = nx.subgraph_view(
            graph,
            filter_edge=is_allowed_edge,
        )

    lengths = nx.single_source_dijkstra_path_length(
        search_graph,
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
    use_turn_aware: bool = True,
) -> list[int] | None:
    """
    START → A → B → START

    use_turn_aware=True:
        曲がりにくさと道路重複を考慮

    use_turn_aware=False:
        従来の最短距離方式
    """

    if use_turn_aware:

        # -----------------------------
        # 1. START → A
        # -----------------------------

        path_1 = shortest_turn_aware_path(
            graph,
            start_node,
            waypoint_a,
            avoid_steps=True,
        )

        if not path_1:
            return None

        # -----------------------------
        # 2. A → B
        # 先ほど通った道を避ける
        # -----------------------------

        used_edges = get_used_edges(path_1)

        path_2 = shortest_turn_aware_path(
            graph,
            waypoint_a,
            waypoint_b,
            used_edges=used_edges,
            initial_prev_node=path_1[-2],
            avoid_steps=True,
        )

        if not path_2:
            return None

        # -----------------------------
        # 3. B → START
        # 以前の2区間の道路を避ける
        # -----------------------------

        used_edges.update(
            get_used_edges(path_2)
        )

        path_3 = shortest_turn_aware_path(
            graph,
            waypoint_b,
            start_node,
            used_edges=used_edges,
            initial_prev_node=path_2[-2],
            avoid_steps=True,
        )

        if not path_3:
            return None

    else:

        # 従来方式を残す
        path_1 = ox.routing.shortest_path(
            graph,
            start_node,
            waypoint_a,
            weight="length",
        )

        if not path_1:
            return None

        path_2 = ox.routing.shortest_path(
            graph,
            waypoint_a,
            waypoint_b,
            weight="length",
        )

        if not path_2:
            return None

        path_3 = ox.routing.shortest_path(
            graph,
            waypoint_b,
            start_node,
            weight="length",
        )

        if not path_3:
            return None


    # =====================================
    # 16.6.3 折り返し発生区間の診断
    # =====================================

    def find_backtrack_positions(path):
        positions = []

        for i in range(1, len(path) - 1):
            if path[i - 1] == path[i + 1]:
                positions.append(i)

        return positions

    # 各区間内の折り返し
    backtracks_1 = find_backtrack_positions(path_1)
    backtracks_2 = find_backtrack_positions(path_2)
    backtracks_3 = find_backtrack_positions(path_3)

    # 各区間を結合
    loop_path = (
        path_1
        + path_2[1:]
        + path_3[1:]
    )

    # 結合後の折り返し
    backtracks_total = find_backtrack_positions(
        loop_path
    )

    # =====================================
    # 16.6.4 接続地点A/Bの折り返しを特定
    # =====================================

    # START → A と A → B の接続
    backtrack_at_a = (
        len(path_1) >= 2
        and len(path_2) >= 2
        and path_1[-2] == path_2[1]
    )

    # A → B と B → START の接続
    backtrack_at_b = (
        len(path_2) >= 2
        and len(path_3) >= 2
        and path_2[-2] == path_3[1]
    )

    if backtrack_at_a or backtrack_at_b:

        # 方向を無視した接続道路ノード
        neighbors_a = (
            set(graph.predecessors(waypoint_a))
            | set(graph.successors(waypoint_a))
        )

        neighbors_b = (
            set(graph.predecessors(waypoint_b))
            | set(graph.successors(waypoint_b))
        )

        print(
            "WAYPOINT BACKTRACK DEBUG:",
            "at_A =", backtrack_at_a,
            "at_B =", backtrack_at_b,
            "waypoint_a =", waypoint_a,
            "neighbors_A =", len(neighbors_a),
            "waypoint_b =", waypoint_b,
            "neighbors_B =", len(neighbors_b),
            flush=True,
        )

    if backtracks_total:
        print(
            "BACKTRACK LOCATION DEBUG:",
            "segment1 =", len(backtracks_1),
            "segment2 =", len(backtracks_2),
            "segment3 =", len(backtracks_3),
            "total =", len(backtracks_total),
            "waypoint_a =", waypoint_a,
            "waypoint_b =", waypoint_b,
            flush=True,
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

def calculate_backtrack_distance_ratio(
    graph,
    path: list[int],
) -> float:
    """
    同じ道路区間を逆方向に戻っている距離の割合を計算する。

    0.0 = 折り返しなし
    1.0に近いほど折り返しが多い
    """

    if len(path) < 2:
        return 0.0


    total_distance_m = 0.0
    backtrack_distance_m = 0.0

    seen_edges = set()


    for i in range(len(path) - 1):

        node_a = path[i]
        node_b = path[i + 1]

        edge_data = graph.get_edge_data(
            node_a,
            node_b,
        )

        if not edge_data:
            continue


        shortest_edge = min(
            edge_data.values(),
            key=lambda edge:
                edge.get("length", 0),
        )

        edge_length_m = shortest_edge.get(
            "length",
            0,
        )

        total_distance_m += edge_length_m


        # 方向を無視した道路区間
        undirected_edge = tuple(
            sorted(
                (
                    node_a,
                    node_b,
                )
            )
        )


        # すでに同じ道路を通っているなら
        # 折り返し距離としてカウント
        if undirected_edge in seen_edges:
            backtrack_distance_m += (
                edge_length_m
            )
        else:
            seen_edges.add(
                undirected_edge
            )


    if total_distance_m == 0:
        return 0.0


    return (
        backtrack_distance_m
        / total_distance_m
    )


# =====================================
# 16.6.2 枝道・即時折り返しの検出
# =====================================

def count_immediate_backtracks(
    path: list[int],
) -> int:
    """
    A → B → A のように、
    進んだ道路を直後に引き返す箇所を数える。

    同じ道路ノードへの即時復帰を検出する。
    """

    count = 0

    for i in range(1, len(path) - 1):

        previous_node = path[i - 1]
        next_node = path[i + 1]

        if previous_node == next_node:
            count += 1

    return count


def select_diverse_routes(
    route_candidates: list[dict],
    max_routes: int = 3,
    max_overlap_ratio: float = 0.60,
) -> list[dict]:
    """
    スコア順の候補から、互いに類似しすぎない
    ルートを最大max_routes件選択する。

    overlapはOSM道路エッジ数ベース。
    """

    if max_routes <= 0:
        return []

    # スコアは小さいほど良い
    sorted_candidates = sorted(
        route_candidates,
        key=lambda route: route["total_score"],
    )

    selected_routes = []
    selected_edge_sets = []

    for candidate in sorted_candidates:

        candidate_edges = get_used_edges(
            candidate["path"]
        )

        is_too_similar = False

        for selected_edges in selected_edge_sets:

            shared_edges = len(
                candidate_edges & selected_edges
            )

            smaller_edge_count = min(
                len(candidate_edges),
                len(selected_edges),
            )

            overlap_ratio = (
                shared_edges / smaller_edge_count
                if smaller_edge_count > 0
                else 0.0
            )

            if overlap_ratio >= max_overlap_ratio:
                is_too_similar = True
                break

        if is_too_similar:
            continue

        selected_routes.append(candidate)
        selected_edge_sets.append(candidate_edges)

        if len(selected_routes) >= max_routes:
            break

    return selected_routes


def calculate_steps_distance_m(graph, path: list[int]) -> float:
    """
    ルート上の階段区間の合計距離を計算する。
    """

    total_steps_m = 0.0

    for node_a, node_b in zip(path, path[1:]):
        edge_data = graph.get_edge_data(node_a, node_b)

        if not edge_data:
            continue

        edge = min(
            edge_data.values(),
            key=lambda item: float(
                item.get("length", float("inf"))
            ),
        )

        highway = edge.get("highway", [])

        if isinstance(highway, str):
            highway_types = [highway]
        elif isinstance(highway, (list, tuple, set)):
            highway_types = list(highway)
        else:
            highway_types = []

        if "steps" in highway_types:
            total_steps_m += float(
                edge.get("length", 0.0)
            )

    return round(total_steps_m, 2)


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


    # =====================================
    # 16.6.6 行き止まり候補の除外
    # =====================================

    original_count = len(normalized_nodes)

    normalized_nodes = filter_through_waypoint_nodes(
        graph,
        normalized_nodes,
    )

    print(
        "WAYPOINT NODE FILTER:",
        "before =", original_count,
        "after =", len(normalized_nodes),
        "removed =", (
            original_count - len(normalized_nodes)
        ),
        flush=True,
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
        max_pairs=160,
    )

    print(
        "NORMALIZED NODES:",
        len(normalized_nodes),
        flush=True,
    )

    print(
        "WAYPOINT PAIRS:",
        len(waypoint_pairs),
        flush=True,
    )


    route_candidates = []

    # 16.2 デバッグ：候補の除外理由を集計
    debug_counts = {
        "loop_entered": 0,
        "path_error": 0,
        "no_path": 0,
        "distance_rejected": 0,
        "overlap_rejected": 0,
        "backtrack_rejected": 0,
        "turn_density_rejected": 0,
        "short_turn_rejected": 0,
        "accepted": 0,
    }


    # -------------------------------------
    # START → A → B → START
    # -------------------------------------

    for waypoint_a, waypoint_b in waypoint_pairs:
        debug_counts["loop_entered"] += 1

        if debug_counts["loop_entered"] <= 3:
            print(
                "LOOP ENTERED:",
                debug_counts["loop_entered"],
                "A:", waypoint_a,
                "B:", waypoint_b,
                flush=True,
            )
        try:

            path = create_multi_waypoint_loop(
                graph=graph,
                start_node=start_node,
                waypoint_a=waypoint_a,
                waypoint_b=waypoint_b,
                use_turn_aware=True,
            )

            if debug_counts["loop_entered"] <= 3:
                print(
                    "PATH GENERATED:",
                    len(path) if path is not None else None,
                    flush=True,
                )

        except Exception as error:
            debug_counts["path_error"] += 1
            print(
                "multi waypoint route error:",
                waypoint_a,
                waypoint_b,
                error,
            )

            continue
        
        



        if not path:
            debug_counts["no_path"] += 1
            continue



        # =====================================
        # 16.7.2.1 階段区間の判定
        # =====================================

        steps_distance_m = calculate_steps_distance_m(
            graph,
            path,
        )

        if steps_distance_m > 0:
            print(
                "STEPS ROUTE REJECTED:",
                "A =", waypoint_a,
                "B =", waypoint_b,
                "steps_m =", steps_distance_m,
                flush=True,
            )
            continue


        # =====================================
        # 16.6.2 即時折り返しの検出
        # =====================================

        immediate_backtracks = (
            count_immediate_backtracks(path)
        )

        if immediate_backtracks > 0:
            print(
                "IMMEDIATE BACKTRACK DETECTED:",
                "count =", immediate_backtracks,
                "A =", waypoint_a,
                "B =", waypoint_b,
                flush=True,
            )


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
            debug_counts["distance_rejected"] += 1
            continue

        print(
            "DISTANCE PASSED:",
            "distance_km =", distance_km,
            "error_km =", distance_error_km,
            flush=True,
        )


        # ---------------------------------
        # 道路重複率
        # ---------------------------------

        overlap_ratio = (
            calculate_edge_overlap_ratio(
                path
            )
        )

        backtrack_ratio = (
            calculate_backtrack_distance_ratio(
                graph,
                path,
            )
        )


        # 50%以上同じ道路なら除外
        if overlap_ratio >= 0.20:
            debug_counts["overlap_rejected"] += 1
            continue

        # 折り返し距離が多すぎる候補を除外
        if backtrack_ratio >= 0.15:
            debug_counts["backtrack_rejected"] += 1
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

        turn_points = detect_turn_points(
            coordinates
        )

        turn_count = len(turn_points)

        if distance_km > 0:
            turn_density = (
                turn_count
                / distance_km
            )
        else:
            turn_density = 0.0

        short_turn_interval_count = 0

        SHORT_TURN_INTERVAL_M = 50

        for i in range(
            len(turn_points) - 1
        ):

            current_turn = turn_points[i]
            next_turn = turn_points[i + 1]

            interval_m = (
                calculate_distance_between_points(
                    current_turn["lat"],
                    current_turn["lon"],
                    next_turn["lat"],
                    next_turn["lon"],
                )
            )

            if (
                interval_m
                < SHORT_TURN_INTERVAL_M
            ):
                short_turn_interval_count += 1

        # ---------------------------------
        # 曲がりすぎるルートを除外
        # ---------------------------------

        MAX_TURN_DENSITY = 8.0
        MAX_SHORT_TURN_INTERVALS = 4

        print(
            "TURN DEBUG:",
            "distance =", round(distance_km, 2),
            "turn_count =", turn_count,
            "turn_density =", round(turn_density, 2),
            "short_intervals =", short_turn_interval_count,
            flush=True,
        )

        if (
            turn_density
            > MAX_TURN_DENSITY
        ):
            debug_counts["turn_density_rejected"] += 1
            continue

        if (
            short_turn_interval_count
            > MAX_SHORT_TURN_INTERVALS
        ):
            debug_counts["short_turn_rejected"] += 1
            continue

        turn_penalty = (
            turn_count * 2
            + turn_density * 3
            + short_turn_interval_count * 5
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

        signals = count_route_signals(
            graph=graph,
            path=path,
        )
        intersections = count_route_intersections(
            graph=graph,
            path=path,
        )

        traffic_score = calculate_route_traffic_score(
            graph=graph,
            path=path,
        )

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
            + turn_penalty
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

                "turn_count":
                    turn_count,

                "turn_density":
                    turn_density,

                "short_turn_interval_count":
                    short_turn_interval_count,

                "turn_penalty":
                    turn_penalty,

                "immediate_backtracks":
                    immediate_backtracks,

                "path_nodes":
                    len(path),

                "waypoint_a":
                    waypoint_a,

                "waypoint_b":
                    waypoint_b,

                "overlap_ratio":
                    overlap_ratio,

                "backtrack_ratio":
                    backtrack_ratio,

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
        debug_counts["accepted"] += 1

    
    # =====================================
    # 16.4.4 標高取得失敗時の処理
    # =====================================

    valid_routes = []
    elevation_errors = []

    for route in route_candidates:

        try:
            elevation_gain_m = get_route_elevation_gain(
                route["coordinates"]
            )

        except Exception as error:
            # 標高取得に失敗した候補を記録
            elevation_errors.append(str(error))

            print(
                "ELEVATION FAILED:",
                "distance =", route["distance_km"],
                "error =", repr(error),
                flush=True,
            )

            # 標高不明を0mとして扱わない
            continue

        # 標高取得に成功した場合
        route["elevation_gain_m"] = elevation_gain_m


        # =====================================
        # 16.5.5 新しい最終スコアを計算
        # =====================================

        # 旧方式のスコアも比較用に計算
        old_base_score = calculate_total_score(
            target_distance_km=target_distance_km,
            actual_distance_km=route["distance_km"],
            elevation_gain_m=elevation_gain_m,
            signals=route["signals"],
            intersections=route["intersections"],
            traffic_score=route["traffic_score"],
            preferences=preferences,
        )

        old_total_score = (
            old_base_score
            + route["overlap_ratio"] * 100
            + route["turn_penalty"]
        )

        # 新方式のスコアを計算
        score_result = calculate_final_route_score(
            target_distance_km=target_distance_km,
            actual_distance_km=route["distance_km"],
            elevation_gain_m=elevation_gain_m,
            signals=route["signals"],
            intersections=route["intersections"],
            traffic_score=route["traffic_score"],
            preferences=preferences,
            turn_density=route["turn_density"],
            short_turn_interval_count=route[
                "short_turn_interval_count"
            ],
            overlap_ratio=route["overlap_ratio"],
        )

        # 新しい総合スコアで上書き
        route["total_score"] = score_result["total_score"]

        print(
            "SCORING COMPARISON:",
            "distance =", route["distance_km"],
            "old =", round(old_total_score, 2),
            "new =", route["total_score"],
            "base =", score_result["base_score"],
            "quality =", score_result["quality_penalty"],
            flush=True,
        )


        valid_routes.append(route)

        print(
            "ELEVATION UPDATED:",
            "distance =", route["distance_km"],
            "gain =", elevation_gain_m,
            "score =", round(route["total_score"], 2),
            "backtracks =", route["immediate_backtracks"],
            "waypoint_a =", route["waypoint_a"],
            "waypoint_b =", route["waypoint_b"],
            flush=True,
        )

    # ルート候補自体が存在するのに
    # 標高取得で全候補が失敗した場合
    if route_candidates and not valid_routes:
        raise ElevationDataUnavailable(
            "全ルート候補の標高取得に失敗しました"
        )

    # 標高取得に成功した候補だけ残す
    route_candidates = valid_routes



    # -------------------------------------
    # 良い順
    # -------------------------------------

    route_candidates.sort(
        key=lambda route:
            route[
                "total_score"
            ]
    )

    print(
        "ACCEPTED ROUTES:",
        len(route_candidates),
        flush=True,
    )

    print(
        "ROUTE FILTER DEBUG:",
        debug_counts,
        flush=True,
    )

    # =====================================
    # 16.6.10 ルート候補間の重複分析
    # =====================================

    print(
        "\n=== ROUTE DIVERSITY DEBUG ===",
        flush=True,
    )

    for i, route in enumerate(
        route_candidates,
        start=1,
    ):
        print(
            f"ROUTE {i}:",
            "distance =", route["distance_km"],
            "score =", round(route["total_score"], 2),
            "turns =", route["turn_count"],
            "backtracks =",
            route["immediate_backtracks"],
            "A =", route["waypoint_a"],
            "B =", route["waypoint_b"],
            flush=True,
        )

    print(
        "\n=== PAIRWISE ROUTE OVERLAP ===",
        flush=True,
    )

    for i in range(len(route_candidates)):

        route_a = route_candidates[i]
        edges_a = get_used_edges(
            route_a["path"]
        )

        for j in range(i + 1, len(route_candidates)):

            route_b = route_candidates[j]
            edges_b = get_used_edges(
                route_b["path"]
            )

            shared_edges = len(
                edges_a & edges_b
            )

            # 少ない方の道路区間数を基準に
            # 共通部分の割合を計算
            smaller_edge_count = min(
                len(edges_a),
                len(edges_b),
            )

            overlap = (
                shared_edges / smaller_edge_count
                if smaller_edge_count > 0
                else 0.0
            )

            print(
                f"ROUTE {i + 1} vs {j + 1}:",
                f"overlap = {overlap:.1%}",
                f"shared_edges = {shared_edges}",
                flush=True,
            )



    # =====================================
    # 16.6.11 類似ルートを除外して選択
    # =====================================

    selected_routes = select_diverse_routes(
        route_candidates=route_candidates,
        max_routes=max_routes,
        max_overlap_ratio=0.60,
    )

    print(
        "DIVERSE ROUTE SELECTION:",
        "candidates =", len(route_candidates),
        "selected =", len(selected_routes),
        flush=True,
    )

    for i, route in enumerate(
        selected_routes,
        start=1,
    ):
        print(
            f"SELECTED ROUTE {i}:",
            "distance =", route["distance_km"],
            "score =", round(route["total_score"], 2),
            "A =", route["waypoint_a"],
            "B =", route["waypoint_b"],
            flush=True,
        )


    # =====================================
    # 16.7.1 信号・交差点の実データ診断
    # =====================================

    print(
        "\n=== OSM ATTRIBUTE DEBUG ===",
        flush=True,
    )

    # グラフ全体の信号機タグを調査
    all_signal_nodes = [
        node_id
        for node_id, data in graph.nodes(data=True)
        if (
            data.get("highway") == "traffic_signals"
            if isinstance(data.get("highway"), str)
            else (
                "traffic_signals" in data.get("highway")
                if isinstance(
                    data.get("highway"),
                    (list, tuple, set),
                )
                else False
            )
        )
    ]

    all_street_count_nodes = [
        node_id
        for node_id, data in graph.nodes(data=True)
        if data.get("street_count") is not None
    ]

    print(
        "GRAPH SIGNAL NODES:",
        len(all_signal_nodes),
        flush=True,
    )

    print(
        "GRAPH STREET_COUNT NODES:",
        len(all_street_count_nodes),
        "/",
        len(graph.nodes),
        flush=True,
    )

    # 最終採用ルートごとに調査
    for i, route in enumerate(selected_routes, start=1):

        path = route["path"]

        signal_node_ids = [
            node_id
            for node_id in set(path)
            if node_id in all_signal_nodes
        ]

        intersection_node_ids = [
            node_id
            for node_id in set(path[1:-1])
            if (
                node_id != path[0]
                and int(
                    graph.nodes[node_id].get(
                        "street_count", 0
                    )
                ) >= 3
            )
        ]

        print(
            f"ROUTE {i} OSM DATA:",
            "distance =", route["distance_km"],
            "signals =", route["signals"],
            "intersections =", route["intersections"],
            "traffic_score =", route["traffic_score"],
            flush=True,
        )

        print(
            "  SIGNAL NODE IDS:",
            signal_node_ids,
            flush=True,
        )

        print(
            "  INTERSECTION NODE IDS:",
            intersection_node_ids,
            flush=True,
        )

        # =====================================
        # 16.7.1.2 交差点ノードの属性確認
        # =====================================

        from collections import Counter

        street_count_distribution = Counter(
            int(graph.nodes[node_id]["street_count"])
            for node_id in intersection_node_ids
        )

        print(
            "  STREET COUNT DISTRIBUTION:",
            dict(sorted(
                street_count_distribution.items()
            )),
            flush=True,
        )

        # 代表的な交差点ノードを5件調査
        for node_id in intersection_node_ids[:5]:

            node_data = graph.nodes[node_id]

            connected_highways = set()

            for u, v, edge_data in graph.in_edges(
                node_id,
                data=True,
            ):
                highway = edge_data.get("highway")

                if isinstance(highway, (list, tuple, set)):
                    connected_highways.update(
                        str(value) for value in highway
                    )
                elif highway is not None:
                    connected_highways.add(str(highway))

            for u, v, edge_data in graph.out_edges(
                node_id,
                data=True,
            ):
                highway = edge_data.get("highway")

                if isinstance(highway, (list, tuple, set)):
                    connected_highways.update(
                        str(value) for value in highway
                    )
                elif highway is not None:
                    connected_highways.add(str(highway))

            print(
                "  INTERSECTION DETAIL:",
                "node =", node_id,
                "street_count =",
                node_data.get("street_count"),
                "lat =", node_data.get("y"),
                "lon =", node_data.get("x"),
                "highways =",
                sorted(connected_highways),
                flush=True,
            )


            # =====================================
            # 16.7.1.3 交差点の道路種別を集計
            # =====================================

            from collections import Counter

            intersection_types = Counter()

            for node_id in intersection_node_ids:

                highway_types = set()

                for _, _, data in graph.in_edges(
                    node_id,
                    data=True,
                ):
                    highway = data.get("highway", [])

                    if isinstance(highway, (list, tuple, set)):
                        highway_types.update(highway)
                    elif isinstance(highway, str):
                        highway_types.add(highway)

                for _, _, data in graph.out_edges(
                    node_id,
                    data=True,
                ):
                    highway = data.get("highway", [])

                    if isinstance(highway, (list, tuple, set)):
                        highway_types.update(highway)
                    elif isinstance(highway, str):
                        highway_types.add(highway)

                if "footway" in highway_types:
                    intersection_types["footwayを含む"] += 1

                if "residential" in highway_types:
                    intersection_types["residentialを含む"] += 1

                if (
                    "primary" in highway_types
                    or "secondary" in highway_types
                    or "tertiary" in highway_types
                ):
                    intersection_types["比較的大きな道路を含む"] += 1

                if "service" in highway_types:
                    intersection_types["serviceを含む"] += 1

            print(
                "  INTERSECTION TYPE SUMMARY:",
                dict(intersection_types),
                flush=True,
            )


    print(
        "=== OSM ATTRIBUTE DEBUG END ===\n",
        flush=True,
    )


    # =====================================
    # 16.7.2 道路種別・交通評価の診断
    # =====================================

    from collections import defaultdict

    print(
        "\n=== TRAFFIC ATTRIBUTE DEBUG ===",
        flush=True,
    )

    for i, route in enumerate(selected_routes, start=1):

        highway_lengths = defaultdict(float)

        sidewalk_length_m = 0.0
        maxspeed_length_m = 0.0
        lanes_length_m = 0.0
        total_length_m = 0.0

        path = route["path"]

        for node_a, node_b in zip(path, path[1:]):

            edge_data = graph.get_edge_data(
                node_a,
                node_b,
            )

            if not edge_data:
                continue

            edge = min(
                edge_data.values(),
                key=lambda item: float(
                    item.get("length", float("inf"))
                ),
            )

            length_m = float(
                edge.get("length", 0.0)
            )

            if length_m <= 0:
                continue

            total_length_m += length_m

            highway = edge.get("highway", "unknown")

            if isinstance(highway, (list, tuple, set)):
                highway_types = [
                    str(value) for value in highway
                ]
            else:
                highway_types = [str(highway)]

            # 交通スコア計算と同じく、
            # 複数種類なら最もリスクの高い分類を採用
            highway_type = max(
                highway_types,
                key=lambda h: HIGHWAY_TRAFFIC_WEIGHTS.get(
                    h, 5.0
                ),
            )

            highway_lengths[highway_type] += length_m

            if any(
                key in edge
                for key in (
                    "sidewalk",
                    "sidewalk:left",
                    "sidewalk:right",
                    "sidewalk:both",
                )
            ):
                sidewalk_length_m += length_m

            if edge.get("maxspeed") is not None:
                maxspeed_length_m += length_m

            if edge.get("lanes") is not None:
                lanes_length_m += length_m

        print(
            f"\nROUTE {i} TRAFFIC DATA:",
            "distance_m =", round(total_length_m, 1),
            "traffic_score =", route["traffic_score"],
            flush=True,
        )

        for highway, length_m in sorted(
            highway_lengths.items(),
            key=lambda item: -item[1],
        ):
            percentage = (
                length_m / total_length_m * 100
                if total_length_m > 0
                else 0.0
            )

            print(
                f"  {highway}:",
                f"{length_m:.1f}m",
                f"({percentage:.1f}%)",
                flush=True,
            )

        if total_length_m > 0:
            print(
                "  ATTRIBUTE COVERAGE:",
                "sidewalk =",
                f"{sidewalk_length_m / total_length_m:.1%}",
                "maxspeed =",
                f"{maxspeed_length_m / total_length_m:.1%}",
                "lanes =",
                f"{lanes_length_m / total_length_m:.1%}",
                flush=True,
            )

    print(
        "=== TRAFFIC ATTRIBUTE DEBUG END ===",
        flush=True,
    )


    return selected_routes


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



def count_route_signals(
    graph,
    path: list[int],
) -> int:
    """
    ルート上の信号ノード数を計算する。

    同じ信号ノードを複数回通過しても
    1地点としてカウントする。
    """

    signal_nodes = set()

    for node_id in path:

        node_data = graph.nodes[node_id]

        highway = node_data.get("highway")

        # highway属性が文字列の場合
        if isinstance(highway, str):
            is_signal = highway == "traffic_signals"

        # 複数属性の場合
        elif isinstance(highway, (list, tuple, set)):
            is_signal = "traffic_signals" in highway

        else:
            is_signal = False

        if is_signal:
            signal_nodes.add(node_id)

    return len(signal_nodes)


def count_route_intersections(
    graph,
    path: list[int],
) -> int:
    """
    ルート上の交差点数を計算する。

    street_count >= 3 のノードを
    交差点として扱う。

    START/GOALは除外し、
    同一ノードの重複も除外する。
    """

    if len(path) < 3:
        return 0

    # START/GOALを除外して重複をなくす
    unique_nodes = set(path[1:-1])

    intersections = set()

    for node_id in unique_nodes:

        # 周回のSTART/GOALノードを除外
        if node_id == path[0]:
            continue

        node_data = graph.nodes[node_id]

        street_count = node_data.get(
            "street_count"
        )

        if street_count is None:
            raise ValueError(
                f"ノード{node_id}に"
                "street_count属性がありません"
            )

        if int(street_count) >= 3:
            intersections.add(node_id)

    return len(intersections)


# =====================================
# 16.3 道路種別による車両交通リスク評価
# =====================================

HIGHWAY_TRAFFIC_WEIGHTS = {
    "footway": 0.0,
    "pedestrian": 0.0,
    "steps": 0.0,
    "corridor": 0.0,
    "path": 1.0,
    "track": 2.0,
    "residential": 3.0,
    "living_street": 2.0,
    "service": 4.0,
    "unclassified": 5.0,
    "tertiary": 6.0,
    "tertiary_link": 6.0,
    "secondary": 7.0,
    "secondary_link": 7.0,
    "primary": 8.0,
    "primary_link": 8.0,
    "trunk": 9.0,
    "trunk_link": 9.0,
    "motorway": 10.0,
    "motorway_link": 10.0,
}


def calculate_route_traffic_score(
    graph,
    path: list[int],
) -> float:
    """
    ルート上の道路種別と区間距離から、
    車両交通リスクの代理指標を計算する。

    0.0 に近いほど低リスク。
    10.0 に近いほど高リスク。

    実際の交通量を表す値ではない。
    """

    if len(path) < 2:
        return 0.0

    weighted_score_sum = 0.0
    total_length_m = 0.0

    for i in range(len(path) - 1):
        node_a = path[i]
        node_b = path[i + 1]

        edge_data = graph.get_edge_data(
            node_a,
            node_b,
        )

        if not edge_data:
            raise ValueError(
                f"道路エッジがありません: "
                f"{node_a} -> {node_b}"
            )

        # 既存の距離計算と同じく
        # 並列エッジのうち最短のものを利用
        edge = min(
            edge_data.values(),
            key=lambda item: float(
                item.get("length", float("inf"))
            ),
        )

        length_m = float(
            edge.get("length", 0.0)
        )

        if length_m <= 0:
            continue

        highway = edge.get("highway")

        if isinstance(highway, (list, tuple, set)):
            highway_types = highway

        elif isinstance(highway, str):
            highway_types = [highway]

        else:
            highway_types = []

        if highway_types:
            # 複数の道路種別がある場合は
            # 安全側に寄せて高い値を採用
            risk_weight = max(
                HIGHWAY_TRAFFIC_WEIGHTS.get(
                    str(highway_type),
                    5.0,
                )
                for highway_type in highway_types
            )
        else:
            # 道路種別が不明な場合は中間値
            risk_weight = 5.0

        weighted_score_sum += (
            risk_weight * length_m
        )

        total_length_m += length_m

    if total_length_m == 0:
        raise ValueError(
            "道路距離を取得できませんでした"
        )

    traffic_score = (
        weighted_score_sum / total_length_m
    )

    return round(traffic_score, 2)



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

    # 16.2 デバッグ：候補が消える理由を調査
    debug_counts = {
        "path_error": 0,
        "no_path": 0,
        "distance_rejected": 0,
        "overlap_rejected": 0,
        "accepted": 0,
    }

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
            print(
                f"Failed to generate route for candidate "
                f"{candidate_node}: {e}"
            )
            traceback.print_exc()
    
    route_candidates.sort(key=lambda route: route["total_score"])

    return route_candidates