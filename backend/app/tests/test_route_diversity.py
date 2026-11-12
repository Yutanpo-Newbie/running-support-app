
from app.services.osm_client import (
    select_diverse_routes,
)


def create_route(path, score):
    return {
        "path": path,
        "total_score": score,
    }


def test_select_diverse_routes():

    routes = [
        create_route(
            [1, 2, 3, 4, 5],
            10.0,
        ),
        create_route(
            [1, 2, 3, 4, 6],
            20.0,
        ),
        create_route(
            [7, 8, 9, 10],
            30.0,
        ),
    ]

    selected = select_diverse_routes(
        route_candidates=routes,
        max_routes=2,
        max_overlap_ratio=0.60,
    )

    assert len(selected) == 2

    # 最も良い候補は採用
    assert selected[0]["total_score"] == 10.0

    # 類似する2番目を飛ばして3番目を採用
    assert selected[1]["total_score"] == 30.0


def test_diverse_routes_respect_limit():

    routes = [
        create_route([1, 2, 3], 10.0),
        create_route([4, 5, 6], 20.0),
        create_route([7, 8, 9], 30.0),
    ]

    selected = select_diverse_routes(
        route_candidates=routes,
        max_routes=2,
    )

    assert len(selected) == 2


def test_diverse_routes_empty():

    assert select_diverse_routes([]) == []
