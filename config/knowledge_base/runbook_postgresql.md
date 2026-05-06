# Runbook: Xử lý sự cố Database PostgreSQL
Mô tả: Sử dụng khi cổng 5432 không phản hồi hoặc ứng dụng báo lỗi "Connection Refused"

## Các bước kiểm tra:
1. Sử dụng tool `check_db_connection` để kiểm tra khả năng kết nối trực tiếp.
2. Sử dụng tool `get_system_metrics` để kiểm tra Disk Usage (Ổ đĩa đầy thường làm DB bị crash).
3. Sử dụng tool `read_service_logs` với `service_name="postgresql"` để tìm lỗi "FATAL: password authentication failed" hoặc "too many connections".


## Hướng xử lý đề xuất:
- Nếu ổ đĩa đầy (>90%), gọi tool `clean_temp_logs` để dọn dẹp trước.
- Nếu quá nhiều kết nối, đề xuất: `Tăng max_connections hoặc kiểm tra Connection Pool`.
- Nếu service bị tắt, đề xuất hành động: `restart_postgresql`.


