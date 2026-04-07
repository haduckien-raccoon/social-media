# Cài Đặt (MySQL Only, 1 Lệnh Docker)

## Yêu cầu
- Cài Docker Desktop hoặc Docker Engine + Docker Compose plugin.
- Mở terminal tại root project.

## Chạy toàn bộ hệ thống
```bash
docker compose -f docker/docker-compose.yml up --build
```

Lệnh trên tự động:
- Build image ứng dụng Django.
- Khởi chạy MySQL + Redis.
- Chờ DB/Redis sẵn sàng.
- Chạy migration tự động.
- Start ASGI server bằng Daphne tại `http://127.0.0.1:8001`.
- App container vẫn chạy Daphne trên `8080` (host map `8001:8080`).
- Mount volume `media_data` để file upload (image/audio/file) không mất sau restart local.

## Dừng hệ thống
```bash
docker compose -f docker/docker-compose.yml down
```

## Dừng và xóa cả data volume
```bash
docker compose -f docker/docker-compose.yml down -v
```

## Chạy test trong container app
```bash
docker compose -f docker/docker-compose.yml exec app python manage.py test apps.posts.tests
```

## Chạy Docker runtime smoke test (tuỳ chọn)
Test này dựng full stack, chờ app healthy, probe API + WebSocket endpoint, rồi tự hạ stack.
```bash
RUN_DOCKER_SMOKE=1 docker compose -f docker/docker-compose.yml exec app \
  python manage.py test apps.posts.tests.test_docker_smoke.DockerComposeRuntimeSmokeTests
```

## Biến môi trường quan trọng (đã có default trong compose)
- `MYSQL_DATABASE`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_HOST`
- `MYSQL_PORT`
- `REDIS_URL`
- `APP_PUBLIC_BASE_URL`
- `LOG_FORMAT`
- `LOG_LEVEL`

## Troubleshooting
- App chưa lên vì DB chưa ready:
  - Xem log: `docker compose -f docker/docker-compose.yml logs -f mysql app`
- Lỗi `mysqlclient 2.2.1 or newer is required; you have 1.4.6`:
  - Nguyên nhân: image cũ còn dùng `PyMySQL` shim.
  - Cách xử lý:
    - `docker compose -f docker/docker-compose.yml down -v`
    - `docker compose -f docker/docker-compose.yml build --no-cache app`
    - `docker compose -f docker/docker-compose.yml up --build`
- Port host 8001 bị trùng:
  - App đang publish `8001:8080`, đổi host port `8001` trong `docker/docker-compose.yml` nếu bị trùng.
  - MySQL/Redis chỉ expose nội bộ Docker network, không map trực tiếp ra host.
- Cần reset sạch môi trường:
  - `docker compose -f docker/docker-compose.yml down -v`
  - Chạy lại `up --build`.
