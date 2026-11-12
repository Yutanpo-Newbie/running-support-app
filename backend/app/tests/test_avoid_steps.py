
import networkx as nx

from app.algorithms.turn_aware_router import (
    shortest_turn_aware_path,
)


def test_avoid_steps_selects_alternative():

    graph = nx.MultiDiGraph()

    positions = {
        1: (0.0, 0.0),
        2: (1.0, 0.0),
        3: (0.0, 1.0),
        4: (1.0, 1.0),
    }

    for node_id, (x, y) in positions.items():
        graph.add_node(node_id, x=x, y=y)

    # 階段を通る経路（短い）
    graph.add_edge(
        1, 2,
        length=10,
        highway="steps",
    )
    graph.add_edge(
        2, 4,
        length=10,
        highway="residential",
    )

    # 階段のない経路
    graph.add_edge(
        1, 3,
        length=20,
        highway="residential",
    )
    graph.add_edge(
        3, 4,
        length=20,
        highway="residential",
    )

    path = shortest_turn_aware_path(
        graph,
        start_node=1,
        end_node=4,
        avoid_steps=True,
    )

    assert path == [1, 3, 4]


def test_avoid_steps_no_alternative():

    graph = nx.MultiDiGraph()

    graph.add_node(1, x=0.0, y=0.0)
    graph.add_node(2, x=1.0, y=0.0)

    graph.add_edge(
        1, 2,
        length=10,
        highway="steps",
    )

    path = shortest_turn_aware_path(
        graph,
        start_node=1,
        end_node=2,
        avoid_steps=True,
    )

    assert path is None
