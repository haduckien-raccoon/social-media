# Hướng Dẫn Chạy Thủ Công

## 1. Yêu cầu
- Python 3.10+ (khuyến nghị 3.12)
- MySQL 8+
- Redis 7+
- Pip

## 2. Cài dependencies
```bash
pip install -r requirements.txt
```

## 3. Cấu hình env
Tạo file `.env` ở thư mục gốc theo mẫu dưới đây:
```env
DJANGO_SECRET_KEY=dev-secret-key
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
APP_BASE_URL=http://127.0.0.1:8080

MYSQL_DATABASE=sudo_social
MYSQL_USER=sudo_user
MYSQL_PASSWORD=sudo_password
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306

REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0
REDIS_SOCKET_TIMEOUT=1
REDIS_SOCKET_CONNECT_TIMEOUT=1

CHANNEL_LAYER_BACKEND=redis
```

## 4. Migrate
```bash
python manage.py migrate
```

## 5. Chạy app
```bash
uvicorn config.asgi:application --host 127.0.0.1 --port 8080
```

Truy cập: `http://127.0.0.1:8080`

## 6. Chạy test
```bash
python manage.py test -v 2
```
