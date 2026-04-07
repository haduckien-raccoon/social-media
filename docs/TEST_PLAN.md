# Kế hoạch kiểm thử hệ thống Realtime Social Media

## 1. Tổng quan chiến lược kiểm thử

### 1.1 Các cấp độ kiểm thử

| Cấp độ | Mục tiêu | Phạm vi |
|--------|-----------|---------|
| **Unit Tests** | Kiểm thử logic nghiệp vụ riêng lẻ | Services, serializers, utils |
| **Integration Tests** | Kiểm thử tích hợp giữa các module | Views + Services, Consumer + Channel Layer |
| **End-to-End Tests** | Kiểm thử flow đầu-cuối | API → Service → WebSocket → Client |
| **Load Tests** | Đo hiệu năng dưới tải nặng | Fanout, API latency, throughput |

### 1.2 Testing Pyramid

```
           ┌─────────────┐
           │  E2E Tests  │  ← 10% (critical user flows)
          ┌──────────────┐
          │ Integration  │  ← 30% (API + WebSocket flows)
         ┌───────────────┐
         │  Unit Tests   │  ← 60% (services, serializers, utils)
        └───────────────┘
```

---

## 2. Unit Tests

### 2.1 Test Structure

```python
# apps/posts/tests/test_services.py
from django.test import TestCase
from apps.accounts.models import User
from apps.posts.services import create_post, create_comment

class PostServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="test", email="test@test.com", password="pass123")
    
    def test_create_post_success(self):
        post = create_post(author=self.user, content="Hello World")
        self.assertEqual(post.content, "Hello World")
        self.assertEqual(post.author, self.user)
```

### 2.2 Coverage Areas

**Services (`apps/posts/services.py`):**
- [ ] `create_post()` - tạo post thành công, validation
- [ ] `create_comment()` - tạo comment + reply, validation
- [ ] `update_comment()` - edit trong 15 phút, permission
- [ ] `soft_delete_comment()` - soft delete, counter update
- [ ] `set_post_reaction()` - toggle reaction, summary aggregation
- [ ] `set_comment_reaction()` - toggle reaction, summary aggregation

**Serializers (`apps/posts/serializers.py`):**
- [ ] `CreatePostSerializer` - validation content
- [ ] `CreateCommentSerializer` - validation content + parent_id
- [ ] `ReactionSerializer` - validation reaction_type

**Cache (`apps/posts/cache.py`):**
- [ ] `get_cached_post_reaction_summary()` - cache miss/ hit
- [ ] `set_cached_post_reaction_summary()` - cache write
- [ ] `invalidate_post_reaction_cache()` - cache invalidation

**Event Processor (`apps/posts/event_processor.py`):**
- [ ] `RealtimeEvent.to_dict()` - serialization
- [ ] `EventProcessor.validate()` - valid/invalid events
- [ ] `EventProcessor.is_duplicate()` - idempotency check
- [ ] `EventProcessor.process()` - full pipeline

**Presence (`apps/posts/presence.py`):**
- [ ] InMemory backend: subscribe, heartbeat, unsubscribe
- [ ] Online user ids retrieval

### 2.3 Chạy Unit Tests

```bash
# Tất cả tests
python manage.py test apps.posts.tests

# Chỉ services
python manage.py test apps.posts.tests.test_services

# Với coverage
coverage run --source=apps manage.py test apps.posts.tests
coverage report
```

---

## 3. Integration Tests

### 3.1 API Integration Tests

```python
# apps/posts/tests/test_views.py
from rest_framework.test import APITestCase
from rest_framework import status

class PostAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(...)
        self.client.force_authenticate(user=self.user)
    
    def test_create_post_via_api(self):
        response = self.client.post('/api/v1/posts/', {'content': 'Test'})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
```

### 3.2 WebSocket Integration Tests

```python
# apps/posts/tests/test_consumers.py
from channels.testing import WebsocketCommunicator
from channels.routing import URLRouter
from django.urls import re_path

class RealtimeConsumerTests(AsyncTestCase):
    async def test_subscribe_post(self):
        communicator = WebsocketCommunicator(
            application,
            '/ws/realtime/',
        )
        connected, subprotocol = await communicator.connect()
        self.assertTrue(connected)
        
        # Subscribe to post
        await communicator.send_json_to({
            'action': 'subscribe_post',
            'post_id': 1
        })
        
        response = await communicator.receive_json_from()
        self.assertEqual(response['event'], 'presence.snapshot')
        
        await communicator.disconnect()
```

### 3.3 Test Coverage Checklist

**API Endpoints:**
- [ ] POST /api/v1/posts - tạo post thành công
- [ ] GET /api/v1/posts - list posts với pagination
- [ ] GET /api/v1/posts/{id} - lấy post chi tiết
- [ ] POST /api/v1/posts/{id}/comments - tạo comment
- [ ] GET /api/v1/posts/{id}/comments - list comments
- [ ] PATCH /api/v1/comments/{id} - edit comment
- [ ] DELETE /api/v1/comments/{id} - soft delete
- [ ] PUT /api/v1/posts/{id}/reaction - toggle reaction
- [ ] PUT /api/v1/comments/{id}/reaction - toggle reaction

**WebSocket Actions:**
- [ ] subscribe_post - tham gia phòng
- [ ] unsubscribe_post - rời phòng
- [ ] heartbeat - refresh presence
- [ ] typing_start - bắt đầu gõ
- [ ] typing_stop - dừng gõ

**Error Cases:**
- [ ] Unauthorized access - 401
- [ ] Post not found - 404
- [ ] Invalid reaction type - 400
- [ ] Comment edit timeout - 400

---

## 4. End-to-End Tests

### 4.1 Realtime Flow Tests

```python
# apps/posts/tests/test_e2e.py
class RealtimeE2ETests(TransactionTestCase):
    """E2E tests yêu cầu real DB (TransactionTestCase)"""
    
    async def test_create_comment_triggers_websocket_event(self):
        # 1. Tạo user và post
        user = await self.create_user()
        post = await self.create_post(user)
        
        # 2. Kết nối WebSocket và subscribe
        comm = await self.connect_websocket(user)
        await comm.send_json_to({'action': 'subscribe_post', 'post_id': post.id})
        await comm.receive_json_from()  # presence.snapshot
        
        # 3. Tạo comment qua API
        response = self.client.post(
            f'/api/v1/posts/{post.id}/comments/',
            {'content': 'Test comment'}
        )
        self.assertEqual(response.status_code, 201)
        
        # 4. Verify WebSocket event nhận được
        event = await comm.receive_json_from(timeout=5)
        self.assertEqual(event['event'], 'comment.created')
        self.assertEqual(event['data']['comment']['content'], 'Test comment')
```

### 4.2 E2E Test Cases

| Test Case | Steps | Expected Result |
|-----------|-------|-----------------|
| **Tạo post → realtime notification** | 1. POST post 2. Verify WS event | `post.created` event received |
| **Thêm comment → realtime notification** | 1. Create post 2. Subscribe WS 3. POST comment | `comment.created` event with comment data |
| **Thích post → reaction update** | 1. Create post 2. Subscribe WS 3. PUT reaction | `reaction.post.updated` with summary |
| **User join/leave presence** | 1. Connect WS 2. Subscribe post 3. Disconnect | `presence.joined` then `presence.left` events |
| **Typing indicator** | 1. Subscribe 2. Send typing_start 3. Send typing_stop | `typing.started` then `typing.stopped` events |

### 4.3 Chạy E2E Tests

```bash
# Run all E2E tests
python manage.py test apps.posts.tests.test_e2e

# Run with verbose output
python manage.py test apps.posts.tests.test_e2e -v 2
```

---

## 5. Load Testing

### 5.1 Benchmark Commands

```bash
# Fanout benchmark - test broadcast performance
python manage.py benchmark_realtime_fanout \
    --subscribers 50 200 \
    --iterations 10

# Query benchmark - test API performance  
python manage.py benchmark_realtime_fanout \
    --query-iterations 20 \
    --query-limit 200
```

### 5.2 Metrics to Measure

| Metric | Target | Critical Threshold |
|--------|--------|-------------------|
| **API Latency (p50)** | < 100ms | > 500ms |
| **API Latency (p95)** | < 300ms | > 1000ms |
| **WebSocket Latency** | < 50ms | > 200ms |
| **Fanout Throughput** | > 1000 msg/s | < 500 msg/s |
| **CPU Usage** | < 70% | > 90% |
| **Memory (RSS)** | < 500MB | > 1GB |

### 5.3 Load Test Scenarios

**Scenario 1: Heavy Read**
- 1000 concurrent users
- GET /api/v1/posts (paginated)
- Measure: p50/p95 latency, throughput

**Scenario 2: Heavy Write**
- 100 concurrent users
- POST /api/v1/posts + comments + reactions
- Measure: write latency, DB load

**Scenario 3: Fanout Stress**
- 1 post, 200 subscribers
- Broadcast event to all
- Measure: broadcast latency, message loss

**Scenario 4: WebSocket Connections**
- 500 concurrent WS connections
- Subscribe to multiple posts
- Measure: connection stability, memory

### 5.4 Tools sử dụng

```bash
# K6 for HTTP load testing (example)
k6 run --vus 100 --duration 30s tests/api_load.js

# Custom Django management command (đã có)
python manage.py benchmark_realtime_fanout
```

---

## 6. Consistency Testing

### 6.1 Eventual Consistency Verification

```python
# Test eventual consistency between DB and realtime
def test_consistency_after_reaction(self):
    # 1. Create post
    post = create_post(author=user, content="Test")
    
    # 2. Add reaction via API
    result = set_post_reaction(user, post.id, "like")
    
    # 3. Verify DB state
    post.refresh_from_db()
    self.assertEqual(post.reactions_count, 1)
    
    # 4. Verify cached summary
    cached = get_cached_post_reaction_summary(post.id)
    self.assertEqual(cached['like'], 1)
```

### 6.2 Idempotency Testing

```python
def test_idempotency_on_duplicate_event(self):
    event = RealtimeEvent(EVENT_POST_CREATED, post_id=1, data={...})
    
    # First process - should succeed
    result1 = event_processor.process(event)
    self.assertTrue(result1)
    
    # Second process with same key - should be skipped
    result2 = event_processor.process(event)
    self.assertFalse(result2)
```

---

## 7. Test Environment Setup

### 7.1 Test Database Configuration

```python
# settings_test.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}
```

### 7.2 Fixtures

```python
# apps/posts/fixtures/test_data.json
[
  {
    "model": "accounts.user",
    "pk": 1,
    "fields": {
      "username": "testuser",
      "email": "test@test.com",
      "is_active": true
    }
  }
]
```

### 7.3 CI/CD Test Pipeline

```yaml
# .github/workflows/test.yml
name: Test Pipeline

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run migrations
        run: python manage.py migrate
      - name: Run unit tests
        run: python manage.py test apps.posts.tests.test_services
      - name: Run integration tests
        run: python manage.py test apps.posts.tests.test_views
      - name: Run E2E tests
        run: python manage.py test apps.posts.tests.test_e2e
      - name: Run linter
        run: flake8 apps/
```

---

## 8. Debugging và Troubleshooting

### 8.1 Test Failures Debugging

```python
# Sử dụng pdb để debug
def test_failing_case(self):
    import pdb; pdb.set_trace()
    ...

# Sử dụng pytest với traceback
python -m pytest apps/posts/tests/ -v --tb=long
```

### 8.2 Common Issues

| Issue | Nguyên nhân | Cách fix |
|-------|-------------|----------|
| WebSocket test timeout | Consumer not responding | Check `await` patterns |
| AssertionError on datetime | Timezone mismatch | Use `timezone.now()` |
| Transaction rollback | Using TestCase instead of TransactionTestCase | Use TransactionTestCase for DB ops |
| Redis connection error | Redis not available in tests | Use in-memory fallback |

### 8.3 Logging cho Tests

```python
# Enable debug logging trong tests
import logging
logging.getLogger('apps.posts').setLevel(logging.DEBUG)
```

---

## 9. Checklist trước khi Release

### 9.1 Pre-release Testing Checklist

- [ ] Tất cả unit tests pass (>80% coverage)
- [ ] Tất cả integration tests pass
- [ ] E2E flows hoạt động đúng
- [ ] Load test với 200 concurrent users pass
- [ ] API p50 latency < 100ms
- [ ] WebSocket latency < 50ms
- [ ] Không có memory leaks sau 10 phút chạy
- [ ] Rate limiting hoạt động đúng
- [ ] Idempotency không miss duplicates

### 9.2 Release Sign-off

```markdown
## Release Checklist

| Item | Status | Notes |
|------|--------|-------|
| Unit Tests | ✅ PASS | 85% coverage |
| Integration Tests | ✅ PASS | 15/15 passed |
| E2E Tests | ✅ PASS | 5/5 flows verified |
| Load Test | ✅ PASS | 200 users, p50<100ms |
| Security Scan | ✅ PASS | No vulnerabilities |
| Code Review | ✅ APPROVED | By: [Reviewer] |

**Approved for release: [Date]**
```

---

## 10. Tài liệu tham khảo

- Django Testing: https://docs.djangoproject.com/en/5.1/topics/testing/
- Channels Testing: https://channels.readthedocs.io/en/stable/testing.html
- k6 Load Testing: https://k6.io/docs/
- pytest-django: https://pytest-django.readthedocs.io/

---

*Document version: 1.0*
*Last updated: 2026-04-05*