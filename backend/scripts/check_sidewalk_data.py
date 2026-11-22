
from pathlib import Path
from collections import Counter
import osmnx as ox

CACHE_DIR = Path("data/graph_cache")

graph_files = sorted(
    CACHE_DIR.glob("*.graphml"),
    key=lambda p: p.stat().st_mtime,
    reverse=True,
)

if not graph_files:
    print("GraphMLキャッシュが見つかりません")
    raise SystemExit(1)

print("使用するキャッシュ:", graph_files[0].name)

graph = ox.load_graphml(graph_files[0])

highway_counts = Counter()
sidewalk_counts = Counter()
footway_counts = Counter()

for _, _, _, data in graph.edges(keys=True, data=True):
    highway = data.get("highway", "unknown")
    sidewalk = data.get("sidewalk", "unknown")
    footway = data.get("footway", "unknown")

    if isinstance(highway, list):
        highway = ",".join(map(str, highway))

    if isinstance(sidewalk, list):
        sidewalk = ",".join(map(str, sidewalk))

    if isinstance(footway, list):
        footway = ",".join(map(str, footway))

    highway_counts[str(highway)] += 1
    sidewalk_counts[str(sidewalk)] += 1
    footway_counts[str(footway)] += 1

print("\n=== 道路種別 ===")
for name, count in highway_counts.most_common():
    print(f"{name}: {count}")

print("\n=== 歩道属性 ===")
for name, count in sidewalk_counts.most_common():
    print(f"{name}: {count}")

print("\n=== footway属性 ===")
for name, count in footway_counts.most_common():
    print(f"{name}: {count}")

print("\n=== 幹線道路のサンプル ===")
shown = 0

for _, _, _, data in graph.edges(keys=True, data=True):
    highway = data.get("highway", "")

    types = highway if isinstance(highway, list) else [highway]

    if any(
        t in ("primary", "secondary", "tertiary", "trunk")
        for t in types
    ):
        print({
            "highway": highway,
            "sidewalk": data.get("sidewalk"),
            "sidewalk:left": data.get("sidewalk:left"),
            "sidewalk:right": data.get("sidewalk:right"),
            "sidewalk:both": data.get("sidewalk:both"),
            "foot": data.get("foot"),
            "length": data.get("length"),
        })

        shown += 1

        if shown >= 10:
            break
