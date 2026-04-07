# Social Media Backend

Realtime backend cho post/comment/reaction/online-comment với Django + Channels + Redis.

## Chạy nhanh (MySQL Only, 1 lệnh)
```bash
docker compose -f docker/docker-compose.yml up --build
```

App chạy tại:
- HTTP API: `http://127.0.0.1:8001`
- WebSocket: `ws://127.0.0.1:8001/ws/realtime/`
- Container app vẫn listen nội bộ trên port `8080` (mapping host `8001 -> 8080`).

## UI/UX mới
- Giao diện đã được đồng bộ theo một design system xuyên suốt giữa Home/Auth/Friends/Realtime Demo.
- Tông màu chính: `#6a5af9`, style card + form + button nhất quán, có trạng thái focus/hover/error rõ ràng.
- Realtime demo mới theo bố cục social timeline:
  - Following feed realtime từ `Friendship=accepted`.
  - Composer hỗ trợ upload `image/audio/file` + preview hợp lý.
  - Comment/reaction sync realtime hai chiều sender/receiver.
  - Dev stream chuyển sang drawer toggle, không làm rối màn hình demo chính.
- Tài liệu UI usage/testing cập nhật tại:
  - `docs/README_UI_USAGE.md`
  - `docs/README_UI_TESTING.md`

## Tài liệu chính
- README cài đặt: `docs/README_INSTALL.md`
- README sử dụng: `docs/README_USAGE.md`
- Bản chi tiết cài đặt: `docs/INSTALL.md`
- Bản chi tiết sử dụng: `docs/USAGE.md`
- README sử dụng UI demo: `docs/README_UI_USAGE.md`
- README test UI manual/unit: `docs/README_UI_TESTING.md`
- Thiết kế hệ thống realtime: `docs/realtime_system.md`

## Test
```bash
docker compose -f docker/docker-compose.yml exec app python manage.py test apps.posts.tests
```

Kiểm tra riêng UI route/template:
```bash
docker compose -f docker/docker-compose.yml exec app python manage.py test apps.core.tests_ui
```

Smoke Docker runtime (API + WS probe):
```bash
RUN_DOCKER_SMOKE=1 docker compose -f docker/docker-compose.yml exec app \
  python manage.py test apps.posts.tests.test_docker_smoke.DockerComposeRuntimeSmokeTests
```

## Benchmark
```bash
docker compose -f docker/docker-compose.yml exec app \
  python manage.py benchmark_realtime_fanout --subscribers 50 200 --iterations 10 --query-iterations 20 --query-limit 200
```
