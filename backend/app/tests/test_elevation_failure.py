
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import osm_client
from app.services.elevation_client import (
    ElevationDataUnavailable,
)


client = TestClient(app)


def test_elevation_failure_all_candidates(
    monkeypatch,
):
    # 今回のテストでは、候補生成そのものを
    # モックして単体テストに切り分ける。
    # 全候補の標高取得失敗を再現するため、
    # 標高計算関数が必ず例外を出すようにする。

    def mock_elevation_failure(coordinates):
        raise ConnectionError(
            "標高サービス接続失敗（テスト）"
        )

    monkeypatch.setattr(
        osm_client,
        "get_route_elevation_gain",
        mock_elevation_failure,
    )

    # 注意：
    # このテストだけではOSMnxのルート生成まで
    # 実行するため、実道路データに依存する。
    # テスト地点にルートがある場合の確認用。
    from app.schemas.route_request import RouteRequest
    from app.services.route_service import (
        generate_osmnx_routes,
    )

    request = RouteRequest(
        start={
            "lat": 35.8721,
            "lon": 140.0106,
        },
        distance_km=2.0,
        preferences={
            "avoid_traffic": True,
            "avoid_signals": True,
            "avoid_intersections": True,
            "elevation_mode": "low",
        },
    )

    with pytest.raises(ElevationDataUnavailable):
        generate_osmnx_routes(request)


from app.api import routes as routes_api


def test_api_returns_503_on_elevation_failure(
    monkeypatch,
):
    def mock_generate_osmnx_routes(request):
        raise ElevationDataUnavailable(
            "全ルート候補の標高取得に失敗しました"
        )

    monkeypatch.setattr(
        routes_api,
        "generate_osmnx_routes",
        mock_generate_osmnx_routes,
    )

    request_body = {
        "start": {
            "lat": 35.8721,
            "lon": 140.0106,
        },
        "distance_km": 2.0,
        "preferences": {
            "avoid_traffic": True,
            "avoid_signals": True,
            "avoid_intersections": True,
            "elevation_mode": "low",
        },
    }

    response = client.post(
        "/api/routes/suggest",
        json=request_body,
    )

    assert response.status_code == 503

    assert (
        "標高取得に失敗"
        in response.json()["detail"]
    )

