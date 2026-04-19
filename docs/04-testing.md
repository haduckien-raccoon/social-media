# Hướng Dẫn Test

## 1. Chạy full suite
```bash
python manage.py test -v 2
```

## 2. Chạy theo module
### Accounts
```bash
python manage.py test apps.accounts.test_accounts_services -v 2
```

### Notifications (SSE + views)
```bash
python manage.py test apps.notifications.test_notifications_sse apps.notifications.test_notifications_views -v 2
```

### Middleware JWT
```bash
python manage.py test apps.middleware.test_jwt_auth_middleware -v 2
```

### Posts + Groups
```bash
python manage.py test apps.posts.test_posts_services apps.groups.test_groups_posts_notifications -v 2
```

## 3. Chạy test trong Docker
```bash
docker compose -f docker/docker-compose.yml run --rm test
```

Kỳ vọng kết quả cuối:
- `Ran <N> tests`
- `OK`

Sau khi test xong, kiểm tra app vẫn chạy:
```bash
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.yml logs web --tail 80
```

## 4. Checklist regression quan trọng
- Create post: text-only, media-only, text+tag, media+tag+file
- Notification: list/open/read/count + SSE realtime
- Profile navigation: author/comment/share-author
- Reaction lifecycle: add/change/remove (bao gồm `wow`)
- Group post flow: pending/approved theo role
- Auth refresh flow: không rớt POST khi cần refresh access token
