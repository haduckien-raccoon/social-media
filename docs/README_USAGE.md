# Hướng Dẫn Sử Dụng

## UI Demo
- Home: `http://127.0.0.1:8001/`
- Realtime social demo: `http://127.0.0.1:8001/demo/realtime/`
- Tài liệu UI chi tiết: `docs/README_UI_USAGE.md`
- Tài liệu test manual/unit UI: `docs/README_UI_TESTING.md`

## 1) API Realtime v1
Base URL: `http://127.0.0.1:8001`

### Feed + Post
- `GET /api/v1/feed` (timeline từ bạn bè accepted + chính bạn)
- `POST /api/v1/posts` (hỗ trợ JSON hoặc `multipart/form-data` với `attachments` nhiều file)
- `GET /api/v1/posts`
- `GET /api/v1/posts/{post_id}`

### Comment
- `POST /api/v1/posts/{post_id}/comments`
- `GET /api/v1/posts/{post_id}/comments`
- `PATCH /api/v1/comments/{comment_id}` (edit trong 15 phút)
- `DELETE /api/v1/comments/{comment_id}` (soft delete)

### Reaction
- `PUT /api/v1/posts/{post_id}/reaction`
- `PUT /api/v1/comments/{comment_id}/reaction`
- Reaction type: `like,love,haha,wow,sad,angry`

## 2) WebSocket
Endpoint: `ws://127.0.0.1:8001/ws/realtime/`

Client action:
- `subscribe_feed`, `unsubscribe_feed`
- `subscribe_post`, `unsubscribe_post`
- `heartbeat`
- `typing_start`, `typing_stop`

Event envelope chuẩn:
```json
{
  "event": "comment.created",
  "post_id": 123,
  "data": {},
  "ts": "2026-04-06T00:00:00Z",
  "request_id": "client-req-1"
}
```

Event chính:
- `post.created.following`
- `comment.created|updated|deleted`
- `reaction.post.updated`, `reaction.comment.updated`
- `presence.snapshot|joined|left`
- `typing.started|stopped`

## 3) Attachment preview behavior
- `image`: render thumbnail/image block.
- `audio`: render audio player inline.
- `file`: render file card + size + open/download link.

## 4) Chạy benchmark query + fanout
```bash
docker compose -f docker/docker-compose.yml exec app \
  python manage.py benchmark_realtime_fanout --subscribers 50 200 --iterations 10 --query-iterations 20 --query-limit 200
```

## 5) Chạy test
```bash
docker compose -f docker/docker-compose.yml exec app python manage.py test apps.posts.tests apps.core.tests_ui
```
