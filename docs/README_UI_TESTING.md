# README UI Testing

## Mục tiêu
Checklist test cho UI social realtime mới, đảm bảo demo ổn định và không hồi quy backend realtime.

## 1) Unit test commands
### Chạy toàn bộ test
```bash
python manage.py test
```

### Chạy test UI route/template
```bash
python manage.py test apps.core.tests_ui
```

### Chạy test realtime module
```bash
python manage.py test apps.posts.tests
```

## 2) Manual test matrix

### A. Social feed + attachment preview
1. Vào `/demo/realtime/`, tạo post có text + ảnh.
2. Tạo post chỉ có audio file (không text).
3. Tạo post có file tài liệu (pdf/txt).
4. Verify preview:
   - ảnh hiển thị thumbnail,
   - audio hiển thị player,
   - file thường hiển thị file card + size.
5. Verify feed card counters hiển thị đúng comment/reaction count.

### B. Realtime 2 chiều (2 tab / 2 user)
1. User A và User B mở cùng màn realtime.
2. User B nhận được `post.created.following` khi user A đăng bài.
3. User A comment trực tiếp dưới post card trong feed (không cần mở detail), user B thấy cập nhật realtime.
4. User B reaction post/comment ở feed card, user A thấy cập nhật realtime.
5. Cả hai chọn cùng active post ở panel detail.
6. User A reply root comment, user B thấy realtime và mở thread replies được.
7. User B typing start/stop -> user A thấy trạng thái typing.
8. Verify không có duplicate update dù nhận event từ cả post room và feed room.

### C. Presence + reconnect
1. User A/B cùng mở một active post.
2. Verify `presence.snapshot` có viewers.
3. User B đóng tab hoặc đổi active post -> user A thấy `presence.left`.
4. Ngắt mạng hoặc restart app, bấm `Reconnect WS` -> trạng thái connected lại.

### D. Dev Stream drawer
1. Mặc định drawer đóng, màn hình business không bị rối.
2. Bấm `Dev Stream` để mở drawer.
3. Verify raw event log hiển thị event envelope và `request_id`.
4. Bấm close/backdrop để đóng drawer.

### E. Responsive + UX consistency
1. Desktop: feed + side panel hiển thị cân đối.
2. Tablet/mobile: layout xuống cột hợp lý, không tràn.
3. Tooltip help hiển thị khi hover icon `?` ở các phần khó.

## 3) Acceptance criteria
- Không có lỗi 500 ở flow demo chính (create post/comment/reaction/realtime).
- Feed following realtime hoạt động đúng với friendship accepted.
- Comment/reaction đồng bộ realtime ở cả sender và receiver, kể cả khi chỉ subscribe feed.
- Dev Stream drawer hoạt động độc lập, không ảnh hưởng luồng business.

## 4) Bug report mẫu
```text
[UI-BUG] <title>
- Environment: local/docker, browser
- Steps to reproduce:
  1) ...
  2) ...
- Actual:
- Expected:
- Evidence: screenshot/log/event payload
- Severity: blocker/high/medium/low
```
