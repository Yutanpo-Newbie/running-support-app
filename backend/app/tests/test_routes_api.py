from fastapi.testclient import TestClient

import app.api.routes as routes_api
from app.main import app
from app.schemas.route_response import (
    RouteCandidate,
    RoutePoint,
    TurnPoint,
    GeoJsonLineString,
)


client = TestClient(app)


def mock_generate_osmnx_routes(request):
    return [
        RouteCandidate(
            id="osm_route_001",
            name="OSM実道路ルート候補1",
            distance_km=2.0,
            elevation_gain_m=0.0,
            signals=0,
            intersections=10,
            traffic_score=0.0,
            total_score=30.0,
            coordinates=[
                RoutePoint(lat=35.8721, lon=140.0106),
                RoutePoint(lat=35.8731, lon=140.0116),
                RoutePoint(lat=35.8721, lon=140.0106),
            ],
            geometry=GeoJsonLineString(
                type="LineString",
                coordinates=[
                    [140.0106, 35.8721],
                    [140.0116, 35.8731],
                    [140.0106, 35.8721],
                ],
            ),
            turn_points=[],
        ),
        RouteCandidate(
            id="osm_route_002",
            name="OSM実道路ルート候補2",
            distance_km=2.1,
            elevation_gain_m=0.0,
            signals=0,
            intersections=20,
            traffic_score=0.0,
            total_score=60.0,
            coordinates=[
                RoutePoint(lat=35.8721, lon=140.0106),
                RoutePoint(lat=35.8741, lon=140.0126),
                RoutePoint(lat=35.8721, lon=140.0106),
            ],
            geometry=GeoJsonLineString(
                type="LineString",
                coordinates=[
                    [140.0106, 35.8721],
                    [140.0126, 35.8741],
                    [140.0106, 35.8721],
                ],
            ),
            turn_points=[],
        ),
    ]


def test_suggest_routes_returns_200(monkeypatch):
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

    response = client.post("/api/routes/suggest", json=request_body)

    assert response.status_code == 200


def test_suggest_routes_returns_routes(monkeypatch):
    monkeypatch.setattr(
        routes_api,
        "ROUTE_ENGINE",
        "osmnx",
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

    response = client.post("/api/routes/suggest", json=request_body)
    data = response.json()

    assert "routes" in data
    assert len(data["routes"]) >= 1


def test_routes_have_osm_route_id_when_engine_is_osmnx(monkeypatch):
    monkeypatch.setattr(
        routes_api,
        "ROUTE_ENGINE",
        "osmnx",
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

    response = client.post("/api/routes/suggest", json=request_body)
    data = response.json()

    for route in data["routes"]:
        assert route["id"].startswith("osm_route_")

def test_routes_have_mock_route_id_when_engine_is_mock(monkeypatch):
    monkeypatch.setattr(
        routes_api,
        "ROUTE_ENGINE",
        "mock",
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

    response = client.post("/api/routes/suggest", json=request_body)
    data = response.json()

    for route in data["routes"]:
        assert route["id"].startswith("route_test")


def test_routes_have_geometry_linestring(monkeypatch):
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

    response = client.post("/api/routes/suggest", json=request_body)
    data = response.json()

    for route in data["routes"]:
        assert "geometry" in route
        assert route["geometry"]["type"] == "LineString"
        assert len(route["geometry"]["coordinates"]) >= 2


def test_routes_are_sorted_by_total_score(monkeypatch):
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

    response = client.post("/api/routes/suggest", json=request_body)
    data = response.json()

    scores = [
        route["total_score"]
        for route in data["routes"]
    ]

    assert scores == sorted(scores)