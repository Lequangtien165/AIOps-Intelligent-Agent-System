# AIOps Intelligent Agent System

Hệ thống AI Agent hỗ trợ phát hiện, phân tích và đề xuất xử lý sự cố trong hạ tầng CNTT. Dự án kết hợp giữa monitoring (Prometheus), xử lý bất đồng bộ (Celery), và AI (RAG + LLM) để tự động hóa quy trình vận hành.

---

## 1. Giới thiệu

Trong các hệ thống hiện đại, việc theo dõi và xử lý sự cố thường tốn nhiều thời gian và phụ thuộc vào con người. Hệ thống này được xây dựng nhằm:

* Tự động tiếp nhận cảnh báo từ hệ thống monitoring
* Phân tích nguyên nhân bằng AI
* Đề xuất hướng xử lý phù hợp
* Cho phép người quản trị phê duyệt trước khi thực thi

---

## 2. Kiến trúc tổng thể

Hệ thống gồm các thành phần chính:

* **FastAPI (app)**: Nhận alert, điều phối xử lý
* **Celery (worker)**: Xử lý tác vụ bất đồng bộ
* **Redis**: Message broker và cache
* **PostgreSQL**: Lưu trữ dữ liệu
* **Prometheus + Alertmanager**: Giám sát và gửi cảnh báo
* **Telegram Bot**: Gửi thông báo và nhận phản hồi
* **Ngrok (tùy chọn)**: Expose webhook ra Internet

Các service được kết nối thông qua Docker network nội bộ.

---

## 3. Luồng hoạt động

1. Prometheus phát hiện bất thường và gửi alert
2. FastAPI nhận alert qua endpoint `/webhook`
3. Alert được đưa vào hàng đợi (Redis)
4. Celery worker xử lý và gọi AI để phân tích
5. Kết quả được gửi tới Telegram
6. Người dùng lựa chọn thực thi hoặc bỏ qua
7. Hệ thống thực hiện hành động và lưu lại kết quả

---

## 4. Cài đặt và chạy hệ thống

### 4.1 Chuẩn bị

Tạo file `.env` với các biến cần thiết:

```env
GEMINI_API_KEY=your_api_key
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
AI_AGENT_PUBLIC_URL=https://your-public-url

REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0

POSTGRES_PASSWORD=your_password
```

---

### 4.2 Khởi động bằng Docker

```bash
docker compose up --build
```

Sau khi khởi động:

* API: http://localhost:8000/docs
* Health check: http://localhost:8000/health
* Prometheus: http://localhost:9090

---

## 5. Lưu ý về kết nối nội bộ

Khi chạy bằng Docker:

* Không sử dụng `localhost` để kết nối giữa các service
* Sử dụng tên service, ví dụ:

  * `redis:6379`
  * `db:5432`

Điều này giúp các container giao tiếp đúng trong mạng nội bộ.

---

## 6. Các chức năng chính

Hệ thống hỗ trợ:

* Kiểm tra trạng thái service
* Phân tích log để tìm lỗi
* Kiểm tra kết nối mạng và port
* Đánh giá tình trạng tài nguyên (disk, memory)
* Đề xuất và thực thi hành động khắc phục

Các chức năng này được đóng gói thành các “tools” để AI sử dụng trong quá trình phân tích.

---

## 7. Monitoring và kiểm tra

Một số endpoint hữu ích:

```bash
GET /health     # trạng thái hệ thống
GET /metrics    # metrics cho Prometheus
```

Kiểm tra Redis:

```bash
docker exec -it redis redis-cli ping
```

Kiểm tra log:

```bash
docker compose logs -f app
docker compose logs -f worker
```

## Có thể test thử hệ thống bằng cách:

    Vào Powershell -> Activate venv --> Paste this:
curl.exe -X POST "http://localhost:8000/webhook" `
-H "Content-Type: application/json" `
-d '{
  \"status\": \"firing\",
  \"alerts\": [
    {
      \"status\": \"firing\",
      \"labels\": {
        \"alertname\": \"PostgresqlDown\",
        \"severity\": \"critical\",
        \"instance\": \"aws-ec2-db-master\",
        \"service\": \"postgresql\"
      },
      \"annotations\": {
        \"summary\": \"Loi nghiem trong: Database PostgreSQL tren AWS khong phan hoi!\",
        \"description\": \"Ket noi toi port 5432 bi tu choi tren instance 10.0.1.10\"
      },
      \"startsAt\": \"2026-05-06T12:00:00Z\",
      \"generatorURL\": \"http://prometheus-fake:9090\"
    }
  ]
}'

---

## 8. Xử lý lỗi thường gặp

### Redis không kết nối được

Nguyên nhân phổ biến:

* Sai `REDIS_HOST`
* Redis chưa khởi động

Cách khắc phục:

* Đảm bảo `REDIS_HOST=redis` khi chạy Docker
* Kiểm tra container Redis đang chạy

---

### Celery không xử lý task

* Kiểm tra log của worker
* Đảm bảo Redis hoạt động bình thường

---

### Webhook Telegram không hoạt động

* Webhook yêu cầu HTTPS
* Có thể sử dụng ngrok để tạo URL public

---

## 9. Tối ưu và mở rộng

Một số hướng cải thiện:

* Thêm reverse proxy (Nginx)
* Bổ sung dashboard theo dõi Celery
* Triển khai trên cloud (AWS/GCP)
* Thiết lập CI/CD cho tự động deploy

# Hướng dẫn chạy 

Đầu tiên thì phải đăng kí ngrok
ngrok http 8000

Sau đó deploy các services lên docker
docker-compose up -d --build

Cuối cùng thì test bằng curl:
curl.exe -X POST "http://localhost:8000/webhook" `
 -H "Content-Type: application/json" `
 -d '{
   \"status\": \"firing\",
   \"alerts\": [
     {
       \"status\": \"firing\",
       \"labels\": {
         \"alertname\": \"PostgresqlDown\",
         \"severity\": \"critical\",
         \"instance\": \"aws-ec2-db-master\",
         \"service\": \"postgresql\"
       },
       \"annotations\": {
         \"summary\": \"Loi nghiem trong: Database PostgreSQL tren AWS khong phan hoi!\",
         \"description\": \"Ket noi toi port 5432 bi tu choi tren instance 10.0.1.10\"
       },
       \"startsAt\": \"2026-05-06T12:00:00Z\",
       \"generatorURL\": \"http://prometheus-fake:9090\"
     }
   ]
 }'
