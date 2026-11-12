
import networkx as nx

from app.services.osm_client import (
    filter_through_waypoint_nodes,
)


def test_filter_dead_end_waypoint():

    graph = nx.MultiDiGraph()

    graph.add_edge(1, 2)
    graph.add_edge(2, 3)
    graph.add_edge(3, 1)

    # ノード4は行き止まり
    graph.add_edge(2, 4)
    graph.add_edge(4, 2)

    result = filter_through_waypoint_nodes(
        graph,
        [1, 2, 3, 4],
    )

    assert result == [1, 2, 3]


def test_all_dead_ends():

    graph = nx.MultiDiGraph()

    graph.add_edge(1, 2)
    graph.add_edge(2, 1)

    result = filter_through_waypoint_nodes(
        graph,
        [1, 2],
    )

    assert result == []
