
import networkx as nx

from app.algorithms.sidewalk_filter import (
    is_allowed_running_edge,
    build_safe_running_graph,
)


def test_independent_sidewalk_allowed():
    assert is_allowed_running_edge({
        "highway": "footway",
        "footway": "sidewalk",
    })


def test_residential_road_allowed():
    assert is_allowed_running_edge({
        "highway": "residential",
    })


def test_major_road_without_sidewalk_blocked():
    assert not is_allowed_running_edge({
        "highway": "primary",
    })


def test_major_road_with_sidewalk_allowed():
    assert is_allowed_running_edge({
        "highway": "secondary",
        "sidewalk": "both",
    })


def test_separate_sidewalk_does_not_allow_carriageway():
    assert not is_allowed_running_edge({
        "highway": "primary",
        "sidewalk": "separate",
    })


def test_steps_blocked():
    assert not is_allowed_running_edge({
        "highway": "steps",
    })


def test_mixed_highway_tags_blocked():
    assert not is_allowed_running_edge({
        "highway": ["residential", "primary"],
    })


def test_safe_graph_preserves_original():
    graph = nx.MultiDiGraph()

    graph.add_edge(
        1, 2, highway="residential", length=50
    )
    graph.add_edge(
        2, 3, highway="trunk", length=50
    )
    graph.add_edge(
        2, 4, highway="footway", length=30
    )

    safe_graph = build_safe_running_graph(graph)

    assert graph.has_edge(2, 3)
    assert not safe_graph.has_edge(2, 3)
    assert safe_graph.has_edge(1, 2)
    assert safe_graph.has_edge(2, 4)
