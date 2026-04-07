# README UI Usage

## Mục tiêu
Hướng dẫn demo giao diện social realtime mới theo flow dễ trình bày: feed following realtime, attachment preview, comment/reaction sync 2 chiều, và dev event stream dạng drawer.

## 1) Entry points
- Home: `http://127.0.0.1:8001/`
- Friends: `http://127.0.0.1:8001/friends/`
- Realtime demo: `http://127.0.0.1:8001/demo/realtime/`

## 2) Bố cục màn realtime
- **Create Post**: nhập nội dung + upload nhiều file (image/audio/file).
- **Following Feed**: timeline bài từ bạn bè accepted + chính bạn, cập nhật realtime.
- **Post-level interactions**: comment/reply/react/edit/delete trực tiếp dưới từng post card.
- **Latest comments preview**: feed chỉ hiển thị 5 root comments gần nhất, replies không hiển thị ở list.
- **Post Detail Thread**: mở chi tiết để xem full thread, có nút mở/đóng replies theo từng root comment.
- **Presence & Typing**: online viewers + typing indicator.
- **Dev Stream**: mở bằng nút `Dev Stream` để xem raw websocket event và thao tác subscribe kỹ thuật.

## 3) Script demo 5-10 phút
1. Login user A và user B ở 2 tab.
2. Từ user A, tạo bài viết kèm file (ảnh/audio/file bất kỳ).
3. Ở tab user B, quan sát feed nhận bài mới realtime (`post.created.following`) không cần refresh.
4. User A tạo root comment ngay dưới post trong feed, user B thấy realtime mà không cần refresh.
5. User B bấm icon reply dưới root comment để mở ô reply inline và gửi reply.
6. User A bấm icon react/edit/delete dưới comment để xác nhận các thao tác inline.
7. Mở `Open detail` để vào panel chi tiết post, bật/tắt replies theo từng root comment.
8. User B bấm `Typing start` rồi `Typing stop`, user A thấy trạng thái typing.
9. Mở `Dev Stream` để show envelope event + `request_id`, sau đó đóng drawer để quay lại business view.

## 4) Hành vi preview tệp
- Image: hiển thị khung ảnh preview trực tiếp trong card post.
- Audio: hiển thị audio player inline.
- File khác: hiển thị file card với tên + dung lượng + open/download.

## 5) Notes cho demo mượt
- App tự subscribe feed và post room theo active post, không cần thao tác subscribe thủ công mỗi lần.
- Feed room cũng nhận event comment/reaction (`*.following`) nên list post cập nhật realtime ngay cả khi chưa mở chi tiết post.
- Khi đổi active post, presence list cũng đổi theo room mới.
- Nếu websocket rớt, dùng `Reconnect WS` để nối lại nhanh.
