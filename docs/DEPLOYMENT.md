# Hướng dẫn Triển khai và Vận hành

## Mục lục

1. [Môi trường và Yêu cầu](#1-môi-trường-và-yêu-cầu)
2. [Cấu hình Production](#2-cấu-hình-production)
3. [Triển khai Docker](#3-triển-khai-docker)
4. [Cấu hình Channel Layer](#4-cấu-hình-channel-layer)
5. [Tối ưu tài nguyên Realtime](#5-tối-ưu-tài-nguyên-realtime)
6. [Monitoring và Logging](#6-monitoring-và-logging)
7. [Bảo mật](#7-bảo-mật)
8. [Backup và Restore](#8-backup-và-restore)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Môi trường và Yêu cầu

### 1.1 Yêu cầu hệ thống

| Thành phần | Phiên bản tối thiểu | Ghi chú |
|------------|---------------------|---------|
| Python | 3.10+ | Khuyến nghị 3.11 |
| Django | 3.2+ | LTS recommended |
| MySQL | 8.0+ | |
| Redis | 6.0+ | |
| Docker | 20.10+ | |
| Docker Compose | 2.0+ | |

### 1.2 Resource Requirements

| Môi trường | CPU | RAM | Storage |
|------------|-----|-----|---------|
| Development | 2 cores | 4GB | 20GB |
| Staging | 4 cores | 8GB | 50GB |
| Production | 8 cores | 16GB | 100GB |

---

## 2. Cấu hình Production

### 2.1 Environment Variables

```bash
# .env file for production

# Django
DJANGO_SECRET_KEY=your-production-secret-key-at-least-50-chars
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=yourdomain.com,api.yourdomain.com

# Database
MYSQL_DATABASE=social_media
MYSQL_USER=social_user
MYSQL_PASSWORD=strong-password-here
MYSQL_HOST=mysql.internal
MYSQL_PORT=3306

# Redis
REDIS_URL=redis://redis.internal:6379/1

# Logging
LOG_FORMAT=json
LOG_LEVEL=INFO

# Rate Limiting
WS_RATE_WINDOW_SECONDS=10
WS_RATE_MAX_MESSAGES=20
WS_RATE_TYPING_MAX=8

# Presence TTL (seconds)
PRESENCE_TTL_SECONDS=30
PRESENCE_GRACE_SECONDS=30

# Email (production)
EMAIL_HOST=smtp.sendgrid.net
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=apikey
EMAIL_HOST_PASSWORD=your-sendgrid-api-key
```

### 2.2 Security Checklist

```bash
# Generate secure secret key
python -c "import secrets; print(secrets.token_urlsafe(50))"

# Set proper permissions
chmod 600 .env
chmod 600 config/settings/production.py
```

---

## 3. Triển khai Docker

### 3.1 Docker Compose Configuration

```yaml
# docker/docker-compose.prod.yml
services:
  app:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    environment:
      - DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY}
      - DJANGO_DEBUG=False
      - MYSQL_HOST=${MYSQL_HOST}
      - REDIS_URL=${REDIS_URL}
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 8G
        reservations:
          cpus: '2'
          memory: 4G
    healthcheck:
      test: ["CMD", "python", "manage.py", "health_check"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 2G

  mysql:
    image: mysql:8.0
    environment:
      - MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD}
      - MYSQL_DATABASE=${MYSQL_DATABASE}
      - MYSQL_USER=${MYSQL_USER}
      - MYSQL_PASSWORD=${MYSQL_PASSWORD}
    volumes:
      - mysql_data:/var/lib/mysql
    command: --default-authentication-plugin=mysql_native_password --max-connections=500
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
```

### 3.2 Deployment Commands

```bash
# Build và start production
docker compose -f docker/docker-compose.prod.yml up -d --build

# Check status
docker compose -f docker/docker-compose.prod.yml ps

# View logs
docker compose -f docker/docker-compose.prod.yml logs -f app

# Restart services
docker compose -f docker/docker-compose.prod.yml restart app

# Stop và remove
docker compose -f docker/docker-compose.prod.yml down
```

### 3.3 Health Check

```python
# apps/core/management/commands/health_check.py
from django.core.management.base import BaseCommand
from django.db import connection
from django.core.cache import cache
import redis


class Command(BaseCommand):
    def handle(self, *args, **options):
        checks = []
        
        # DB check
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            checks.append(("database", True, None))
        except Exception as e:
            checks.append(("database", False, str(e)))
        
        # Redis check
        try:
            r = redis.from_url(cache.client._server)
            r.ping()
            checks.append(("redis", True, None))
        except Exception as e:
            checks.append(("redis", False, str(e)))
        
        failed = [name for name, ok, _ in checks if not ok]
        
        if failed:
            self.stderr.write(f"FAILED: {', '.join(failed)}")
            exit(1)
        
        self.stdout.write("OK")
```

---

## 4. Cấu hình Channel Layer

### 4.1 Redis Channel Layer

```python
# config/settings/production.py

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [os.getenv("REDIS_URL", "redis://127.0.0.1:6379/1")],
            "symmetric_encryption_keys": [os.getenv("CHANNEL_SECRET_KEY")],
            # Production tuning
            "capacity": 1000,
            "expiry": 60,
        }
    }
}
```

### 4.2 Multiple Workers

```bash
# Run multiple Daphne workers
daphne -b 0.0.0.0 -p 8000 config.asgi:application --workers 4
```

### 4.3 WebSocket Scaling

```
                    ┌─────────────────┐
                    │  Load Balancer  │
                    │   (nginx/haproxy)│
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
   ┌─────────┐         ┌─────────┐         ┌─────────┐
   │Worker 1 │         │Worker 2 │         │Worker 3 │
   │Channel 1│◄────────│Channel 2│◄────────│Channel 3│
   └────┬────┘         └────┬────┘         └────┬────┘
        │                   │                   │
        └───────────────────┴───────────────────┘
                            │
                    ┌───────┴───────┐
                    │  Redis Pub/Sub │
                    │ (Event Fanout) │
                    └───────────────┘
```

---

## 5. Tối ưu tài nguyên Realtime

### 5.1 WebSocket Connection Management

```python
# settings.py - Connection tuning
WS_MAX_CONNECTIONS = 10000
WS_HEARTBEAT_INTERVAL = 30
WS_MESSAGE_QUEUE_SIZE = 100
```

### 5.2 Rate Limiting Configuration

```python
# Tối ưu rate limit cho production
WS_RATE_WINDOW_SECONDS = 10    # Cửa sổ 10s
WS_RATE_MAX_MESSAGES = 30      # Tăng lên nếu cần
WS_RATE_TYPING_MAX = 10        # Typing events
WS_RATE_HEARTBEAT_MAX = 20     # Heartbeats
WS_RATE_VIOLATION_CLOSE_THRESHOLD = 3  # Đóng sau 3 vi phạm
```

### 5.3 Presence TTL Tuning

```python
# Cân bằng giữa responsiveness và resource
PRESENCE_TTL_SECONDS = 30       # Timeout sau 30s không heartbeat
PRESENCE_GRACE_SECONDS = 15     # Thêm 15s grace period
# Tổng: 45s before marked offline
```

### 5.4 Connection Pooling

```python
# MySQL connection pooling
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.getenv("MYSQL_DATABASE"),
        "USER": os.getenv("MYSQL_USER"),
        "PASSWORD": os.getenv("MYSQL_PASSWORD"),
        "HOST": os.getenv("MYSQL_HOST"),
        "OPTIONS": {
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            "charset": "utf8mb4",
            "connect_timeout": 10,
            "read_timeout": 30,
            "write_timeout": 30,
        },
        "CONN_MAX_AGE": 60,  # Reuse connections
    }
}
```

### 5.5 Redis Connection

```python
# Redis connection tuning
REDIS_POOL_ARGS = {
    "max_connections": 50,
    "socket_timeout": 5,
    "socket_connect_timeout": 5,
    "retry_on_timeout": True,
    "health_check_interval": 30,
}
```

---

## 6. Monitoring và Logging

### 6.1 Structured Logging

```python
# settings.py - JSON logging
LOGGING = {
    "version": 1,
    "formatters": {
        "json": {
            "()": "apps.core.logging_utils.JSONLogFormatter"
        }
    },
    "handlers": {
        "json_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "/var/log/django/app.json",
            "maxBytes": 1024 * 1024 * 100,  # 100MB
            "backupCount": 10,
            "formatter": "json"
        }
    },
    "loggers": {
        "apps": {
            "handlers": ["json_file"],
            "level": "INFO",
            "propagate": False
        }
    }
}
```

### 6.2 Key Metrics to Monitor

| Metric | Alert Threshold | Description |
|--------|-----------------|-------------|
| API p95 latency | > 1000ms | Slow requests |
| WebSocket connections | > 8000 | High concurrency |
| Redis memory | > 80% | Memory pressure |
| DB connections | > 80% max | Connection pool full |
| Error rate | > 1% | Application errors |
| CPU usage | > 80% | Resource pressure |

### 6.3 Prometheus Metrics Example

```python
# apps/metrics.py
from django.utils import timezone
from django.db import connection


def get_db_metrics():
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 
                count(*) as total_connections,
                SUM(num_commands) as total_commands
            FROM performance_schema.events_statements_summary_by_account_by_event_name
        """)
        return dictfetchall(cursor)


def get_redis_info():
    r = redis.Redis.from_url(settings.REDIS_URL)
    return r.info()
```

### 6.4 Grafana Dashboard Metrics

```
# Dashboard panels:
1. Request Rate (requests/second)
2. Response Time (p50, p95, p99)
3. WebSocket Active Connections
4. Redis Memory Usage
5. Database Connections
6. Error Rate by Type
7. Active Users
```

---

## 7. Bảo mật

### 7.1 JWT Security

```python
# Access token - short lived
ACCESS_TOKEN_LIFETIME = timedelta(minutes=15)

# Refresh token - long lived
REFRESH_TOKEN_LIFETIME = timedelta(days=7)

# Token algorithm
JWT_ALGORITHM = "HS256"  # or RS256 for production

# Cookie security
COOKIE_ARGS = {
    "httponly": True,
    "secure": True,  # HTTPS only in production
    "samesite": "Lax",
    "max_age": 15 * 60,  # 15 minutes for access
}
```

### 7.2 WebSocket Authentication

```python
# Middleware validates JWT on every WebSocket connect
# Invalid/missing token → close with code 4401

# Event authorization - verify user can see post
def authorize_event(user, post_id):
    # Check if user has permission to view post
    # (friend-only, public, etc.)
    return True
```

### 7.3 Rate Limiting Security

```python
# Prevent DoS attacks
RATE_LIMIT_CONFIG = {
    "api_post_per_minute": 30,
    "api_comment_per_minute": 60,
    "ws_messages_per_10s": 30,
    "ws_connections_per_ip": 10,
}
```

### 7.4 CORS Configuration

```python
# settings.py
CORS_ALLOWED_ORIGINS = [
    "https://yourdomain.com",
    "https://app.yourdomain.com",
]
CORS_ALLOW_CREDENTIALS = True
```

---

## 8. Backup và Restore

### 8.1 Database Backup

```bash
# Daily backup script
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
mysqldump -h $MYSQL_HOST -u $MYSQL_USER -p$MYSQL_PASSWORD $MYSQL_DATABASE | gzip > /backup/db_$DATE.sql.gz

# Keep 7 days retention
find /backup -name "db_*.sql.gz" -mtime +7 -delete
```

### 8.2 Redis Backup

```bash
# RDB backup
redis-cli BGSAVE

# Or AOF
redis-cli CONFIG SET appendonly yes
```

### 8.3 Restore Procedure

```bash
# Restore MySQL
gunzip < db_20260405_120000.sql.gz | mysql -h $MYSQL_HOST -u $MYSQL_USER -p$MYSQL_PASSWORD $MYSQL_DATABASE

# Clear Redis cache after restore
redis-cli FLUSHDB
```

---

## 9. Troubleshooting

### 9.1 Common Issues

| Issue | Symptoms | Solution |
|-------|----------|----------|
| WebSocket connection refused | ws:// fails | Check publish `8001:8080` and Daphne listening on container port 8080 |
| Redis connection error | "Redis unavailable" | Check REDIS_URL, network |
| High latency | p95 > 1000ms | Profile DB queries, add indexes |
| Memory leak | RSS growing | Check WebSocket cleanup, restart workers |
| 500 errors on API | Internal server error | Check logs, DB connection |

### 9.2 Debug Commands

```bash
# Check Django process
docker compose exec app ps aux

# Check WebSocket connections
docker compose exec app python -c "
import redis
r = redis.Redis.from_url('redis://redis:6379/1')
print('Keys:', r.keys('presence:*'))
"

# Database query debug
docker compose exec app python manage.py dbshell
> SHOW PROCESSLIST;
> EXPLAIN SELECT * FROM posts_post WHERE ...

# Check channel layer
docker compose exec app python -c "
from channels.layers import get_channel_layer
layer = get_channel_layer()
print('Layer:', layer)
"
```

### 9.3 Emergency Procedures

```bash
# 1. Service down - restart
docker compose restart app

# 2. Database locked - kill connections
docker compose exec mysql mysql -e "KILL ALL CONNECTIONS;"

# 3. Redis OOM - flush cache (last resort)
redis-cli FLUSHALL

# 4. Rollback deployment
docker compose -f docker-compose.prod.yml down
git checkout previous-tag
docker compose -f docker-compose.prod.yml up -d
```

---

## Checklist trước Production

- [ ] `DJANGO_DEBUG=False`
- [ ] `DJANGO_SECRET_KEY` đã đổi (không default)
- [ ] ALLOWED_HOSTS configured đúng domain
- [ ] SSL/TLS enabled (HTTPS)
- [ ] Database backup đã test restore
- [ ] Health check endpoint hoạt động
- [ ] Monitoring/alerting configured
- [ ] Log rotation configured
- [ ] Rate limiting enabled
- [ ] JWT tokens có expiration properly set

---

*Document version: 1.0*
*Last updated: 2026-04-05*
