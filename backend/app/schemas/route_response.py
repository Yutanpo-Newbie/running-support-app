#Backend to frontend(response)
from pydantic import BaseModel
from typing import List, Literal

class RoutePoint(BaseModel):
    lat: float
    lon: float

class TurnPoint(BaseModel):
    lat: float
    lon: float
    direction: Literal["left", "right", "straight"]
    instruction: str

class GeoJsonLineString(BaseModel):
    type: Literal["LineString"]
    coordinates: List[List[float]]

class RouteCandidate(BaseModel):
    id: str
    name: str
    distance_km: float
    elevation_gain_m: float
    signals: int
    intersections: int
    traffic_score: float
    total_score: float
    coordinates: List[RoutePoint]
    geometry: GeoJsonLineString
    turn_points: List[TurnPoint]

class RouteResponse(BaseModel):
    routes: List[RouteCandidate]