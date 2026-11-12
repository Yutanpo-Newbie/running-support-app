import json
import math
import time
from pathlib import Path
import requests

class ElevationDataUnavailable(Exception):
    """標高を取得できず、ルート評価を完了できない場合"""
    pass

# 国土地理院の標高取得サービス
GSI_ELEVATION_URL = (
    "https://cyberjapandata2.gsi.go.jp"
    "/general/dem/scripts/getelevation.php"
)


def get_elevation(
    lat: float,
    lon: float,
) -> float:
    """
    指定された緯度・経度から
    国土地理院の標高データを取得する。

    戻り値：標高（m）
    """

    params = {
        "lat": lat,
        "lon": lon,
        "outtype": "JSON",
    }

    response = requests.get(
        GSI_ELEVATION_URL,
        params=params,
        timeout=15,
    )

    response.raise_for_status()

    data = response.json()

    elevation = data.get("elevation")

    # 標高が取得できなかった場合
    if (
        elevation is None
        or elevation == "-----"
    ):
        raise ValueError(
            f"標高を取得できませんでした: "
            f"lat={lat}, lon={lon}"
        )

    return float(elevation)


# =====================================
# 16.4.2 標高キャッシュと累積上昇量
# =====================================

ELEVATION_CACHE_FILE = Path(
    "data/elevation_cache.json"
)

SAMPLE_INTERVAL_M = 100.0

# 標高の微小変化を無視する暫定閾値
ELEVATION_THRESHOLD_M = 1.0


def distance_m(point_a, point_b):
    """2地点間の直線距離（m）"""

    radius = 6371000.0

    lat1 = math.radians(point_a["lat"])
    lat2 = math.radians(point_b["lat"])

    dlat = lat2 - lat1
    dlon = math.radians(
        point_b["lon"] - point_a["lon"]
    )

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    return 2 * radius * math.asin(
        min(1.0, math.sqrt(a))
    )


def sample_route_points(
    coordinates,
    interval_m=SAMPLE_INTERVAL_M,
):
    """
    ルート座標列を約100m間隔でサンプリングする。
    """

    if not coordinates:
        return []

    sampled = [coordinates[0]]
    next_distance = interval_m
    walked_distance = 0.0

    for start, end in zip(
        coordinates[:-1],
        coordinates[1:],
    ):
        segment_length = distance_m(start, end)

        if segment_length <= 0:
            continue

        while (
            walked_distance + segment_length
            >= next_distance
        ):
            ratio = (
                next_distance - walked_distance
            ) / segment_length

            point = {
                "lat": (
                    start["lat"]
                    + (end["lat"] - start["lat"])
                    * ratio
                ),
                "lon": (
                    start["lon"]
                    + (end["lon"] - start["lon"])
                    * ratio
                ),
            }

            sampled.append(point)
            next_distance += interval_m

        walked_distance += segment_length

    if distance_m(sampled[-1], coordinates[-1]) > 1:
        sampled.append(coordinates[-1])

    return sampled


def load_elevation_cache():
    """保存済み標高データを読み込む"""

    if not ELEVATION_CACHE_FILE.exists():
        return {}

    with open(
        ELEVATION_CACHE_FILE,
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def save_elevation_cache(cache):
    """標高データを保存する"""

    ELEVATION_CACHE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = ELEVATION_CACHE_FILE.with_suffix(
        ".tmp"
    )

    with open(
        temporary_file,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(cache, file, indent=2)

    temporary_file.replace(ELEVATION_CACHE_FILE)


def calculate_elevation_gain(
    elevations,
    threshold_m=ELEVATION_THRESHOLD_M,
):
    """上り方向の標高差だけ合計する"""

    gain = 0.0

    for previous, current in zip(
        elevations[:-1],
        elevations[1:],
    ):
        difference = current - previous

        if difference >= threshold_m:
            gain += difference

    return round(gain, 2)


def get_route_elevation_gain(coordinates):
    """
    ルート上の標高を取得して
    累積上昇量を計算する。
    """

    sampled_points = sample_route_points(
        coordinates
    )

    if len(sampled_points) < 2:
        return 0.0

    cache = load_elevation_cache()
    elevations = []

    for point in sampled_points:

        cache_key = (
            f'{point["lat"]:.5f},'
            f'{point["lon"]:.5f}'
        )

        if cache_key in cache:
            elevation = float(cache[cache_key])

        else:
            elevation = get_elevation(
                lat=point["lat"],
                lon=point["lon"],
            )

            cache[cache_key] = elevation
            save_elevation_cache(cache)

            # 新規取得時の連続アクセスを抑える
            time.sleep(0.3)

        elevations.append(elevation)

    return calculate_elevation_gain(elevations)
