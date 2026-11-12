
from app.services.osm_client import (
    count_immediate_backtracks,
)


def test_no_backtrack():

    path = [1, 2, 3, 4, 1]

    assert count_immediate_backtracks(path) == 0


def test_single_backtrack():

    path = [1, 2, 3, 2, 4]

    assert count_immediate_backtracks(path) == 1


def test_multiple_backtracks():

    path = [1, 2, 3, 2, 4, 5, 4, 1]

    assert count_immediate_backtracks(path) == 2


def test_short_path():

    assert count_immediate_backtracks([1, 2]) == 0
    assert count_immediate_backtracks([]) == 0
