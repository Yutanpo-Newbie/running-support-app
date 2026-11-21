
"""
歩道・生活道路を優先するための探索グラフ生成。

元のOSMグラフとキャッシュは変更しない。
歩行者の通行可否を確認できない幹線道路を除外する。
"""

MAJOR_ROADS = {
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "motorway",
    "motorway_link",
}

PEDESTRIAN_ROADS = {
    "footway",
    "pedestrian",
    "path",
    "living_street",
}

SIDEWALK_PRESENT = {
    "yes",
    "both",
    "left",
    "right",
    "designated",
}

SIDEWALK_KEYS = (
    "sidewalk",
    "sidewalk:both",
    "sidewalk:left",
    "sidewalk:right",
)


def tag_values(value) -> set[str]:
    """
    OSMnxのタグは文字列またはリストの場合がある。
    """
    if value is None:
        return set()

    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = [value]

    result = set()

    for item in values:
        for part in str(item).lower().split(";"):
            result.add(part.strip())

    return result


def has_confirmed_sidewalk(data: dict) -> bool:
    """
    車道側のOSM属性に歩道の存在が明記されているか。
    separateは独立歩道側を利用するため対象外。
    """
    for key in SIDEWALK_KEYS:
        values = tag_values(data.get(key))

        if values & SIDEWALK_PRESENT:
            return True

    return False


def is_allowed_running_edge(data: dict) -> bool:
    """
    ランニング用探索グラフに残す道路か判定する。
    """

    highway = tag_values(data.get("highway"))
    foot = tag_values(data.get("foot"))
    access = tag_values(data.get("access"))

    # 明示的な歩行禁止・立入禁止
    if foot & {"no", "private"}:
        return False

    if access & {"no", "private"} and not (
        foot & {"yes", "designated", "permissive"}
    ):
        return False

    # 階段は今回は除外
    if "steps" in highway:
        return False

    if highway & {"motorway", "motorway_link"}:
        return False

    # 幹線道路を含むエッジは慎重に扱う
    # 歩道が確認できる場合のみ残す
    if highway & MAJOR_ROADS:
        return has_confirmed_sidewalk(data)

    # 歩行者専用・生活道路などは残す
    # 元グラフはnetwork_type="walk"を前提とする
    return True


def build_safe_running_graph(graph):
    """
    元グラフを変更せず、通行制約を適用した
    探索用グラフを返す。
    """

    safe_graph = graph.copy()

    removed_edges = []

    for u, v, key, data in safe_graph.edges(
        keys=True,
        data=True,
    ):
        if not is_allowed_running_edge(data):
            removed_edges.append((u, v, key))

    safe_graph.remove_edges_from(removed_edges)

    # 通行可能なエッジを失った孤立ノードを除去
    isolated_nodes = [
        node
        for node in safe_graph.nodes
        if safe_graph.degree(node) == 0
    ]

    safe_graph.remove_nodes_from(isolated_nodes)

    print(
        "SAFE RUNNING GRAPH:",
        "original_edges =", graph.number_of_edges(),
        "safe_edges =", safe_graph.number_of_edges(),
        "removed_edges =", len(removed_edges),
        "removed_nodes =", len(isolated_nodes),
        flush=True,
    )

    return safe_graph
