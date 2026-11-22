
import networkx as nx

from app.algorithms.waypoint_generator import (
    generate_waypoint_pairs,
)


def make_test_graph():
    graph = nx.MultiDiGraph()

    # START、東、西、南の4地点
    nodes = {
        0: (0.0, 0.0),
        1: (0.0, 0.001),
        2: (0.0, -0.001),
        3: (-0.001, 0.0),
    }

    for node, (lat, lon) in nodes.items():
        graph.add_node(node, y=lat, x=lon)

    # 双方向で200mの道路を構成
    edges = [
        (0, 1), (0, 2), (0, 3),
        (1, 2), (1, 3), (2, 3),
    ]

    for a, b in edges:
        graph.add_edge(a, b, length=200)
        graph.add_edge(b, a, length=200)

    return graph


def test_pairs_with_distance_estimation():
    graph = make_test_graph()

    pairs = generate_waypoint_pairs(
        graph=graph,
        start_node=0,
        candidate_nodes=[1, 2, 3],
        target_distance_m=600,
        max_pairs=20,
    )

    # 最短周回600mのペアを生成できる
    assert len(pairs) > 0
    assert len(pairs) == len(set(pairs))

    # 方位角差180度の東西ペアは除外
    assert (1, 2) not in pairs
    assert (2, 1) not in pairs


def test_pairs_exclude_too_long_routes():
    graph = make_test_graph()

    pairs = generate_waypoint_pairs(
        graph=graph,
        start_node=0,
        candidate_nodes=[1, 2, 3],
        target_distance_m=300,
        max_pairs=20,
    )

    # 600mの最短周回でも、
    # 300m指定の許容上限375mを超える
    assert pairs == []


def test_pairs_respect_max_pairs():
    graph = make_test_graph()

    pairs = generate_waypoint_pairs(
        graph=graph,
        start_node=0,
        candidate_nodes=[1, 2, 3],
        target_distance_m=600,
        max_pairs=2,
    )

    assert len(pairs) == 2


def test_legacy_mode():
    graph = make_test_graph()

    pairs = generate_waypoint_pairs(
        graph=graph,
        start_node=0,
        candidate_nodes=[1, 2, 3],
        max_pairs=20,
    )

    assert len(pairs) > 0
