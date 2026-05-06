# Runbook: Xử lý sự cố Redis Cache
Mô tả: Sử dụng khi cổng 6379 bị đóng hoặc Celery không thể đẩy task vào hàng đợi.

## Các bước kiểm tra:
1. Sử dụng tool `check_redis_ping` để kiểm tra phản hồi tức thời.
2. Sử dụng tool `get_system_metrics` để xem RAM. Redis lưu dữ liệu trên RAM nên nếu RAM đầy (>95%), Redis sẽ ngừng hoạt động.
3. Sử dụng tool `list_running_services` để xác nhận process `redis-server` còn chạy không.

## Hướng xử lý đề xuất:
- Nếu RAM đầy, đề xuất hành động: `Giải phóng bộ nhớ hoặc tăng cấu hình RAM`.
- Nếu service bị stop, đề xuất hành động: `systemctl restart redis`.
