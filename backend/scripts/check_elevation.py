
from app.services.elevation_client import (
    get_elevation,
)

# これまでのルート生成テスト地点
TEST_POINTS = [
    {
        "name": "START地点",
        "lat": 35.8721,
        "lon": 140.0106,
    },
    {
        "name": "ルート中間地点A",
        "lat": 35.8695615,
        "lon": 140.0118004,
    },
    {
        "name": "ルート中間地点B",
        "lat": 35.8655564,
        "lon": 140.0123754,
    },
]


def main():

    print("=== 標高取得テスト ===")

    for point in TEST_POINTS:

        try:
            elevation = get_elevation(
                lat=point["lat"],
                lon=point["lon"],
            )

            print(
                f'{point["name"]}: '
                f'{elevation:.2f} m'
            )

        except Exception as error:
            print(
                f'{point["name"]}: '
                f"取得失敗 - {error}"
            )


if __name__ == "__main__":
    main()
