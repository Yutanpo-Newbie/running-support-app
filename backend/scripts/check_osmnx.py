import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.osm_client import (
    get_road_graph,
    get_graph_summary,
    get_nearest_node,
    get_node_coordinates,
    get_candidate_nodes_by_distance,
    get_shortest_path,
    convert_path_to_coordinates,
    create_loop_path,
    calculate_path_length_m,
    calculate_path_length_km,
    generate_loop_route_candidates,
)

from app.utils.geo import convert_to_geojson_linestring
from app.schemas.route_request import RoutePreferences


def main():
    lat = 35.8721
    lon = 140.0106
    dist_m = 1000

    print("OSMnx road graph check")
    print(f"center: lat={lat}, lon={lon}")
    print(f"dist_m: {dist_m}")

    graph = get_road_graph(
        lat=lat,
        lon=lon,
        dist_m=dist_m,
    )

    summary = get_graph_summary(graph)

    print("Graph summary:")
    print(f"nodes: {summary['nodes']}")
    print(f"edges: {summary['edges']}")

    nearest_node_id = get_nearest_node(
        graph=graph,
        lat=lat,
        lon=lon,
    )

    nearest_node = get_node_coordinates(
        graph=graph,
        node_id=nearest_node_id,
    )

    print("Nearest node:")
    print(f"node_id: {nearest_node['node_id']}")
    print(f"lat: {nearest_node['lat']}")
    print(f"lon: {nearest_node['lon']}")

    target_loop_distance_km = 2.0
    target_oneway_distance_m = target_loop_distance_km * 1000 / 2

    candidate_nodes = get_candidate_nodes_by_distance(
        graph=graph,
        start_node=nearest_node_id,
        target_distance_m=target_oneway_distance_m,
        tolerance_m=200,
        max_candidates=10,
    )

    print("Candidate nodes:")
    print(f"target_loop_distance_km: {target_loop_distance_km}")
    print(f"target_oneway_distance_m: {target_oneway_distance_m}")

    for candidate in candidate_nodes:
        print(
            f"node_id: {candidate['node_id']} / "
            f"lat: {candidate['lat']} / "
            f"lon: {candidate['lon']} / "
            f"distance_m: {candidate['distance_m']} / "
            f"error_m: {candidate['distance_error_m']}"
        )

    if candidate_nodes:
        selected_candidate = candidate_nodes[0]

        path = get_shortest_path(
            graph=graph,
            start_node=nearest_node_id,
            end_node=selected_candidate["node_id"],
        )

        path_coordinates = convert_path_to_coordinates(
            graph=graph,
            path=path,
        )

        print("Shortest path:")
        print(f"start_node: {nearest_node_id}")
        print(f"end_node: {selected_candidate['node_id']}")
        print(f"path_nodes: {len(path)}")
        print(f"path_coordinates: {len(path_coordinates)}")

        print("First 5 coordinates:")
        for point in path_coordinates[:5]:
            print(point)

        return_path = get_shortest_path(
            graph=graph,
            start_node=selected_candidate["node_id"],
            end_node=nearest_node_id,
        )

        return_path_coordinates = convert_path_to_coordinates(
            graph=graph,
            path=return_path,
        )

        print("Return shortest path:")
        print(f"start_node: {selected_candidate['node_id']}")
        print(f"end_node: {nearest_node_id}")
        print(f"return_path_nodes: {len(return_path)}")
        print(f"return_path_coordinates: {len(return_path_coordinates)}")

        print("First 5 return coordinates:")
        for point in return_path_coordinates[:5]:
            print(point)

        loop_path = create_loop_path(
            outbound_path=path,
            return_path=return_path,
        )

        loop_coordinates = convert_path_to_coordinates(
            graph=graph,
            path=loop_path,
        )

        loop_length_m = calculate_path_length_m(
            graph=graph,
            path=loop_path,
        )

        loop_length_km = calculate_path_length_km(
            graph=graph,
            path=loop_path,
        )

        print("Loop path:")
        print(f"loop_path_nodes: {len(loop_path)}")
        print(f"loop_coordinates: {len(loop_coordinates)}")
        print(f"loop_length_m: {loop_length_m}")
        print(f"loop_length_km: {loop_length_km}")

        print("First 5 loop coordinates:")
        for point in loop_coordinates[:5]:
            print(point)

        print("Last 5 loop coordinates:")
        for point in loop_coordinates[-5:]:
            print(point)

        loop_geometry = convert_to_geojson_linestring(loop_coordinates)

        print("Loop GeoJSON:")
        print(f"type: {loop_geometry['type']}")
        print(f"coordinates_count: {len(loop_geometry['coordinates'])}")

        print("First 5 GeoJSON coordinates:")
        for point in loop_geometry["coordinates"][:5]:
            print(point)
        
        preferences = RoutePreferences(
            avoid_traffic=True,
            avoid_signals=True,
            avoid_intersections=True,
            elevation_mode="low",
        )

        osm_route_candidates = generate_loop_route_candidates(
            graph=graph,
            start_node=nearest_node_id,
            candidate_nodes=candidate_nodes,
            target_distance_km=target_loop_distance_km,
            preferences=preferences,
            max_routes=5,
        )

        print("OSM route candidates:")
        print(f"count: {len(osm_route_candidates)}")

        for index, route in enumerate(osm_route_candidates, start=1):
            print(
                f"route_{index} / "
                f"candidate_node_id: {route['candidate_node_id']} / "
                f"distance_km: {route['distance_km']} / "
                f"distance_error_m: {route['distance_error_m']} / "
                f"path_nodes: {route['path_nodes']} / "
                f"intersections: {route['intersections']} / "
                f"score: {route['total_score']} / "
                f"coordinates: {len(route['coordinates'])} /"
                f"geometry_type: {route['geometry']['type']} / "
                f"geometry_coordinates: {len(route['geometry']['coordinates'])}"
            )
            

if __name__ == "__main__":
    main()