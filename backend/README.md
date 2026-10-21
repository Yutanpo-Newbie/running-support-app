# Running Support App Backend

## 概要

本プロジェクトは、卒業研究で開発するランニングサポートアプリのバックエンドAPIである。

現在地または指定したスタート地点と希望走行距離、ユーザーの好み条件をもとに、複数のランニングルート候補を生成し、距離・高低差・信号数・交差点数・交通スコアなどを用いて評価する。

現段階では、OpenStreetMapやMapbox Trafficとは未接続であり、仮の周回ルート候補を生成してAPIレスポンスとして返す。

---

## 主な機能

- FastAPIによるバックエンドAPI
- ルート提案API `/api/routes/suggest`
- 現在地・希望距離・好み条件の受け取り
- 仮の周回ルート候補を3件生成
- ルート座標列から距離を計算
- 距離誤差・高低差・信号数・交差点数・交通スコアによる `total_score` 計算
- `total_score` が低い順にルート候補を並び替え
- Mapbox表示を想定したGeoJSON LineString形式の `geometry` を返却
- 分岐点案内用の `turn_points` を返却

---

## ルート生成エンジンの切り替え

本バックエンドでは、`.env` の `ROUTE_ENGINE` によってルート生成方式を切り替える。

```env
ROUTE_ENGINE=mock

---


```md
## 現段階の到達点

現段階では、バックエンドAPIとして以下を実装済みである。

- FastAPIによるルート提案API
- リクエストスキーマ・レスポンススキーマ
- 仮ルート生成
- OSMnxによる実道路ネットワーク取得
- 最寄り道路ノード取得
- 候補ノード取得
- 実道路に沿った往復型ルート生成
- ルート距離計算
- GeoJSON LineString形式での返却
- `total_score` によるルート候補の並び替え
- mock版 / osmnx版の切り替え
- pytestによるテスト
- API仕様書・アルゴリズム仕様書・データソース整理

これにより、Swift + Mapbox Maps SDK側へ渡せる形式で、実道路ルート候補を返せる状態になった。


## ディレクトリ構成 2026/08/01時点

```text
running-support-app-backend/
├── app/
│   ├── main.py
│   ├── api/
│   │   └── routes.py
│   ├── schemas/
│   │   ├── route_request.py
│   │   └── route_response.py
│   ├── services/
│   │   └── route_service.py
│   ├── algorithms/
│   │   ├── waypoint_generator.py
│   │   └── scoring.py
│   └── utils/
│       └── geo.py
├── tests/
│   ├── test_geo.py
│   ├── test_scoring.py
│   └── test_routes_api.py
├── docs/
│   └── api-spec.md
├── scripts/
│   └── sample_request.py
├── requirements.txt
├── README.md
├── .env
└── .env.example
