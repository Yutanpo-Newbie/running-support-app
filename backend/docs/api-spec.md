# Running Support App Backend API Specification

## 概要

本APIは、ランニングサポートアプリにおけるルート提案機能を提供する。

フロントエンド側でユーザーが指定した現在地、希望走行距離、ルート条件をバックエンドに送信し、バックエンド側で複数のルート候補を生成・評価して返す。

---

## エンドポイント一覧

| メソッド | パス | 内容 |
|---|---|---|
| GET | `/` | API起動確認 |
| POST | `/api/routes/suggest` | ランニングルート候補を提案 |

---

## GET `/`

### 概要

APIサーバーが起動しているか確認する。

### レスポンス例

```json
{
  "message": "Running Support App Backend is running"
}