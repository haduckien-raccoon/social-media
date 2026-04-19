# SUDO Social Platform

SUDO là ứng dụng mạng xã hội realtime (Django + Channels) với các module chính:
- Accounts (register/login/profile)
- Friends
- Posts (create/share/comment/reaction/tag)
- Groups
- Notifications (SSE realtime)

## Quick Start

### 1) Chạy nhanh bằng Docker (khuyến nghị)
```bash
docker compose -f docker/docker-compose.yml up --build -d
```
App: `http://localhost:8080`

Chạy test trong Docker:
```bash
docker compose -f docker/docker-compose.yml run --rm test
```

Dừng stack:
```bash
docker compose -f docker/docker-compose.yml down
```

### 2) Chạy thủ công
Xem hướng dẫn chi tiết: [`docs/01-manual-run.md`](docs/01-manual-run.md)

## Bộ tài liệu đầy đủ
- Chạy thủ công: [`docs/01-manual-run.md`](docs/01-manual-run.md)
- Chạy Docker: [`docs/02-docker-run.md`](docs/02-docker-run.md)
- Hướng dẫn deploy: [`docs/03-deploy.md`](docs/03-deploy.md)
- Hướng dẫn test: [`docs/04-testing.md`](docs/04-testing.md)
- Tóm tắt chức năng: [`docs/05-feature-summary.md`](docs/05-feature-summary.md)
- Luồng tổng quát hệ thống: [`docs/06-system-flow-overview.md`](docs/06-system-flow-overview.md)
- Luồng chi tiết từng chức năng: [`docs/07-functional-flows-detailed.md`](docs/07-functional-flows-detailed.md)
- Danh mục file code (core/runtime/test/docs): [`docs/08-code-inventory.md`](docs/08-code-inventory.md)

## Runtime Contract (Env)
Các biến quan trọng:
- `APP_BASE_URL`
- `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST`, `MYSQL_PORT`
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`, `REDIS_SOCKET_TIMEOUT`, `REDIS_SOCKET_CONNECT_TIMEOUT`
- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`

File mẫu Docker env: [`docker/.env.docker.example`](docker/.env.docker.example)
