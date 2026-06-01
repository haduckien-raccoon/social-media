# Hướng Dẫn Deploy

## 1. Mục tiêu triển khai
- Chạy ổn định với stack: `web + mysql + redis + neo4j`
- Tự migrate khi khởi động app
- Có healthcheck rõ ràng

## 2. Quy trình deploy chuẩn
1. Pull source mới nhất.
2. Cập nhật `docker/.env.docker` cho môi trường deploy.
3. Build và khởi chạy lại stack:
```bash
docker compose --env-file docker/.env.docker -f docker/docker-compose.yml up --build -d
```
4. Kiểm tra health/log:
```bash
docker compose --env-file docker/.env.docker -f docker/docker-compose.yml ps
docker compose --env-file docker/.env.docker -f docker/docker-compose.yml logs web --tail 200
```

## 3. Biến môi trường production khuyến nghị
- `DJANGO_DEBUG=False`
- `DJANGO_SECRET_KEY=<secret mạnh>`
- `DJANGO_ALLOWED_HOSTS=<domain thật,IP>`
- `APP_BASE_URL=https://<domain-thật>`
- `CHANNEL_LAYER_BACKEND=redis`
- `DJANGO_SERVE_STATIC=True` nếu chưa có reverse proxy/static server riêng
- `NEO4J_URI=neo4j://neo4j:7687`
- `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`

## 4. Reverse Proxy (khuyến nghị)
Deploy production nên đặt sau Nginx/Caddy:
- SSL/TLS termination
- forward `X-Forwarded-*`
- expose cổng 80/443 thay vì trực tiếp 8080

## 5. Rollback cơ bản
Nếu bản mới có sự cố:
1. Checkout về commit stable.
2. Rebuild lại container.
3. `docker compose --env-file docker/.env.docker -f docker/docker-compose.yml up --build -d`
4. Verify lại smoke test.
