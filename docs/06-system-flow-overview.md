# Luồng Hoạt Động Tổng Quát

## 1. Kiến trúc runtime
- **Web**: Django ASGI (`uvicorn`) xử lý HTTP + WebSocket
- **MySQL**: dữ liệu nghiệp vụ
- **Redis**:
  - channel layer cho WebSocket
  - pub/sub cho SSE notifications

## 2. Sơ đồ tổng quan
```mermaid
flowchart LR
    U[User Browser] -->|HTTP| W[Django ASGI]
    U -->|WebSocket| W
    U -->|SSE| W

    W -->|ORM| DB[(MySQL)]
    W -->|Pub/Sub + Channel Layer| R[(Redis)]

    R -->|SSE event| W
    W -->|notification stream| U
    W -->|websocket event| U
```

## 3. Luồng request chuẩn
1. JWT middleware xác thực từ cookie `access/refresh`.
2. View gọi service xử lý nghiệp vụ.
3. Service ghi DB và phát event realtime khi cần.
4. UI nhận update qua WebSocket/SSE và render lại.

## 4. Luồng Docker startup
```mermaid
sequenceDiagram
    participant C as docker compose
    participant M as mysql
    participant R as redis
    participant W as web

    C->>M: start
    C->>R: start
    C->>W: start
    W->>M: wait until healthy
    W->>R: wait until healthy
    W->>W: python manage.py migrate
    W->>W: uvicorn config.asgi:application
```
