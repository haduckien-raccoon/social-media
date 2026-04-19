# Code Inventory (Phân Loại File)

## 1. Core business code
### Accounts
- `apps/accounts/models.py`
- `apps/accounts/services.py`
- `apps/accounts/views.py`
- `apps/accounts/urls.py`

### Friends
- `apps/friends/models.py`
- `apps/friends/services.py`
- `apps/friends/views.py`
- `apps/friends/urls.py`

### Posts
- `apps/posts/models.py`
- `apps/posts/services.py`
- `apps/posts/views.py`
- `apps/posts/consumers.py`
- `apps/posts/urls.py`
- `apps/posts/migrations/`

### Groups
- `apps/groups/models.py`
- `apps/groups/services.py`
- `apps/groups/views.py`
- `apps/groups/urls.py`

### Notifications
- `apps/notifications/models.py`
- `apps/notifications/services.py`
- `apps/notifications/signals.py`
- `apps/notifications/views.py`
- `apps/notifications/urls.py`

## 2. Runtime hệ thống
- `config/settings.py`
- `config/asgi.py`
- `config/urls.py`
- `apps/middleware/jwt_auth.py`
- `apps/middleware/utils.py`

## 3. Giao diện (templates)
- `templates/base.html`
- `templates/posts/*.html`
- `templates/groups/*.html`
- `templates/accounts/*.html`
- `templates/notifications/list.html`

## 4. Docker / deploy
- `docker/Dockerfile`
- `docker/docker-compose.yml`
- `docker/entrypoint.sh`
- `docker/.env.docker.example`
- `docker/.env.docker`

## 5. Test code
### Accounts
- `apps/accounts/test_accounts_services.py`

### Friends
- `apps/friends/test_friends_notifications.py`

### Posts
- `apps/posts/test_posts_services.py`

### Groups
- `apps/groups/test_groups_posts_notifications.py`

### Notifications
- `apps/notifications/test_notifications_sse.py`
- `apps/notifications/test_notifications_views.py`

### Middleware
- `apps/middleware/test_jwt_auth_middleware.py`

## 6. Documentation files
- `README.md`
- `docs/01-manual-run.md`
- `docs/02-docker-run.md`
- `docs/03-deploy.md`
- `docs/04-testing.md`
- `docs/05-feature-summary.md`
- `docs/06-system-flow-overview.md`
- `docs/07-functional-flows-detailed.md`
- `docs/08-code-inventory.md`
