# API Reference

Backend Routerの実装から確認できるAPIです。全Endpointは`/api`配下です。

## Health

| Method | Endpoint | Response |
|---|---|---|
| GET | `/api/health` | `{"status":"ok","app":"Argus","version":"0.1.0"}` |

## Monitors

| Method | Endpoint | Request | Response |
|---|---|---|---|
| GET | `/api/monitors` | なし | `{"monitors": MonitorResponse[]}` |
| POST | `/api/monitors` | `MonitorCreate` | `MonitorResponse`、201 |
| GET | `/api/monitors/{monitor_id}` | なし | `MonitorResponse` |
| PATCH | `/api/monitors/{monitor_id}` | `MonitorUpdate` | `MonitorResponse` |
| DELETE | `/api/monitors/{monitor_id}` | なし | 204 |

### MonitorCreate

```json
{
  "name": "meter_001",
  "display_name": "第1工場 ガスメーター",
  "location": "第1工場"
}
```

### MonitorUpdate

`display_name`、`location`、`enabled`、`source`、`inference`を任意で含めます。

## Sources

| Method | Endpoint | Request | Response |
|---|---|---|---|
| POST | `/api/sources/check` | `VideoSourceInput` | `ConnectionCheckResponse` |
| GET | `/api/url-history` | なし | `{"items": UrlHistoryResponse[]}` |
| DELETE | `/api/url-history/{history_id}` | なし | 204 |

接続確認が成功し、`source_type`が`url`の場合、URL履歴を保存します。

## Cameras

| Method | Endpoint | Response |
|---|---|---|
| GET | `/api/cameras` | `{"cameras":[{"device_id": number, "label": string}]}` |

OpenCVのカメラ番号0〜4を探索します。

## Streams

| Method | Endpoint | Response |
|---|---|---|
| GET | `/api/monitors/{monitor_id}/snapshot` | `image/jpeg` |
| GET | `/api/monitors/{monitor_id}/stream` | `multipart/x-mixed-replace; boundary=frame` |

Runtimeが存在しない場合は409、最新フレームがない場合は503です。

