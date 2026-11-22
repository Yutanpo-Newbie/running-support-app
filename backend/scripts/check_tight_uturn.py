
import osmnx as ox

from app.algorithms.turn_aware_router import (
    calculate_tight_uturn_penalty,
)

# 保存済みOSMグラフを読み込む
graph = ox.load_graphml(
    "data/graph_cache/graph_1794397437.graphml"
)

# 既知の約12mのU字型接続路
test_nodes = (
    10294556579,
    10678345881,
    10678345882,
    10678345880,
    9642515182,
)

# U字型接続ペナルティを計算
penalty = calculate_tight_uturn_penalty(
    graph=graph,
    nodes=test_nodes,
    penalty_m=200.0,
)

print("TIGHT UTURN PENALTY:", penalty)

assert penalty == 200.0, (
    f"Expected 200.0, got {penalty}"
)

print("TIGHT UTURN TEST PASSED")
