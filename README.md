# 🤖 AIOps Intelligent Agent System

> Hệ thống AI Agent tự động phát hiện, phân tích và đề xuất hướng xử lý sự cố trong hạ tầng CNTT — kết hợp monitoring, xử lý bất đồng bộ và AI.

---

## 📐 Kiến trúc hệ thống

```
┌─────────────────────────────────────────────────────────┐
│                     Docker Network                      │
│                                                         │
│  Prometheus ──► Alertmanager ──► FastAPI (app:8000)     │
│                                      │                  │
│                                   Redis                 │
│                                      │                  │
│                                Celery Worker            │
│                                      │                  │
│                              Gemini AI API              │
│                                      │                  │
│                             Telegram Bot ◄──► User      │
│                                      │                  │
│                               PostgreSQL                │
└─────────────────────────────────────────────────────────┘
```

| Thành phần | Vai trò |
|---|---|
| **FastAPI** | Nhận alert, điều phối xử lý qua `/webhook` |
| **Celery** | Xử lý tác vụ bất đồng bộ |
| **Redis** | Message broker + cache |
| **PostgreSQL** | Lưu trữ dữ liệu và log |
| **Prometheus + Alertmanager** | Giám sát hạ tầng, gửi cảnh báo |
| **Telegram Bot** | Gửi thông báo, nhận phản hồi từ người dùng |
| **Ngrok** *(optional)* | Expose webhook ra Internet |

---

## 🔄 Luồng hoạt động

```
1. Prometheus phát hiện bất thường
        ↓
2. Gửi alert đến FastAPI qua /webhook
        ↓
3. Alert được đưa vào Redis queue
        ↓
4. Celery worker xử lý → gọi AI phân tích
        ↓
5. Kết quả gửi về Telegram
        ↓
6. Người dùng chọn: ✅ Thực thi  hoặc  ❌ Bỏ qua
        ↓
7. Hệ thống thực hiện hành động & lưu log
```

---

## ⚙️ Cài đặt & chạy hệ thống

### 1. Tạo file `.env`

```env
# AI & Telegram
GEMINI_API_KEY=your_api_key
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
AI_AGENT_PUBLIC_URL=https://your-public-url

# Redis
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0

# PostgreSQL
POSTGRES_PASSWORD=your_password
```

### 2. Chạy bằng Docker

```bash
docker compose up --build
```

Sau khi khởi động thành công:

| Service | URL |
|---|---|
| API Docs | http://localhost:8000/docs |
| Health Check | http://localhost:8000/health |
| Prometheus | http://localhost:9090 |

---

## ⚠️ Lưu ý quan trọng (Docker networking)

Khi các service chạy trong Docker, **không dùng `localhost`** để giao tiếp giữa các container — hãy dùng **tên service** thay thế:

```
❌  localhost:6379      ✅  redis:6379
❌  localhost:5432      ✅  db:5432
```

---

## 🛠️ Chức năng chính

Các chức năng được đóng gói thành **tools** để AI Agent sử dụng:

- 🔍 Kiểm tra trạng thái service
- 📋 Phân tích log
- 🌐 Kiểm tra network / port
- 📊 Theo dõi tài nguyên (CPU, RAM, disk)
- 🔧 Đề xuất & thực thi hành động khắc phục

---

## 📡 Monitoring & Debug

### Endpoints

```
GET /health     # Kiểm tra trạng thái hệ thống
GET /metrics    # Metrics cho Prometheus
```

### Kiểm tra Redis

```bash
docker exec -it redis redis-cli ping
# Kết quả mong đợi: PONG
```

### Xem log

```bash
docker compose logs -f app       # Log FastAPI
docker compose logs -f worker    # Log Celery
```

---

## 🧪 Test hệ thống

**Bước 1:** Chạy Ngrok để expose webhook

```bash
ngrok http 8000
```

**Bước 2:** Khởi động server

```bash
docker compose up -d --build
```

**Bước 3:** Gửi request test (PowerShell)

```powershell
curl.exe -X POST "http://localhost:8000/webhook" `
  -H "Content-Type: application/json" `
  -d '{
    "status": "firing",
    "alerts": [
      {
        "status": "firing",
        "labels": {
          "alertname": "PostgresqlDown",
          "severity": "critical",
          "instance": "aws-ec2-db-master",
          "service": "postgresql"
        },
        "annotations": {
          "summary": "Loi nghiem trong: Database PostgreSQL khong phan hoi",
          "description": "Ket noi toi port 5432 bi tu choi"
        },
        "startsAt": "2026-05-06T12:00:00Z",
        "generatorURL": "http://prometheus-fake:9090"
      }
    ]
  }'
```

---

## 🐛 Lỗi thường gặp

<details>
<summary><b>❌ Redis không kết nối được</b></summary>

**Nguyên nhân:**
- Sai giá trị `REDIS_HOST` trong `.env`
- Container Redis chưa chạy

**Cách xử lý:**
```env
# Đảm bảo .env có:
REDIS_HOST=redis
```
```bash
# Kiểm tra container
docker compose ps redis
```
</details>

<details>
<summary><b>❌ Celery không chạy task</b></summary>

**Cách xử lý:**
```bash
docker compose logs -f worker   # Kiểm tra log
docker compose ps redis         # Đảm bảo Redis đang chạy
```
</details>

<details>
<summary><b>❌ Telegram webhook lỗi</b></summary>

**Nguyên nhân:** Telegram yêu cầu endpoint phải là **HTTPS**.

**Cách xử lý:** Dùng Ngrok để expose webhook với HTTPS:
```bash
ngrok http 8000
# Dùng URL https://xxxx.ngrok.io làm AI_AGENT_PUBLIC_URL
```
</details>

---

## 🚀 Hướng phát triển

- [ ] Thêm **Nginx** làm reverse proxy
- [ ] **Dashboard** theo dõi Celery tasks
- [ ] Deploy lên **AWS / GCP**
- [ ] Tích hợp **CI/CD** tự động    