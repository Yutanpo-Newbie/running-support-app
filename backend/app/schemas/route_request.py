#Frontend to backend(request)
from pydantic import BaseModel, Field

class StartPoint(BaseModel):
    lat: float = Field(..., description="緯度")
    lon: float = Field(..., description="経度")

class RoutePreferences(BaseModel):
    avoid_traffic: bool = True
    avoid_signals: bool = True
    avoid_intersections: bool = True
    elevation_mode: str = "low" # low / normal / high

class RouteRequest(BaseModel):
    start: StartPoint
    distance_km: float = Field(..., gt=0, description="希望走行距離 km")
    preferences: RoutePreferences
    