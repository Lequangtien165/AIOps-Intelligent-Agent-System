# Runbook: Xử lý sự cố Docker & Containers
Mô tả: Sử dụng khi các container không thể khởi động hoặc Docker Daemon bị treo.

## Các bước kiểm tra:
1. Sử dụng tool `list_running_services` để xem danh sách các container đang chạy.
2. Sử dụng tool `get_system_metrics` để kiểm tra Disk Usage của phân vùng `/var/lib/docker`.

## Hướng xử lý đề xuất: 
- Nếu Docker Daemon chết, đề xuất hành động: `restart_docker`.
- Nếu hết bộ nhớ đệm container, đề xuất: `Chạy lệnh docker system prune để dọn dẹp`.
- Nếu container cụ thể bị crash liên tục, đề xuất: ` Kiểm tra Dockerfile hoặc Entrypoint`.
