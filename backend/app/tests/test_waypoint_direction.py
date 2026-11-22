
from app.services.osm_client import (
    select_direction_balanced_candidates,
)


def make_candidate(node_id, lat, lon, error):
    return {
        "node_id": node_id,
        "lat": lat,
        "lon": lon,
        "distance_m": 1000.0 + error,
        "distance_error_m": error,
    }


def test_direction_balanced_candidates():
    # 北・東・南・西に各5件配置
    candidates = []
    node_id = 1

    directions = [
        (0.001, 0),    # N
        (0, 0.001),    # E
        (-0.001, 0),   # S
        (0, -0.001),   # W
    ]

    for lat, lon in directions:
        for i in range(5):
            candidates.append(
                make_candidate(
                    node_id=node_id,
                    lat=lat * (1 + i * 0.1),
                    lon=lon * (1 + i * 0.1),
                    error=float(i),
                )
            )
            node_id += 1

    selected = select_direction_balanced_candidates(
        candidates=candidates,
        start_lat=0,
        start_lon=0,
        max_candidates=8,
    )

    assert len(selected) == 8

    # 最初の8件で各方向から2件ずつ選ばれる
    selected_ids = {
        candidate["node_id"]
        for candidate in selected
    }

    assert len(selected_ids) == 8

    for start_id in (1, 6, 11, 16):
        assert start_id in selected_ids
        assert start_id + 1 in selected_ids


def test_direction_balanced_fills_empty_directions():
    # 東側にしか候補がない場合でも
    # 最大件数まで選択する
    candidates = [
        make_candidate(
            node_id=i,
            lat=0,
            lon=0.001 + i * 0.0001,
            error=float(i),
        )
        for i in range(1, 11)
    ]

    selected = select_direction_balanced_candidates(
        candidates=candidates,
        start_lat=0,
        start_lon=0,
        max_candidates=6,
    )

    assert len(selected) == 6

    assert [
        candidate["node_id"]
        for candidate in selected
    ] == [1, 2, 3, 4, 5, 6]


def test_direction_balanced_empty_candidates():
    selected = select_direction_balanced_candidates(
        candidates=[],
        start_lat=0,
        start_lon=0,
        max_candidates=40,
    )

    assert selected == []
