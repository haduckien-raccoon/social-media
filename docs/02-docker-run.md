# Hướng Dẫn Chạy Bằng Docker

## 1. Chuẩn bị env Docker
Copy file mẫu:
```bash
cp docker/.env.docker.example docker/.env.docker
```

Có thể chỉnh các biến trong `docker/.env.docker` nếu cần.

## 2. Start toàn bộ stack
```bash
docker compose -f docker/docker-compose.yml up --build -d
```

Stack gồm:
- `web` (Django ASGI + migrate tự động khi start)
- `mysql`
- `redis`

App chạy tại: `http://localhost:8080`

## 3. Kiểm tra trạng thái
```bash
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.yml logs web --tail 200
```

## 4. Chạy test trong Docker
```bash
docker compose -f docker/docker-compose.yml run --rm test
```

## 5. Stop stack
```bash
docker compose -f docker/docker-compose.yml down
```

## 6. Xóa cả data volume (nếu cần reset sạch)
```bash
docker compose -f docker/docker-compose.yml down -v
```

## 7. Troubleshooting nhanh
### Lỗi `exec /app/docker/entrypoint.sh: no such file or directory`
Nguyên nhân thường gặp trên Windows: file shell script dùng CRLF làm shebang bị lỗi khi chạy trong Linux container.

Hiện tại Dockerfile đã normalize line ending tự động trong bước build (`sed -i 's/\r$//' /app/docker/entrypoint.sh`).

Khi gặp lỗi này, chạy lại:
```bash
docker compose -f docker/docker-compose.yml up --build -d
docker compose -f docker/docker-compose.yml logs web --tail 120
```

### Kiểm tra stack đã khỏe
Kỳ vọng `web` có trạng thái `healthy`:
```bash
docker compose -f docker/docker-compose.yml ps
```
