# Runbook: Xử lý sự cố Nginx Down
Mô tả: Sử dụng khi port 80 không phản hồi hoặc service nginx ở trạng thái inactive.

## Các bước kiểm tra:
1. Sử dụng tool `check_http_service` với url="http://localhost" để kiểm tra mã trạng thái HTTP.
2. Sử dụng tool `get_system_metrics` để xem CPU/RAM có bị quá tải không.
3. Sử dụng tool `read_service_logs` với tham số `service_name="nginx"` để tìm lỗi cấu hình.

## Hướng xử lý đề xuất:
- Nếu log báo "Address already in use", đề xuất kiểm tra process chiếm port.
- Nếu không có lỗi cấu hình rõ ràng, đề xuất hành động: `restart_nginx`.
- Nếu ổ đĩa đầy (>90%), gọi tool `clean_temp_logs` và thực hiện dọn dẹp log trước khi restart.
- Nếu gặp lỗi 502/504, kiểm tra kết nối đến Backend/App server.

## Lưu ý an toàn:
- Luôn xin phê duyệt trước khi restart trong giờ cao điểm.

<!--->
# Runbook: <Tên sự cố>
Mô tả: <Khi nào dùng runbook này>

## Các bước kiểm tra:
1. Gọi tool `get_system_metrics` để kiểm tra CPU/RAM.
2. Gọi tool `get_network_metrics` để kiểm tra packet loss.
3. Gọi tool `ping_host` với host="<địa chỉ>" để test connectivity.
4. Gọi tool `read_service_logs` với service_name="<tên>" để đọc log.

## Hướng xử lý đề xuất:
- Nếu <điều kiện A>, đề xuất hành động: `<action_name>`.
- Nếu <điều kiện B>, đề xuất hành động: `<action_name_2>`.

## Lưu ý an toàn:
- <Cảnh báo cụ thể>
<!--->