
import heapq
import math
from itertools import count


def calculate_turn_angle(graph, prev_node, current_node, next_node):
    """
    進行方向の変化角度を計算する。

    0度   = 直進
    90度  = 右左折
    180度 = Uターン

    左右の区別はせず、角度の大きさを返す。
    """

    prev = graph.nodes[prev_node]
    current = graph.nodes[current_node]
    next_data = graph.nodes[next_node]

    lat_scale = math.cos(
        math.radians(current["y"])
    )

    # 現在地点へ入ってきた方向
    dx1 = (
        current["x"] - prev["x"]
    ) * lat_scale
    dy1 = current["y"] - prev["y"]

    # 次の地点へ出ていく方向
    dx2 = (
        next_data["x"] - current["x"]
    ) * lat_scale
    dy2 = next_data["y"] - current["y"]

    angle1 = math.atan2(dy1, dx1)
    angle2 = math.atan2(dy2, dx2)

    angle = abs(
        math.degrees(angle2 - angle1)
    )

    return min(angle, 360 - angle)


def calculate_turn_penalty(angle):
    """
    曲がり角度に応じて追加コストを返す。
    単位は距離コスト相当のメートル。

    初期設定であり、実験で調整する。
    """

    if angle < 20:
        return 0.0

    if angle < 45:
        return 10.0

    if angle < 120:
        return 80.0

    if angle < 160:
        return 180.0

    # Uターンは強く避ける
    return 500.0


def get_edge_length(graph, node_a, node_b):
    """
    MultiDiGraphの並行エッジのうち
    最短の道路距離を取得する。
    """

    edge_data = graph.get_edge_data(
        node_a,
        node_b,
    )

    if not edge_data:
        return None

    return min(
        float(data["length"])
        for data in edge_data.values()
    )


def calculate_tight_uturn_penalty(
    graph,
    nodes,
    penalty_m=200.0,
    max_connector_m=20.0,
    min_turn_angle=60.0,
    min_net_angle=150.0,
):
    """
    5ノードの経路から、短距離で
    約180度方向が反転するU字型接続を検出する。

    nodes = (a, b, c, d, e)

    a → b → c → d → e

    bとdで曲がり、b→c→dが短い場合に評価。
    """

    if len(nodes) != 5:
        return 0.0

    a, b, c, d, e = nodes

    if any(node is None for node in nodes):
        return 0.0

    # 同一点による不正な角度計算を避ける
    if a == b or b == c or c == d or d == e:
        return 0.0

    length_1 = get_edge_length(graph, b, c)
    length_2 = get_edge_length(graph, c, d)

    if length_1 is None or length_2 is None:
        return 0.0

    connector_length = length_1 + length_2

    if connector_length > max_connector_m:
        return 0.0

    # 接続路の両端にある右左折
    first_angle = calculate_turn_angle(
        graph, a, b, c
    )

    second_angle = calculate_turn_angle(
        graph, c, d, e
    )

    if (
        first_angle < min_turn_angle
        or second_angle < min_turn_angle
    ):
        return 0.0

    # 接続路に入る前と出た後の進行方向
    before = graph.nodes[a]
    first = graph.nodes[b]
    last = graph.nodes[d]
    after = graph.nodes[e]

    lat_scale = math.cos(
        math.radians(
            (first["y"] + last["y"]) / 2.0
        )
    )

    dx1 = (first["x"] - before["x"]) * lat_scale
    dy1 = first["y"] - before["y"]

    dx2 = (after["x"] - last["x"]) * lat_scale
    dy2 = after["y"] - last["y"]

    if (
        math.hypot(dx1, dy1) < 1e-12
        or math.hypot(dx2, dy2) < 1e-12
    ):
        return 0.0

    angle1 = math.atan2(dy1, dx1)
    angle2 = math.atan2(dy2, dx2)

    difference = abs(
        math.degrees(angle2 - angle1)
    )

    net_angle = min(
        difference,
        360.0 - difference,
    )

    if net_angle < min_net_angle:
        return 0.0

    return penalty_m


def get_undirected_edge(node_a, node_b):
    """
    A→B と B→A を同じ道路区間として扱う。
    """
    return frozenset((node_a, node_b))


def get_used_edges(path):
    """
    経路で使用した道路区間の集合。
    """

    return {
        get_undirected_edge(a, b)
        for a, b in zip(path, path[1:])
    }


def shortest_turn_aware_path(
    graph,
    start_node,
    end_node,
    used_edges=None,
    reuse_penalty_factor=5.0,
    max_states=100000,
    initial_prev_node=None,
    avoid_steps=False,
    diversity_edges=None,
    diversity_penalty_factor=1.5,
    avoid_tight_uturns=False,
    tight_uturn_penalty_m=200.0,
    initial_history_nodes=None,
):
    """
    曲がりにくさを考慮したDijkstra法。

    評価：
      道路距離
      + 方向転換ペナルティ
      + 既使用道路の再通過ペナルティ

    used_edgesには以前の区間で使った道路を渡す。
    """

    if start_node == end_node:
        return [start_node]

    if used_edges is None:
        used_edges = set()
    if diversity_edges is None:
        diversity_edges = set()

    if diversity_penalty_factor < 1.0:
        raise ValueError(
            "diversity_penalty_factorは1.0以上にしてください"
        )


    # =====================================
    # 探索開始状態の初期化
    # =====================================

    if avoid_tight_uturns:
        if initial_history_nodes is not None:
            history = list(initial_history_nodes[-3:])
        elif initial_prev_node is not None:
            history = [initial_prev_node]
        else:
            history = []

        history = (
            [None] * max(0, 3 - len(history))
            + history
        )[-3:]

        start_state = (
            *history,
            start_node,
        )

    else:
        # 従来の2ノード状態
        start_state = (
            initial_prev_node,
            start_node,
        )


    distances = {start_state: 0.0}
    previous_states = {}

    sequence = count()

    queue = [
        (0.0, next(sequence), start_state)
    ]

    visited = set()

    while queue:

        cost, _, state = heapq.heappop(queue)

        if state in visited:
            continue

        visited.add(state)

        if len(visited) > max_states:
            return None

        prev_node = state[-2]
        current_node = state[-1]

        if current_node == end_node:

            # 状態を遡って経路を復元する
            path = [current_node]

            while state in previous_states:
                state = previous_states[state]
                path.append(state[-1])

            path.reverse()
            return path

        for next_node in graph.successors(current_node):


            # =====================================
            # 16.6.7 探索開始直後の逆走を禁止
            # =====================================

            if (
                state == start_state
                and initial_prev_node is not None
                and next_node == initial_prev_node
            ):
                continue

            edge_length = get_edge_length(
                graph,
                current_node,
                next_node,
            )


            # =====================================
            # 16.7.2.2 階段道路の探索禁止
            # =====================================

            if avoid_steps:

                edge_data = graph.get_edge_data(
                    current_node,
                    next_node,
                )

                if edge_data:

                    # 現在の距離計算と同じく
                    # 最短エッジを評価対象にする
                    shortest_edge = min(
                        edge_data.values(),
                        key=lambda data: float(
                            data.get("length", float("inf"))
                        ),
                    )

                    highway = shortest_edge.get(
                        "highway", []
                    )

                    if isinstance(highway, str):
                        highway_types = [highway]
                    elif isinstance(
                        highway, (list, tuple, set)
                    ):
                        highway_types = highway
                    else:
                        highway_types = []

                    if "steps" in highway_types:
                        continue


            if edge_length is None:
                continue


            # =====================================
            # STEP 16.36
            # 歩行者向け道路を優先する探索コスト
            # =====================================

            edge_data = graph.get_edge_data(
                current_node,
                next_node,
            )

            shortest_edge = min(
                edge_data.values(),
                key=lambda data: float(
                    data.get("length", float("inf"))
                ),
            )

            highway = shortest_edge.get("highway", [])

            if isinstance(highway, str):
                highway_types = {highway.lower()}
            elif isinstance(highway, (list, tuple, set)):
                highway_types = {
                    str(value).lower()
                    for value in highway
                }
            else:
                highway_types = set()

            if highway_types & {
                "footway",
                "pedestrian",
                "path",
                "living_street",
            }:
                road_penalty = 0.0

            elif highway_types & {
                "residential",
                "service",
            }:
                road_penalty = edge_length * 0.15

            elif highway_types & {
                "unclassified",
                "tertiary",
            }:
                road_penalty = edge_length * 0.5

            elif highway_types & {
                "secondary",
                "primary",
                "trunk",
            }:
                road_penalty = edge_length * 2.0

            else:
                road_penalty = edge_length * 0.25


            # 曲がりペナルティ
            turn_penalty = 0.0

            if prev_node is not None:
                turn_angle = calculate_turn_angle(
                    graph,
                    prev_node,
                    current_node,
                    next_node,
                )

                turn_penalty = calculate_turn_penalty(
                    turn_angle
                )

            # 以前の区間で通った道路は
            # なるべく使わない
            edge_key = get_undirected_edge(
                current_node,
                next_node,
            )

            reuse_penalty = 0.0

            if edge_key in used_edges:
                reuse_penalty = (
                    edge_length
                    * (reuse_penalty_factor - 1.0)
                )


            # =====================================
            # 16.14 他ルートとの重複回避
            # =====================================

            diversity_penalty = 0.0

            if edge_key in diversity_edges:
                diversity_penalty = (
                    edge_length
                    * (diversity_penalty_factor - 1.0)
                )


            # =====================================
            # STEP 16.35
            # 短距離U字型接続ペナルティ
            # =====================================

            tight_uturn_penalty = 0.0

            if avoid_tight_uturns:

                recent_nodes = (
                    *state,
                    next_node,
                )

                tight_uturn_penalty = (
                    calculate_tight_uturn_penalty(
                        graph=graph,
                        nodes=recent_nodes,
                        penalty_m=tight_uturn_penalty_m,
                    )
                )



            new_cost = (
                cost
                + edge_length
                + road_penalty
                + turn_penalty
                + reuse_penalty
                + diversity_penalty
                + tight_uturn_penalty
            )



            if avoid_tight_uturns:
                next_state = (
                    *state[1:],
                    next_node,
                )
            else:
                next_state = (
                    current_node,
                    next_node,
                )


            if new_cost < distances.get(
                next_state,
                float("inf"),
            ):
                distances[next_state] = new_cost
                previous_states[next_state] = state

                heapq.heappush(
                    queue,
                    (
                        new_cost,
                        next(sequence),
                        next_state,
                    )
                )

    return None
