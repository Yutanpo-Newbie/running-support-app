
import networkx as nx

from app.algorithms.turn_aware_router import (
    calculate_turn_penalty,
    shortest_turn_aware_path,
    get_used_edges,
)


def test_turn_penalty():
    assert calculate_turn_penalty(0) == 0
    assert calculate_turn_penalty(90) == 80
    assert calculate_turn_penalty(180) == 500


def test_turn_aware_prefers_straight_route():

    graph = nx.MultiDiGraph()

    # x=経度相当、y=緯度相当
    graph.add_node(0, x=0.0, y=0.0)
    graph.add_node(1, x=1.0, y=0.0)
    graph.add_node(2, x=1.0, y=1.0)
    graph.add_node(3, x=2.0, y=1.0)
    graph.add_node(4, x=1.0, y=0.5)

    # 短いが2回曲がるルート：300m
    graph.add_edge(0, 1, length=100)
    graph.add_edge(1, 2, length=100)
    graph.add_edge(2, 3, length=100)

    # 長いが直進できるルート：400m
    graph.add_edge(0, 4, length=200)
    graph.add_edge(4, 3, length=200)

    path = shortest_turn_aware_path(
        graph,
        0,
        3,
    )

    assert path == [0, 4, 3]


def test_used_edges_ignore_direction():
    edges = get_used_edges([1, 2, 3])

    assert frozenset((2, 1)) in edges
    assert frozenset((3, 2)) in edges
