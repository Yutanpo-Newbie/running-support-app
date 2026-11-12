
from app.algorithms.scoring import (
    calculate_route_quality_penalty,
)


def test_quality_penalty_zero():

    result = calculate_route_quality_penalty(
        turn_density=0.0,
        short_turn_interval_count=0,
        overlap_ratio=0.0,
    )

    assert result == 0.0


def test_quality_penalty_max():

    result = calculate_route_quality_penalty(
        turn_density=8.0,
        short_turn_interval_count=4,
        overlap_ratio=0.20,
    )

    assert result == 50.0


def test_fewer_turns_get_better_score():

    route_a = calculate_route_quality_penalty(
        turn_density=3.0,
        short_turn_interval_count=1,
        overlap_ratio=0.0,
    )

    route_b = calculate_route_quality_penalty(
        turn_density=7.0,
        short_turn_interval_count=4,
        overlap_ratio=0.0,
    )

    assert route_a < route_b


def test_lower_overlap_gets_better_score():

    route_a = calculate_route_quality_penalty(
        turn_density=4.0,
        short_turn_interval_count=2,
        overlap_ratio=0.0,
    )

    route_b = calculate_route_quality_penalty(
        turn_density=4.0,
        short_turn_interval_count=2,
        overlap_ratio=0.15,
    )

    assert route_a < route_b
