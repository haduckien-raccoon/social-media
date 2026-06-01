# Docker Compose Deploy Report

File nay tong hop quy trinh da ra soat va cach chay stack Docker Compose cho du an SUDO Social Platform.

## 1. Muc tieu

- Chay duoc ung dung Django ASGI bang mot lenh `docker compose`.
- Dong bo day du cac dich vu runtime: `web`, `mysql`, `redis`, `neo4j`.
- Tach cau hinh bang `docker/.env.docker`, khong dua secret va data runtime vao Docker image.
- Co volume rieng cho database, Redis, Neo4j, media upload, staticfiles va logs.

## 2. Cac file da chinh

- `docker/docker-compose.yml`: them Neo4j, sua port web ve `8080:8080`, bo override MySQL sai password, them volume runtime va healthcheck.
- `docker/entrypoint.sh`: tu dong `migrate` va `collectstatic` truoc khi start Uvicorn.
- `docker/.env.docker.example`: bo sung bien `DJANGO_SERVE_STATIC`, `COLLECT_STATIC` va Neo4j.
- `docker/.env.docker`: bo sung cac bien runtime con thieu cho stack hien tai.
- `.dockerignore`: loai `.git`, env that, database sqlite, logs, uploads, cache va dataset training lon khoi Docker build context; chi giu hai badwords JSON ma runtime dang doc.
- `requirements.txt`: sua dependency Neo4j ve package pip hop le `neo4j==6.2.0`.

## 3. Kien truc compose

| Service | Vai tro | Port |
| --- | --- | --- |
| `web` | Django ASGI/Uvicorn, tu dong migrate va collectstatic | `${WEB_PORT:-8080}:8080` |
| `mysql` | Database chinh | internal only |
| `redis` | Channel layer, SSE/cache/pubsub | internal only |
| `neo4j` | Graph recommendation/feed/friend suggestion | internal only |

`mysql`, `redis` va `neo4j` chi nam trong Docker network, khong publish ra host. Neu deploy sau Nginx/Caddy, reverse proxy nen forward vao `web:8080`.

## 4. Chay moi tu dau

Chay tai thu muc root cua project:

```bash
cp docker/.env.docker.example docker/.env.docker
```

Mo `docker/.env.docker` va doi cac gia tri bat buoc:

- `DJANGO_SECRET_KEY`
- `DJANGO_ALLOWED_HOSTS`
- `APP_BASE_URL`
- `WEB_PORT` neu port mac dinh `8080` tren host dang bi dung
- `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD`
- `NEO4J_AUTH`, `NEO4J_PASSWORD`
- thong tin SMTP neu can gui email that

Kiem tra compose:

```bash
docker compose --env-file docker/.env.docker -f docker/docker-compose.yml config --quiet
```

Build va start stack:

```bash
docker compose --env-file docker/.env.docker -f docker/docker-compose.yml up --build -d
```

Kiem tra trang thai:

```bash
docker compose --env-file docker/.env.docker -f docker/docker-compose.yml ps
docker compose --env-file docker/.env.docker -f docker/docker-compose.yml logs web --tail 200
```

Kiem tra health endpoint:

```bash
curl http://localhost:<WEB_PORT>/health/
```

Truy cap app:

```text
http://localhost:<WEB_PORT>
```

Mac dinh `WEB_PORT=8080`. Tren may hien tai neu cong `8080` da bi dung, dat `WEB_PORT=8081` va cap nhat `APP_BASE_URL` tuong ung.

## 5. Lenh van hanh

Xem log tung service:

```bash
docker compose --env-file docker/.env.docker -f docker/docker-compose.yml logs mysql --tail 100
docker compose --env-file docker/.env.docker -f docker/docker-compose.yml logs redis --tail 100
docker compose --env-file docker/.env.docker -f docker/docker-compose.yml logs neo4j --tail 100
docker compose --env-file docker/.env.docker -f docker/docker-compose.yml logs web --tail 100
```

Chay test trong Docker:

```bash
docker compose --env-file docker/.env.docker -f docker/docker-compose.yml run --rm test
```

Dung stack nhung giu data:

```bash
docker compose --env-file docker/.env.docker -f docker/docker-compose.yml down
```

Reset sach ca volume data:

```bash
docker compose --env-file docker/.env.docker -f docker/docker-compose.yml down -v
```

## 6. Checklist deploy production

- Dat `DJANGO_DEBUG=False`.
- Doi toan bo password mac dinh trong `docker/.env.docker`.
- Dat `DJANGO_ALLOWED_HOSTS` theo domain/IP deploy.
- Dat `APP_BASE_URL=https://<domain-that>`.
- Dat reverse proxy HTTPS truoc port `8080`.
- Backup volume `mysql_data`, `neo4j_data` va `media_data` truoc khi deploy ban moi.
- Khong commit `docker/.env.docker`; file nay chi dung tren may/server deploy.
- Neu can debug database tren host, nen tao compose override rieng de publish port tam thoi thay vi mo cong trong file deploy chinh.

## 7. Ghi chu ky thuat

- `docker/.env.docker` duoc Compose doc qua `env_file`, nhung khong duoc copy vao image do da nam trong `.dockerignore`.
- Static file duoc collect vao `/app/staticfiles`; media upload nam trong `/app/images`.
- Web container doi MySQL va Redis qua healthcheck compose. Neo4j co healthcheck rieng truoc khi web start.
- Driver Python dung package `neo4j==6.2.0`; code import `from neo4j import GraphDatabase`.
