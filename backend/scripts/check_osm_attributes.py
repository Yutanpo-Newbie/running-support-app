
from collections import Counter

from app.services.osm_client import get_road_graph


# 以前からテストに使っている地点
LAT = 35.8721
LON = 140.0106

# OSMグラフ取得（既存キャッシュを利用）
graph = get_road_graph(
    lat=LAT,
    lon=LON,
    dist_m=1000,
)

print("=== OSM属性確認 ===")
print("ノード数:", len(graph.nodes))
print("エッジ数:", len(graph.edges))

# =====================================
# 1. ノード属性を確認
# =====================================

signal_nodes = [
    node_id
    for node_id, data in graph.nodes(data=True)
    if data.get("highway") == "traffic_signals"
]

print("\n【信号機】")
print("信号ノード数:", len(signal_nodes))
print("サンプル:", signal_nodes[:5])

# =====================================
# 2. 道路属性の種類を確認
# =====================================

highway_counts = Counter()
tag_counts = Counter()

for u, v, key, data in graph.edges(
    keys=True,
    data=True,
):
    highway = data.get("highway", "unknown")

    if isinstance(highway, list):
        for value in highway:
            highway_counts[str(value)] += 1
    else:
        highway_counts[str(highway)] += 1

    for tag in (
        "sidewalk",
        "lanes",
        "maxspeed",
        "surface",
        "lit",
    ):
        if data.get(tag) is not None:
            tag_counts[tag] += 1

print("\n【道路種別】")

for name, count in highway_counts.most_common():
    print(f"{name}: {count}")

print("\n【道路属性の登録数】")

for tag, count in tag_counts.items():
    print(f"{tag}: {count}")

# =====================================
# 3. 実際のエッジデータを表示
# =====================================

print("\n【道路データサンプル】")

for index, (u, v, key, data) in enumerate(
    graph.edges(keys=True, data=True)
):
    if index >= 5:
        break

    print({
        "highway": data.get("highway"),
        "length": data.get("length"),
        "sidewalk": data.get("sidewalk"),
        "lanes": data.get("lanes"),
        "maxspeed": data.get("maxspeed"),
        "surface": data.get("surface"),
        "lit": data.get("lit"),
    })

# =====================================
# 16.2 交差点属性の確認
# =====================================

street_count_nodes = [
    data
    for _, data in graph.nodes(data=True)
    if data.get("street_count") is not None
]

intersection_nodes = [
    node_id
    for node_id, data in graph.nodes(data=True)
    if data.get("street_count") is not None
    and int(data["street_count"]) >= 3
]

print("\n【交差点データ】")
print("street_count保持ノード:", len(street_count_nodes))
print("交差点候補ノード:", len(intersection_nodes))

print("\n【street_countサンプル】")

for node_id, data in list(graph.nodes(data=True))[:10]:
    print(
        node_id,
        "street_count =",
        data.get("street_count")
    )


# =====================================
# 16.3 追加道路属性の取得確認
# =====================================

from collections import Counter

additional_tags = [
    "sidewalk",
    "sidewalk:left",
    "sidewalk:right",
    "sidewalk:both",
    "footway",
    "lanes",
    "maxspeed",
    "surface",
    "lit",
]

tag_counts = Counter()
tag_values = {
    tag: Counter()
    for tag in additional_tags
}

for u, v, key, data in graph.edges(
    keys=True,
    data=True,
):
    for tag in additional_tags:

        value = data.get(tag)

        if value is None:
            continue

        tag_counts[tag] += 1
        tag_values[tag][str(value)] += 1

print("\n=== 16.3 追加属性確認 ===")

print("総エッジ数:", len(graph.edges))

for tag in additional_tags:
    print(
        f"{tag}: {tag_counts[tag]}件"
    )

print("\n【sidewalk の値】")

for tag in [
    "sidewalk",
    "sidewalk:left",
    "sidewalk:right",
    "sidewalk:both",
]:
    print(f"\n{tag}")

    for value, count in tag_values[
        tag
    ].most_common(10):
        print(
            f"  {value}: {count}"
        )

print("\n【lanes の値】")

for value, count in tag_values[
    "lanes"
].most_common(10):
    print(f"  {value}: {count}")

print("\n【maxspeed の値】")

for value, count in tag_values[
    "maxspeed"
].most_common(10):
    print(f"  {value}: {count}")
