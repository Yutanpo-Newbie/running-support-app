from app.schemas.route_request import RouteRequest
from app.schemas.route_response import (
    RouteCandidate, RoutePoint, TurnPoint, GeoJsonLineString,
    )
from app.utils.geo import calculate_route_distance_km, convert_to_geojson_linestring
from app.algorithms.scoring import calculate_total_score
from app.algorithms.waypoint_generator import generate_loop_coordinates
from app.services.osm_client import (
    get_road_graph,
    get_nearest_node,
    get_candidate_nodes_by_distance,
    generate_loop_route_candidates,
)

def generate_mock_routes(request: RouteRequest) -> list[RouteCandidate]:
    """
    仮ルート候補を複数生成する関数。

    現段階ではOSMやMapboxは使わず、
    スタート地点を基準にした疑似的なルートを3本作る。
    """

    start_lat = request.start.lat
    start_lon = request.start.lon

    generated_coordinates = generate_loop_coordinates(
        start_lat=start_lat,
        start_lon=start_lon,
        distance_km=request.distance_km,
    )

    mock_route_data = [
        {
            "id": "route_test001",
            "name": "仮ルート:信号少なめ",
            "coordinates": generated_coordinates[0],
            "elevation_gain_m": 30.0,
            "signals": 2,
            "intersections": 10,
            "traffic_score": 8.0,
            "turn_points": [
                {
                    "lat": generated_coordinates[0][1]["lat"],
                    "lon": generated_coordinates[0][1]["lon"],
                    "direction": "right",
                    "instruction": "次は右折です",
                }
            ],
        },
        {
            "id": "route_test002",
            "name": "仮ルート:距離優先・車通り多め",
            "coordinates": generated_coordinates[1],
            "elevation_gain_m": 40.0,
            "signals": 10,
            "intersections": 24,
            "traffic_score": 18.0,
            "turn_points": [
                {
                    "lat": generated_coordinates[1][1]["lat"],
                    "lon": generated_coordinates[1][1]["lon"],
                    "direction": "left",
                    "instruction": "次は左折です",
                },
            ],
        },
        {
            "id": "route_test003",
            "name": "仮ルート:坂道少なめ・車通り少なめ",
            "coordinates": generated_coordinates[2],
            "elevation_gain_m": 5.0,
            "signals": 6,
            "intersections": 14,
            "traffic_score": 3.0,
            "turn_points": [
                {
                    "lat": generated_coordinates[2][1]["lat"],
                    "lon": generated_coordinates[2][1]["lon"],
                    "direction": "straight",
                    "instruction": "次は道なりです",
                }
            ],
        },
    ]

    route_candidates = []

    for route_data in mock_route_data:
        coordinates = route_data["coordinates"]

        actual_distance_km = calculate_route_distance_km(coordinates)
        geojson_geometry = convert_to_geojson_linestring(coordinates)

        total_score = calculate_total_score(
            target_distance_km=request.distance_km,
            actual_distance_km=actual_distance_km,
            elevation_gain_m=route_data["elevation_gain_m"],
            signals=route_data["signals"],
            intersections=route_data["intersections"],
            traffic_score=route_data["traffic_score"],
            preferences=request.preferences,
        )

        route_candidate = RouteCandidate(
            id=route_data["id"],
            name=route_data["name"],
            distance_km=round(actual_distance_km, 2),
            elevation_gain_m=route_data["elevation_gain_m"],
            signals=route_data["signals"],
            intersections=route_data["intersections"],
            traffic_score=route_data["traffic_score"],
            total_score=total_score,
            coordinates=[
                RoutePoint(
                    lat=point["lat"],
                    lon=point["lon"],
                )
                for point in coordinates
            ],
            geometry=GeoJsonLineString(
                type=geojson_geometry["type"],
                coordinates=geojson_geometry["coordinates"],
            ),
            turn_points=[
                TurnPoint(
                    lat=point["lat"],
                    lon=point["lon"],
                    direction=point["direction"],
                    instruction=point["instruction"],
                )
                for point in route_data["turn_points"]
            ],
        )

        route_candidates.append(route_candidate)

    route_candidates.sort(key=lambda route: route.total_score)

    return route_candidates

def generate_osmnx_routes(request: RouteRequest) -> list[RouteCandidate]:
    """
    OSMnxを使って、実道路ネットワーク上のルート候補を生成する。
    現段階では start → candidate → start の往復型ルートを返す。
    """

    start_lat = request.start.lat
    start_lon = request.start.lon

    # 希望距離に応じて道路グラフの取得範囲を決める
    # 例: 2kmなら周辺1000m、5kmなら周辺2500m程度
    graph_dist_m = int(max(request.distance_km * 1000 / 2 + 500, 1000))

    graph = get_road_graph(
        lat=start_lat,
        lon=start_lon,
        dist_m=graph_dist_m,
    )

    start_node = get_nearest_node(
        graph=graph,
        lat=start_lat,
        lon=start_lon,
    )

    target_oneway_distance_m = request.distance_km * 1000 / 2

    candidate_nodes = get_candidate_nodes_by_distance(
        graph=graph,
        start_node=start_node,
        target_distance_m=target_oneway_distance_m,
        tolerance_m=300,
        max_candidates=10,
    )

    osm_route_candidates = generate_loop_route_candidates(
        graph=graph,
        start_node=start_node,
        candidate_nodes=candidate_nodes,
        target_distance_km=request.distance_km,
        preferences=request.preferences,
        max_routes=3,
    )

    routes: list[RouteCandidate] = []

    for index, route in enumerate(osm_route_candidates, start=1):
        route_candidate = RouteCandidate(
            id=f"osm_route_{index:03d}",
            name=f"OSM実道路ルート候補{index}",
            distance_km=route["distance_km"],
            elevation_gain_m=route["elevation_gain_m"],
            signals=route["signals"],
            intersections=route["intersections"],
            traffic_score=route["traffic_score"],
            total_score=route["total_score"],
            coordinates=[
                RoutePoint(
                    lat=point["lat"],
                    lon=point["lon"],
                )
                for point in route["coordinates"]
            ],
            geometry=GeoJsonLineString(
                type=route["geometry"]["type"],
                coordinates=route["geometry"]["coordinates"],
            ),
            turn_points=[],
        )

        routes.append(route_candidate)

    return routes