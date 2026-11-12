
import networkx as nx

from app.services.osm_client import (
    get_candidate_nodes_by_distance,
)


def test_step_free_waypoint_distance():

    graph = nx.MultiDiGraph()

    for node_id in range(1, 5):
        graph.add_node(
            node_id,
            x=float(node_id),
            y=0.0,
        )

    # 階段を含む近道
    graph.add_edge(
        1, 2,
        length=50,
        highway="steps",
    )
    graph.add_edge(
        2, 4,
        length=50,
        highway="residential",
    )

    # 階段を使わない迂回路
    graph.add_edge(
        1, 3,
        length=100,
        highway="residential",
    )
    graph.add_edge(
        3, 4,
        length=100,
        highway="residential",
    )

    candidates = get_candidate_nodes_by_distance(
        graph=graph,
        start_node=1,
        target_distance_m=100,
        tolerance_m=0,
        max_candidates=10,
        avoid_steps=True,
    )

    candidate_ids = {
        candidate["node_id"]
        for candidate in candidates
    }

    # 迂回路上の100m地点は候補になる
    assert 3 in candidate_ids

    # 階段経由なら100mだが、
    # 階段回避時は200mになるため候補外
    assert 4 not in candidate_ids
