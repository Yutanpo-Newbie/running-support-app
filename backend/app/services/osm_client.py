import osmnx as ox
import networkx as nx
from app.schemas.route_request import RoutePreferences
from app.utils.geo import convert_to_geojson_linestring
from app.algorithms.turn_detector import (
    detect_turn_points,
    calculate_bearing,
    normalize_angle,
)
from collections import Counter
from app.algorithms.turn_aware_router import (
    shortest_turn_aware_path,
    get_used_edges,
)
from app.algorithms.waypoint_generator import (
    generate_waypoint_pairs,
    group_nearby_waypoints,
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


# =====================================
# 16.11 経由地点候補の方向分散
# =====================================

def select_direction_balanced_candidates(
    candidates: list[dict],
    start_lat: float,
    start_lon: float,
    max_candidates: int,
) -> list[dict]:
    """
    距離条件を満たす候補を8方向へ分類し、
    各方向から順番に選択する。

    各方向の内部では距離誤差が小さい順にする。
    候補が少ない方向があっても、他の方向から
    補充して最大max_candidates件を返す。
    """

    if max_candidates <= 0:
        return []

    direction_names = [
        "N", "NE", "E", "SE",
        "S", "SW", "W", "NW",
    ]

    direction_buckets = {
        direction: []
        for direction in direction_names
    }

    for candidate in candidates:

        bearing = calculate_bearing(
            start_lat,
            start_lon,
            candidate["lat"],
            candidate["lon"],
        )

        direction_index = int(
            (bearing + 22.5) // 45
        ) % 8

        direction = direction_names[
            direction_index
        ]

        direction_buckets[direction].append(
            candidate
        )

    # 各方向の候補を距離誤差順に並べる
    for direction in direction_names:
        direction_buckets[direction].sort(
            key=lambda candidate: (
                candidate["distance_error_m"],
                str(candidate["node_id"]),
            )
        )

    print(
        "\n=== WAYPOINT DIRECTION POOL ===",
        flush=True,
    )

    for direction in direction_names:
        print(
            f"{direction}:",
            len(direction_buckets[direction]),
            flush=True,
        )

    # 方向ごとに1件ずつ取る操作を繰り返す
    selected = []
    next_indexes = {
        direction: 0
        for direction in direction_names
    }

    while len(selected) < max_candidates:

        added_in_round = False

        for direction in direction_names:

            index = next_indexes[direction]
            bucket = direction_buckets[direction]

            if index >= len(bucket):
                continue

            selected.append(bucket[index])
            next_indexes[direction] += 1
            added_in_round = True

            if len(selected) >= max_candidates:
                break

        # 全方向の候補を使い切った場合
        if not added_in_round:
            break

    print(
        "DIRECTION BALANCED CANDIDATES:",
        len(selected),
        flush=True,
    )

    return selected


def get_candidate_nodes_by_distance(
    graph,
    start_node,
    target_distance_m: float,
    tolerance_m: float = 200,
    max_candidates: int = 10,
    avoid_steps: bool = False,
    direction_balanced: bool = False,
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

    # =====================================
    # 16.11 経由地点の選択方式
    # =====================================

    # 従来方式：
    # 距離誤差が小さい順に選択
    if not direction_balanced:

        candidates.sort(
            key=lambda node: (
                node["distance_error_m"],
                str(node["node_id"]),
            )
        )

        return candidates[:max_candidates]

    # 新方式：
    # 8方向に分散して選択
    start_node_data = graph.nodes[start_node]

    start_lat = start_node_data["y"]
    start_lon = start_node_data["x"]

    return select_direction_balanced_candidates(
        candidates=candidates,
        start_lat=start_lat,
        start_lon=start_lon,
        max_candidates=max_candidates,
    )


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



def convert_path_to_detailed_coordinates(
    graph,
    path: list,
) -> list[dict]:
    """
    OSMエッジのgeometryを使って、
    道路の曲線を含む表示用座標列を生成する。

    戻り値:
    [{"lat": ..., "lon": ...}, ...]
    """

    if not path:
        return []

    if len(path) == 1:
        node = graph.nodes[path[0]]
        return [{
            "lat": node["y"],
            "lon": node["x"],
        }]

    coordinates = []

    for u, v in zip(path[:-1], path[1:]):

        # u → v のエッジ情報を取得
        edge_data = graph.get_edge_data(u, v)

        if not edge_data:
            raise ValueError(
                f"エッジが存在しません: {u} → {v}"
            )

        # 複数の並行エッジがある場合は
        # lengthが最小のものを採用
        edge = min(
            edge_data.values(),
            key=lambda data: float(
                data.get("length", float("inf"))
            ),
        )

        geometry = edge.get("geometry")

        if geometry is not None:

            # Shapely座標は (経度, 緯度)
            edge_coords = list(geometry.coords)

            # geometryの向きが進行方向と
            # 一致するように調整
            start_node = graph.nodes[u]

            start_lon = start_node["x"]
            start_lat = start_node["y"]

            first = edge_coords[0]
            last = edge_coords[-1]

            first_distance = (
                (first[0] - start_lon) ** 2
                + (first[1] - start_lat) ** 2
            )

            last_distance = (
                (last[0] - start_lon) ** 2
                + (last[1] - start_lat) ** 2
            )

            if last_distance < first_distance:
                edge_coords.reverse()

        else:
            # geometryがないエッジは
            # 始点・終点を直線で結ぶ
            start_node = graph.nodes[u]
            end_node = graph.nodes[v]

            edge_coords = [
                (start_node["x"], start_node["y"]),
                (end_node["x"], end_node["y"]),
            ]

        # 隣接エッジの重複座標を除く
        if coordinates:
            edge_coords = edge_coords[1:]

        for lon, lat in edge_coords:
            coordinates.append({
                "lat": lat,
                "lon": lon,
            })

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
    diversity_edges=None,
    diversity_penalty_factor: float = 1.5,
    avoid_tight_uturns: bool = False,
    tight_uturn_penalty_m: float = 200.0,
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
            diversity_edges=diversity_edges,
            diversity_penalty_factor=diversity_penalty_factor,
            avoid_tight_uturns=avoid_tight_uturns,
            tight_uturn_penalty_m=tight_uturn_penalty_m,
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
            diversity_edges=diversity_edges,
            diversity_penalty_factor=diversity_penalty_factor,
            avoid_tight_uturns=avoid_tight_uturns,
            tight_uturn_penalty_m=tight_uturn_penalty_m,
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
            diversity_edges=diversity_edges,
            diversity_penalty_factor=diversity_penalty_factor,
            avoid_tight_uturns=avoid_tight_uturns,
            tight_uturn_penalty_m=tight_uturn_penalty_m,
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
    

def detect_junction_turn_points(
    graph,
    path: list[int],
    coordinates: list[dict],
) -> list[dict]:
    """
    交差点における進行方向の選択を考慮して
    ナビゲーション用の曲がり角を検出する。

    1. 従来の角度判定（30度超）を実行
    2. 進行可能な別の道路があるか確認
    3. 選択した道が明確に道なりなら案内を省略
    """

    if len(path) < 3:
        return []

    if len(path) != len(coordinates):
        raise ValueError(
            "pathとcoordinatesの長さが一致しません"
        )

    turn_points = []

    for i in range(1, len(path) - 1):

        prev_node = path[i - 1]
        current_node = path[i]
        next_node = path[i + 1]

        # まず既存の角度判定
        local_coordinates = coordinates[i - 1:i + 2]

        detected = detect_turn_points(
            local_coordinates
        )

        if not detected:
            continue

        turn = detected[0]

        # 現在ノードから進める道路
        # 戻ってきた方向は選択肢に含めない
        possible_next_nodes = (
            set(graph.successors(current_node))
            - {prev_node, current_node}
        )

        # 進行方向の選択肢が1つしかない場合、
        # 道なりとみなして案内を省略
        if len(possible_next_nodes) < 2:
            continue

        if next_node not in possible_next_nodes:
            continue

        prev = graph.nodes[prev_node]
        current = graph.nodes[current_node]
        next_data = graph.nodes[next_node]

        # 交差点に入ってくる方向
        incoming_bearing = calculate_bearing(
            prev["y"], prev["x"],
            current["y"], current["x"],
        )

        # 実際に進む方向
        chosen_bearing = calculate_bearing(
            current["y"], current["x"],
            next_data["y"], next_data["x"],
        )

        chosen_angle = abs(normalize_angle(
            chosen_bearing - incoming_bearing
        ))

        # その他の選択肢の曲がり角度
        alternative_angles = []

        for candidate_node in possible_next_nodes:

            if candidate_node == next_node:
                continue

            candidate = graph.nodes[candidate_node]

            candidate_bearing = calculate_bearing(
                current["y"], current["x"],
                candidate["y"], candidate["x"],
            )

            candidate_angle = abs(normalize_angle(
                candidate_bearing - incoming_bearing
            ))

            alternative_angles.append(candidate_angle)

        if not alternative_angles:
            continue

        # 選んだ道路が比較的まっすぐで、
        # 他の道路より明確に自然な進行方向なら
        # 道なりとみなし案内を省略
        NATURAL_TURN_MAX_ANGLE = 60.0
        NATURAL_TURN_MARGIN = 30.0

        is_natural_continuation = (
            chosen_angle <= NATURAL_TURN_MAX_ANGLE
            and all(
                alternative_angle
                >= chosen_angle + NATURAL_TURN_MARGIN
                for alternative_angle in alternative_angles
            )
        )

        if is_natural_continuation:
            continue

        # 進行方向を選ぶ必要があると判断
        turn["path_index"] = i
        turn_points.append(turn)

    return turn_points


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

    print(
        "\n=== STEP 16.12 CALL DEBUG ===",
        "target_distance_km =", target_distance_km,
        "normalized_nodes =", len(normalized_nodes),
        flush=True,
    )


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
        target_distance_m=target_distance_km * 1000,
        distance_tolerance_ratio=0.25,
    )



    # =====================================
    # STEP 16.29 修正版
    # 160組の経由地点Aのグループ分布
    # =====================================

    from collections import Counter

    # 既存の経路生成処理と同じ形式で
    # 経由地点A・BのノードIDを取得する
    pair_a_nodes = []

    for pair in waypoint_pairs:

        if isinstance(pair, dict):
            waypoint_a = pair.get("waypoint_a")

        elif isinstance(pair, (tuple, list)):
            waypoint_a = pair[0]

        else:
            raise TypeError(
                f"Unexpected waypoint pair type: {type(pair)}"
            )

        # ノードIDが辞書で格納されている場合
        if isinstance(waypoint_a, dict):
            waypoint_a = waypoint_a.get(
                "node_id",
                waypoint_a.get("id"),
            )

        if waypoint_a is None:
            raise ValueError(
                f"Cannot extract waypoint A: {pair}"
            )

        pair_a_nodes.append(waypoint_a)

    # 実際に経由地点Aとして使われるノードを
    # 15m以内でグループ化
    waypoint_groups = group_nearby_waypoints(
        graph=graph,
        candidate_nodes=pair_a_nodes,
        threshold_m=15.0,
    )

    node_to_group = {}

    for group_id, nodes in enumerate(waypoint_groups):
        for node in nodes:
            node_to_group[node] = group_id

    a_group_counts = Counter(
        node_to_group[node]
        for node in pair_a_nodes
    )

    print(
        "\n=== SELECTED PAIR GROUP DISTRIBUTION ===",
        flush=True,
    )

    print(
        "total_pairs =",
        len(waypoint_pairs),
        "unique_A_groups =",
        len(a_group_counts),
        flush=True,
    )

    for group_id, count in a_group_counts.most_common():
        print(
            "PAIR A GROUP:",
            group_id,
            "pairs =",
            count,
            "nodes =",
            waypoint_groups[group_id],
            flush=True,
        )

    print(
        "=== SELECTED PAIR GROUP DISTRIBUTION END ===",
        flush=True,
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


    # =====================================
    # STEP 16.30
    # グループ別の品質フィルタ診断
    # =====================================

    from collections import defaultdict, Counter

    first_pass_group_stats = defaultdict(Counter)

    def record_group_result(waypoint_a, reason):
        group_id = node_to_group.get(waypoint_a, -1)
        first_pass_group_stats[group_id][reason] += 1


    # -------------------------------------
    # START → A → B → START
    # -------------------------------------

    # STEP 16.31：曲がり角間隔の比較集計
    interval_comparison_stats = Counter()
    interval_comparison_samples = []

    # STEP 16.32：品質条件の比較用
    quality_sensitivity_candidates = []

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

            # STEP 16.30：グループ別除外理由を記録
            record_group_result(waypoint_a, "distance")

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

        turn_points = detect_junction_turn_points(
            graph=graph,
            path=path,
            coordinates=coordinates,
        )

        turn_count = len(turn_points)

        # =====================================
        # 歩道優先ルートの曲がり角診断
        # =====================================

        if debug_counts["loop_entered"] <= 3:
            print(
                "\n=== TURN POINT DETAIL DEBUG ===",
                flush=True,
            )

            print(
                "route_distance_km =",
                distance_km,
                "turn_count =",
                turn_count,
                flush=True,
            )

            for index, point in enumerate(
                turn_points[:15],
                start=1,
            ):
                print(
                    f"TURN {index}:",
                    "direction =", point.get("direction"),
                    "lat =", point.get("lat"),
                    "lon =", point.get("lon"),
                    flush=True,
                )

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



        # =====================================
        # STEP 16.31
        # 直線距離と道路距離による判定比較
        # =====================================

        route_short_count = 0

        for i in range(len(turn_points) - 1):
            interval_m = calculate_turn_interval_along_path(
                graph=graph,
                path=path,
                start_index=turn_points[i]["path_index"],
                end_index=turn_points[i + 1]["path_index"],
            )

            if interval_m < 50:
                route_short_count += 1

        interval_comparison_stats["checked"] += 1

        if route_short_count != short_turn_interval_count:
            interval_comparison_stats["changed"] += 1

        # 現在の短間隔判定では除外されるが、
        # 道路距離なら通過する候補
        if (
            turn_density <= 8.0
            and short_turn_interval_count > 4
            and route_short_count <= 4
        ):
            interval_comparison_stats["rescued"] += 1

            if len(interval_comparison_samples) < 10:
                interval_comparison_samples.append({
                    "group": node_to_group.get(waypoint_a, -1),
                    "A": waypoint_a,
                    "B": waypoint_b,
                    "distance_km": distance_km,
                    "turn_density": round(turn_density, 2),
                    "straight_short": short_turn_interval_count,
                    "route_short": route_short_count,
                })

        # ---------------------------------
        # 曲がりすぎるルートを除外
        # ---------------------------------

        MAX_TURN_DENSITY = 8.0
        MAX_SHORT_TURN_INTERVALS = 5


        # =====================================
        # STEP 16.32
        # 除外前の候補を診断用に保存
        # =====================================

        quality_sensitivity_candidates.append({
            "path": path,
            "distance_km": distance_km,
            "turn_density": turn_density,
            "short_intervals": short_turn_interval_count,
            "waypoint_a": waypoint_a,
            "waypoint_b": waypoint_b,
        })


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
            record_group_result(waypoint_a, "turn_density")
            continue

        if (
            short_turn_interval_count
            > MAX_SHORT_TURN_INTERVALS
        ):
            debug_counts["short_turn_rejected"] += 1
            record_group_result(waypoint_a, "short_turns")
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



        # =====================================
        # 15.36 STEP2
        # 地図表示用の詳細座標を生成
        # =====================================

        detailed_coordinates = (
            convert_path_to_detailed_coordinates(
                graph=graph,
                path=path,
            )
        )

        # 青いルートの表示には詳細座標を使う
        loop_geometry = convert_to_geojson_linestring(
            detailed_coordinates
        )

        print(
            "ROUTE GEOMETRY DEBUG:",
            "node_points =", len(coordinates),
            "detailed_points =", len(detailed_coordinates),
            flush=True,
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

                "turn_points": 
                    turn_points,

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
        record_group_result(waypoint_a, "accepted")


    print(
        "\n=== FIRST PASS TURN INTERVAL COMPARISON ===",
        flush=True,
    )

    print(
        "distance_passed_checked =",
        interval_comparison_stats["checked"],
        "changed =",
        interval_comparison_stats["changed"],
        "rescued =",
        interval_comparison_stats["rescued"],
        flush=True,
    )

    for sample in interval_comparison_samples:
        print("RESCUED CANDIDATE:", sample, flush=True)

    print(
        "=== FIRST PASS TURN INTERVAL COMPARISON END ===",
        flush=True,
    )



    # =====================================
    # STEP 16.32
    # 品質条件の感度分析
    # =====================================

    print(
        "\n=== QUALITY THRESHOLD SENSITIVITY ===",
        flush=True,
    )

    scenarios = [
        (8.0, 4),   # 現在の条件
        (8.0, 5),   # 短間隔を1回だけ緩和
        (9.0, 4),   # 曲がり角密度を緩和
        (9.0, 5),
        (10.0, 6),
    ]

    for max_density, max_short in scenarios:

        passing = [
            route
            for route in quality_sensitivity_candidates
            if (
                route["turn_density"] <= max_density
                and route["short_intervals"] <= max_short
            )
        ]

        # 同じ道路エッジ集合を使う候補をまとめる
        unique_paths = {}

        for route in passing:
            edge_key = frozenset(
                tuple(sorted((u, v)))
                for u, v in zip(
                    route["path"][:-1],
                    route["path"][1:],
                )
            )
            unique_paths.setdefault(edge_key, route)

        print(
            "SCENARIO:",
            f"density<={max_density}",
            f"short<={max_short}",
            "passing =", len(passing),
            "unique_paths =", len(unique_paths),
            "unique_A =", len({
                route["waypoint_a"]
                for route in passing
            }),
            flush=True,
        )


        # =====================================
        # STEP 16.33
        # 品質条件ごとに最大何本の
        # 多様なルートが選べるか調べる
        # =====================================

        from itertools import combinations

        unique_routes = list(unique_paths.values())

        # 各ルートの道路エッジ集合
        edge_sets = [
            get_used_edges(route["path"])
            for route in unique_routes
        ]

        def overlap_between(i, j):
            edges_a = edge_sets[i]
            edges_b = edge_sets[j]

            smaller_count = min(
                len(edges_a),
                len(edges_b),
            )

            if smaller_count == 0:
                return 0.0

            return (
                len(edges_a & edges_b)
                / smaller_count
            )

        # 3本→2本の順に、
        # 全組み合わせで重複60%未満を調査
        best_combination = None

        for count in (3, 2):
            valid_combinations = []

            for indexes in combinations(
                range(len(unique_routes)),
                count,
            ):
                if all(
                    overlap_between(i, j) < 0.60
                    for i, j in combinations(indexes, 2)
                ):
                    valid_combinations.append(indexes)

            if valid_combinations:
                # 診断用の暫定順位
                # 目標距離との差が小さい組を優先
                best_combination = min(
                    valid_combinations,
                    key=lambda indexes: sum(
                        abs(
                            unique_routes[i]["distance_km"]
                            - target_distance_km
                        )
                        for i in indexes
                    ),
                )
                break

        if best_combination is None:
            best_combination = (
                (0,) if unique_routes else ()
            )

        print(
            "DIVERSITY SCENARIO:",
            f"density<={max_density}",
            f"short<={max_short}",
            "max_diverse_routes =",
            len(best_combination),
            flush=True,
        )

        for i in best_combination:
            route = unique_routes[i]

            print(
                "  DIVERSE CANDIDATE:",
                "distance =", round(route["distance_km"], 2),
                "turn_density =", round(route["turn_density"], 2),
                "short_intervals =", route["short_intervals"],
                "A =", route["waypoint_a"],
                "B =", route["waypoint_b"],
                flush=True,
            )

        for i, j in combinations(best_combination, 2):
            print(
                "  DIVERSE PAIR OVERLAP:",
                f"{overlap_between(i, j):.1%}",
                flush=True,
            )


    print(
        "=== QUALITY THRESHOLD SENSITIVITY END ===",
        flush=True,
    )


    
    # =====================================
    # 16.16 別方向の経由地点ペアによる第2探索
    # =====================================

    if route_candidates:

        # 第1探索で最も評価の良いルート
        reference_route = min(
            route_candidates,
            key=lambda route: route["total_score"],
        )

        reference_edges = get_used_edges(
            reference_route["path"]
        )

        start_data = graph.nodes[start_node]
        ref_a_data = graph.nodes[
            reference_route["waypoint_a"]
        ]

        reference_bearing = calculate_bearing(
            start_data["y"],
            start_data["x"],
            ref_a_data["y"],
            ref_a_data["x"],
        )

        # ---------------------------------
        # 基準ルートと異なる方向のAを選ぶ
        # ---------------------------------

        direction_buckets = {
            sector: []
            for sector in range(8)
        }

        for waypoint_a, waypoint_b in waypoint_pairs:

            if (
                waypoint_a
                == reference_route["waypoint_a"]
            ):
                continue

            a_data = graph.nodes[waypoint_a]

            bearing = calculate_bearing(
                start_data["y"],
                start_data["x"],
                a_data["y"],
                a_data["x"],
            )

            angle_difference = abs(
                normalize_angle(
                    bearing - reference_bearing
                )
            )

            # 出発方向が60度以上異なる候補
            if angle_difference < 60.0:
                continue

            sector = int(
                (bearing + 22.5) // 45
            ) % 8

            direction_buckets[sector].append(
                (
                    angle_difference,
                    waypoint_a,
                    waypoint_b,
                )
            )

        # 各方向内で基準ルートとの
        # 方向差が大きいものを優先
        for sector in range(8):
            direction_buckets[sector].sort(
                key=lambda item: (
                    -item[0],
                    str(item[1]),
                    str(item[2]),
                )
            )

        # 方向を分散して最大16組を選択
        alternative_pairs = []
        indexes = {
            sector: 0
            for sector in range(8)
        }

        MAX_ALTERNATIVE_PAIRS = 16

        while (
            len(alternative_pairs)
            < MAX_ALTERNATIVE_PAIRS
        ):

            added = False

            for sector in range(8):

                index = indexes[sector]
                bucket = direction_buckets[sector]

                if index >= len(bucket):
                    continue

                _, waypoint_a, waypoint_b = (
                    bucket[index]
                )

                alternative_pairs.append(
                    (waypoint_a, waypoint_b)
                )

                indexes[sector] += 1
                added = True

                if (
                    len(alternative_pairs)
                    >= MAX_ALTERNATIVE_PAIRS
                ):
                    break

            if not added:
                break
    

        print(
            "\n=== FIRST PASS GROUP REJECTION DEBUG ===",
            flush=True,
        )

        total_recorded = 0

        for group_id in sorted(first_pass_group_stats):

            stats = first_pass_group_stats[group_id]
            total = sum(stats.values())
            total_recorded += total

            print(
                "GROUP:",
                group_id,
                "total =", total,
                "accepted =", stats["accepted"],
                "distance =", stats["distance"],
                "turn_density =", stats["turn_density"],
                "short_turns =", stats["short_turns"],
                "backtrack =", stats["backtrack"],
                "overlap =", stats["overlap"],
                "path_error =", stats["path_error"],
                "other =", stats["other"],
                "steps =", stats["steps"],
                "no_path =", stats["no_path"],
                flush=True,
            )

        print(
            "TOTAL RECORDED:",
            total_recorded,
            "/",
            len(waypoint_pairs),
            flush=True,
        )

        print(
            "=== FIRST PASS GROUP REJECTION DEBUG END ===",
            flush=True,
        )

        # =====================================
        # STEP 16.25
        # 第1探索の経由地点集中度を調査
        # =====================================

        from collections import Counter

        print(
            "\n=== FIRST PASS WAYPOINT DIVERSITY ===",
            flush=True,
        )

        a_counts = Counter()
        b_counts = Counter()
        pair_counts = Counter()

        unique_paths = set()

        for route in route_candidates:

            waypoint_a = route.get("waypoint_a")
            waypoint_b = route.get("waypoint_b")

            a_counts[waypoint_a] += 1
            b_counts[waypoint_b] += 1
            pair_counts[(waypoint_a, waypoint_b)] += 1

            unique_paths.add(tuple(route["path"]))

        print(
            "accepted_candidates =",
            len(route_candidates),
            flush=True,
        )

        print(
            "unique_paths =",
            len(unique_paths),
            flush=True,
        )

        print(
            "unique_waypoint_A =",
            len(a_counts),
            flush=True,
        )

        print(
            "unique_waypoint_B =",
            len(b_counts),
            flush=True,
        )

        print(
            "WAYPOINT A DISTRIBUTION:",
            a_counts.most_common(10),
            flush=True,
        )

        print(
            "WAYPOINT B DISTRIBUTION:",
            b_counts.most_common(10),
            flush=True,
        )

        print(
            "WAYPOINT PAIR DISTRIBUTION:",
            pair_counts.most_common(10),
            flush=True,
        )

        print(
            "=== FIRST PASS WAYPOINT DIVERSITY END ===",
            flush=True,
        )

    
        # =====================================
        # STEP 16.28
        # 採用候補の経由地点グループ集中度
        # =====================================

        from collections import Counter

        accepted_a_nodes = [
            route["waypoint_a"]
            for route in route_candidates
        ]

        accepted_groups = group_nearby_waypoints(
            graph=graph,
            candidate_nodes=accepted_a_nodes,
            threshold_m=15.0,
        )

        print(
            "\n=== ACCEPTED WAYPOINT CLUSTER DEBUG ===",
            flush=True,
        )

        print(
            "accepted_routes =",
            len(route_candidates),
            "unique_A_nodes =",
            len(set(accepted_a_nodes)),
            "A_clusters =",
            len(accepted_groups),
            flush=True,
        )

        node_to_cluster = {}

        for group_id, nodes in enumerate(accepted_groups):
            for node in nodes:
                node_to_cluster[node] = group_id

        cluster_counts = Counter(
            node_to_cluster[node]
            for node in accepted_a_nodes
        )

        for group_id, nodes in enumerate(accepted_groups):
            print(
                "ACCEPTED A CLUSTER:",
                "group =", group_id,
                "routes =", cluster_counts[group_id],
                "nodes =", nodes,
                flush=True,
            )

        print(
            "=== ACCEPTED WAYPOINT CLUSTER DEBUG END ===",
            flush=True,
        )


    
        # =====================================
        # STEP 16.26
        # 採用候補の経由地点Aの近接調査
        # =====================================

        print(
            "\n=== WAYPOINT A PROXIMITY DEBUG ===",
            flush=True,
        )

        waypoint_a_nodes = sorted(
            {
                route.get("waypoint_a")
                for route in route_candidates
                if route.get("waypoint_a") in graph.nodes
            }
        )

        for i in range(len(waypoint_a_nodes)):

            node_a = waypoint_a_nodes[i]
            data_a = graph.nodes[node_a]

            for j in range(i + 1, len(waypoint_a_nodes)):

                node_b = waypoint_a_nodes[j]
                data_b = graph.nodes[node_b]

                distance_m = calculate_distance_between_points(
                    data_a["y"],
                    data_a["x"],
                    data_b["y"],
                    data_b["x"],
                )

                if distance_m <= 30.0:

                    print(
                        "NEARBY WAYPOINT A:",
                        node_a,
                        node_b,
                        "distance_m =",
                        round(distance_m, 2),
                        flush=True,
                    )

        print(
            "=== WAYPOINT A PROXIMITY DEBUG END ===",
            flush=True,
        )


        print(
            "\n=== SECOND PASS DIVERSITY DEBUG ===",
            flush=True,
        )

        print(
            "reference_distance =",
            reference_route["distance_km"],
            "reference_A =",
            reference_route["waypoint_a"],
            "alternative_pairs =",
            len(alternative_pairs),
            flush=True,
        )

        second_pass_attempted = 0
        second_pass_quality_passed = 0
        second_pass_diverse_passed = 0
        nearby_turn_debug_count = 0
        second_pass_rejected = {
            "path_error": 0,
            "no_path": 0,
            "distance": 0,
            "backtrack": 0,
            "steps": 0,
            "overlap": 0,
            "backtrack_ratio": 0,
            "turn_density": 0,
            "short_turns": 0,
            "similarity": 0,
        }

        # 第2探索で採用した経路も管理
        diversity_reference_sets = [
            reference_edges
        ]

        # ---------------------------------
        # 弱めのペナルティから順に試す
        # ---------------------------------

        for penalty_factor in [1.5, 2.0]:

            if second_pass_diverse_passed >= 2:
                break

            for waypoint_a, waypoint_b in alternative_pairs:

                if second_pass_diverse_passed >= 2:
                    break

                second_pass_attempted += 1

                # 採用済み経路の道路集合
                diversity_edges = set()

                for edges in diversity_reference_sets:
                    diversity_edges.update(edges)

                try:
                    path = create_multi_waypoint_loop(
                        graph=graph,
                        start_node=start_node,
                        waypoint_a=waypoint_a,
                        waypoint_b=waypoint_b,
                        use_turn_aware=True,
                        diversity_edges=diversity_edges,
                        diversity_penalty_factor=penalty_factor,
                    )

                except Exception as error:
                    second_pass_rejected["path_error"] += 1
                    print(
                        "SECOND PASS PATH ERROR:",
                        repr(error),
                        flush=True,
                    )
                    continue

                if not path:
                    second_pass_rejected["no_path"] += 1
                    continue

                # ---------------------------------
                # 既存の品質条件を再評価
                # ---------------------------------

                distance_km = calculate_path_length_km(
                    graph,
                    path,
                )

                distance_error_km = abs(
                    distance_km - target_distance_km
                )

                if (
                    distance_error_km
                    > target_distance_km * 0.25
                ):
                    second_pass_rejected["distance"] += 1
                    continue

                if count_immediate_backtracks(path) > 0:
                    second_pass_rejected["backtrack"] += 1
                    continue

                if calculate_steps_distance_m(
                    graph, path
                ) > 0:
                    second_pass_rejected["steps"] += 1
                    continue

                overlap_ratio = calculate_edge_overlap_ratio(
                    path
                )

                if overlap_ratio >= 0.20:
                    second_pass_rejected["overlap"] += 1
                    continue

                backtrack_ratio = calculate_backtrack_distance_ratio(
                    graph,
                    path,
                )

                if backtrack_ratio >= 0.15:
                    second_pass_rejected["backtrack_ratio"] += 1
                    continue

                coordinates = convert_path_to_coordinates(
                    graph,
                    path,
                )

                turn_points = detect_junction_turn_points(
                    graph=graph,
                    path=path,
                    coordinates=coordinates,
                )

                turn_count = len(turn_points)

                turn_density = (
                    turn_count / distance_km
                    if distance_km > 0
                    else 0.0
                )

                short_turn_interval_count = 0

                for i in range(len(turn_points) - 1):

                    interval_m = calculate_turn_interval_along_path(
                        graph=graph,
                        path=path,
                        start_index=turn_points[i]["path_index"],
                        end_index=turn_points[i + 1]["path_index"],
                    )

                    if interval_m < 50:
                        short_turn_interval_count += 1

                # =====================================
                # 16.19 曲がり角間隔の計算方法を比較
                # =====================================

                straight_short_count = 0
                route_short_count = 0

                for i in range(len(turn_points) - 1):

                    # 直線距離
                    straight_m = calculate_distance_between_points(
                        turn_points[i]["lat"],
                        turn_points[i]["lon"],
                        turn_points[i + 1]["lat"],
                        turn_points[i + 1]["lon"],
                    )

                    # 道路に沿った距離
                    route_m = calculate_turn_interval_along_path(
                        graph=graph,
                        path=path,
                        start_index=turn_points[i]["path_index"],
                        end_index=turn_points[i + 1]["path_index"],
                    )

                    if straight_m < 50:
                        straight_short_count += 1

                    if route_m < 50:
                        route_short_count += 1

                # 距離条件を通過した候補のうち
                # 最初の5件のみ表示
                if not hasattr(
                    generate_multi_waypoint_route_candidates,
                    "_step1619_debug_count",
                ):
                    generate_multi_waypoint_route_candidates._step1619_debug_count = 0

                if (
                    generate_multi_waypoint_route_candidates._step1619_debug_count
                    < 5
                ):
                    print(
                        "TURN INTERVAL COMPARISON:",
                        f"distance={distance_km:.2f}km",
                        f"turns={turn_count}",
                        f"straight_short={straight_short_count}",
                        f"route_short={route_short_count}",
                        f"current_short={short_turn_interval_count}",
                        flush=True,
                    )

                    generate_multi_waypoint_route_candidates._step1619_debug_count += 1

                # =====================================
                # 16.22 小さなU字型経路の診断
                # =====================================

                tight_uturns = detect_tight_uturns(
                    graph=graph,
                    path=path,
                    turn_points=turn_points,
                    max_interval_m=20.0,
                    min_net_angle=150.0,
                )

                if tight_uturns:

                    print(
                        "TIGHT UTURN DETECTED:",
                        "A =", waypoint_a,
                        "B =", waypoint_b,
                        "count =", len(tight_uturns),
                        "details =", tight_uturns[:3],
                        flush=True,
                    )

                if turn_density > 8.0:
                    second_pass_rejected["turn_density"] += 1
                    continue


                if short_turn_interval_count > 5:

                    second_pass_rejected["short_turns"] += 1

                    # ---------------------------------
                    # 16.20 近接する右左折の原因調査
                    # ---------------------------------

                    if nearby_turn_debug_count < 5:

                        print(
                            "\n=== NEARBY TURN INVESTIGATION ===",
                            flush=True,
                        )

                        print(
                            "route_distance_km =",
                            round(distance_km, 2),
                            "turn_count =",
                            turn_count,
                            "short_intervals =",
                            short_turn_interval_count,
                            "A =",
                            waypoint_a,
                            "B =",
                            waypoint_b,
                            flush=True,
                        )

                        debug_nearby_turn_groups(
                            graph=graph,
                            path=path,
                            turn_points=turn_points,
                            threshold_m=15.0,
                        )

                        nearby_turn_debug_count += 1

                    continue


                second_pass_quality_passed += 1

                # ---------------------------------
                # 他ルートとの重複率を確認
                # ---------------------------------

                candidate_edges = get_used_edges(
                    path
                )

                is_diverse = True

                for existing_edges in diversity_reference_sets:

                    smaller_count = min(
                        len(candidate_edges),
                        len(existing_edges),
                    )

                    shared_edges = len(
                        candidate_edges & existing_edges
                    )

                    overlap = (
                        shared_edges / smaller_count
                        if smaller_count > 0
                        else 0.0
                    )

                    if overlap >= 0.60:
                        is_diverse = False
                        break

                if not is_diverse:
                    second_pass_rejected["similarity"] += 1
                    continue

                # ---------------------------------
                # 最終スコア計算に必要な情報
                # ---------------------------------

                detailed_coordinates = (
                    convert_path_to_detailed_coordinates(
                        graph,
                        path,
                    )
                )

                loop_geometry = convert_to_geojson_linestring(
                    detailed_coordinates
                )

                signals = count_route_signals(
                    graph,
                    path,
                )

                intersections = count_route_intersections(
                    graph,
                    path,
                )

                traffic_score = calculate_route_traffic_score(
                    graph,
                    path,
                )

                # 第1探索と同じ仮スコア
                turn_penalty = (
                    turn_count * 2
                    + turn_density * 3
                    + short_turn_interval_count * 5
                )

                base_score = calculate_total_score(
                    target_distance_km=target_distance_km,
                    actual_distance_km=distance_km,
                    elevation_gain_m=0.0,
                    signals=signals,
                    intersections=intersections,
                    traffic_score=traffic_score,
                    preferences=preferences,
                )

                total_score = (
                    base_score
                    + overlap_ratio * 100
                    + turn_penalty
                )

                # 既存のroute_candidatesと同じ形式
                new_route = {
                    "path": path,
                    "coordinates": coordinates,
                    "geometry": loop_geometry,
                    "turn_points": turn_points,
                    "distance_km": distance_km,
                    "distance_m": round(
                        distance_km * 1000, 2
                    ),
                    "distance_error_m": round(
                        distance_error_km * 1000, 2
                    ),
                    "turn_count": turn_count,
                    "turn_density": turn_density,
                    "short_turn_interval_count":
                        short_turn_interval_count,
                    "turn_penalty": turn_penalty,
                    "immediate_backtracks": 0,
                    "path_nodes": len(path),
                    "waypoint_a": waypoint_a,
                    "waypoint_b": waypoint_b,
                    "overlap_ratio": overlap_ratio,
                    "backtrack_ratio": backtrack_ratio,
                    "elevation_gain_m": 0.0,
                    "signals": signals,
                    "intersections": intersections,
                    "traffic_score": traffic_score,
                    "total_score": total_score,
                }

                route_candidates.append(new_route)

                diversity_reference_sets.append(
                    candidate_edges
                )

                second_pass_diverse_passed += 1

                print(
                    "SECOND PASS ACCEPTED:",
                    "factor =", penalty_factor,
                    "distance =", distance_km,
                    "turns =", turn_count,
                    "A =", waypoint_a,
                    "B =", waypoint_b,
                    flush=True,
                )

        print(
            "SECOND PASS SUMMARY:",
            "attempted =", second_pass_attempted,
            "quality_passed =", second_pass_quality_passed,
            "diverse_passed =", second_pass_diverse_passed,
            flush=True,
        )
        print(
            "SECOND PASS REJECTION DETAILS:",
            second_pass_rejected,
            flush=True,
        )

        print(
            "=== SECOND PASS DIVERSITY DEBUG END ===",
            flush=True,
        )

    # =====================================
    # 16.13 同一道路ルートの重複除去
    # =====================================

    original_count = len(route_candidates)

    unique_routes = {}

    for route in route_candidates:

        # 方向を無視した道路区間の集合
        edge_key = frozenset(
            tuple(sorted((u, v)))
            for u, v in zip(
                route["path"],
                route["path"][1:],
            )
        )

        # 完全に同じ道路区間を使う候補は
        # 距離誤差が小さい方を残す
        if edge_key not in unique_routes:
            unique_routes[edge_key] = route

        else:
            existing = unique_routes[edge_key]

            if (
                route["distance_error_m"]
                < existing["distance_error_m"]
            ):
                unique_routes[edge_key] = route

    route_candidates = list(unique_routes.values())

    print(
        "DEDUPLICATED ROUTES:",
        "before =", original_count,
        "after =", len(route_candidates),
        flush=True,
    )


    # =====================================
    # STEP 16.23
    # 全候補のU字型経路を比較
    # =====================================

    print(
        "\n=== ALL CANDIDATE UTURN DEBUG ===",
        flush=True,
    )

    routes_with_uturn = 0
    routes_without_uturn = 0

    for route_number, route in enumerate(
        route_candidates,
        start=1,
    ):

        tight_uturns = detect_tight_uturns(
            graph=graph,
            path=route["path"],
            turn_points=route["turn_points"],
            max_interval_m=20.0,
            min_net_angle=150.0,
        )

        uturn_count = len(tight_uturns)

        if uturn_count > 0:
            routes_with_uturn += 1
        else:
            routes_without_uturn += 1

        print(
            "CANDIDATE:",
            route_number,
            "distance =",
            round(route["distance_km"], 2),
            "turns =",
            len(route["turn_points"]),
            "tight_uturns =",
            uturn_count,
            "details =",
            tight_uturns[:2],
            flush=True,
        )

    print(
        "UTURN CANDIDATE SUMMARY:",
        "with_uturn =",
        routes_with_uturn,
        "without_uturn =",
        routes_without_uturn,
        flush=True,
    )

    print(
        "=== ALL CANDIDATE UTURN DEBUG END ===",
        flush=True,
    )

    # =====================================
    # STEP 16.24
    # U字型接続路を使わない代替経路の調査
    # =====================================

    import networkx as nx

    print(
        "\n=== UTURN BYPASS DEBUG ===",
        flush=True,
    )

    # 南側の2本の歩道にあるノード
    start_check_node = 9642515182
    end_check_node = 10294556579

    # 問題のU字型接続路
    blocked_edges = [
        (10678345880, 10678345882),
        (10678345882, 10678345881),
    ]

    # 元のgraphは変更しない
    test_graph = graph.copy()

    # 接続路を両方向とも一時的に削除
    for u, v in blocked_edges:
        for a, b in [(u, v), (v, u)]:
            if test_graph.has_edge(a, b):
                if test_graph.is_multigraph():
                    for key in list(
                        test_graph[a][b].keys()
                    ):
                        test_graph.remove_edge(a, b, key)
                else:
                    test_graph.remove_edge(a, b)

    # 元の接続経路
    try:
        original_length = nx.shortest_path_length(
            graph,
            source=start_check_node,
            target=end_check_node,
            weight="length",
        )

        print(
            "ORIGINAL CONNECTION:",
            round(original_length, 1),
            "m",
            flush=True,
        )

    except (nx.NetworkXNoPath, nx.NodeNotFound):
        print(
            "ORIGINAL CONNECTION: no path",
            flush=True,
        )

    # U字型接続路を削除した場合
    try:
        bypass_path = nx.shortest_path(
            test_graph,
            source=start_check_node,
            target=end_check_node,
            weight="length",
        )

        bypass_length = nx.path_weight(
            test_graph,
            bypass_path,
            weight="length",
        ) if not test_graph.is_multigraph() else sum(
            min(
                float(data.get("length", 0))
                for data in test_graph[u][v].values()
            )
            for u, v in zip(
                bypass_path[:-1],
                bypass_path[1:],
            )
        )

        print(
            "BYPASS CONNECTION:",
            round(bypass_length, 1),
            "m",
            "nodes =",
            len(bypass_path),
            flush=True,
        )

    except (nx.NetworkXNoPath, nx.NodeNotFound):
        print(
            "BYPASS CONNECTION: no path",
            flush=True,
        )

    print(
        "=== UTURN BYPASS DEBUG END ===",
        flush=True,
    )



    
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


    # =====================================
    # 16.22 最終候補のU字型経路診断
    # =====================================

    print(
        "\n=== SELECTED ROUTE UTURN DEBUG ===",
        flush=True,
    )

    for route_number, route in enumerate(
        selected_routes,
        start=1,
    ):

        tight_uturns = detect_tight_uturns(
            graph=graph,
            path=route["path"],
            turn_points=route["turn_points"],
            max_interval_m=20.0,
            min_net_angle=150.0,
        )

        print(
            "SELECTED ROUTE:",
            route_number,
            "tight_uturn_count =",
            len(tight_uturns),
            "details =",
            tight_uturns[:5],
            flush=True,
        )

    print(
        "=== SELECTED ROUTE UTURN DEBUG END ===",
        flush=True,
    )



    # =====================================
    # 16.9 歩道・歩行者道利用率の詳細診断
    # =====================================

    print(
        "\n=== PEDESTRIAN ROUTE DEBUG ===",
        flush=True,
    )

    for index, route in enumerate(
        selected_routes,
        start=1,
    ):

        analysis = analyze_pedestrian_route(
            graph=graph,
            path=route["path"],
        )

        print(
            f"\nROUTE {index}:",
            flush=True,
        )

        print(
            "total_distance_m =",
            analysis["total_distance_m"],
            flush=True,
        )

        for category, distance_m in sorted(
            analysis["categories_m"].items(),
            key=lambda item: -item[1],
        ):

            percentage = (
                analysis["categories_pct"][category]
            )

            print(
                f"  {category}:",
                f"{distance_m:.1f}m",
                f"({percentage:.1f}%)",
                flush=True,
            )

    print(
        "=== PEDESTRIAN ROUTE DEBUG END ===\n",
        flush=True,
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


    # =====================================
    # 16.15 多様性ペナルティ係数の比較実験
    # =====================================

    if selected_routes:

        reference_route = selected_routes[0]

        reference_edges = get_used_edges(
            reference_route["path"]
        )

        print(
            "\n=== DIVERSITY PENALTY COMPARISON ===",
            flush=True,
        )

        for penalty_factor in [1.0, 1.5, 2.0, 3.0, 4.0]:

            alternative_path = create_multi_waypoint_loop(
                graph=graph,
                start_node=start_node,
                waypoint_a=reference_route["waypoint_a"],
                waypoint_b=reference_route["waypoint_b"],
                use_turn_aware=True,
                diversity_edges=reference_edges,
                diversity_penalty_factor=penalty_factor,
            )

            if not alternative_path:
                print(
                    f"factor={penalty_factor}: no path",
                    flush=True,
                )
                continue

            alternative_edges = get_used_edges(
                alternative_path
            )

            shared_edges = len(
                reference_edges & alternative_edges
            )

            smaller_count = min(
                len(reference_edges),
                len(alternative_edges),
            )

            overlap = (
                shared_edges / smaller_count
                if smaller_count > 0
                else 0.0
            )

            distance_km = calculate_path_length_km(
                graph,
                alternative_path,
            )

            coordinates = convert_path_to_coordinates(
                graph,
                alternative_path,
            )

            turns = detect_junction_turn_points(
                graph=graph,
                path=alternative_path,
                coordinates=coordinates,
            )

            turn_density = (
                len(turns) / distance_km
                if distance_km > 0
                else 0.0
            )

            short_intervals = 0

            for i in range(len(turns) - 1):
                interval_m = calculate_distance_between_points(
                    turns[i]["lat"],
                    turns[i]["lon"],
                    turns[i + 1]["lat"],
                    turns[i + 1]["lon"],
                )

                if interval_m < 50:
                    short_intervals += 1

            distance_ok = (
                abs(distance_km - target_distance_km)
                <= target_distance_km * 0.25
            )

            quality_ok = (
                distance_ok
                and turn_density <= 8.0
                and short_intervals <= 5
                and calculate_edge_overlap_ratio(
                    alternative_path
                ) < 0.20
                and calculate_backtrack_distance_ratio(
                    graph,
                    alternative_path,
                ) < 0.15
                and calculate_steps_distance_m(
                    graph,
                    alternative_path,
                ) == 0.0
            )

            print(
                f"factor={penalty_factor}",
                f"distance={distance_km:.2f}km",
                f"turns={len(turns)}",
                f"turn_density={turn_density:.2f}",
                f"short_intervals={short_intervals}",
                f"overlap={overlap:.1%}",
                f"backtracks={count_immediate_backtracks(alternative_path)}",
                f"quality_ok={quality_ok}",
                f"diverse_ok={overlap < 0.60}",
                flush=True,
            )

        print(
            "=== DIVERSITY PENALTY COMPARISON END ===",
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


def calculate_turn_interval_along_path(
    graph,
    path: list[int],
    start_index: int,
    end_index: int,
) -> float:
    """
    2つの曲がり角の間を、
    実際の経路に沿った距離[m]で計算する。
    """

    if not (
        0 <= start_index <= end_index < len(path)
    ):
        raise ValueError("path_indexが不正です")

    sub_path = path[start_index:end_index + 1]

    return calculate_path_length_m(
        graph,
        sub_path,
    )

def debug_nearby_turn_groups(
    graph,
    path,
    turn_points,
    threshold_m=15.0,
):
    """
    STEP 16.20

    近接する連続右左折を調査する。

    - 道路に沿った距離で近接判定
    - 近接した曲がり角をグループ化
    - グループ全体の進行方向変化を調査

    この関数は診断専用。
    turn_pointsや経路自体は変更しない。
    """

    if len(turn_points) < 2:
        return

    # ---------------------------------
    # 各曲がり角の経路上の位置を取得
    # ---------------------------------

    indexed_turns = []

    for turn in turn_points:
        index = turn.get("path_index")

        if index is None:
            continue

        if not (0 <= index < len(path)):
            continue

        indexed_turns.append(
            (index, turn)
        )

    indexed_turns.sort(key=lambda item: item[0])

    if len(indexed_turns) < 2:
        print(
            "NEARBY TURN DEBUG: insufficient path_index",
            flush=True,
        )
        return

    # ---------------------------------
    # 曲がり角同士の走行距離を調査
    # ---------------------------------

    thresholds = [5, 10, 15, 20, 30]

    threshold_counts = {
        value: 0 for value in thresholds
    }

    intervals = []

    for i in range(len(indexed_turns) - 1):

        first_index = indexed_turns[i][0]
        second_index = indexed_turns[i + 1][0]

        interval_m = calculate_turn_interval_along_path(
            graph=graph,
            path=path,
            start_index=first_index,
            end_index=second_index,
        )

        intervals.append(interval_m)

        for value in thresholds:
            if interval_m < value:
                threshold_counts[value] += 1

    print(
        "NEARBY TURN THRESHOLD COUNTS:",
        threshold_counts,
        flush=True,
    )

    # ---------------------------------
    # 隣り合う近接曲がり角をグループ化
    # ---------------------------------

    groups = []
    current_group = [indexed_turns[0]]

    for i, interval_m in enumerate(intervals):

        if interval_m < threshold_m:
            current_group.append(
                indexed_turns[i + 1]
            )

        else:
            if len(current_group) >= 2:
                groups.append(current_group)

            current_group = [
                indexed_turns[i + 1]
            ]

    if len(current_group) >= 2:
        groups.append(current_group)

    print(
        "NEARBY TURN GROUPS:",
        len(groups),
        flush=True,
    )

    # ---------------------------------
    # グループ全体の進行方向を調査
    # ---------------------------------

    for group_number, group in enumerate(
        groups[:10], start=1
    ):

        first_index = group[0][0]
        last_index = group[-1][0]

        group_distance_m = (
            calculate_turn_interval_along_path(
                graph,
                path,
                first_index,
                last_index,
            )
        )

        # グループの手前と先で
        # 最大25m程度の区間を取得する
        before_index = first_index
        after_index = last_index

        while before_index > 0:

            distance_m = calculate_turn_interval_along_path(
                graph,
                path,
                before_index - 1,
                first_index,
            )

            before_index -= 1

            if distance_m >= 25.0:
                break

        while after_index < len(path) - 1:

            distance_m = calculate_turn_interval_along_path(
                graph,
                path,
                last_index,
                after_index + 1,
            )

            after_index += 1

            if distance_m >= 25.0:
                break

        # グループの前後の方向変化
        net_angle = None

        if (
            before_index < first_index
            and after_index > last_index
        ):

            before = graph.nodes[
                path[before_index]
            ]

            first = graph.nodes[
                path[first_index]
            ]

            last = graph.nodes[
                path[last_index]
            ]

            after = graph.nodes[
                path[after_index]
            ]

            lat_scale = math.cos(
                math.radians(first["y"])
            )

            dx1 = (
                first["x"] - before["x"]
            ) * lat_scale

            dy1 = (
                first["y"] - before["y"]
            )

            dx2 = (
                after["x"] - last["x"]
            ) * lat_scale

            dy2 = (
                after["y"] - last["y"]
            )

            if (
                math.hypot(dx1, dy1) > 0
                and math.hypot(dx2, dy2) > 0
            ):

                angle1 = math.atan2(dy1, dx1)
                angle2 = math.atan2(dy2, dx2)

                difference = abs(
                    math.degrees(angle2 - angle1)
                )

                net_angle = min(
                    difference,
                    360.0 - difference,
                )

        node_ids = [
            path[index]
            for index, _ in group
        ]

        print(
            "NEARBY TURN GROUP:",
            f"group={group_number}",
            f"turns={len(group)}",
            f"distance_m={group_distance_m:.1f}",
            f"net_angle={net_angle}",
            f"nodes={node_ids}",
            flush=True,
        )


        # =====================================
        # 16.21 近接ノード周辺の道路構造
        # =====================================

        print(
            "NEARBY TURN ROAD DETAILS:",
            flush=True,
        )

        # グループ周辺の経路ノードを取得
        range_start = max(0, first_index - 3)
        range_end = min(
            len(path),
            last_index + 4,
        )

        for path_index in range(
            range_start,
            range_end,
        ):

            node = path[path_index]
            node_data = graph.nodes[node]

            highway_types = set()

            # 前後の道路属性を取得
            if path_index < len(path) - 1:

                next_node = path[path_index + 1]

                edge_data = graph.get_edge_data(
                    node,
                    next_node,
                )

                if edge_data:

                    for data in edge_data.values():

                        highway = data.get(
                            "highway",
                            [],
                        )

                        if isinstance(highway, str):
                            highway_types.add(highway)

                        elif isinstance(
                            highway,
                            (list, tuple, set),
                        ):
                            highway_types.update(highway)

            print(
                "  node_index =", path_index,
                "node_id =", node,
                "lat =", node_data.get("y"),
                "lon =", node_data.get("x"),
                "highway =", sorted(highway_types),
                "in_group =",
                first_index <= path_index <= last_index,
                flush=True,
            )

        print(
            "NEARBY TURN ROAD DETAILS END",
            flush=True,
        )


def detect_tight_uturns(
    graph,
    path,
    turn_points,
    max_interval_m=20.0,
    min_net_angle=150.0,
    direction_window_m=25.0,
):
    """
    STEP 16.22

    近距離で進行方向が大きく反転する
    U字型経路を検出する。

    診断専用：
    経路の変更や候補の除外は行わない。
    """

    if len(path) < 3 or len(turn_points) < 2:
        return []

    indexed_turns = []

    for turn in turn_points:
        index = turn.get("path_index")

        if (
            isinstance(index, int)
            and 0 < index < len(path) - 1
        ):
            indexed_turns.append((index, turn))

    indexed_turns.sort(key=lambda item: item[0])

    results = []

    for i in range(len(indexed_turns) - 1):

        first_index = indexed_turns[i][0]
        last_index = indexed_turns[i + 1][0]

        if first_index >= last_index:
            continue

        interval_m = calculate_turn_interval_along_path(
            graph,
            path,
            first_index,
            last_index,
        )

        if interval_m > max_interval_m:
            continue

        # 曲がり角の手前で約25m進んだ地点を探す
        before_index = first_index

        while before_index > 0:

            before_index -= 1

            distance_m = calculate_turn_interval_along_path(
                graph,
                path,
                before_index,
                first_index,
            )

            if distance_m >= direction_window_m:
                break

        # 曲がり角の先で約25m進んだ地点を探す
        after_index = last_index

        while after_index < len(path) - 1:

            after_index += 1

            distance_m = calculate_turn_interval_along_path(
                graph,
                path,
                last_index,
                after_index,
            )

            if distance_m >= direction_window_m:
                break

        if (
            before_index == first_index
            or after_index == last_index
        ):
            continue

        before = graph.nodes[path[before_index]]
        first = graph.nodes[path[first_index]]
        last = graph.nodes[path[last_index]]
        after = graph.nodes[path[after_index]]

        latitude = (
            first["y"] + last["y"]
        ) / 2.0

        lat_scale = math.cos(math.radians(latitude))

        # 進入方向
        dx1 = (
            first["x"] - before["x"]
        ) * lat_scale

        dy1 = first["y"] - before["y"]

        # 退出方向
        dx2 = (
            after["x"] - last["x"]
        ) * lat_scale

        dy2 = after["y"] - last["y"]

        if (
            math.hypot(dx1, dy1) < 1e-12
            or math.hypot(dx2, dy2) < 1e-12
        ):
            continue

        angle1 = math.atan2(dy1, dx1)
        angle2 = math.atan2(dy2, dx2)

        angle_difference = abs(
            math.degrees(angle2 - angle1)
        )

        net_angle = min(
            angle_difference,
            360.0 - angle_difference,
        )

        if net_angle < min_net_angle:
            continue

        results.append({
            "first_index": first_index,
            "last_index": last_index,
            "first_node": path[first_index],
            "last_node": path[last_index],
            "interval_m": round(interval_m, 2),
            "net_angle": round(net_angle, 2),
            "path_nodes": path[
                first_index:last_index + 1
            ],
        })

    return results



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


def analyze_pedestrian_route(graph, path: list[int]) -> dict:
    """
    採用ルートの道路種別・歩道利用状況を集計する。

    OSMの道路属性に基づく分類であり、
    現地の歩道の有無や安全性を保証するものではない。
    """

    from collections import defaultdict

    categories = defaultdict(float)

    def to_tag_set(value):
        if value is None:
            return set()

        if isinstance(value, (list, tuple, set)):
            values = value
        else:
            values = [value]

        result = set()

        for item in values:
            for part in str(item).lower().split(";"):
                result.add(part.strip())

        return result

    major_roads = {
        "motorway", "motorway_link",
        "trunk", "trunk_link",
        "primary", "primary_link",
        "secondary", "secondary_link",
        "tertiary", "tertiary_link",
    }

    sidewalk_values = {
        "yes", "both", "left",
        "right", "designated",
    }

    total_distance_m = 0.0

    for node_a, node_b in zip(path, path[1:]):

        edge_data = graph.get_edge_data(
            node_a, node_b
        )

        if not edge_data:
            raise ValueError(
                f"エッジがありません: {node_a} -> {node_b}"
            )

        # 既存の距離・交通スコア計算と同じく、
        # 最短の並列エッジを採用
        edge = min(
            edge_data.values(),
            key=lambda data: float(
                data.get("length", float("inf"))
            ),
        )

        length_m = float(edge.get("length", 0.0))

        if length_m <= 0:
            continue

        total_distance_m += length_m

        highway = to_tag_set(edge.get("highway"))
        footway = to_tag_set(edge.get("footway"))

        sidewalk_tags = set()

        for key in (
            "sidewalk",
            "sidewalk:left",
            "sidewalk:right",
            "sidewalk:both",
        ):
            sidewalk_tags.update(
                to_tag_set(edge.get(key))
            )

        # 分類は排他的に行う。
        # 1つの区間を複数カテゴリに足さない。
        if "steps" in highway:
            category = "steps"

        elif highway & major_roads:
            if sidewalk_tags & sidewalk_values:
                category = "major_with_sidewalk"
            else:
                category = "major_without_confirmed_sidewalk"

        elif "footway" in highway:
            if "sidewalk" in footway:
                category = "footway_sidewalk"
            elif "crossing" in footway:
                category = "footway_crossing"
            else:
                category = "other_footway"

        elif "pedestrian" in highway:
            category = "pedestrian"

        elif "path" in highway:
            category = "path"

        elif "living_street" in highway:
            category = "living_street"

        elif "residential" in highway:
            category = "residential"

        elif "unclassified" in highway:
            category = "unclassified"

        elif "service" in highway:
            category = "service"

        elif "track" in highway:
            category = "track"

        else:
            category = "other"

        categories[category] += length_m

    result = {
        "total_distance_m": round(total_distance_m, 1),
        "categories_m": {
            key: round(value, 1)
            for key, value in categories.items()
        },
        "categories_pct": {
            key: round(
                value / total_distance_m * 100, 1
            )
            for key, value in categories.items()
        } if total_distance_m > 0 else {},
    }

    return result



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