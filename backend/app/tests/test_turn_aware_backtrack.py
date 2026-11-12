
import networkx as nx

from app.algorithms.turn_aware_router import (
    shortest_turn_aware_path,
)


def create_test_graph():
    graph = nx.MultiDiGraph()

    positions = {
        1: (0.0, 0.0),
        2: (1.0, 0.0),
        3: (1.0, 1.0),
        4: (0.0, 1.0),
    }

    for node_id, (x, y) in positions.items():
        graph.add_node(
            node_id,
            x=x,
            y=y,
        )

    # A(2)から直前のノード1へ戻る経路
    graph.add_edge(2, 1, length=10)
    graph.add_edge(1, 4, length=10)

    # A(2)から別の道を通る経路
    graph.add_edge(2, 3, length=10)
    graph.add_edge(3, 4, length=10)

    return graph


def test_avoid_immediate_backtrack():
    graph = create_test_graph()

    path = shortest_turn_aware_path(
        graph,
        start_node=2,
        end_node=4,
        initial_prev_node=1,
    )

    assert path == [2, 3, 4]


def test_no_alternative_route():
    graph = nx.MultiDiGraph()

    graph.add_node(1, x=0.0, y=0.0)
    graph.add_node(2, x=1.0, y=0.0)
    graph.add_node(4, x=0.0, y=1.0)

    graph.add_edge(2, 1, length=10)
    graph.add_edge(1, 4, length=10)

    path = shortest_turn_aware_path(
        graph,
        start_node=2,
        end_node=4,
        initial_prev_node=1,
    )

    assert path is None
