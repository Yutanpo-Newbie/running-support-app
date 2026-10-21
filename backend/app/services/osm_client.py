import osmnx as ox
import networkx as nx
from app.algorithms.scoring import calculate_total_score
from app.schemas.route_request import RoutePreferences
from app.utils.geo import convert_to_geojson_linestring

def get_road_graph(
    lat: float,
    lon: float,
    dist_m: int = 1000,
):
    """
    指定した緯度経度の周辺道路ネットワークを取得する。

    Parameters
    ----------
    lat : float
        緯度
    lon : float
        経度
    dist_m : int
        取得する範囲。単位はメートル。

    Returns
    -------
    networkx.MultiDiGraph
        OSMnxで取得した道路ネットワークグラフ
    """

    graph = ox.graph_from_point(
        center_point=(lat, lon),
        dist=dist_m,
        network_type="walk",
        simplify=True,
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