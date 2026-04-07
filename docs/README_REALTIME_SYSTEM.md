# Realtime System Design: Post / Comment / Reaction / Online Comment

## 1) Kiến trúc tổng thể
- Stack: Django + DRF + Channels + Redis.
- Tách lớp rõ ràng:
- `views.py`: transport layer (HTTP JSON API).
- `services.py`: business logic + transaction + validation.
- `realtime.py`: chuẩn hóa event envelope và publish.
- `consumers.py`: websocket action handler.
- `presence.py`: online presence + typing state qua Redis TTL.

Luồng chuẩn giúp team debug nhanh vì mỗi lỗi thuộc một lớp trách nhiệm rõ ràng.

## 2) Luồng dữ liệu chính
### 2.0 Following feed + post attachments
1. User tạo post qua `POST /api/v1/posts` (JSON hoặc multipart với `attachments[]`).
2. Service validate giới hạn số file, kích thước, MIME/extension.
3. Sau commit DB, phát:
- `post.created` vào post room.
- `post.created.following` vào feed room của các user nằm trong friendship accepted + author.
4. Client subscribe feed bằng `subscribe_feed` sẽ nhận bài mới realtime ngay.

### 2.1 Comment create/update/delete
1. API nhận request và validate schema.
2. `services` chạy trong `transaction.atomic()`.
3. Counter (`comments_count`) cập nhật bằng `F()` để an toàn khi concurrent.
4. `transaction.on_commit()` publish event realtime sau khi DB commit thành công.

### 2.2 Reaction toggle/update
1. Tìm reaction hiện tại của `(user, target)`.
2. Cùng loại => unreact, khác loại => update, chưa có => create.
3. Counter (`reactions_count`) cập nhật bằng `F()`.
4. Re-aggregate summary theo reaction type và phát event tương ứng.

### 2.3 Online comment / presence / typing
1. Client subscribe vào post room qua websocket.
2. Presence lưu Redis key theo heartbeat TTL (mỗi connection có key riêng).
3. Snapshot viewers được trả về ngay khi subscribe.
4. `presence.joined` chỉ phát khi user online lần đầu trong room (hỗ trợ multi-tab).
5. `presence.left` chỉ phát khi user không còn connection active.
6. Typing dùng TTL ngắn + throttle để tránh spam event.

## 3) Vì sao chọn kiến trúc này
- `on_commit` tránh realtime “ảo” (event gửi đi nhưng DB rollback).
- Redis TTL giảm ghi DB liên tục cho trạng thái online.
- Service layer giúp code review và onboarding nhanh, giảm logic trùng trong view.
- Envelope event thống nhất `{event, post_id, data, ts, request_id}` giúp trace logs và client xử lý đồng nhất.

## 4) API contract (v1)
- `GET /api/v1/feed` (following timeline)
- `POST /api/v1/posts`
- `GET /api/v1/posts`
- `GET /api/v1/posts/{post_id}`
- `POST /api/v1/posts/{post_id}/comments`
- `GET /api/v1/posts/{post_id}/comments`
- `PATCH /api/v1/comments/{comment_id}` (edit trong 15 phút)
- `DELETE /api/v1/comments/{comment_id}` (soft delete)
- `PUT /api/v1/posts/{post_id}/reaction`
- `PUT /api/v1/comments/{comment_id}/reaction`

Reaction v1: `like,love,haha,wow,sad,angry`

Attachment metadata trả về trong post payload:
- `type`: `image|audio|file`
- `url`
- `name`
- `size`
- `content_type`
- `preview_kind`

## 5) WebSocket contract
Endpoint:
- `ws://<host>/ws/realtime/`

Client actions:
- `subscribe_feed`
- `unsubscribe_feed`
- `subscribe_post`
- `unsubscribe_post`
- `heartbeat`
- `typing_start`
- `typing_stop`

Server events:
- `post.created.following`
- `comment.created`
- `comment.updated`
- `comment.deleted`
- `reaction.post.updated`
- `reaction.comment.updated`
- `presence.snapshot`
- `presence.joined`
- `presence.left`
- `typing.started`
- `typing.stopped`

## 6) Tối ưu đã áp dụng
- Counter comment/reaction cập nhật bằng `F()` (giảm race condition).
- Unique constraint reaction `(user, post)` và `(user, comment)`.
- Index cho truy vấn list/aggregate thường gặp.
- Presence dùng TTL để tự expire khi client mất kết nối đột ngột.
- Fallback in-memory cho presence khi Redis unavailable (để local/test không bị chặn).

## 7) Vận hành & checklist
- Cần Redis chạy trước khi scale websocket đa instance.
- Nếu không có Redis, hệ thống vẫn chạy với fallback in-memory (không phù hợp production đa node).
- Khi điều tra lỗi realtime, ưu tiên trace theo `request_id` trong event envelope.

## 8) Hardening production đã bổ sung
- WebSocket rate-limit theo action (balanced profile) để chống spam:
- Typing giới hạn chặt hơn action thường.
- Heartbeat giới hạn riêng để tránh flood.
- Vượt ngưỡng trả `error` với `code=rate_limited`, vi phạm lặp lại có thể đóng kết nối.
- Structured logging JSON cho API + WS + service:
- Trường chuẩn: `request_id,user_id,post_id,connection_id,action,event,error_code,latency_ms`.
- Có middleware correlation để đồng bộ request-id giữa request HTTP và log backend.
- Benchmark command:
- `python manage.py benchmark_realtime_fanout`
- Đo cả query path (comments + reaction aggregate) và fanout path (group_send đến nhiều subscribers).

## 9) Docker one-command (MySQL only)
- Mặc định chạy toàn hệ thống bằng:
- `docker compose -f docker/docker-compose.yml up --build`
- Stack gồm: `app + mysql + redis`.
- Container app tự chạy `wait_for_db`, `wait_for_redis`, `migrate`, rồi start ASGI server.
