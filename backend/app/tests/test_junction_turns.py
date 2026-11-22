
import networkx as nx

from app.services.osm_client import (
    detect_junction_turn_points,
)


def make_graph(nodes, edges):
    graph = nx.MultiDiGraph()

    for node_id, (lat, lon) in nodes.items():
        graph.add_node(node_id, y=lat, x=lon)

    for u, v in edges:
        graph.add_edge(u, v, length=100)

    return graph


def get_coordinates(graph, path):
    return [
        {
            "lat": graph.nodes[node]["y"],
            "lon": graph.nodes[node]["x"],
        }
        for node in path
    ]


def test_right_turn_with_straight_option():
    # 南から進入し、直進可能な交差点を右折
    graph = make_graph(
        {
            1: (-0.001, 0),
            2: (0, 0),
            3: (0, 0.001),
            4: (0.001, 0),
        },
        [(1, 2), (2, 3), (2, 4)],
    )

    path = [1, 2, 3]

    turns = detect_junction_turn_points(
        graph, path, get_coordinates(graph, path)
    )

    assert len(turns) == 1
    assert turns[0]["direction"] == "right"


def test_natural_bend_is_ignored():
    # 道なり約35度、別の道は約90度
    graph = make_graph(
        {
            1: (-0.001, 0),
            2: (0, 0),
            3: (0.001, 0.0007),
            4: (0, 0.001),
        },
        [(1, 2), (2, 3), (2, 4)],
    )

    path = [1, 2, 3]

    turns = detect_junction_turn_points(
        graph, path, get_coordinates(graph, path)
    )

    assert len(turns) == 0


def test_t_junction_turn_is_kept():
    # 南から進入し、左右に分かれるT字路
    graph = make_graph(
        {
            1: (-0.001, 0),
            2: (0, 0),
            3: (0, 0.001),
            4: (0, -0.001),
        },
        [(1, 2), (2, 3), (2, 4)],
    )

    path = [1, 2, 3]

    turns = detect_junction_turn_points(
        graph, path, get_coordinates(graph, path)
    )

    assert len(turns) == 1
    assert turns[0]["direction"] == "right"


def test_single_exit_does_not_notify():
    # 一本道の90度カーブ
    graph = make_graph(
        {
            1: (-0.001, 0),
            2: (0, 0),
            3: (0, 0.001),
        },
        [(1, 2), (2, 3)],
    )

    path = [1, 2, 3]

    turns = detect_junction_turn_points(
        graph, path, get_coordinates(graph, path)
    )

    assert len(turns) == 0
