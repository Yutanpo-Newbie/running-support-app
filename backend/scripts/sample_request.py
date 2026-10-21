import json
import requests


API_URL = "http://127.0.0.1:8000/api/routes/suggest"


def main():
    request_body = {
        "start": {
            "lat": 35.8721,
            "lon": 140.0106,
        },
        "distance_km": 5.0,
        "preferences": {
            "avoid_traffic": True,
            "avoid_signals": True,
            "avoid_intersections": True,
            "elevation_mode": "low",
        },
    }

    response = requests.post(API_URL, json=request_body, timeout=10)

    print("Status Code:", response.status_code)

    if response.status_code != 200:
        print("Error Response:")
        print(response.text)
        return

    data = response.json()

    print("\nRoute Candidates:")
    for route in data["routes"]:
        print(
            f'- {route["id"]} / {route["name"]} / '
            f'distance={route["distance_km"]}km / '
            f'score={route["total_score"]}'
        )

    print("\nFull JSON Response:")
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()